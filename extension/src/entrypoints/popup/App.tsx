import React, { useEffect, useState } from "react";
import AuthGate from "./components/AuthGate";
import SaveForm from "./components/SaveForm";
import Settings from "./components/Settings";
import { getMode, getApiUrl, type Mode } from "@/lib/settings";

type View = "main" | "settings";

type AuthState =
  | { status: "loading" }
  | { status: "signed_out" }
  | { status: "signed_in"; accessToken: string }
  | { status: "local" };

export default function App() {
  const [view, setView] = useState<View>("main");
  const [auth, setAuth] = useState<AuthState>({ status: "loading" });
  const [apiUrl, setApiUrl] = useState("");
  const [mode, setModeState] = useState<Mode>("cloud");

  useEffect(() => {
    init();
  }, []);

  async function init() {
    const currentMode = await getMode();
    const url = await getApiUrl();
    setModeState(currentMode);
    setApiUrl(url);

    if (currentMode === "local") {
      setAuth({ status: "local" });
    } else {
      await checkSession();
    }
  }

  async function checkSession() {
    const { accessToken } = await chrome.runtime.sendMessage({
      type: "GET_SESSION",
    });
    if (accessToken) {
      setAuth({ status: "signed_in", accessToken });
    } else {
      setAuth({ status: "signed_out" });
    }
  }

  async function handleSignIn() {
    setAuth({ status: "loading" });
    const result = await chrome.runtime.sendMessage({
      type: "SIGN_IN_WITH_GOOGLE",
    });
    if (result.success) {
      await checkSession();
    } else {
      setAuth({ status: "signed_out" });
    }
  }

  async function handleSignOut() {
    await chrome.runtime.sendMessage({ type: "SIGN_OUT" });
    setAuth({ status: "signed_out" });
  }

  async function handleModeChange(newMode: Mode) {
    setModeState(newMode);
    const url = await getApiUrl();
    setApiUrl(url);

    if (newMode === "local") {
      setAuth({ status: "local" });
    } else {
      setAuth({ status: "loading" });
      await checkSession();
    }
  }

  if (view === "settings") {
    return (
      <div className="p-4 w-[400px]">
        <Settings onBack={() => setView("main")} onModeChange={handleModeChange} />
      </div>
    );
  }

  const isReady = auth.status === "signed_in" || auth.status === "local";
  const accessToken = auth.status === "signed_in" ? auth.accessToken : null;

  return (
    <div className="p-4 w-[400px]">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h1 className="text-base font-semibold text-gray-900">LLM Wiki</h1>
          {mode === "local" && (
            <span className="text-[10px] font-medium text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
              local
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {auth.status === "signed_in" && (
            <button
              onClick={handleSignOut}
              className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
            >
              Sign out
            </button>
          )}
          <button
            onClick={() => setView("settings")}
            className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            Settings
          </button>
        </div>
      </div>

      {/* Body */}
      {auth.status === "loading" && (
        <div className="flex items-center justify-center py-8">
          <div className="w-5 h-5 border-2 border-gray-300 border-t-gray-900 rounded-full animate-spin" />
        </div>
      )}

      {auth.status === "signed_out" && <AuthGate onSignIn={handleSignIn} />}

      {isReady && apiUrl && (
        <SaveForm apiUrl={apiUrl} accessToken={accessToken} />
      )}
    </div>
  );
}
