import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ingestPdfFromUrl,
  setDocumentSourceUrl,
  uploadPdfBlob,
} from "./api";

const API_URL = "https://api.llmwiki.app";
const ACCESS_TOKEN = "test-access-token";
const KNOWLEDGE_BASE_ID = "7b067d6f-2cd1-4ee1-8d83-34136f4f59a9";

function response(
  status: number,
  data?: unknown,
  headers?: Record<string, string>,
): Response {
  return new Response(data === undefined ? null : JSON.stringify(data), {
    status,
    headers: {
      ...(data === undefined ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PDF API helpers", () => {
  it("ingests a hosted PDF by URL without relaying its bytes through the extension", async () => {
    const result = { id: "doc-from-url", status: "pending" };
    const fetchMock = vi.fn(async () => response(201, result));
    vi.stubGlobal("fetch", fetchMock);

    const pdfUrl = "https://papers.example/report.pdf?ref=mail&signature=a%2Bb";
    await expect(
      ingestPdfFromUrl(
        API_URL,
        ACCESS_TOKEN,
        pdfUrl,
        KNOWLEDGE_BASE_ID,
        "/research/",
      ),
    ).resolves.toEqual(result);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(`${API_URL}/v1/documents/from-url`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${ACCESS_TOKEN}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        knowledge_base_id: KNOWLEDGE_BASE_ID,
        url: pdfUrl,
        path: "/research/",
      }),
    });
  });

  it("uploads the original Blob in local mode instead of materializing a number array", async () => {
    const fetchMock = vi.fn(async () => response(201, { id: "local-doc" }));
    vi.stubGlobal("fetch", fetchMock);
    const pdf = new Blob(["%PDF-test"], { type: "application/pdf" });

    await expect(
      uploadPdfBlob(
        API_URL,
        null,
        pdf,
        "report.pdf",
        KNOWLEDGE_BASE_ID,
        "/research/",
      ),
    ).resolves.toEqual({ id: "local-doc", status: "pending" });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${API_URL}/v1/upload`);
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const form = init.body as FormData;
    const uploadedFile = form.get("file");
    expect(uploadedFile).toBeInstanceOf(Blob);
    expect((uploadedFile as Blob).size).toBe(pdf.size);
    expect((uploadedFile as Blob).type).toBe("application/pdf");
    expect(form.get("path")).toBe("/research/");
  });

  it("uploads a Blob through TUS in hosted fallback mode", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        response(201, undefined, { Location: "/v1/uploads/upload-1" }),
      )
      .mockResolvedValueOnce(
        response(204, undefined, { "X-Document-Id": "hosted-doc" }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const pdf = new Blob(["%PDF-hosted-test"], { type: "application/pdf" });

    await expect(
      uploadPdfBlob(
        API_URL,
        ACCESS_TOKEN,
        pdf,
        "report.pdf",
        KNOWLEDGE_BASE_ID,
        "/research/",
      ),
    ).resolves.toEqual({ id: "hosted-doc", status: "pending" });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_URL}/v1/uploads`);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: "POST",
      headers: expect.objectContaining({
        Authorization: `Bearer ${ACCESS_TOKEN}`,
        "Tus-Resumable": "1.0.0",
        "Upload-Length": String(pdf.size),
      }),
    });
    expect(fetchMock.mock.calls[1]).toEqual([
      `${API_URL}/v1/uploads/upload-1`,
      expect.objectContaining({
        method: "PATCH",
        body: pdf,
        headers: expect.objectContaining({
          Authorization: `Bearer ${ACCESS_TOKEN}`,
          "Content-Type": "application/offset+octet-stream",
        }),
      }),
    ]);
  });

  it("records the source URL after a browser-side fallback upload", async () => {
    const fetchMock = vi.fn(async () => response(200, { id: "doc-1" }));
    vi.stubGlobal("fetch", fetchMock);
    const sourceUrl = "https://private.example/report.pdf?ref=mail&token=secret";

    await expect(
      setDocumentSourceUrl(API_URL, ACCESS_TOKEN, "doc-1", sourceUrl),
    ).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith(`${API_URL}/v1/documents/doc-1`, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${ACCESS_TOKEN}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ metadata: { source_url: sourceUrl } }),
    });
  });
});
