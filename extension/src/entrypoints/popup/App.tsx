import React, { useEffect, useRef, useState } from "react";
import AuthGate from "./components/AuthGate";
import SaveForm from "./components/SaveForm";
import Settings from "./components/Settings";
import {
  checkLocalHealth,
  getMode,
  getApiUrl,
  isBuiltInDisabledHost,
  isDomainDisabled,
  setDomainDisabled,
  setMode,
  type Mode,
} from "@/lib/settings";

type View = "main" | "settings";

type AuthState =
  | { status: "loading" }
  | { status: "signed_out" }
  | { status: "signed_in"; accessToken: string }
  | { status: "local" };

export default function App() {
  const [view, setView] = useState<View>("main");
  const [auth, setAuth] = useState<AuthState>({ status: "loading" });
  const [authError, setAuthError] = useState<string | null>(null);
  const [authNotice, setAuthNotice] = useState<string | null>(null);
  const [apiUrl, setApiUrl] = useState("");
  const [mode, setModeState] = useState<Mode>("cloud");
  const [currentHost, setCurrentHost] = useState<string | null>(null);
  const [hostDisabled, setHostDisabled] = useState(false);
  const [showReloadHint, setShowReloadHint] = useState(false);
  const authNoticeTimer = useRef<number | null>(null);

  useEffect(() => {
    init().catch(() => setAuth({ status: "signed_out" }));
    detectCurrentHost();
  }, []);

  async function detectCurrentHost() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab?.url) return;
      const host = new URL(tab.url).hostname.replace(/^www\./, "");
      if (!host) return;
      setCurrentHost(host);
      setHostDisabled(await isDomainDisabled(host));
    } catch {
      // Restricted page or no permissions; the toggle button stays hidden.
    }
  }

  async function handleToggleHost() {
    if (!currentHost) return;
    const next = !hostDisabled;
    await setDomainDisabled(currentHost, next);
    setHostDisabled(next);
    setShowReloadHint(true);
    window.setTimeout(() => setShowReloadHint(false), 3000);
  }

  useEffect(() => {
    return () => {
      if (authNoticeTimer.current) window.clearTimeout(authNoticeTimer.current);
    };
  }, []);

  function showAuthNotice(message: string) {
    setAuthNotice(message);
    if (authNoticeTimer.current) window.clearTimeout(authNoticeTimer.current);
    authNoticeTimer.current = window.setTimeout(() => {
      setAuthNotice(null);
      authNoticeTimer.current = null;
    }, 3500);
  }

  async function init() {
    const currentMode = await getMode();
    const url = await getApiUrl();
    setModeState(currentMode);
    setApiUrl(url);

    if (currentMode === "local") {
      const connected = await checkLocalHealth(url);
      if (!connected) {
        await setMode("cloud");
        const cloudUrl = await getApiUrl();
        setModeState("cloud");
        setApiUrl(cloudUrl);
        setAuthError(`Could not connect to ${url}/health. Switched back to cloud.`);
        await checkSession();
        return;
      }
      setAuth({ status: "local" });
    } else {
      await checkSession();
    }
  }

  async function checkSession() {
    // MV3 service worker may be cold; sendMessage can reject or resolve
    // undefined until it wakes, so retry instead of hanging on "loading".
    let response: { accessToken?: string | null } | undefined;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        response = await chrome.runtime.sendMessage({ type: "GET_SESSION" });
      } catch {
        response = undefined;
      }
      if (response !== undefined) break;
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
    const accessToken = response?.accessToken ?? null;
    setAuth(accessToken ? { status: "signed_in", accessToken } : { status: "signed_out" });
  }

  async function handleSignIn() {
    setAuthError(null);
    setAuth({ status: "loading" });
    const result = await chrome.runtime.sendMessage({
      type: "SIGN_IN_WITH_GOOGLE",
    });
    if (result.success) {
      await checkSession();
      showAuthNotice("Signed in to LLM Wiki");
    } else {
      setAuthError(result.error ?? "Sign in failed");
      setAuth({ status: "signed_out" });
    }
  }

  async function handlePasswordSignIn(email: string, password: string) {
    setAuthError(null);
    setAuth({ status: "loading" });
    const result = await chrome.runtime.sendMessage({
      type: "SIGN_IN_WITH_PASSWORD",
      email,
      password,
    });
    if (result.success) {
      await checkSession();
      showAuthNotice("Signed in to LLM Wiki");
    } else {
      setAuthError(result.error ?? "Sign in failed");
      setAuth({ status: "signed_out" });
    }
  }

  async function handleSignOut() {
    setAuthError(null);
    setAuthNotice(null);
    await chrome.runtime.sendMessage({ type: "SIGN_OUT" });
    setAuth({ status: "signed_out" });
  }

  async function handleModeChange(newMode: Mode) {
    setModeState(newMode);
    const url = await getApiUrl();
    setApiUrl(url);

    if (newMode === "local") {
      setAuthError(null);
      setAuthNotice(null);
      setAuth({ status: "local" });
    } else {
      setAuth({ status: "loading" });
      await checkSession();
    }
  }

  if (view === "settings") {
    return (
      <div className="w-full overflow-hidden rounded-lg border border-zinc-200 bg-zinc-50 p-4 font-sans text-zinc-950 shadow-[0_8px_30px_rgba(15,23,42,0.14),0_1px_2px_rgba(15,23,42,0.08)] ring-1 ring-white/80">
        <Settings
          onBack={() => setView("main")}
          onModeChange={handleModeChange}
          isSignedIn={auth.status === "signed_in"}
          onSignOut={handleSignOut}
        />
      </div>
    );
  }

  const isReady = auth.status === "signed_in" || auth.status === "local";
  const accessToken = auth.status === "signed_in" ? auth.accessToken : null;

  const showHostToggle = !!currentHost && !isBuiltInDisabledHost(currentHost);

  return (
    <div className="w-full overflow-hidden rounded-lg border border-zinc-200 bg-zinc-50 p-4 font-sans text-zinc-950 shadow-[0_8px_30px_rgba(15,23,42,0.14),0_1px_2px_rgba(15,23,42,0.08)] ring-1 ring-white/80">
      {/* Header — source chip (left) + actions (right) */}
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2 text-xs text-zinc-500">
          {currentHost && (
            <span className="min-w-0 truncate font-medium text-zinc-700">{currentHost}</span>
          )}
          {mode === "local" && (
            <span className="rounded border border-zinc-200 bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-600">
              local
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {showHostToggle && (
            <button
              onClick={handleToggleHost}
              title={`${hostDisabled ? "Enable" : "Disable"} on ${currentHost}`}
              className="rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
            >
              {hostDisabled ? (
                /* eye-off */
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
                  <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
                  <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
                  <line x1="2" y1="2" x2="22" y2="22" />
                </svg>
              ) : (
                /* eye */
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              )}
            </button>
          )}
          <button
            onClick={() => setView("settings")}
            className="rounded-md px-2 py-1 text-xs font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
          >
            Settings
          </button>
        </div>
      </div>

      {showReloadHint && (
        <div className="mb-3 rounded-md border border-zinc-200 bg-zinc-100 px-3 py-1.5 text-[11px] text-zinc-600">
          Reload the page to apply.
        </div>
      )}

      {/* Body */}
      {auth.status === "loading" && (
        <div className="flex items-center justify-center py-8">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-200 border-t-zinc-800" />
        </div>
      )}

      {auth.status === "signed_out" && (
        <>
          {authError && (
            <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {authError}
            </div>
          )}
          <AuthGate
            onSignIn={handleSignIn}
            onPasswordSignIn={handlePasswordSignIn}
          />
        </>
      )}

      {authNotice && auth.status === "signed_in" && (
        <div className="mb-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          {authNotice}
        </div>
      )}

      {isReady && apiUrl && (
        <SaveForm apiUrl={apiUrl} accessToken={accessToken} />
      )}
    </div>
  );
}
