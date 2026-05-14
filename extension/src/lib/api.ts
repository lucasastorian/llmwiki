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

export interface Highlight {
  id: string;
  type: "text" | "pdf";
  anchor?: HighlightAnchor | null;
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

// ── smartFetch ──────────────────────────────────────────────
//
// MV3 content scripts make `fetch` calls from the page's origin. Most sites
// (Substack, Medium, console.cloud.google.com, anywhere with strict CSP) will
// block our API calls via CORS or CSP. The background service worker runs on
// the extension origin with host_permissions: ["<all_urls>"] — fetches there
// succeed. So when we're inside a content script we proxy through the
// background via chrome.runtime.sendMessage. In the popup (which loads on
// chrome-extension://...) direct fetch already works, so we use it.

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
  const res = await fetch(`${apiUrl}/v1/knowledge-bases`, {
    headers: authHeaders(accessToken),
  });
  if (!res.ok) throw new Error(`Failed to fetch knowledge bases: ${res.status}`);
  return res.json();
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
  payload: { url: string; title: string; html: string; highlights?: Highlight[] },
): Promise<SaveResult> {
  const res = await fetch(
    `${apiUrl}/v1/knowledge-bases/${knowledgeBaseId}/documents/web`,
    {
      method: "POST",
      headers: jsonHeaders(accessToken),
      body: JSON.stringify(payload),
    },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Save failed (${res.status}): ${text}`);
  }
  return res.json();
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

export async function savePdf(
  apiUrl: string,
  accessToken: string | null,
  pdfBytes: Uint8Array,
  filename: string,
  knowledgeBaseId: string,
): Promise<SaveResult> {
  // Copy bytes into a fresh ArrayBuffer so the resulting Blob/body matches
  // the BodyInit / BlobPart types regardless of the source buffer's TypedArray
  // backing (some lib.dom.d.ts versions reject SharedArrayBuffer-backed views).
  const pdfBuffer = new ArrayBuffer(pdfBytes.byteLength);
  new Uint8Array(pdfBuffer).set(pdfBytes);

  // Local mode: use multipart upload
  if (!accessToken) {
    const form = new FormData();
    form.append("file", new Blob([pdfBuffer], { type: "application/pdf" }), filename);
    form.append("path", "/webclipper/");
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
    `filename ${btoa(filename)}`,
    `knowledge_base_id ${btoa(knowledgeBaseId)}`,
    `path ${btoa("/webclipper/")}`,
  ].join(",");

  const createRes = await fetch(`${apiUrl}/v1/uploads`, {
    method: "POST",
    headers: {
      ...authHeaders(accessToken),
      "Tus-Resumable": "1.0.0",
      "Upload-Length": String(pdfBuffer.byteLength),
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
    body: pdfBuffer,
  });
  if (!patchRes.ok && patchRes.status !== 204) {
    throw new Error(`Upload failed: ${patchRes.status}`);
  }

  const documentId = patchRes.headers.get("X-Document-Id") ?? "";
  return { id: documentId, status: "pending" };
}
