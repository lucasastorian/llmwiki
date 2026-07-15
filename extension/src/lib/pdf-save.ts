import {
  ingestPdfFromUrl,
  PdfIngestError,
  setDocumentSourceUrl,
  uploadPdfBlob,
  type SaveResult,
} from "./api";

const MAX_PDF_BYTES = 100 * 1024 * 1024;
const DOWNLOAD_TIMEOUT_MS = 120_000;
const MAX_URL_INGEST_LENGTH = 2_048;

export interface SavePdfFromTabRequest {
  url: string;
  apiUrl: string;
  accessToken: string | null;
  knowledgeBaseId: string;
  path: string;
}

export interface SavePdfDependencies {
  ingestPdfFromUrl: typeof ingestPdfFromUrl;
  uploadPdfBlob: typeof uploadPdfBlob;
  setDocumentSourceUrl: typeof setDocumentSourceUrl;
  fetchPdf: typeof fetch;
  maxPdfBytes: number;
  downloadTimeoutMs: number;
}

const defaultDependencies: SavePdfDependencies = {
  ingestPdfFromUrl,
  uploadPdfBlob,
  setDocumentSourceUrl,
  fetchPdf: (input, init) => fetch(input, init),
  maxPdfBytes: MAX_PDF_BYTES,
  downloadTimeoutMs: DOWNLOAD_TIMEOUT_MS,
};

export function shouldUseBrowserPdfFallback(error: unknown): boolean {
  if (!(error instanceof PdfIngestError)) return false;
  if ([400, 404, 405, 501].includes(error.status)) return true;
  // URL ingestion caps public downloads at 50 MiB while authenticated TUS
  // uploads support 100 MiB. Do not confuse that limit with account quota 413s.
  return error.status === 413 && /PDF exceeds the \d+ MB download limit/i.test(error.detail);
}

export async function savePdfFromTab(
  request: SavePdfFromTabRequest,
  dependencies: SavePdfDependencies = defaultDependencies,
): Promise<SaveResult> {
  const { url, apiUrl, accessToken, knowledgeBaseId, path } = request;

  // Public hosted PDFs can travel publisher -> API -> S3. This avoids both the
  // browser upload and Chrome runtime messaging entirely, and the API records
  // source_url so repeat saves are deduplicated.
  if (accessToken && isHttpUrl(url) && url.length <= MAX_URL_INGEST_LENGTH) {
    try {
      return await dependencies.ingestPdfFromUrl(
        apiUrl,
        accessToken,
        url,
        knowledgeBaseId,
        path,
      );
    } catch (error) {
      if (!shouldUseBrowserPdfFallback(error)) throw error;
    }
  }

  // Private, cookie-authenticated, large, and local PDFs stay as a Blob in the
  // durable offscreen document. No PDF bytes cross Chrome runtime messaging.
  const { response, pdf } = await downloadPdf(
    dependencies.fetchPdf,
    url,
    dependencies.maxPdfBytes,
    dependencies.downloadTimeoutMs,
  );
  if (!(await hasPdfSignature(pdf))) {
    throw new Error("This page did not return a PDF. It may require signing in again.");
  }

  const filename = pdfFilename(response, url);
  const result = await dependencies.uploadPdfBlob(
    apiUrl,
    accessToken,
    pdf,
    filename,
    knowledgeBaseId,
    path,
  );

  // Upload endpoints predate URL ingestion, so record the source immediately
  // afterward. Saving succeeded even if this best-effort dedupe annotation
  // fails; surfacing an error here would encourage a duplicate retry.
  try {
    await dependencies.setDocumentSourceUrl(apiUrl, accessToken, result.id, url);
  } catch (error) {
    console.warn("[llmwiki] PDF saved but source URL could not be recorded", error);
  }

  return { ...result, filename };
}

async function downloadPdf(
  fetchPdf: typeof fetch,
  url: string,
  maxBytes: number,
  timeoutMs: number,
): Promise<{ response: Response; pdf: Blob }> {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const response = await fetchPdf(url, {
      credentials: "include",
      cache: "default",
      headers: { Accept: "application/pdf,*/*" },
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`PDF download failed (${response.status})`);
    }

    const declaredSize = Number(response.headers.get("content-length"));
    if (Number.isFinite(declaredSize) && declaredSize > maxBytes) {
      await response.body?.cancel();
      throw pdfTooLargeError();
    }

    if (!response.body) {
      throw new Error("PDF download returned an empty response body");
    }

    const reader = response.body.getReader();
    const chunks: ArrayBuffer[] = [];
    let received = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!value?.byteLength) continue;

        received += value.byteLength;
        if (received > maxBytes) {
          await reader.cancel();
          throw pdfTooLargeError();
        }

        // Give Blob ArrayBuffer-backed chunks. This also releases the fetch
        // implementation's buffers as the stream advances.
        const copy = new ArrayBuffer(value.byteLength);
        new Uint8Array(copy).set(value);
        chunks.push(copy);
      }
    } finally {
      reader.releaseLock();
    }

    return {
      response,
      pdf: new Blob(chunks, {
        type: response.headers.get("content-type") ?? "application/pdf",
      }),
    };
  } catch (error) {
    if (timedOut) {
      throw new Error("PDF download timed out after 2 minutes");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function pdfTooLargeError(): Error {
  return new Error("PDF exceeds the 100 MiB upload limit");
}

async function hasPdfSignature(pdf: Blob): Promise<boolean> {
  if (pdf.size < 5) return false;
  const signature = new Uint8Array(await pdf.slice(0, 5).arrayBuffer());
  return String.fromCharCode(...signature) === "%PDF-";
}

function isHttpUrl(value: string): boolean {
  try {
    const protocol = new URL(value).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

function pdfFilename(response: Response, sourceUrl: string): string {
  const disposition = response.headers.get("content-disposition") ?? "";
  const encoded = disposition.match(/filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i)?.[1];
  if (encoded) {
    const decoded = decodeFilename(encoded.replace(/^['"]|['"]$/g, ""));
    if (decoded) return sanitizePdfFilename(decoded);
  }

  const plain = disposition.match(/filename\s*=\s*(?:"([^"]+)"|([^;]+))/i);
  const headerName = plain?.[1] ?? plain?.[2];
  if (headerName?.trim()) return sanitizePdfFilename(headerName.trim());

  try {
    const segment = new URL(sourceUrl).pathname.split("/").pop() ?? "";
    return sanitizePdfFilename(decodeFilename(segment));
  } catch {
    return "document.pdf";
  }
}

function decodeFilename(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function sanitizePdfFilename(value: string): string {
  let name = value.replace(/\\/g, "/").split("/").pop() ?? "";
  name = name.replace(/[\x00-\x1f\x7f<>:"|?*]/g, "").trim().replace(/[. ]+$/, "");
  if (!name) name = "document";
  if (!name.toLowerCase().endsWith(".pdf")) name += ".pdf";
  if (name.length > 120) name = `${name.slice(0, 116).replace(/[. ]+$/, "")}.pdf`;
  return name;
}
