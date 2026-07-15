import { savePdfFromTab } from "@/lib/pdf-save";
import {
  CLOSE_PDF_SAVE_CONTEXT,
  GET_PDF_SAVE_STATUS,
  START_PDF_SAVE,
  type GetPdfSaveStatusMessage,
  type PdfSaveJobStatus,
  type StartPdfSaveMessage,
} from "@/lib/pdf-save-jobs";
import type { SaveResult } from "@/lib/api";

const jobs = new Map<string, PdfSaveJobStatus>();
const activeSaves = new Map<string, Promise<SaveResult>>();
let cleanupTimer: number | undefined;
let closing = false;

chrome.runtime.onMessage.addListener((message: unknown, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || !isJobMessage(message)) return false;

  if (message.type === START_PDF_SAVE) {
    if (closing) {
      sendResponse({ accepted: false });
      return false;
    }
    if (jobs.has(message.jobId)) {
      sendResponse({ accepted: true });
      return false;
    }

    if (cleanupTimer !== undefined) {
      clearTimeout(cleanupTimer);
      cleanupTimer = undefined;
    }
    jobs.set(message.jobId, { state: "running" });
    sendResponse({ accepted: true });

    const key = requestKey(message.request);
    let save = activeSaves.get(key);
    if (!save) {
      save = savePdfFromTab(message.request);
      activeSaves.set(key, save);
      const created = save;
      void created.then(
        () => {
          if (activeSaves.get(key) === created) activeSaves.delete(key);
        },
        () => {
          if (activeSaves.get(key) === created) activeSaves.delete(key);
        },
      );
    }

    // A popup reopened during an active save gets its own job handle attached
    // to the same promise rather than launching a duplicate transfer.
    void save
      .then((result) => jobs.set(message.jobId, { state: "success", result }))
      .catch((error: unknown) => {
        jobs.set(message.jobId, {
          state: "error",
          error: error instanceof Error ? error.message : "PDF save failed",
        });
      })
      .finally(() => scheduleCleanup(5 * 60_000));
    return false;
  }

  const status = jobs.get(message.jobId) ?? { state: "missing" as const };
  sendResponse(status);
  if (status.state === "success" || status.state === "error") {
    jobs.delete(message.jobId);
    if (jobs.size === 0) scheduleCleanup(1_000);
  }
  return false;
});

function isJobMessage(
  message: unknown,
): message is StartPdfSaveMessage | GetPdfSaveStatusMessage {
  if (!message || typeof message !== "object" || !("type" in message)) return false;
  const type = (message as { type?: unknown }).type;
  return type === START_PDF_SAVE || type === GET_PDF_SAVE_STATUS;
}

function scheduleCleanup(delay: number): void {
  if (cleanupTimer !== undefined) clearTimeout(cleanupTimer);
  cleanupTimer = window.setTimeout(() => {
    cleanupTimer = undefined;
    if ([...jobs.values()].some((job) => job.state === "running")) {
      scheduleCleanup(5 * 60_000);
      return;
    }
    jobs.clear();
    closing = true;
    void chrome.runtime.sendMessage({ type: CLOSE_PDF_SAVE_CONTEXT }).catch(() => {
      // If shutdown failed, continue serving jobs in this still-live context.
      closing = false;
    });
  }, delay);
}

function requestKey(request: StartPdfSaveMessage["request"]): string {
  return JSON.stringify([
    request.apiUrl,
    request.url,
    request.knowledgeBaseId,
    request.path,
    request.accessToken !== null,
  ]);
}
