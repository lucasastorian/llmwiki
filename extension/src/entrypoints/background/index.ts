import { getSupabase } from "@/lib/supabase";
import { getApiUrl, clearAccountSelections } from "@/lib/settings";
import { isAllowedApiFetchUrl } from "@/lib/security";
import {
  CLOSE_PDF_SAVE_CONTEXT,
  ENSURE_PDF_SAVE_CONTEXT,
  GET_PDF_SAVE_STATUS,
  START_PDF_SAVE,
  type GetPdfSaveStatusMessage,
  type StartPdfSaveMessage,
} from "@/lib/pdf-save-jobs";
import { API_READ_TIMEOUT_MS, API_WRITE_TIMEOUT_MS, runWithDeadline } from "@/lib/deadline";

type BackgroundMessage =
  | { type: "SIGN_IN_WITH_GOOGLE" }
  | { type: "SIGN_IN_WITH_PASSWORD"; email: string; password: string }
  | { type: "SIGN_OUT" }
  | { type: "GET_SESSION" }
  | { type: typeof ENSURE_PDF_SAVE_CONTEXT }
  | { type: typeof CLOSE_PDF_SAVE_CONTEXT }
  | {
      type: "API_FETCH";
      url: string;
      method?: string;
      headers?: Record<string, string>;
      body?: string;
      timeoutMs?: number;
    };

type Message = BackgroundMessage | StartPdfSaveMessage | GetPdfSaveStatusMessage;

interface ApiFetchResponse {
  ok: boolean;
  status: number;
  data?: unknown;
  error?: string;
}

