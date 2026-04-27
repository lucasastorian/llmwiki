export type Mode = "cloud" | "local";

const STORAGE_KEY = "llmwiki_mode";
const LOCAL_URL_KEY = "llmwiki_local_url";

const DEFAULT_CLOUD_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const DEFAULT_LOCAL_URL = "http://localhost:8000";

export async function getMode(): Promise<Mode> {
  const result = await chrome.storage.local.get(STORAGE_KEY);
  return result[STORAGE_KEY] === "local" ? "local" : "cloud";
}

export async function setMode(mode: Mode): Promise<void> {
  await chrome.storage.local.set({ [STORAGE_KEY]: mode });
}

export async function getApiUrl(): Promise<string> {
  const mode = await getMode();
  if (mode === "local") {
    const result = await chrome.storage.local.get(LOCAL_URL_KEY);
    return result[LOCAL_URL_KEY] || DEFAULT_LOCAL_URL;
  }
  return DEFAULT_CLOUD_URL;
}

export async function setLocalUrl(url: string): Promise<void> {
  await chrome.storage.local.set({ [LOCAL_URL_KEY]: url });
}

export async function getLocalUrl(): Promise<string> {
  const result = await chrome.storage.local.get(LOCAL_URL_KEY);
  return result[LOCAL_URL_KEY] || DEFAULT_LOCAL_URL;
}
