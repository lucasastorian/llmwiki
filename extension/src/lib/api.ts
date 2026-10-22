import {
  API_READ_TIMEOUT_MS,
  API_WRITE_TIMEOUT_MS,
  PDF_UPLOAD_TIMEOUT_MS,
  runWithDeadline,
  runtimeMessageWithDeadline,
} from "./deadline";

export interface KnowledgeBase {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  source_count: number;
  wiki_page_count: number;
  created_at: string;
  updated_at: string;
}

export interface SaveResult {
  id: string;
  status: string;
  version?: number;
  highlights?: Highlight[];
  filename?: string;
  title?: string | null;
  path?: string;
  knowledge_base_id?: string;
  already_exists?: boolean;
}

export class PdfIngestError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail || `PDF URL ingest failed (${status})`);
    this.name = "PdfIngestError";
  }
}

export interface HighlightAnchor {
  xpath: string;
  endXPath?: string;
  startOffset: number;
  endOffset: number;
  textContent: string;
  prefix?: string | null;
  suffix?: string | null;
}

export interface TextAnchor {
  textStart: number;
  textEnd: number;
  textContent: string;
  prefix?: string | null;
  suffix?: string | null;
}

export interface Highlight {
  id: string;
  type: "text" | "pdf";
  anchor?: HighlightAnchor | null;
  textAnchor?: TextAnchor | null;
  comment: string | null;
  color: string;
  createdAt: string;
}

export interface DocumentByUrl {
  id: string;
  knowledge_base_id: string;
  title: string | null;
  path: string;
  filename: string;
  version: number;
  highlights: Highlight[];
}

export interface HighlightsResponse {
  id: string;
  version: number;
  highlights: Highlight[];
}

function authHeaders(accessToken: string | null): Record<string, string> {
  if (!accessToken) return {};
  return { Authorization: `Bearer ${accessToken}` };
}

function jsonHeaders(accessToken: string | null): Record<string, string> {
  return {
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    "Content-Type": "application/json",
  };
}

async function errorDetail(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) return `Request failed (${response.status})`;
  try {
    const data = JSON.parse(text) as { detail?: unknown };
    return typeof data.detail === "string" ? data.detail : text;
  } catch {
    return text;
  }
}

