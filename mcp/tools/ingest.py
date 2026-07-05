"""Source ingestion — pull a public PDF into a knowledge base by URL (hosted mode only)."""

import httpx
from mcp.server.fastmcp import FastMCP, Context

from config import settings

INGEST_TIMEOUT = 120


def _bearer_token() -> str | None:
    from mcp.server.auth.middleware.auth_context import get_access_token

    access_token = get_access_token()
    return access_token.token if access_token else None


def register(mcp: FastMCP, get_user_id, fs_factory) -> None:

    @mcp.tool(
        name="add_source_from_url",
        description=(
            "Download a publicly accessible PDF by URL and add it to a knowledge base "
            "as a source document. Works with arXiv links (abstract or PDF URLs), "
            "papers, reports — any direct PDF link.\n\n"
            "The PDF is extracted and indexed in the background; it becomes readable "
            "and searchable a minute or two after this returns. PDFs only — for web "
            "pages the user should use the browser extension."
        ),
    )
    async def add_source_from_url(
        ctx: Context,
        knowledge_base: str,
        url: str,
        path: str = "/",
    ) -> str:
        url = url.strip()
        if not url.lower().startswith(("http://", "https://")):
            return "Error: url must be a public http(s) address."

        user_id = get_user_id(ctx)
        fs = fs_factory(user_id)
        kb = await fs.resolve_kb(knowledge_base)
        if not kb:
            return f"Error: knowledge base '{knowledge_base}' not found."

        token = _bearer_token()
        if not token:
            return "Error: not authenticated."

        result = await _post_from_url(str(kb["id"]), url, path, token)
        if result.get("error"):
            return f"Error: {result['error']}"
        if result.get("already_exists"):
            return (
                f"Already saved: **{result.get('title') or result.get('filename')}** "
                f"(`{result.get('filename')}`) — no duplicate was created."
            )
        return (
            f"Downloaded **{result['filename']}** into **{kb['name']}**. "
            "Extraction and indexing run in the background — the document becomes "
            "readable and searchable in a minute or two."
        )


async def _post_from_url(kb_id: str, url: str, path: str, token: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=INGEST_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.API_URL}/v1/documents/from-url",
                json={"knowledge_base_id": kb_id, "url": url, "path": path},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as e:
        return {"error": f"could not reach the ingestion service: {e}"}
    if resp.status_code in (200, 201):
        return resp.json()
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    return {"error": detail}
