"""Search tool — browse, search, and query references in the knowledge vault."""

import logging
from typing import Literal

from mcp.server.fastmcp import FastMCP, Context

from db import scoped_query, scoped_queryrow
from .helpers import get_user_id, resolve_kb, deep_link, glob_match, resolve_path, MAX_LIST, MAX_SEARCH

logger = logging.getLogger(__name__)

_CONTEXT_CHARS = 120


def _extract_snippet(content: str, query: str) -> str:
    """Extract a context snippet around a query match."""
    if not content:
        return "(empty)"
    idx = content.lower().find(query.lower())
    if idx < 0:
        return content[:_CONTEXT_CHARS * 2].strip()
    start = max(0, idx - _CONTEXT_CHARS)
    end = min(len(content), idx + len(query) + _CONTEXT_CHARS)
    snippet = content[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."
    return snippet


class SearchHandler:
    """Executes list, search, and reference queries on the knowledge vault."""

    def __init__(self, user_id: str, kb: dict):
        self.user_id = user_id
        self.kb = kb
        self.kb_id = str(kb["id"])
        self.slug = kb["slug"]

    async def list_documents(self, target: str, tags: list[str] | None) -> str:
        """List documents matching a glob pattern and optional tag filter."""
        docs = await scoped_query(
            self.user_id,
            "SELECT id, filename, title, path, file_type, tags, page_count, updated_at "
            "FROM documents WHERE knowledge_base_id = $1 AND NOT archived AND user_id = $2 "
            "ORDER BY path, filename",
            self.kb["id"], self.user_id,
        )

        if target not in ("*", "**", "**/*"):
            glob_pat = "/" + target.lstrip("/") if not target.startswith("/") else target
            docs = [d for d in docs if glob_match(d["path"] + d["filename"], glob_pat)]

        if tags:
            tag_set = {t.lower() for t in tags}
            docs = [d for d in docs if tag_set.issubset({t.lower() for t in (d["tags"] or [])})]

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
                lines.append(self._format_wiki_line(doc))

        return "\n".join(lines)

    async def search_chunks(self, query: str, path: str, tags: list[str] | None, limit: int) -> str:
        """Full-text search across document chunks."""
        path_clause = self._path_filter_clause(path)

        matches = await scoped_query(
            self.user_id,
            f"SELECT dc.content, dc.page, dc.header_breadcrumb, dc.chunk_index, "
            f"  d.filename, d.title, d.path, d.file_type, d.tags, "
            f"  pgroonga_score(dc.tableoid, dc.ctid) AS score "
            f"FROM document_chunks dc "
            f"JOIN documents d ON dc.document_id = d.id "
            f"WHERE dc.knowledge_base_id = $1 "
            f"  AND dc.content &@~ $2 "
            f"  AND NOT d.archived"
            f"  AND d.user_id = $3"
            f"{path_clause} "
            f"ORDER BY score DESC, dc.chunk_index "
            f"LIMIT {limit}",
            self.kb["id"], query, self.user_id,
        )

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
        if query == "uncited":
            return await self._find_uncited()
        if query == "stale":
            return await self._find_stale()
        return await self._document_references(path)

    async def _find_uncited(self) -> str:
        """Find source documents not cited by any wiki page."""
        rows = await scoped_query(
            self.user_id,
            "SELECT d.filename, d.title, d.path, d.file_type "
            "FROM documents d "
            "WHERE d.knowledge_base_id = $1 AND NOT d.archived AND d.user_id = $2 "
            "  AND d.path NOT LIKE '/wiki/%%' "
            "  AND d.id NOT IN (SELECT target_document_id FROM document_references WHERE reference_type = 'cites') "
            "ORDER BY d.filename",
            self.kb["id"], self.user_id,
        )
        if not rows:
            return "All sources are cited in at least one wiki page."
        lines = [f"**{len(rows)} uncited source(s)** — not referenced by any wiki page:\n"]
        for r in rows:
            lines.append(f"  {r['path']}{r['filename']} ({r['file_type']})")
        return "\n".join(lines)

    async def _find_stale(self) -> str:
        """Find wiki pages flagged as potentially stale."""
        rows = await scoped_query(
            self.user_id,
            "SELECT d.filename, d.title, d.path, d.stale_since "
            "FROM documents d "
            "WHERE d.knowledge_base_id = $1 AND NOT d.archived AND d.user_id = $2 "
            "  AND d.stale_since IS NOT NULL "
            "ORDER BY d.stale_since DESC",
            self.kb["id"], self.user_id,
        )
        if not rows:
            return "No stale pages found."
        lines = [f"**{len(rows)} potentially stale page(s)** — a page they reference was updated:\n"]
        for r in rows:
            stale = r["stale_since"].strftime("%Y-%m-%d %H:%M") if r["stale_since"] else ""
            title = r["title"] or r["filename"]
            lines.append(f"  {r['path']}{r['filename']} ({title}) — stale since {stale}")
        return "\n".join(lines)

    async def _document_references(self, path: str) -> str:
        """Show forward references and backlinks for a specific document."""
        if not path or path in ("*", "**"):
            return "references mode requires a `path` to a specific document, or `query=\"uncited\"` / `query=\"stale\"`."

        dir_path, filename = resolve_path(path)
        doc = await scoped_queryrow(
            self.user_id,
            "SELECT id, filename, title, path FROM documents "
            "WHERE knowledge_base_id = $1 AND filename = $2 AND path = $3 AND NOT archived AND user_id = $4",
            self.kb["id"], filename, dir_path, self.user_id,
        )
        if not doc:
            return f"Document '{path}' not found."

        forward = await scoped_query(
            self.user_id,
            "SELECT d.filename, d.title, d.path, dr.reference_type, dr.page "
            "FROM document_references dr "
            "JOIN documents d ON dr.target_document_id = d.id "
            "WHERE dr.source_document_id = $1 AND NOT d.archived AND d.user_id = $2 "
            "ORDER BY dr.reference_type, d.path, d.filename",
            doc["id"], self.user_id,
        )

        backlinks = await scoped_query(
            self.user_id,
            "SELECT d.filename, d.title, d.path, dr.reference_type, dr.page "
            "FROM document_references dr "
            "JOIN documents d ON dr.source_document_id = d.id "
            "WHERE dr.target_document_id = $1 AND NOT d.archived AND d.user_id = $2 "
            "ORDER BY dr.reference_type, d.path, d.filename",
            doc["id"], self.user_id,
        )

        title = doc["title"] or doc["filename"]
        lines = [f"**References for {title}** (`{dir_path}{filename}`):\n"]

        if forward:
            cites = [r for r in forward if r["reference_type"] == "cites"]
            links = [r for r in forward if r["reference_type"] == "links_to"]
            if cites:
                lines.append(f"**Cites ({len(cites)} sources):**")
                for r in cites:
                    page_str = f", p.{r['page']}" if r["page"] else ""
                    lines.append(f"  {r['path']}{r['filename']}{page_str}")
            if links:
                lines.append(f"\n**Links to ({len(links)} pages):**")
                for r in links:
                    lines.append(f"  {r['path']}{r['filename']} ({r['title'] or r['filename']})")
        else:
            lines.append("No outgoing references.")

        lines.append("")
        if backlinks:
            lines.append(f"**Referenced by ({len(backlinks)} pages):**")
            for r in backlinks:
                ref = "cites" if r["reference_type"] == "cites" else "links to"
                lines.append(f"  {r['path']}{r['filename']} ({r['title'] or r['filename']}) — {ref}")
        else:
            lines.append("No incoming references (backlinks).")

        return "\n".join(lines)

    def _path_filter_clause(self, path: str) -> str:
        """Build a SQL path filter clause from a path pattern."""
        if path in ("*", "**", "**/*"):
            return ""
        if path.startswith("/wiki"):
            return " AND d.path LIKE '/wiki/%%'"
        if path in ("/", "/*"):
            return " AND d.path NOT LIKE '/wiki/%%'"
        return ""

    def _format_source_line(self, doc: dict) -> str:
        """Format a single source document for list output."""
        tag_str = f" [{', '.join(doc['tags'])}]" if doc["tags"] else ""
        date_part = f", {doc['updated_at'].strftime('%Y-%m-%d')}" if doc["updated_at"] else ""
        pages_part = f", {doc['page_count']}p" if doc["page_count"] else ""
        return f"  {doc['path']}{doc['filename']} ({doc['file_type']}{pages_part}{date_part}){tag_str}"

    def _format_wiki_line(self, doc: dict) -> str:
        """Format a single wiki page for list output."""
        date_part = f", {doc['updated_at'].strftime('%Y-%m-%d')}" if doc["updated_at"] else ""
        return f"  {doc['path']}{doc['filename']}{date_part}"

    def _format_search_result(self, match: dict, query: str) -> str:
        """Format a single search result with snippet."""
        filepath = f"{match['path']}{match['filename']}"
        page_str = f" (p.{match['page']})" if match["page"] else ""
        breadcrumb = f"\n  {match['header_breadcrumb']}" if match["header_breadcrumb"] else ""
        snippet = _extract_snippet(match["content"], query)
        link = deep_link(self.slug, match["path"], match["filename"])
        score = match.get("score", 0)
        score_str = f" [{score:.1f}]" if score else ""
        return f"**{filepath}**{page_str}{score_str} — [view]({link}){breadcrumb}\n```\n{snippet}\n```\n"


async def _list_all_kbs(user_id: str) -> str:
    """List all knowledge bases for the user."""
    kbs = await scoped_query(
        user_id,
        "SELECT name, slug, created_at FROM knowledge_bases WHERE user_id = $1 ORDER BY created_at DESC",
        user_id,
    )
    if not kbs:
        return "No knowledge bases found. Create one first."

    lines = ["**Knowledge Bases:**\n"]
    for kb in kbs:
        doc_count = await scoped_queryrow(
            user_id,
            "SELECT count(*) as cnt FROM documents WHERE knowledge_base_id = ("
            "SELECT id FROM knowledge_bases WHERE slug = $1 AND user_id = $2) AND NOT archived",
            kb["slug"], user_id,
        )
        cnt = doc_count["cnt"] if doc_count else 0
        lines.append(f"  {kb['slug']}/ — {kb['name']} ({cnt} documents)")
    return "\n".join(lines)


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        name="search",
        description=(
            "Browse or search the knowledge vault.\n\n"
            "Sources (raw documents) live at `/`. Wiki pages (LLM-compiled) live at `/wiki/`.\n\n"
            "Modes:\n"
            "- list: browse files and folders\n"
            "- search: keyword search across document content (searches chunks for precise results with page numbers)\n"
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

        kb = await resolve_kb(user_id, knowledge_base)
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
