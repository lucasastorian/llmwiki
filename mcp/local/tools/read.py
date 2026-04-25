"""Read tool — retrieve document content from the local vault."""

import logging

from mcp.server.fastmcp import FastMCP, Context

from infra.db.sqlite import (
    get_document, fuzzy_find_document, get_pages, get_all_pages,
    batch_list_documents, get_workspace,
)
from infra.storage.local import load_bytes
from .helpers import get_user_id, deep_link, resolve_path, parse_page_range, glob_match
from .references import get_backlinks_summary
from tools.read import _text, _image, _extract_sections, MAX_BATCH_CHARS

logger = logging.getLogger(__name__)

_IMAGE_TYPES = {"png", "jpg", "jpeg", "webp", "gif"}
_SPREADSHEET_TYPES = {"xlsx", "xls", "csv"}
_TEXT_TYPES = {"md", "txt", "csv", "html", "svg", "json", "xml"}


class ReadHandler:
    """Reads documents from the local vault."""

    def __init__(self, user_id: str, kb: dict):
        self.user_id = user_id
        self.kb = kb
        self.slug = kb["slug"]

    async def read(self, path: str, pages: str, sections: list[str] | None, include_images: bool) -> str | list:
        """Read a single document or batch via glob pattern."""
        if "*" in path or "?" in path:
            return await self._read_batch(path)
        return await self._read_single(path, pages, sections, include_images)

    async def _read_single(self, path: str, pages: str, sections: list[str] | None, include_images: bool) -> str | list:
        """Read a single document by path."""
        doc = await self._fetch_document(path)
        if not doc:
            return f"Document '{path}' not found in {self.slug}."

        header = self._build_header(doc)
        file_type = doc.get("file_type", "")

        if file_type in _IMAGE_TYPES:
            return await self._read_image(doc, header, include_images)

        if pages and doc.get("page_count"):
            return await self._read_pages(doc, header, pages)

        if file_type in _SPREADSHEET_TYPES and not pages:
            return await self._read_spreadsheet_index(doc, header)

        content = doc.get("content") or ""
        if sections:
            content = _extract_sections(content, sections)

        backlinks = await get_backlinks_summary(self.user_id, str(doc["id"]))
        return header + content + backlinks

    async def _read_batch(self, path: str) -> str:
        """Batch-read documents matching a glob pattern."""
        docs = await batch_list_documents(self.user_id, self.slug)

        glob_pat = "/" + path.lstrip("/") if not path.startswith("/") else path
        docs = [d for d in docs if glob_match(d["path"] + d["filename"], glob_pat)]

        if not docs:
            return f"No documents matching `{path}` in {self.slug}."

        parts = []
        chars_used = 0
        skipped = []

        for doc in docs:
            if chars_used >= MAX_BATCH_CHARS:
                skipped.append(doc)
                continue

            ft = doc.get("file_type", "")
            remaining = MAX_BATCH_CHARS - chars_used
            link = deep_link(self.slug, doc["path"], doc["filename"])

            if ft in _TEXT_TYPES and doc.get("content"):
                content = doc["content"]
                if len(content) > remaining:
                    content = content[:remaining] + "\n\n... (truncated)"
                parts.append(f"### [{doc['path']}{doc['filename']}]({link})\n\n{content}")
                chars_used += len(content)
            elif (doc.get("page_count") or 0) > 0:
                page_rows = await get_all_pages(str(doc["id"]))
                page_parts = []
                doc_chars = 0
                for r in page_rows:
                    page_text = f"**— Page {r['page']} —**\n\n{r['content']}"
                    if doc_chars + len(page_text) > remaining:
                        break
                    page_parts.append(page_text)
                    doc_chars += len(page_text)
                if page_parts:
                    parts.append(f"### [{doc['path']}{doc['filename']}]({link})\n\n" + "\n\n".join(page_parts))
                    chars_used += doc_chars
            else:
                skipped.append(doc)

        header = f"**{len(parts)} document(s)** matching `{path}`"
        if skipped:
            header += f"\n*{len(skipped)} more beyond budget — read individually*"
        header += "\n\n---\n\n"

        return header + "\n\n---\n\n".join(parts)

    async def _read_pages(self, doc: dict, header: str, pages_str: str) -> str:
        """Read specific pages from a multi-page document."""
        max_page = doc["page_count"]
        page_nums = parse_page_range(pages_str, max_page)
        if not page_nums:
            return header + f"Invalid page range: {pages_str} (document has {max_page} pages)"

        page_rows = await get_pages(str(doc["id"]), page_nums)
        if not page_rows:
            return header + f"No page data found for pages {pages_str}."

        parts = [header]
        for row in page_rows:
            parts.append(f"**— Page {row['page']} —**\n\n{row['content']}")
        return "\n\n".join(parts)

    async def _read_spreadsheet_index(self, doc: dict, header: str) -> str:
        """Show sheet index for spreadsheet files."""
        page_rows = await get_all_pages(str(doc["id"]))
        if not page_rows:
            return header + (doc.get("content") or "(no data)")
        lines = [header, "**Sheets:**\n"]
        for row in page_rows:
            lines.append(f"  Page {row['page']}")
        lines.append(f"\nUse `pages=\"1\"` to read a specific sheet.")
        return "\n".join(lines)

    async def _read_image(self, doc: dict, header: str, include_images: bool) -> str | list:
        """Load and return an image file from the local filesystem."""
        if not include_images:
            return header + "(Image file — set `include_images=true` to view)"
        relative = doc.get("relative_path") or (doc["path"].rstrip("/") + "/" + doc["filename"]).lstrip("/")
        img_bytes = await load_bytes(relative)
        if img_bytes:
            file_type = doc.get("file_type", "png")
            fmt = "jpeg" if file_type in ("jpg", "jpeg") else file_type
            return [_text(header), _image(img_bytes, fmt)]
        return header + "(Image could not be loaded)"

    async def _fetch_document(self, path: str) -> dict | None:
        """Fetch document by exact path, with fuzzy fallback."""
        dir_path, filename = resolve_path(path)
        doc = await get_document(self.user_id, self.slug, filename, dir_path)
        if not doc:
            search_name = path.lstrip("/").split("/")[-1]
            doc = await fuzzy_find_document(self.user_id, self.slug, search_name)
        return doc

    def _build_header(self, doc: dict) -> str:
        """Build the metadata header for a document."""
        tags_str = ", ".join(doc["tags"]) if doc.get("tags") else "none"
        link = deep_link(self.slug, doc["path"], doc["filename"])
        file_type = doc.get("file_type", "")

        header = (
            f"**{doc.get('title') or doc['filename']}**\n"
            f"Type: {file_type} | Tags: {tags_str} | Version: {doc.get('version', 0)}"
        )
        if doc.get("page_count"):
            header += f" | Pages: {doc['page_count']}"
        header += f"\n[View]({link})\n\n---\n\n"
        return header


async def _resolve_local_kb(user_id: str, slug: str) -> dict | None:
    """Resolve a local workspace as a knowledge base."""
    ws = await get_workspace()
    if not ws:
        return None
    return {"id": ws["id"], "name": ws["name"], "slug": ws["name"]}


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        name="read",
        description=(
            "Read document content from the knowledge vault.\n\n"
            "Accepts a single file path OR a glob pattern to batch-read multiple files:\n"
            "- `path=\"notes.md\"` — read one file\n"
            "- `path=\"/wiki/**\"` — read all wiki pages\n\n"
            "For PDFs and office docs, use `pages` to read specific page ranges.\n"
            "Set `include_images=true` to include embedded images."
        ),
        structured_output=False,
    )
    async def read(
        ctx: Context,
        knowledge_base: str,
        path: str,
        pages: str = "",
        sections: list[str] | None = None,
        include_images: bool = False,
    ) -> str | list:
        user_id = get_user_id(ctx)

        kb = await _resolve_local_kb(user_id, knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        handler = ReadHandler(user_id, kb)
        return await handler.read(path, pages, sections, include_images)
