import React, { useEffect, useRef, useState } from "react";
import AuthGate from "./components/AuthGate";
import SaveForm from "./components/SaveForm";
import Settings from "./components/Settings";
import { EyeIcon, EyeOffIcon } from "./components/EyeIcons";
import {
  checkLocalHealth,
  getMode,
  getApiUrl,
  isBuiltInDisabledHost,
  isDomainDisabled,
  normalizeHost,
  setDomainDisabled,
  type Mode,
} from "@/lib/settings";
import { runtimeMessageWithDeadline, withDeadline } from "@/lib/deadline";

type View = "main" | "settings";

type AuthState =
  | { status: "loading" }
  | { status: "signed_out" }
  | { status: "signed_in"; accessToken: string }
  | { status: "local" }
  | { status: "error"; message: string };

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
  const startupAttempt = useRef(0);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    void startInit();
    void detectCurrentHost();
    return () => {
      startupAttempt.current += 1;
      mounted.current = false;
    };
  }, []);

  async function startInit() {
    const attempt = ++startupAttempt.current;
    setAuthError(null);
    setAuth({ status: "loading" });
    try {
      await withDeadline(
        init(attempt),
        20_000,
        "Extension startup timed out. Please retry.",
      );
    } catch (error) {
      if (attempt !== startupAttempt.current) return;
      // Stops a timed-out init that resolves late from overwriting the error state.
      startupAttempt.current += 1;
      const message = error instanceof Error ? error.message : "The extension could not start.";
      setAuth({ status: "error", message });
    }
  }

  async function detectCurrentHost() {
    try {
      const [tab] = await withDeadline(
        chrome.tabs.query({ active: true, currentWindow: true }),
        5_000,
        "Active tab lookup timed out",
      );
      if (!mounted.current) return;
      if (!tab?.url) return;
      const host = normalizeHost(new URL(tab.url).hostname);
      if (!host) return;
      setCurrentHost(host);
      const disabled = await withDeadline(
        isDomainDisabled(host),
        5_000,
        "Domain preference lookup timed out",
      );
      if (!mounted.current) return;
      setHostDisabled(disabled);
    } catch {
      // Restricted page; the toggle stays hidden.
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

  async function init(attempt: number) {
    const currentMode = await getMode();
    const url = await getApiUrl();
    if (attempt !== startupAttempt.current) return;
    setModeState(currentMode);
    setApiUrl(url);

    if (currentMode === "local") {
      const connected = await checkLocalHealth(url);
      if (attempt !== startupAttempt.current) return;
      if (!connected) {
        setAuth({
          status: "error",
          message: `Could not connect to ${url}/health. Your local preference was kept; start the local app and retry.`,
        });
        return;
      }
      setAuth({ status: "local" });
    } else {
      await checkSession(attempt);
    }
  }

  async function checkSession(startupAttemptId?: number) {
    // A cold MV3 service worker can reject or resolve undefined until it wakes.
    let response: { accessToken?: string | null; error?: string } | undefined;
    let lastError: unknown = new Error("The extension background did not respond");
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        response = await runtimeMessageWithDeadline(
          { type: "GET_SESSION" },
          4_000,
          "Timed out while checking your session",
        );
        if (!response) throw new Error("The extension background did not respond");
        if (response.error) throw new Error(response.error);
      } catch (error) {
        lastError = error;
        response = undefined;
      }
      if (response !== undefined) break;
      if (attempt < 2) await new Promise((resolve) => setTimeout(resolve, 150));
    }
    if (!response) throw lastError;
    if (startupAttemptId !== undefined && startupAttemptId !== startupAttempt.current) return;
    const accessToken = response?.accessToken ?? null;
    setAuth(accessToken ? { status: "signed_in", accessToken } : { status: "signed_out" });
  }

  async function handleSignIn() {
    setAuthError(null);
    setAuth({ status: "loading" });
    try {
      const result = await runtimeMessageWithDeadline<{ success?: boolean; error?: string }>(
        { type: "SIGN_IN_WITH_GOOGLE" },
        5 * 60_000,
        "Google sign-in timed out",
      );
      if (!result?.success) throw new Error(result?.error ?? "Sign in failed");
      await checkSession();
      showAuthNotice("Signed in to LLM Wiki");
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Sign in failed");
      setAuth({ status: "signed_out" });
    }
  }

  async function handlePasswordSignIn(email: string, password: string) {
    setAuthError(null);
    setAuth({ status: "loading" });
    try {
      const result = await runtimeMessageWithDeadline<{ success?: boolean; error?: string }>(
        { type: "SIGN_IN_WITH_PASSWORD", email, password },
        30_000,
        "Password sign-in timed out",
      );
      if (!result?.success) throw new Error(result?.error ?? "Sign in failed");
      await checkSession();
      showAuthNotice("Signed in to LLM Wiki");
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Sign in failed");
      setAuth({ status: "signed_out" });
    }
  }

  async function handleSignOut() {
    setAuthError(null);
    setAuthNotice(null);
    try {
      const result = await runtimeMessageWithDeadline<{ success?: boolean; error?: string }>(
        { type: "SIGN_OUT" },
        15_000,
        "Sign out timed out",
      );
      if (!result?.success) throw new Error(result?.error ?? "Sign out failed");
      setAuth({ status: "signed_out" });
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Sign out failed");
      setView("main");
    }
  }

  async function handleModeChange(newMode: Mode) {
    setModeState(newMode);
    let url: string;
    try {
      url = await withDeadline(
        getApiUrl(),
        5_000,
        "API settings lookup timed out",
      );
    } catch (error) {
      setAuth({
        status: "error",
        message: error instanceof Error ? error.message : "Could not load API settings.",
      });
      return;
    }
    setApiUrl(url);

    if (newMode === "local") {
      setAuthError(null);
      setAuthNotice(null);
      setAuth({ status: "local" });
    } else {
      setAuth({ status: "loading" });
      try {
        await checkSession();
      } catch (error) {
        setAuth({
          status: "error",
          message: error instanceof Error ? error.message : "Could not check your session.",
        });
      }
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
              {hostDisabled ? <EyeOffIcon /> : <EyeIcon />}
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

      {authError && auth.status !== "loading" && (
        <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {authError}
        </div>
      )}

      {auth.status === "loading" && (
        <div className="flex items-center justify-center py-8">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-200 border-t-zinc-800" />
        </div>
      )}

      {auth.status === "signed_out" && (
        <>
          <AuthGate
            onSignIn={handleSignIn}
            onPasswordSignIn={handlePasswordSignIn}
          />
        </>
      )}

      {auth.status === "error" && (
        <div className="space-y-3 py-2">
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
            {auth.message}
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => void startInit()}
              className="h-9 flex-1 rounded-md bg-zinc-950 px-3 text-xs font-medium text-white hover:bg-zinc-800"
            >
              Retry
            </button>
            <button
              onClick={() => setView("settings")}
              className="h-9 flex-1 rounded-md border border-zinc-200 bg-white px-3 text-xs font-medium text-zinc-700 hover:bg-zinc-100"
            >
              Settings
            </button>
          </div>
        </div>
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
