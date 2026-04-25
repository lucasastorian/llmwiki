"""Search tool — browse, search, and query references (local mode)."""

import logging
from typing import Literal

from mcp.server.fastmcp import FastMCP, Context

from infra.db.sqlite import list_knowledge_bases, list_documents, search_chunks, get_workspace
from .helpers import get_user_id, deep_link, glob_match, MAX_LIST, MAX_SEARCH
from .references import query_references as _query_refs
from tools.search import _extract_snippet

logger = logging.getLogger(__name__)


class SearchHandler:
    """Executes list, search, and reference queries on the local vault."""

    def __init__(self, user_id: str, kb: dict):
        self.user_id = user_id
        self.kb = kb
        self.slug = kb["slug"]

    async def list_documents(self, target: str, tags: list[str] | None) -> str:
        """List documents matching a glob pattern and optional tag filter."""
        docs = await list_documents(self.user_id, self.slug)

        if target not in ("*", "**", "**/*"):
            glob_pat = "/" + target.lstrip("/") if not target.startswith("/") else target
            docs = [d for d in docs if glob_match(d["path"] + d["filename"], glob_pat)]

        if tags:
            tag_set = {t.lower() for t in tags}
            docs = [d for d in docs if tag_set.issubset({t.lower() for t in (d.get("tags") or [])})]

        if not docs:
            return f"No matches for `{target}` in {self.slug}."

        sources = [d for d in docs if not d["path"].startswith("/wiki/")]
        wiki_pages = [d for d in docs if d["path"].startswith("/wiki/")]

        lines = [f"**{self.kb['name']}** (`{target}`):\n"]

        if sources:
            lines.append(f"**Sources ({len(sources)}):**")
            for doc in sources[:MAX_LIST]:
                lines.append(self._format_source_line(doc))
            if len(sources) > MAX_LIST:
                lines.append(f"  ... {len(sources) - MAX_LIST} more")

        if wiki_pages:
            if sources:
                lines.append("")
            lines.append(f"**Wiki ({len(wiki_pages)} pages):**")
            for doc in wiki_pages[:MAX_LIST]:
                lines.append(f"  {doc['path']}{doc['filename']}")

        return "\n".join(lines)

    async def search_chunks(self, query: str, path: str, tags: list[str] | None, limit: int) -> str:
        """Full-text search across document chunks."""
        path_filter = self._path_filter_key(path)

        matches = await search_chunks(self.user_id, self.slug, query, limit=limit, path_filter=path_filter)

        if tags:
            tag_set = {t.lower() for t in tags}
            matches = [m for m in matches if tag_set.issubset({t.lower() for t in (m.get("tags") or [])})]

        if not matches:
            return f"No matches for `{query}` in {self.slug}."

        lines = [f"**{len(matches)} result(s)** for `{query}`:\n"]
        for m in matches:
            lines.append(self._format_search_result(m, query))

        return "\n".join(lines)

    async def query_references(self, path: str, query: str) -> str:
        """Query the citation/link graph."""
        return await _query_refs(self.user_id, self.slug, path, query)

    def _path_filter_key(self, path: str) -> str | None:
        """Map a path pattern to a local search filter key."""
        if path in ("*", "**", "**/*"):
            return None
        if path.startswith("/wiki"):
            return "wiki"
        if path in ("/", "/*"):
            return "sources"
        return None

    def _format_source_line(self, doc: dict) -> str:
        """Format a single source document for list output."""
        tag_str = f" [{', '.join(doc['tags'])}]" if doc.get("tags") else ""
        pages_part = f", {doc['page_count']}p" if doc.get("page_count") else ""
        return f"  {doc['path']}{doc['filename']} ({doc.get('file_type', '')}{pages_part}){tag_str}"

    def _format_search_result(self, match: dict, query: str) -> str:
        """Format a single search result with snippet."""
        filepath = f"{match['path']}{match['filename']}"
        page_str = f" (p.{match['page']})" if match.get("page") else ""
        breadcrumb = f"\n  {match['header_breadcrumb']}" if match.get("header_breadcrumb") else ""
        snippet = _extract_snippet(match.get("content", ""), query)
        link = deep_link(self.slug, match["path"], match["filename"])
        return f"**{filepath}**{page_str} — [view]({link}){breadcrumb}\n```\n{snippet}\n```\n"


async def _list_all_kbs(user_id: str) -> str:
    """List all knowledge bases for the user."""
    kbs = await list_knowledge_bases(user_id)
    if not kbs:
        return "No workspace initialized."
    lines = ["**Knowledge Bases:**\n"]
    for kb in kbs:
        lines.append(f"  {kb['slug']}/ — {kb['name']} ({kb.get('source_count', 0)} sources, {kb.get('wiki_count', 0)} wiki pages)")
    return "\n".join(lines)


async def _resolve_local_kb(user_id: str, slug: str) -> dict | None:
    """Resolve a local workspace as a knowledge base."""
    ws = await get_workspace()
    if not ws:
        return None
    return {"id": ws["id"], "name": ws["name"], "slug": ws["name"]}


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

        handler = SearchHandler(user_id, kb)

        if mode == "list":
            return await handler.list_documents(path, tags)
        elif mode == "search":
            if not query:
                return "search mode requires a query."
            return await handler.search_chunks(query, path, tags, min(limit, MAX_SEARCH))
        elif mode == "references":
            return await handler.query_references(path, query)

        return f"Unknown mode: {mode}"
