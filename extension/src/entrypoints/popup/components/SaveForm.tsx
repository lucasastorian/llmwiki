import React, { useEffect, useState } from "react";
import { saveWebPage, savePdf } from "@/lib/api";
import KBPicker from "./KBPicker";
import StatusFeedback, { type Status } from "./StatusFeedback";

interface Props {
  apiUrl: string;
  accessToken: string | null;
}

interface TabInfo {
  url: string;
  title: string;
  isPdf: boolean;
  tabId: number;
}

export default function SaveForm({ apiUrl, accessToken }: Props) {
  const [tab, setTab] = useState<TabInfo | null>(null);
  const [title, setTitle] = useState("");
  const [knowledgeBaseId, setKnowledgeBaseId] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>({ type: "idle" });

  useEffect(() => {
    detectCurrentPage();
  }, []);

  async function detectCurrentPage() {
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!activeTab?.url || !activeTab.id) return;

    const url = activeTab.url;
    const isPdf =
      url.toLowerCase().endsWith(".pdf") ||
      (activeTab.title?.toLowerCase().endsWith(".pdf") ?? false);

    setTab({ url, title: activeTab.title ?? "", isPdf, tabId: activeTab.id });
    setTitle(activeTab.title ?? "");
  }

  async function handleSave() {
    if (!tab || !knowledgeBaseId) return;

    try {
      if (tab.isPdf) {
        await handleSavePdf();
      } else {
        await handleSaveWeb();
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Save failed";
      setStatus({ type: "error", message });
    }
  }

  async function handleSaveWeb() {
    if (!tab || !knowledgeBaseId) return;

    setStatus({ type: "saving", message: "Extracting page..." });

    let html: string;
    try {
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.tabId },
        func: () => document.documentElement.outerHTML,
      });
      html = result as string;
    } catch {
      throw new Error("Could not extract page content. Try refreshing the page.");
    }

    setStatus({ type: "saving", message: "Saving to LLM Wiki..." });

    await saveWebPage(apiUrl, accessToken, knowledgeBaseId, {
      url: tab.url,
      title: title || tab.title,
      html,
    });

    setStatus({ type: "success" });
  }

  async function handleSavePdf() {
    if (!tab || !knowledgeBaseId) return;

    setStatus({ type: "saving", message: "Downloading PDF..." });

    const downloadResult = await chrome.runtime.sendMessage({
      type: "DOWNLOAD_PDF",
      url: tab.url,
    });

    if ("error" in downloadResult) {
      throw new Error(downloadResult.error);
    }

    setStatus({ type: "saving", message: "Uploading to LLM Wiki..." });

    const pdfBytes = new Uint8Array(downloadResult.blob);
    await savePdf(apiUrl, accessToken, pdfBytes, downloadResult.filename, knowledgeBaseId);

    setStatus({ type: "success" });
  }

  if (!tab) {
    return (
      <div className="flex items-center justify-center py-6">
        <div className="w-5 h-5 border-2 border-gray-300 border-t-gray-900 rounded-full animate-spin" />
      </div>
    );
  }

  const isSaving = status.type === "saving";
  const canSave = knowledgeBaseId && !isSaving && status.type !== "success";

  return (
    <div className="space-y-3">
      {/* Type badge + URL */}
      <div className="flex items-center gap-1.5">
        <span
          className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${
            tab.isPdf ? "bg-red-50 text-red-700" : "bg-gray-100 text-gray-700"
          }`}
        >
          {tab.isPdf ? "PDF" : "Web"}
        </span>
        <span className="text-xs text-gray-400 truncate max-w-[320px]">{tab.url}</span>
      </div>

      {/* Title */}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Title</label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm
                     text-gray-900 shadow-sm focus:border-gray-900 focus:ring-1
                     focus:ring-gray-900 outline-none"
          placeholder="Page title"
        />
      </div>

      {/* KB picker */}
      <KBPicker
        apiUrl={apiUrl}
        accessToken={accessToken}
        value={knowledgeBaseId}
        onChange={setKnowledgeBaseId}
      />

      {/* Save button */}
      <button
        onClick={handleSave}
        disabled={!canSave}
        className="w-full py-2 px-4 rounded-md text-sm font-medium text-white
                   bg-gray-900 hover:bg-gray-800 disabled:opacity-50
                   disabled:cursor-not-allowed transition-colors shadow-sm"
      >
        {isSaving ? "Saving..." : "Save to LLM Wiki"}
      </button>

      <StatusFeedback status={status} />
    </div>
  );
}
