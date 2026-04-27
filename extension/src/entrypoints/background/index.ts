import { getSupabase } from "@/lib/supabase";
import { GOOGLE_CLIENT_ID } from "@/lib/constants";

type Message =
  | { type: "SIGN_IN_WITH_GOOGLE" }
  | { type: "SIGN_OUT" }
  | { type: "GET_SESSION" }
  | { type: "DOWNLOAD_PDF"; url: string };

export default defineBackground(() => {
  const supabase = getSupabase();

  // Keep session fresh across service worker restarts
  supabase.auth.onAuthStateChange((event, _session) => {
    console.log("[bg] auth:", event);
  });

  chrome.runtime.onMessage.addListener(
    (message: Message, _sender, sendResponse) => {
      handleMessage(message).then(sendResponse);
      return true; // will respond asynchronously
    },
  );

  async function handleMessage(msg: Message) {
    switch (msg.type) {
      case "SIGN_IN_WITH_GOOGLE":
        return signInWithGoogle();
      case "SIGN_OUT":
        return signOut();
      case "GET_SESSION":
        return getSession();
      case "DOWNLOAD_PDF":
        return downloadPdf(msg.url);
      default:
        return { error: "Unknown message type" };
    }
  }

  // ── Google OAuth via chrome.identity ────────────────────

  async function signInWithGoogle(): Promise<{
    success: boolean;
    error?: string;
  }> {
    try {
      // 1. Generate nonce — raw for Supabase, SHA-256 hex for Google
      const rawNonce = crypto.randomUUID();
      const hashBuffer = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(rawNonce),
      );
      const hashedNonce = Array.from(new Uint8Array(hashBuffer))
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("");

      // 2. Build Google OAuth URL
      const redirectUrl = chrome.identity.getRedirectURL();
      const authUrl = new URL("https://accounts.google.com/o/oauth2/v2/auth");
      authUrl.searchParams.set("client_id", GOOGLE_CLIENT_ID);
      authUrl.searchParams.set("response_type", "id_token");
      authUrl.searchParams.set("redirect_uri", redirectUrl);
      authUrl.searchParams.set("scope", "openid email profile");
      authUrl.searchParams.set("nonce", hashedNonce);
      authUrl.searchParams.set("prompt", "consent");

      // 3. Launch auth flow
      const responseUrl = await chrome.identity.launchWebAuthFlow({
        url: authUrl.toString(),
        interactive: true,
      });

      if (!responseUrl) {
        return { success: false, error: "Auth flow cancelled" };
      }

      // 4. Extract id_token from fragment
      const params = new URLSearchParams(
        new URL(responseUrl).hash.substring(1),
      );
      const idToken = params.get("id_token");
      if (!idToken) {
        return { success: false, error: "No id_token in response" };
      }

      // 5. Sign in with Supabase
      const { error } = await supabase.auth.signInWithIdToken({
        provider: "google",
        token: idToken,
        nonce: rawNonce,
      });

      if (error) {
        return { success: false, error: error.message };
      }

      return { success: true };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Auth failed";
      return { success: false, error: message };
    }
  }

  async function signOut() {
    await supabase.auth.signOut();
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
        if (lastSegment?.endsWith(".pdf")) {
          filename = lastSegment;
        }
      }

      return { blob: bytes, filename };
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "PDF download failed";
      return { error: message };
    }
  }
});
