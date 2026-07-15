import { afterEach, describe, expect, it, vi } from "vitest";

import { PdfIngestError } from "./api";
import { savePdfFromTab } from "./pdf-save";

const API_URL = "https://api.llmwiki.app";
const ACCESS_TOKEN = "test-access-token";
const KNOWLEDGE_BASE_ID = "7b067d6f-2cd1-4ee1-8d83-34136f4f59a9";
const PDF_URL = "https://private.example/report.pdf?ref=mail&signature=a%2Bb";
const PATH = "/research/";

function request(accessToken: string | null = ACCESS_TOKEN) {
  return {
    url: PDF_URL,
    apiUrl: API_URL,
    accessToken,
    knowledgeBaseId: KNOWLEDGE_BASE_ID,
    path: PATH,
  };
}

function pdfResponse(filename = "private-report.pdf"): Response {
  return new Response(new Blob(["%PDF-1.7 test"], { type: "application/pdf" }), {
    status: 200,
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `attachment; filename="${filename}"`,
    },
  });
}

function ingestError(status: number, detail: string): Error {
  return new PdfIngestError(status, detail);
}

function dependencies() {
  return {
    ingestPdfFromUrl: vi.fn(async () => ({ id: "fast-doc", status: "pending" })),
    fetchPdf: vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => pdfResponse()),
    uploadPdfBlob: vi.fn(async () => ({ id: "fallback-doc", status: "pending" })),
    setDocumentSourceUrl: vi.fn(async () => undefined),
    maxPdfBytes: 100 * 1024 * 1024,
    downloadTimeoutMs: 120_000,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("savePdfFromTab", () => {
  it("uses hosted URL ingestion without downloading the PDF in Chrome", async () => {
    const deps = dependencies();

    await expect(savePdfFromTab(request(), deps)).resolves.toEqual({
      id: "fast-doc",
      status: "pending",
    });

    expect(deps.ingestPdfFromUrl).toHaveBeenCalledWith(
      API_URL,
      ACCESS_TOKEN,
      PDF_URL,
      KNOWLEDGE_BASE_ID,
      PATH,
    );
    expect(deps.fetchPdf).not.toHaveBeenCalled();
    expect(deps.uploadPdfBlob).not.toHaveBeenCalled();
    expect(deps.setDocumentSourceUrl).not.toHaveBeenCalled();
  });

  it("falls back in the same context for a PDF the hosted fetcher cannot reach", async () => {
    const deps = dependencies();
    deps.ingestPdfFromUrl.mockRejectedValueOnce(
      ingestError(400, "URL host is not publicly reachable"),
    );

    const result = await savePdfFromTab(request(), deps);

    expect(deps.fetchPdf).toHaveBeenCalledWith(
      PDF_URL,
      expect.objectContaining({
        credentials: "include",
        cache: "default",
        headers: { Accept: "application/pdf,*/*" },
        signal: expect.any(AbortSignal),
      }),
    );
    expect(deps.uploadPdfBlob).toHaveBeenCalledWith(
      API_URL,
      ACCESS_TOKEN,
      expect.any(Blob),
      "private-report.pdf",
      KNOWLEDGE_BASE_ID,
      PATH,
    );
    expect(deps.setDocumentSourceUrl).toHaveBeenCalledWith(
      API_URL,
      ACCESS_TOKEN,
      "fallback-doc",
      PDF_URL,
    );
    expect(result).toEqual({
      id: "fallback-doc",
      status: "pending",
      filename: "private-report.pdf",
    });
    expect(result).not.toHaveProperty("blob");
    expect(Object.values(result).some(Array.isArray)).toBe(false);
  });

  it("skips hosted URL ingestion in local mode", async () => {
    const deps = dependencies();

    await expect(savePdfFromTab(request(null), deps)).resolves.toMatchObject({
      id: "fallback-doc",
      status: "pending",
    });

    expect(deps.ingestPdfFromUrl).not.toHaveBeenCalled();
    expect(deps.fetchPdf).toHaveBeenCalledOnce();
    expect(deps.uploadPdfBlob).toHaveBeenCalledWith(
      API_URL,
      null,
      expect.any(Blob),
      "private-report.pdf",
      KNOWLEDGE_BASE_ID,
      PATH,
    );
    expect(deps.setDocumentSourceUrl).toHaveBeenCalledWith(
      API_URL,
      null,
      "fallback-doc",
      PDF_URL,
    );
  });

  it.each([
    [401, "Not authenticated"],
    [403, "Knowledge base not found or not owned by you"],
    [413, "Storage quota exceeded"],
    [429, "Rate limit exceeded"],
    [500, "Internal server error"],
  ])("does not mask a non-fetch ingest error (%i)", async (status, detail) => {
    const deps = dependencies();
    const error = ingestError(status, detail);
    deps.ingestPdfFromUrl.mockRejectedValueOnce(error);

    await expect(savePdfFromTab(request(), deps)).rejects.toBe(error);
    expect(deps.fetchPdf).not.toHaveBeenCalled();
    expect(deps.uploadPdfBlob).not.toHaveBeenCalled();
  });

  it("can fall back when the URL-ingest service rejects a PDF at its own size cap", async () => {
    const deps = dependencies();
    deps.ingestPdfFromUrl.mockRejectedValueOnce(
      ingestError(413, "PDF exceeds the 50 MB download limit"),
    );

    await expect(savePdfFromTab(request(), deps)).resolves.toMatchObject({
      id: "fallback-doc",
    });
    expect(deps.fetchPdf).toHaveBeenCalledOnce();
  });

  it("accepts a compatibility status from an API without URL ingestion", async () => {
    const deps = dependencies();
    deps.ingestPdfFromUrl.mockRejectedValueOnce(
      ingestError(501, "URL ingestion is only available in hosted mode"),
    );

    await expect(savePdfFromTab(request(), deps)).resolves.toMatchObject({
      id: "fallback-doc",
    });
    expect(deps.fetchPdf).toHaveBeenCalledOnce();
    expect(deps.uploadPdfBlob).toHaveBeenCalledOnce();
  });

  it("skips URL ingestion when a signed URL exceeds the API's URL limit", async () => {
    const deps = dependencies();
    const longUrl = `https://private.example/report.pdf?signature=${"x".repeat(2_100)}`;

    await expect(savePdfFromTab({ ...request(), url: longUrl }, deps)).resolves.toMatchObject({
      id: "fallback-doc",
    });

    expect(deps.ingestPdfFromUrl).not.toHaveBeenCalled();
    expect(deps.fetchPdf).toHaveBeenCalledWith(longUrl, expect.any(Object));
  });

  it("rejects an HTML response before fallback upload", async () => {
    const deps = dependencies();
    deps.ingestPdfFromUrl.mockRejectedValueOnce(
      ingestError(400, "Could not fetch URL"),
    );
    deps.fetchPdf.mockResolvedValueOnce(
      new Response("<html>Please sign in</html>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      }),
    );

    await expect(savePdfFromTab(request(), deps)).rejects.toThrow(
      "This page did not return a PDF",
    );
    expect(deps.uploadPdfBlob).not.toHaveBeenCalled();
    expect(deps.setDocumentSourceUrl).not.toHaveBeenCalled();
  });

  it("rejects a declared PDF larger than 100 MiB before reading or uploading it", async () => {
    const deps = dependencies();
    deps.ingestPdfFromUrl.mockRejectedValueOnce(
      ingestError(400, "Could not fetch URL"),
    );
    deps.fetchPdf.mockResolvedValueOnce(
      new Response("%PDF-1.7", {
        status: 200,
        headers: {
          "Content-Type": "application/pdf",
          "Content-Length": String(100 * 1024 * 1024 + 1),
        },
      }),
    );

    await expect(savePdfFromTab(request(), deps)).rejects.toThrow(
      "PDF exceeds the 100 MiB upload limit",
    );
    expect(deps.uploadPdfBlob).not.toHaveBeenCalled();
  });

  it("caps the streamed body when Content-Length understates the PDF size", async () => {
    const deps = dependencies();
    deps.maxPdfBytes = 10;
    deps.ingestPdfFromUrl.mockRejectedValueOnce(
      ingestError(400, "Could not fetch URL"),
    );
    deps.fetchPdf.mockResolvedValueOnce(
      new Response("%PDF-12345x", {
        status: 200,
        headers: {
          "Content-Type": "application/pdf",
          "Content-Length": "5",
        },
      }),
    );

    await expect(savePdfFromTab(request(), deps)).rejects.toThrow(
      "PDF exceeds the 100 MiB upload limit",
    );
    expect(deps.uploadPdfBlob).not.toHaveBeenCalled();
  });

  it("keeps the timeout active while the response body is streaming", async () => {
    const deps = dependencies();
    deps.downloadTimeoutMs = 20;
    deps.ingestPdfFromUrl.mockRejectedValueOnce(
      ingestError(400, "Could not fetch URL"),
    );
    deps.fetchPdf.mockImplementationOnce(async (_input, init) => {
      const signal = init?.signal;
      return new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode("%PDF-"));
            signal?.addEventListener(
              "abort",
              () => controller.error(new DOMException("Aborted", "AbortError")),
              { once: true },
            );
          },
        }),
        { status: 200, headers: { "Content-Type": "application/pdf" } },
      );
    });

    await expect(savePdfFromTab(request(), deps)).rejects.toThrow(
      "PDF download timed out after 2 minutes",
    );
    expect(deps.uploadPdfBlob).not.toHaveBeenCalled();
  });

  it("decodes a Unicode content-disposition filename for the Blob upload", async () => {
    const deps = dependencies();
    deps.fetchPdf.mockResolvedValueOnce(
      new Response("%PDF-1.7 unicode", {
        status: 200,
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition":
            "attachment; filename*=UTF-8''r%C3%A9sum%C3%A9%20%E2%80%94%202026.pdf",
        },
      }),
    );

    await expect(savePdfFromTab(request(null), deps)).resolves.toMatchObject({
      filename: "résumé — 2026.pdf",
    });
    expect(deps.uploadPdfBlob).toHaveBeenCalledWith(
      API_URL,
      null,
      expect.any(Blob),
      "résumé — 2026.pdf",
      KNOWLEDGE_BASE_ID,
      PATH,
    );
  });

  it("does not turn a successful upload into a failure when source tagging fails", async () => {
    const deps = dependencies();
    const annotationError = new Error("metadata update unavailable");
    deps.setDocumentSourceUrl.mockRejectedValueOnce(annotationError);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(savePdfFromTab(request(null), deps)).resolves.toEqual({
      id: "fallback-doc",
      status: "pending",
      filename: "private-report.pdf",
    });
    expect(warn).toHaveBeenCalledWith(
      "[llmwiki] PDF saved but source URL could not be recorded",
      annotationError,
    );
  });
});
