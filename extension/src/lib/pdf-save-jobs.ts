import type { SaveResult } from "./api";
import type { SavePdfFromTabRequest } from "./pdf-save";
import { withDeadline } from "./deadline";

export const ENSURE_PDF_SAVE_CONTEXT = "ENSURE_PDF_SAVE_CONTEXT";
export const START_PDF_SAVE = "START_PDF_SAVE";
export const GET_PDF_SAVE_STATUS = "GET_PDF_SAVE_STATUS";
export const CLOSE_PDF_SAVE_CONTEXT = "CLOSE_PDF_SAVE_CONTEXT";

export interface StartPdfSaveMessage {
  type: typeof START_PDF_SAVE;
  jobId: string;
  request: SavePdfFromTabRequest;
}

export interface GetPdfSaveStatusMessage {
  type: typeof GET_PDF_SAVE_STATUS;
  jobId: string;
}

export type PdfSaveJobStatus =
  | { state: "running" }
  | { state: "success"; result: SaveResult }
  | { state: "error"; error: string }
  | { state: "missing" };

export interface PdfSaveJobClientDependencies {
  sendMessage(message: unknown): Promise<unknown>;
  wait(milliseconds: number): Promise<void>;
  createJobId(): string;
  now?(): number;
  messageTimeoutMs?: number;
  jobTimeoutMs?: number;
}

export const PDF_JOB_TIMEOUT_MS = 15 * 60_000;
const PDF_JOB_MESSAGE_TIMEOUT_MS = 10_000;

const defaultDependencies: PdfSaveJobClientDependencies = {
  sendMessage: (message) => chrome.runtime.sendMessage(message),
  wait: (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
  createJobId: () => crypto.randomUUID(),
  now: () => Date.now(),
  messageTimeoutMs: PDF_JOB_MESSAGE_TIMEOUT_MS,
  jobTimeoutMs: PDF_JOB_TIMEOUT_MS,
};

/** Runs the save in the offscreen document so closing the popup stops polling, not the save. */
export async function runPdfSaveJob(
  request: SavePdfFromTabRequest,
  dependencies: PdfSaveJobClientDependencies = defaultDependencies,
): Promise<SaveResult> {
  const now = dependencies.now ?? (() => Date.now());
  const messageTimeoutMs = dependencies.messageTimeoutMs ?? PDF_JOB_MESSAGE_TIMEOUT_MS;
  const jobTimeoutMs = dependencies.jobTimeoutMs ?? PDF_JOB_TIMEOUT_MS;
  const sendMessage = (message: unknown) => withDeadline(
    dependencies.sendMessage(message),
    messageTimeoutMs,
    "The PDF save context did not respond",
  );
  const deadlineAt = now() + jobTimeoutMs;

  const ready = await sendMessage({ type: ENSURE_PDF_SAVE_CONTEXT }) as {
    ready?: boolean;
    error?: string;
  } | undefined;
  if (!ready?.ready) {
    throw new Error(ready?.error ?? "Could not start the PDF save context");
  }

  const jobId = dependencies.createJobId();
  const startMessage: StartPdfSaveMessage = { type: START_PDF_SAVE, jobId, request };
  let accepted = false;

  // createDocument resolves before the offscreen listener is registered.
  for (let attempt = 0; attempt < 10 && !accepted; attempt += 1) {
    if (attempt > 0) {
      try {
        await sendMessage({ type: ENSURE_PDF_SAVE_CONTEXT });
      } catch {
        // Previous context may still be shutting down.
      }
    }
    try {
      const response = await sendMessage(startMessage) as {
        accepted?: boolean;
      } | undefined;
      accepted = response?.accepted === true;
    } catch {
      // The receiver may still be loading.
    }
    if (!accepted) await dependencies.wait(50);
  }
  if (!accepted) throw new Error("PDF save context did not become ready");

  let missingPolls = 0;
  while (now() < deadlineAt) {
    await dependencies.wait(250);
    if (now() >= deadlineAt) break;
    let status: PdfSaveJobStatus | undefined;
    try {
      status = await sendMessage({
        type: GET_PDF_SAVE_STATUS,
        jobId,
      } satisfies GetPdfSaveStatusMessage) as PdfSaveJobStatus | undefined;
    } catch {
      status = undefined;
    }

    if (!status || status.state === "missing") {
      missingPolls += 1;
      if (missingPolls >= 20) throw new Error("PDF save context was interrupted");
      continue;
    }
    missingPolls = 0;
    if (status.state === "running") continue;
    if (status.state === "error") throw new Error(status.error);
    return status.result;
  }
  const minutes = Math.max(1, Math.ceil(jobTimeoutMs / 60_000));
  throw new Error(`PDF save timed out after ${minutes} minute${minutes === 1 ? "" : "s"}`);
}
