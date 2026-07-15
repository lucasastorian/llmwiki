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

// ── smartFetch ──────────────────────────────────────────────
//
// MV3 content scripts make `fetch` calls from the page's origin. Most sites
// (Substack, Medium, console.cloud.google.com, anywhere with strict CSP) will
// block our API calls via CORS or CSP. The background service worker runs on
// the extension origin and holds the required host permission for the API
// origin — fetches there succeed. So when we're inside a content script we
// proxy through the background via chrome.runtime.sendMessage. In the popup
// (which loads on chrome-extension://...) direct fetch already works, so we
// use it.

function isContentScriptContext(): boolean {
  if (typeof window === "undefined") return false;
  // popup/background pages have chrome-extension:// origin
  return window.location.protocol !== "chrome-extension:";
}

interface SmartFetchInit {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
}

interface SmartFetchResponse {
  ok: boolean;
  status: number;
  data: unknown;
  text: string;
}

async function smartFetch(url: string, init?: SmartFetchInit): Promise<SmartFetchResponse> {
  if (isContentScriptContext()) {
    const resp = await chrome.runtime.sendMessage({
      type: "API_FETCH",
      url,
      method: init?.method ?? "GET",
      headers: init?.headers,
      body: init?.body,
    });
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
  const res = await fetch(url, init);
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
  const res = await fetch(`${apiUrl}/v1/knowledge-bases`, {
    method: "POST",
    headers: jsonHeaders(accessToken),
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(`Failed to create knowledge base: ${res.status}`);
  return res.json();
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

export async function replaceHighlights(
  apiUrl: string,
  accessToken: string | null,
  documentId: string,
  highlights: Highlight[],
  expectedVersion?: number,
): Promise<HighlightsResponse> {
  const res = await smartFetch(
    `${apiUrl}/v1/documents/${documentId}/highlights`,
    {
      method: "PATCH",
      headers: jsonHeaders(accessToken),
      body: JSON.stringify({ highlights, expectedVersion }),
    },
  );
  if (res.status === 409) {
    throw Object.assign(new Error("Version conflict"), { conflict: true });
  }
  if (!res.ok) {
    throw new Error(`Save highlights failed (${res.status}): ${res.text}`);
  }
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
  const response = await fetch(`${apiUrl}/v1/documents/from-url`, {
    method: "POST",
    headers: jsonHeaders(accessToken),
    body: JSON.stringify({
      knowledge_base_id: knowledgeBaseId,
      url,
      path,
    }),
  });
  if (!response.ok) {
    throw new PdfIngestError(response.status, await errorDetail(response));
  }
  return response.json() as Promise<SaveResult>;
}

export async function setDocumentSourceUrl(
  apiUrl: string,
  accessToken: string | null,
  documentId: string,
  sourceUrl: string,
): Promise<void> {
  const response = await fetch(`${apiUrl}/v1/documents/${documentId}`, {
    method: "PATCH",
    headers: jsonHeaders(accessToken),
    body: JSON.stringify({ metadata: { source_url: sourceUrl } }),
  });
  if (!response.ok) {
    throw new Error(`Could not record PDF source URL (${response.status})`);
  }
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
  // Local mode: use multipart upload
  if (!accessToken) {
    const form = new FormData();
    form.append("file", pdf, filename);
    form.append("path", path);
    const res = await fetch(`${apiUrl}/v1/upload`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    const data = await res.json();
    return { id: data.id, status: "pending" };
  }

  // Cloud mode: TUS upload
  const metadata = [
    `filename ${utf8Base64(filename)}`,
    `knowledge_base_id ${utf8Base64(knowledgeBaseId)}`,
    `path ${utf8Base64(path)}`,
  ].join(",");

  const createRes = await fetch(`${apiUrl}/v1/uploads`, {
    method: "POST",
    headers: {
      ...authHeaders(accessToken),
      "Tus-Resumable": "1.0.0",
      "Upload-Length": String(pdf.size),
      "Upload-Metadata": metadata,
    },
  });
  if (!createRes.ok) {
    const text = await createRes.text();
    throw new Error(`Upload init failed (${createRes.status}): ${text}`);
  }

  const location = createRes.headers.get("Location");
  if (!location) throw new Error("No Location header in TUS response");
  const uploadUrl = location.startsWith("http")
    ? location
    : `${apiUrl}${location}`;

  const patchRes = await fetch(uploadUrl, {
    method: "PATCH",
    headers: {
      ...authHeaders(accessToken),
      "Tus-Resumable": "1.0.0",
      "Upload-Offset": "0",
      "Content-Type": "application/offset+octet-stream",
    },
    body: pdf,
  });
  if (!patchRes.ok && patchRes.status !== 204) {
    throw new Error(`Upload failed: ${patchRes.status}`);
  }

  const documentId = patchRes.headers.get("X-Document-Id");
  if (!documentId) throw new Error("Upload completed without a document id");
  return { id: documentId, status: "pending" };
}