export default defineBackground(() => {
  const supabase = getSupabase();

  chrome.runtime.onMessage.addListener(
    (message: Message, sender, sendResponse) => {
      // Defense in depth: no externally_connectable, but still reject foreign senders.
      if (sender.id !== chrome.runtime.id) return false;
      // Offscreen document owns these; returning false leaves it the sole responder.
      if (message.type === START_PDF_SAVE || message.type === GET_PDF_SAVE_STATUS) {
        return false;
      }
      handleMessage(message)
        .then(sendResponse)
        .catch((err: unknown) => {
          sendResponse({ error: err instanceof Error ? err.message : "Background error" });
        });
      return true; // keeps the channel open for the async sendResponse
    },
  );

  async function handleMessage(msg: BackgroundMessage) {
    switch (msg.type) {
      case "SIGN_IN_WITH_GOOGLE":
        return signInWithGoogle();
      case "SIGN_IN_WITH_PASSWORD":
        return signInWithPassword(msg.email, msg.password);
      case "SIGN_OUT":
        return signOut();
      case "GET_SESSION":
        return getSession();
      case ENSURE_PDF_SAVE_CONTEXT:
        return ensurePdfSaveContext();
      case CLOSE_PDF_SAVE_CONTEXT:
        return closePdfSaveContext();
      case "API_FETCH":
        return apiFetchProxy(msg);
      default:
        return { error: "Unknown message type" };
    }
  }

  // MV3 content-script fetches use the page origin and hit CORS/CSP; the worker's extension origin does not.
  async function apiFetchProxy(
    msg: {
      url: string;
      method?: string;
      headers?: Record<string, string>;
      body?: string;
      timeoutMs?: number;
    },
  ): Promise<ApiFetchResponse> {
    try {
      if (!isAllowedApiFetchUrl(msg.url, await getApiUrl())) {
        return { ok: false, status: 403, error: "Blocked extension fetch target" };
      }
      const requestedTimeout = Number.isFinite(msg.timeoutMs)
        ? Number(msg.timeoutMs)
        : API_READ_TIMEOUT_MS;
      const timeoutMs = Math.min(Math.max(requestedTimeout, 1_000), API_WRITE_TIMEOUT_MS);
      return await runWithDeadline(async (signal) => {
        const res = await fetch(msg.url, {
          method: msg.method ?? "GET",
          headers: msg.headers,
          body: msg.body,
          signal,
        });
        let data: unknown = null;
        const text = await res.text();
        if (text) {
          try {
            data = JSON.parse(text);
          } catch {
            data = text;
          }
        }
        return { ok: res.ok, status: res.status, data };
      }, timeoutMs, `API request timed out after ${Math.ceil(timeoutMs / 1_000)} seconds`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Network error";
      return { ok: false, status: 0, error: message };
    }
  }

  // Supabase brokers Google OAuth: a bundled client_secret is unsafe and Google rejects chromiumapp.org redirects.
  // Supabase Redirect URLs must allow https://<extension-id>.chromiumapp.org/auth/callback.
  async function signInWithGoogle(): Promise<{
    success: boolean;
    error?: string;
  }> {
    try {
      const redirectTo = chrome.identity.getRedirectURL("auth/callback");

      const { data, error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo,
          skipBrowserRedirect: true,
          scopes: "openid email profile",
        },
      });
      if (error) {
        return { success: false, error: error.message };
      }
      if (!data?.url) {
        return { success: false, error: "Supabase returned no OAuth URL" };
      }

      const callbackUrl = await chrome.identity.launchWebAuthFlow({
        url: data.url,
        interactive: true,
      });
      if (!callbackUrl) {
        return { success: false, error: "Auth flow cancelled" };
      }

      const parsed = new URL(callbackUrl);
      const oauthError = parsed.searchParams.get("error_description")
        || parsed.searchParams.get("error");
      if (oauthError) {
        return { success: false, error: oauthError };
      }
      const code = parsed.searchParams.get("code");
      if (!code) {
        return { success: false, error: "No auth code in callback URL" };
      }

      const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);
      if (exchangeError) {
        return { success: false, error: exchangeError.message };
      }
      return { success: true };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Auth failed";
      return { success: false, error: message };
    }
  }

  async function signInWithPassword(
    email: string,
    password: string,
  ): Promise<{ success: boolean; error?: string }> {
    try {
      const { error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      if (error) {
        return { success: false, error: error.message };
      }
      return { success: true };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Sign in failed";
      return { success: false, error: message };
    }
  }

  async function signOut() {
    await supabase.auth.signOut();
    await clearAccountSelections();
    return { success: true };
  }

  async function getSession() {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    return {
      accessToken: session?.access_token ?? null,
      userId: session?.user?.id ?? null,
    };
  }

  let offscreenCreation: Promise<void> | null = null;
  const offscreenUrl = chrome.runtime.getURL("offscreen.html");

  async function ensurePdfSaveContext(): Promise<{ ready: true }> {
    if (!(await hasPdfSaveContext())) {
      offscreenCreation ??= chrome.offscreen.createDocument({
        url: offscreenUrl,
        reasons: ["BLOBS" as chrome.offscreen.Reason],
        justification: "Keep PDF download and upload blobs alive after the popup closes",
      });
      try {
        await offscreenCreation;
      } finally {
        offscreenCreation = null;
      }
    }
    return { ready: true };
  }

  async function closePdfSaveContext(): Promise<{ closed: true }> {
    if (offscreenCreation) await offscreenCreation;
    if (await hasPdfSaveContext()) await chrome.offscreen.closeDocument();
    return { closed: true };
  }

  async function hasPdfSaveContext(): Promise<boolean> {
    // runtime.getContexts is Chrome 116+; 109-115 fall back to the worker's clients.
    if ("getContexts" in chrome.runtime) {
      const contexts = await new Promise<chrome.runtime.ExtensionContext[]>((resolve) => {
        chrome.runtime.getContexts({
          contextTypes: ["OFFSCREEN_DOCUMENT" as chrome.runtime.ContextType],
          documentUrls: [offscreenUrl],
        }, resolve);
      });
      return contexts.length > 0;
    }

    const workerScope = globalThis as typeof globalThis & {
      clients: { matchAll(): Promise<ReadonlyArray<{ url: string }>> };
    };
    const extensionClients = await workerScope.clients.matchAll();
    return extensionClients.some((client) => client.url === offscreenUrl);
  }

});
