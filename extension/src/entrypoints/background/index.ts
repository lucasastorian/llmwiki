import { getSupabase } from "@/lib/supabase";
import { getApiUrl, clearAccountSelections } from "@/lib/settings";
import { isAllowedApiFetchUrl, isSupportedRemoteResourceUrl } from "@/lib/security";
import type { AuthChangeEvent, Session } from "@supabase/auth-js";

type Message =
  | { type: "SIGN_IN_WITH_GOOGLE" }
  | { type: "SIGN_IN_WITH_PASSWORD"; email: string; password: string }
  | { type: "SIGN_OUT" }
  | { type: "GET_SESSION" }
  | { type: "DOWNLOAD_PDF"; url: string }
  | { type: "FETCH_IMAGE_DATA_URL"; url: string; maxBytes?: number }
  | {
      type: "API_FETCH";
      url: string;
      method?: string;
      headers?: Record<string, string>;
      body?: string;
    };

interface ApiFetchResponse {
  ok: boolean;
  status: number;
  data?: unknown;
  error?: string;
}

export default defineBackground(() => {
  const supabase = getSupabase();

  supabase.auth.onAuthStateChange((_event: AuthChangeEvent, _session: Session | null) => {});

  chrome.runtime.onMessage.addListener(
    (message: Message, sender, sendResponse) => {
      // Only our own contexts (popup, injected content scripts) may drive these
      // privileged handlers. Without externally_connectable no web page can
      // reach here, but reject foreign senders as defense in depth.
      if (sender.id !== chrome.runtime.id) return false;
      handleMessage(message)
        .then(sendResponse)
        .catch((err: unknown) => {
          sendResponse({ error: err instanceof Error ? err.message : "Background error" });
        });
      return true; // will respond asynchronously
    },
  );

  async function handleMessage(msg: Message) {
    switch (msg.type) {
      case "SIGN_IN_WITH_GOOGLE":
        return signInWithGoogle();
      case "SIGN_IN_WITH_PASSWORD":
        return signInWithPassword(msg.email, msg.password);
      case "SIGN_OUT":
        return signOut();
      case "GET_SESSION":
        return getSession();
      case "DOWNLOAD_PDF":
        return downloadPdf(msg.url);
      case "FETCH_IMAGE_DATA_URL":
        return fetchImageDataUrl(msg.url, msg.maxBytes);
      case "API_FETCH":
        return apiFetchProxy(msg);
      default:
        return { error: "Unknown message type" };
    }
  }

  // ── API fetch proxy ─────────────────────────────────────
  //
  // Content scripts in MV3 fetch from the page's origin, which means most
  // sites (Substack, console.cloud.google.com, NYT, etc.) block our calls
  // via CORS or strict CSP. The background service worker has the privileged
  // chrome-extension origin and the required host_permission for the API
  // origin, so it can make the request and forward the result. The target is
  // gated to the configured API origin by isAllowedApiFetchUrl.

  async function apiFetchProxy(
    msg: {
      url: string;
      method?: string;
      headers?: Record<string, string>;
      body?: string;
    },
  ): Promise<ApiFetchResponse> {
    try {
      if (!isAllowedApiFetchUrl(msg.url, await getApiUrl())) {
        return { ok: false, status: 403, error: "Blocked extension fetch target" };
      }
      const res = await fetch(msg.url, {
        method: msg.method ?? "GET",
        headers: msg.headers,
        body: msg.body,
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
    } catch (err) {
      const message = err instanceof Error ? err.message : "Network error";
      return { ok: false, status: 0, error: message };
    }
  }

  // ── Google OAuth via Supabase as the broker ─────────────
  //
  // The extension does NOT talk to Google's token endpoint directly. Reasons:
  //   - Web app OAuth clients require a client_secret on token exchange.
  //     Embedding a client_secret in the extension is unsafe.
  //   - Google rejects launchWebAuthFlow with chromiumapp.org as the direct
  //     Google redirect URI ("browser may not be secure") on many clients.
  //
  // Instead we route through Supabase Auth, which already has the Google
  // client_secret stored server-side:
  //   1. Ask Supabase to build a Google OAuth URL with `redirectTo` = our
  //      chromiumapp.org/auth/callback. `skipBrowserRedirect: true` keeps us
  //      from auto-redirecting in this context — we just want the URL.
  //   2. Open Supabase's URL with launchWebAuthFlow. Google sees Supabase's
  //      callback as the redirect target (a normal https URL, so no
  //      "browser may not be secure" complaints).
  //   3. Google → Supabase's hosted callback → Supabase exchanges code →
  //      Supabase redirects to chromiumapp.org/auth/callback?code=<supabase>
  //      with its OWN single-use code, not Google's.
  //   4. We pull `code` and call `supabase.auth.exchangeCodeForSession(code)`
  //      to materialize a session in chrome.storage.
  //
  // Required Supabase Auth Settings → URL Configuration → Redirect URLs:
  //   https://<extension-id>.chromiumapp.org/auth/callback
  //
  // Google Cloud OAuth client just needs Supabase's callback as before:
  //   https://iaosaklvjwtviaadjbul.supabase.co/auth/v1/callback

  async function signInWithGoogle(): Promise<{
    success: boolean;
    error?: string;
  }> {
    try {
      const redirectTo = chrome.identity.getRedirectURL("auth/callback");

      // Step 1: ask Supabase for the Google OAuth URL.
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

      // Step 2-3: open Google's auth via Supabase's URL. Supabase handles the
      // Google code exchange server-side and redirects to redirectTo with a
      // Supabase auth code.
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

      // Step 4: trade Supabase's code for an actual session.
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

  // ── PDF Download ────────────────────────────────────────

  async function downloadPdf(
    url: string,
  ): Promise<{ blob: number[]; filename: string } | { error: string }> {
    try {
      const response = await fetch(url);
      if (!response.ok) {
        return { error: `Download failed: ${response.status}` };
      }

      const buffer = await response.arrayBuffer();
      const bytes = Array.from(new Uint8Array(buffer));

      // Derive filename
      let filename = "document.pdf";
      const disposition = response.headers.get("content-disposition");
      if (disposition) {
        const match = disposition.match(
          /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/,
        );
        if (match?.[1]) {
          filename = match[1].replace(/['"]/g, "");
        }
      } else {
        const lastSegment = new URL(url).pathname.split("/").pop();
        if (lastSegment) {
          filename = lastSegment.endsWith(".pdf") ? lastSegment : `${lastSegment}.pdf`;
        }
      }

      return { blob: bytes, filename };
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "PDF download failed";
      return { error: message };
    }
  }

  async function fetchImageDataUrl(
    url: string,
    maxBytes = 2_500_000,
  ): Promise<{ dataUrl: string; size: number; mimeType: string } | { error: string }> {
    try {
      if (!isSupportedRemoteResourceUrl(url)) {
        return { error: "Unsupported image URL" };
      }
      // No credentials: capture the public bytes of cross-origin images, never
      // the viewer's authenticated version (which would archive private images
      // into the wiki). The API falls back to its own credential-less fetch.
      const response = await fetch(url, {
        credentials: "omit",
        cache: "force-cache",
      });
      if (!response.ok) {
        return { error: `Image fetch failed: ${response.status}` };
      }

      const mimeType = (response.headers.get("content-type") || "").split(";", 1)[0].toLowerCase();
      if (!["image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"].includes(mimeType)) {
        return { error: `Unsupported image type: ${mimeType || "unknown"}` };
      }

      const buffer = await response.arrayBuffer();
      if (buffer.byteLength > maxBytes) {
        return { error: `Image too large: ${buffer.byteLength}` };
      }

      const bytes = new Uint8Array(buffer);
      let binary = "";
      const chunkSize = 0x8000;
      for (let i = 0; i < bytes.length; i += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
      }

      return {
        dataUrl: `data:${mimeType};base64,${btoa(binary)}`,
        size: buffer.byteLength,
        mimeType,
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Image fetch failed";
      return { error: message };
    }
  }
});
