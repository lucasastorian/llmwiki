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

function authHeaders(accessToken: string | null): HeadersInit {
  if (!accessToken) return {};
  return { Authorization: `Bearer ${accessToken}` };
}

function jsonHeaders(accessToken: string | null): HeadersInit {
  return {
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    "Content-Type": "application/json",
  };
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
  payload: { url: string; title: string; html: string },
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

export async function savePdf(
  apiUrl: string,
  accessToken: string | null,
  pdfBytes: Uint8Array,
  filename: string,
  knowledgeBaseId: string,
): Promise<SaveResult> {
  // Local mode: use multipart upload
  if (!accessToken) {
    const form = new FormData();
    form.append("file", new Blob([pdfBytes], { type: "application/pdf" }), filename);
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
      "Upload-Length": String(pdfBytes.length),
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
    body: pdfBytes,
  });
  if (!patchRes.ok && patchRes.status !== 204) {
    throw new Error(`Upload failed: ${patchRes.status}`);
  }

  const documentId = patchRes.headers.get("X-Document-Id") ?? "";
  return { id: documentId, status: "pending" };
}
