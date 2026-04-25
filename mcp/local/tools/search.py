"""Local search tool — browses and searches workspace docs via SQLite + FTS5."""

import logging
from typing import Literal

from mcp.server.fastmcp import FastMCP, Context

from infra.db.sqlite import (
    list_knowledge_bases, list_documents, search_chunks, get_document,
    get_workspace,
)
from .helpers import get_user_id, deep_link, glob_match, resolve_path, MAX_LIST, MAX_SEARCH
from .references import query_references
from tools.search import _extract_snippet

logger = logging.getLogger(__name__)


async def _resolve_local_kb(user_id: str, slug: str) -> dict | None:
    ws = await get_workspace()
    if not ws:
        return None
    return {"id": ws["id"], "name": ws["name"], "slug": ws["name"]}


async def _list_all_kbs(user_id: str) -> str:
    kbs = await list_knowledge_bases(user_id)
    if not kbs:
        return "No workspace initialized."
    lines = ["**Knowledge Bases:**\n"]
    for kb in kbs:
        lines.append(f"  {kb['slug']}/ — {kb['name']} ({kb.get('source_count', 0)} sources, {kb.get('wiki_count', 0)} wiki pages)")
    return "\n".join(lines)


async def _list_docs(user_id: str, kb: dict, target: str, tags: list[str] | None) -> str:
    docs = await list_documents(user_id, kb["slug"])

    if target not in ("*", "**", "**/*"):
        glob_pat = "/" + target.lstrip("/") if not target.startswith("/") else target
        docs = [d for d in docs if glob_match(d["path"] + d["filename"], glob_pat)]

    if tags:
        tag_set = {t.lower() for t in tags}
        docs = [d for d in docs if tag_set.issubset({t.lower() for t in (d.get("tags") or [])})]

    if not docs:
        return f"No matches for `{target}` in {kb['slug']}."

    sources = [d for d in docs if not d["path"].startswith("/wiki/")]
    wiki_pages = [d for d in docs if d["path"].startswith("/wiki/")]

    lines = [f"**{kb['name']}** (`{target}`):\n"]

    if sources:
        lines.append(f"**Sources ({len(sources)}):**")
        for doc in sources[:MAX_LIST]:
            tag_str = f" [{', '.join(doc['tags'])}]" if doc.get("tags") else ""
            pages_part = f", {doc['page_count']}p" if doc.get("page_count") else ""
            lines.append(f"  {doc['path']}{doc['filename']} ({doc.get('file_type', '')}{pages_part}){tag_str}")
        if len(sources) > MAX_LIST:
            lines.append(f"  ... {len(sources) - MAX_LIST} more")

    if wiki_pages:
        if sources:
            lines.append("")
        lines.append(f"**Wiki ({len(wiki_pages)} pages):**")
        for doc in wiki_pages[:MAX_LIST]:
            lines.append(f"  {doc['path']}{doc['filename']}")

    return "\n".join(lines)


async def _search_local(user_id: str, kb: dict, query: str, path: str, tags: list[str] | None, limit: int) -> str:
    path_filter = None
    if path not in ("*", "**", "**/*"):
        if path.startswith("/wiki"):
            path_filter = "wiki"
        elif path == "/" or path == "/*":
            path_filter = "sources"

    matches = await search_chunks(user_id, kb["slug"], query, limit=limit, path_filter=path_filter)

    if tags:
        tag_set = {t.lower() for t in tags}
        matches = [m for m in matches if tag_set.issubset({t.lower() for t in (m.get("tags") or [])})]

    if not matches:
        return f"No matches for `{query}` in {kb['slug']}."

    lines = [f"**{len(matches)} result(s)** for `{query}`:\n"]
    for m in matches:
        filepath = f"{m['path']}{m['filename']}"
        page_str = f" (p.{m['page']})" if m.get("page") else ""
        breadcrumb = f"\n  {m['header_breadcrumb']}" if m.get("header_breadcrumb") else ""
        snippet = _extract_snippet(m.get("content", ""), query)
        link = deep_link(kb["slug"], m["path"], m["filename"])
        lines.append(f"**{filepath}**{page_str} — [view]({link}){breadcrumb}")
        lines.append(f"```\n{snippet}\n```\n")

    return "\n".join(lines)


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        name="search",
        description=(
            "Browse or search the knowledge vault.\n\n"
            "Sources (raw documents) live at `/`. Wiki pages (LLM-compiled) live at `/wiki/`.\n\n"
            "Modes:\n"
            "- list: browse files and folders\n"
            "- search: keyword search across document content\n"
            "- references: query the citation/link graph for a document\n\n"
            "References mode examples:\n"
            "- `search(mode=\"references\", path=\"/wiki/concepts/scaling.md\")` — what it cites + what links to it\n"
            "- `search(mode=\"references\", path=\"paper.pdf\")` — which wiki pages cite this source\n"
            "- `search(mode=\"references\", query=\"uncited\")` — sources with no wiki citations\n"
            "- `search(mode=\"references\", query=\"stale\")` — pages flagged as potentially stale\n\n"
            "Use `path` to scope: `*` for root, `/wiki/**` for wiki only, `*.pdf` for PDFs, etc.\n"
            "Use `tags` to filter by document tags."
        ),
    )
    async def search(
        ctx: Context,
        knowledge_base: str,
        mode: Literal["list", "search", "references"] = "list",
        query: str = "",
        path: str = "*",
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> str:
        user_id = get_user_id(ctx)

        if not knowledge_base:
            return await _list_all_kbs(user_id)

        kb = await _resolve_local_kb(user_id, knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        if mode == "list":
            return await _list_docs(user_id, kb, path, tags)
        elif mode == "search":
            if not query:
                return "search mode requires a query."
            return await _search_local(user_id, kb, query, path, tags, min(limit, MAX_SEARCH))
        elif mode == "references":
            return await query_references(user_id, kb["slug"], path, query)

        return f"Unknown mode: {mode}"