function utf8Base64(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

// MV3 content scripts fetch from the page origin and hit CORS/CSP, so they proxy through the background.
function isContentScriptContext(): boolean {
  if (typeof window === "undefined") return false;
  return window.location.protocol !== "chrome-extension:";
}

interface SmartFetchInit {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  timeoutMs?: number;
}

interface SmartFetchResponse {
  ok: boolean;
  status: number;
  data: unknown;
  text: string;
}

async function smartFetch(url: string, init?: SmartFetchInit): Promise<SmartFetchResponse> {
  const timeoutMs = init?.timeoutMs ?? API_READ_TIMEOUT_MS;
  if (isContentScriptContext()) {
    const resp = await runtimeMessageWithDeadline<{
      ok?: boolean;
      status?: number;
      data?: unknown;
      error?: string;
    }>(
      {
        type: "API_FETCH",
        url,
        method: init?.method ?? "GET",
        headers: init?.headers,
        body: init?.body,
        timeoutMs,
      },
      timeoutMs + 1_000,
      "The API request did not receive a background response",
    );
    if (resp?.error && resp?.status === 0) {
      throw new Error(resp.error);
    }
    const text =
      typeof resp?.data === "string"
        ? resp.data
        : resp?.data
          ? JSON.stringify(resp.data)
          : "";
    return {
      ok: !!resp?.ok,
      status: resp?.status ?? 0,
      data: resp?.data ?? null,
      text,
    };
  }
  return runWithDeadline(async (signal) => {
    const res = await fetch(url, {
      method: init?.method,
      headers: init?.headers,
      body: init?.body,
      signal,
    });
    const text = await res.text();
    let data: unknown = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    return { ok: res.ok, status: res.status, data, text };
  }, timeoutMs, `API request timed out after ${Math.ceil(timeoutMs / 1_000)} seconds`);
}

export async function fetchKnowledgeBases(
  apiUrl: string,
  accessToken: string | null,
): Promise<KnowledgeBase[]> {
  const res = await smartFetch(`${apiUrl}/v1/knowledge-bases`, {
    headers: authHeaders(accessToken),
  });
  if (!res.ok) throw new Error(`Failed to fetch knowledge bases: ${res.status}`);
  return res.data as KnowledgeBase[];
}

export async function createKnowledgeBase(
  apiUrl: string,
  accessToken: string | null,
  name: string,
): Promise<KnowledgeBase> {
  const res = await smartFetch(`${apiUrl}/v1/knowledge-bases`, {
    method: "POST",
    headers: jsonHeaders(accessToken),
    body: JSON.stringify({ name }),
    timeoutMs: API_WRITE_TIMEOUT_MS,
  });
  if (!res.ok) throw new Error(`Failed to create knowledge base: ${res.status}`);
  return res.data as KnowledgeBase;
}

export async function saveWebPage(
  apiUrl: string,
  accessToken: string | null,
  knowledgeBaseId: string,
  payload: { url: string; title: string; html: string; path?: string; highlights?: Highlight[] },
): Promise<SaveResult> {
  const res = await smartFetch(
    `${apiUrl}/v1/knowledge-bases/${knowledgeBaseId}/documents/web`,
    {
      method: "POST",
      headers: jsonHeaders(accessToken),
      body: JSON.stringify(payload),
      timeoutMs: API_WRITE_TIMEOUT_MS,
    },
  );
  if (!res.ok) {
    throw new Error(`Save failed (${res.status}): ${res.text}`);
  }
  return res.data as SaveResult;
}

export async function getDocumentByUrl(
  apiUrl: string,
  accessToken: string | null,
  url: string,
): Promise<DocumentByUrl | null> {
  const res = await smartFetch(
    `${apiUrl}/v1/documents/by-url?url=${encodeURIComponent(url)}`,
    { headers: authHeaders(accessToken) },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Lookup failed: ${res.status}`);
  return res.data as DocumentByUrl;
}

export async function getHighlights(
  apiUrl: string,
  accessToken: string | null,
  documentId: string,
): Promise<HighlightsResponse> {
  const res = await smartFetch(
    `${apiUrl}/v1/documents/${documentId}/highlights`,
    { headers: authHeaders(accessToken) },
  );
  if (!res.ok) throw new Error(`Fetch highlights failed: ${res.status}`);
  return res.data as HighlightsResponse;
}

export async function moveDocument(
  apiUrl: string,
  accessToken: string | null,
  documentId: string,
  knowledgeBaseId: string,
): Promise<void> {
  const res = await smartFetch(`${apiUrl}/v1/documents/${documentId}`, {
    method: "PATCH",
    headers: jsonHeaders(accessToken),
    body: JSON.stringify({ knowledge_base_id: knowledgeBaseId }),
    timeoutMs: API_WRITE_TIMEOUT_MS,
  });
  if (!res.ok) {
    throw new Error(`Move failed (${res.status})`);
  }
}

export async function ingestPdfFromUrl(
  apiUrl: string,
  accessToken: string,
  url: string,
  knowledgeBaseId: string,
  path = "/webclipper/",
): Promise<SaveResult> {
  return runWithDeadline(async (signal) => {
    const response = await fetch(`${apiUrl}/v1/documents/from-url`, {
      method: "POST",
      headers: jsonHeaders(accessToken),
      body: JSON.stringify({
        knowledge_base_id: knowledgeBaseId,
        url,
        path,
      }),
      signal,
    });
    if (!response.ok) {
      throw new PdfIngestError(response.status, await errorDetail(response));
    }
    return response.json() as Promise<SaveResult>;
  }, API_WRITE_TIMEOUT_MS, "PDF URL ingestion timed out");
}

export async function setDocumentSourceUrl(
  apiUrl: string,
  accessToken: string | null,
  documentId: string,
  sourceUrl: string,
): Promise<void> {
  await runWithDeadline(async (signal) => {
    const response = await fetch(`${apiUrl}/v1/documents/${documentId}`, {
      method: "PATCH",
      headers: jsonHeaders(accessToken),
      body: JSON.stringify({ metadata: { source_url: sourceUrl } }),
      signal,
    });
    if (!response.ok) {
      throw new Error(`Could not record PDF source URL (${response.status})`);
    }
  }, API_READ_TIMEOUT_MS, "Recording the PDF source URL timed out");
}

export async function upsertHighlight(
  apiUrl: string,
  accessToken: string | null,
  documentId: string,
  highlight: Highlight,
  expectedVersion?: number,
): Promise<HighlightsResponse> {
  const res = await smartFetch(
    `${apiUrl}/v1/documents/${documentId}/highlights`,
    {
      method: "POST",
      headers: jsonHeaders(accessToken),
      body: JSON.stringify({ highlight, expectedVersion }),
      timeoutMs: API_WRITE_TIMEOUT_MS,
    },
  );
  if (res.status === 409) {
    throw Object.assign(new Error("Version conflict"), { conflict: true });
  }
  if (!res.ok) {
    throw new Error(`Save highlight failed (${res.status}): ${res.text}`);
  }
  return res.data as HighlightsResponse;
}

export async function deleteHighlight(
  apiUrl: string,
  accessToken: string | null,
  documentId: string,
  highlightId: string,
  expectedVersion?: number,
): Promise<HighlightsResponse> {
  const params = expectedVersion === undefined
    ? ""
    : `?expectedVersion=${encodeURIComponent(String(expectedVersion))}`;
  const res = await smartFetch(
    `${apiUrl}/v1/documents/${documentId}/highlights/${encodeURIComponent(highlightId)}${params}`,
    {
      method: "DELETE",
      headers: authHeaders(accessToken),
      timeoutMs: API_WRITE_TIMEOUT_MS,
    },
  );
  if (res.status === 409) {
    throw Object.assign(new Error("Version conflict"), { conflict: true });
  }
  if (!res.ok) {
    throw new Error(`Delete highlight failed (${res.status}): ${res.text}`);
  }
  return res.data as HighlightsResponse;
}

export async function uploadPdfBlob(
  apiUrl: string,
  accessToken: string | null,
  pdf: Blob,
  filename: string,
  knowledgeBaseId: string,
  path = "/webclipper/",
): Promise<SaveResult> {
  // No token means local mode, which takes multipart instead of TUS.
  if (!accessToken) {
    const form = new FormData();
    form.append("file", pdf, filename);
    form.append("path", path);
    return runWithDeadline(async (signal) => {
      const res = await fetch(`${apiUrl}/v1/upload`, {
        method: "POST",
        body: form,
        signal,
      });
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
      const data = await res.json();
      return { id: data.id, status: "pending" };
    }, PDF_UPLOAD_TIMEOUT_MS, "PDF upload timed out");
  }

  const metadata = [
    `filename ${utf8Base64(filename)}`,
    `knowledge_base_id ${utf8Base64(knowledgeBaseId)}`,
    `path ${utf8Base64(path)}`,
  ].join(",");

  const { response: createRes, errorText: createErrorText } = await runWithDeadline(
    async (signal) => {
      const response = await fetch(`${apiUrl}/v1/uploads`, {
        method: "POST",
        headers: {
          ...authHeaders(accessToken),
          "Tus-Resumable": "1.0.0",
          "Upload-Length": String(pdf.size),
          "Upload-Metadata": metadata,
        },
        signal,
      });
      return {
        response,
        errorText: response.ok ? "" : await response.text(),
      };
    },
    API_WRITE_TIMEOUT_MS,
    "PDF upload initialization timed out",
  );
  if (!createRes.ok) {
    throw new Error(`Upload init failed (${createRes.status}): ${createErrorText}`);
  }

  const location = createRes.headers.get("Location");
  if (!location) throw new Error("No Location header in TUS response");
  const uploadUrl = location.startsWith("http")
    ? location
    : `${apiUrl}${location}`;

  const patchRes = await runWithDeadline(
    (signal) => fetch(uploadUrl, {
      method: "PATCH",
      headers: {
        ...authHeaders(accessToken),
        "Tus-Resumable": "1.0.0",
        "Upload-Offset": "0",
        "Content-Type": "application/offset+octet-stream",
      },
      body: pdf,
      signal,
    }),
    PDF_UPLOAD_TIMEOUT_MS,
    "PDF upload timed out",
  );
  if (!patchRes.ok && patchRes.status !== 204) {
    throw new Error(`Upload failed: ${patchRes.status}`);
  }

  const documentId = patchRes.headers.get("X-Document-Id");
  if (!documentId) throw new Error("Upload completed without a document id");
  return { id: documentId, status: "pending" };
}
