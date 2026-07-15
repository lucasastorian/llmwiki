import { describe, expect, it, vi } from "vitest";

import {
  ENSURE_PDF_SAVE_CONTEXT,
  GET_PDF_SAVE_STATUS,
  START_PDF_SAVE,
  runPdfSaveJob,
  type PdfSaveJobClientDependencies,
} from "./pdf-save-jobs";

const request = {
  url: "https://private.example/report.pdf?signature=abc",
  apiUrl: "https://api.llmwiki.app",
  accessToken: "access-token",
  knowledgeBaseId: "7b067d6f-2cd1-4ee1-8d83-34136f4f59a9",
  path: "/research/",
};

function dependencies(responses: unknown[]): PdfSaveJobClientDependencies & {
  messages: unknown[];
} {
  const messages: unknown[] = [];
  return {
    messages,
    createJobId: () => "pdf-job-1",
    wait: vi.fn(async () => undefined),
    sendMessage: vi.fn(async (message: unknown) => {
      messages.push(message);
      return responses.shift();
    }),
  };
}

describe("runPdfSaveJob", () => {
  it("relays only a small job request and polls its offscreen status", async () => {
    const deps = dependencies([
      { ready: true },
      undefined,
      { ready: true },
      { accepted: true },
      { state: "running" },
      { state: "success", result: { id: "doc-1", status: "pending" } },
    ]);

    await expect(runPdfSaveJob(request, deps)).resolves.toEqual({
      id: "doc-1",
      status: "pending",
    });

    expect(deps.messages).toEqual([
      { type: ENSURE_PDF_SAVE_CONTEXT },
      { type: START_PDF_SAVE, jobId: "pdf-job-1", request },
      { type: ENSURE_PDF_SAVE_CONTEXT },
      { type: START_PDF_SAVE, jobId: "pdf-job-1", request },
      { type: GET_PDF_SAVE_STATUS, jobId: "pdf-job-1" },
      { type: GET_PDF_SAVE_STATUS, jobId: "pdf-job-1" },
    ]);
    expect(JSON.stringify(deps.messages)).not.toContain("blob");
  });

  it("surfaces the terminal error reported by the offscreen job", async () => {
    const deps = dependencies([
      { ready: true },
      { accepted: true },
      { state: "error", error: "PDF download failed (403)" },
    ]);

    await expect(runPdfSaveJob(request, deps)).rejects.toThrow(
      "PDF download failed (403)",
    );
  });

  it("fails clearly when the background cannot create the durable context", async () => {
    const deps = dependencies([{ error: "Offscreen API unavailable" }]);

    await expect(runPdfSaveJob(request, deps)).rejects.toThrow(
      "Offscreen API unavailable",
    );
    expect(deps.messages).toEqual([{ type: ENSURE_PDF_SAVE_CONTEXT }]);
  });
});
