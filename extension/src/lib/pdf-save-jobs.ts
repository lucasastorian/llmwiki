import type { SaveResult } from "./api";
import type { SavePdfFromTabRequest } from "./pdf-save";

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
}

const defaultDependencies: PdfSaveJobClientDependencies = {
  sendMessage: (message) => chrome.runtime.sendMessage(message),
  wait: (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
  createJobId: () => crypto.randomUUID(),
};

/**
 * Run a PDF save in the offscreen extension document and poll only its small
 * status object. Destroying the popup stops polling, but not the save itself.
 */
export async function runPdfSaveJob(
  request: SavePdfFromTabRequest,
  dependencies: PdfSaveJobClientDependencies = defaultDependencies,
): Promise<SaveResult> {
  const ready = await dependencies.sendMessage({ type: ENSURE_PDF_SAVE_CONTEXT }) as {
    ready?: boolean;
    error?: string;
  } | undefined;
  if (!ready?.ready) {
    throw new Error(ready?.error ?? "Could not start the PDF save context");
  }

  const jobId = dependencies.createJobId();
  const startMessage: StartPdfSaveMessage = { type: START_PDF_SAVE, jobId, request };
  let accepted = false;

  // createDocument resolves after the page is created, but allow a short load
  // window before treating a missing offscreen listener as a hard failure.
  for (let attempt = 0; attempt < 10 && !accepted; attempt += 1) {
    if (attempt > 0) {
      try {
        await dependencies.sendMessage({ type: ENSURE_PDF_SAVE_CONTEXT });
      } catch {
        // The previous context may be finishing its idle shutdown.
      }
    }
    try {
      const response = await dependencies.sendMessage(startMessage) as {
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
  while (true) {
    await dependencies.wait(250);
    let status: PdfSaveJobStatus | undefined;
    try {
      status = await dependencies.sendMessage({
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
}
