"""Read tool — retrieve document content from the knowledge vault."""

import base64
import json
import logging

from mcp.server.fastmcp import FastMCP, Context
from mcp.types import TextContent, ImageContent

from vaultfs import VaultFS
from .helpers import deep_link, resolve_path, parse_page_range, glob_match
from .references import get_backlinks_summary

logger = logging.getLogger(__name__)

MAX_BATCH_CHARS = 120_000

_IMG_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}

_IMAGE_TYPES = {"png", "jpg", "jpeg", "webp", "gif"}
_PAGE_TYPES = {"pdf", "pptx", "ppt", "docx", "doc", "xlsx", "xls", "csv"}
_SPREADSHEET_TYPES = {"xlsx", "xls", "csv"}
_TEXT_TYPES = {"md", "txt", "csv", "html", "svg", "json", "xml"}


def _text(s: str) -> TextContent:
    """Wrap a string in an MCP TextContent block."""
    return TextContent(type="text", text=s)


def _image(data: bytes, fmt: str) -> ImageContent:
    """Wrap image bytes in an MCP ImageContent block."""
    return ImageContent(
        type="image",
        data=base64.b64encode(data).decode(),
        mimeType=_IMG_MIME.get(fmt, f"image/{fmt}"),
    )


def _extract_sections(content: str, section_names: list[str]) -> str:
    """Extract named markdown sections from content."""
    lines = content.split("\n")
    sections = []
    current_section = None
    current_lines = []

    for line in lines:
        if line.startswith("#"):
            if current_section and current_lines:
                sections.append((current_section, "\n".join(current_lines)))
            heading = line.lstrip("#").strip()
            current_section = heading
            current_lines = [line]
        elif current_section:
            current_lines.append(line)

    if current_section and current_lines:
        sections.append((current_section, "\n".join(current_lines)))

    wanted = {s.lower() for s in section_names}
    matched = [text for name, text in sections if name.lower() in wanted]

    if not matched:
        return f"No sections matching {section_names} found."
    return "\n\n".join(matched)


class ReadHandler:
    """Reads documents from the knowledge vault."""

    def __init__(self, fs: VaultFS, kb: dict):
        self.fs = fs
        self.kb = kb
        self.kb_id = str(kb["id"])
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
        file_type = doc.get("file_type") or ""

        if file_type in _IMAGE_TYPES:
            return await self._read_image(doc, header, include_images)

        if file_type in _PAGE_TYPES and pages:
            return await self._read_pages(doc, header, pages, include_images)

        if file_type in _SPREADSHEET_TYPES and not pages:
            return await self._read_spreadsheet_index(doc, header)

        content = doc.get("content") or ""
        if sections:
            content = _extract_sections(content, sections)

        backlinks = await get_backlinks_summary(self.fs, str(doc["id"]))
        return header + content + backlinks

    async def _read_batch(self, path: str) -> str:
        """Batch-read documents matching a glob pattern."""
        docs = await self.fs.list_documents_with_content(self.kb_id)

        glob_pat = "/" + path.lstrip("/") if not path.startswith("/") else path
        docs = [d for d in docs if glob_match(d["path"] + d["filename"], glob_pat)]

        if not docs:
            return f"No documents matching `{path}` in {self.slug}."

        parts = []
        chars_used = 0
        truncated_docs = 0
        skipped_docs = []

        for doc in docs:
            if chars_used >= MAX_BATCH_CHARS:
                skipped_docs.append(doc)
                continue

            link = deep_link(self.slug, doc["path"], doc["filename"])
            ft = doc.get("file_type") or ""
            remaining = MAX_BATCH_CHARS - chars_used

            if ft in _TEXT_TYPES and doc.get("content"):
                content = doc["content"]
                if len(content) > remaining:
                    content = content[:remaining] + "\n\n... (truncated)"
                    truncated_docs += 1
                parts.append(f"### [{doc['path']}{doc['filename']}]({link})\n\n{content}")
                chars_used += len(content)

            elif (doc.get("page_count") or 0) > 0:
                page_text, doc_chars, pages_included, was_truncated = await self._read_batch_pages(doc, remaining)
                if was_truncated:
                    truncated_docs += 1
                total_pages = doc["page_count"]
                remaining_pages = total_pages - pages_included
                suffix = ""
                if remaining_pages > 0:
                    suffix = f"\n\n*({remaining_pages} more pages — use `pages=\"{pages_included+1}-{total_pages}\"` to continue)*"
                parts.append(f"### [{doc['path']}{doc['filename']}]({link}) ({total_pages} pages)\n\n{page_text}{suffix}")
                chars_used += doc_chars

            else:
                skipped_docs.append(doc)

        header = f"**{len(parts)} document(s)** matching `{path}`"
        if truncated_docs:
            header += f" (some truncated to fit {MAX_BATCH_CHARS:,} char budget)"
        if skipped_docs:
            header += f"\n*{len(skipped_docs)} more document(s) beyond budget — read individually*"
        header += "\n\n---\n\n"

        return header + "\n\n---\n\n".join(parts)

    async def _read_pages(self, doc: dict, header: str, pages_str: str, include_images: bool) -> str | list:
        """Read specific pages from a multi-page document."""
        max_page = doc.get("page_count") or 1
        page_nums = parse_page_range(pages_str, max_page)
        if not page_nums:
            return header + f"Invalid page range: {pages_str} (document has {max_page} pages)"

        doc_id = str(doc["id"])
        page_rows = await self.fs.get_pages(doc_id, page_nums)

        if not page_rows:
            return header + f"No page data found for pages {pages_str}."

        content_blocks: list[TextContent | ImageContent] = [_text(header)]
        has_images = False

        for row in page_rows:
            content_blocks.append(_text(f"**— Page {row['page']} —**\n\n{row['content']}"))

            if not include_images:
                continue

            elements = row.get("elements")
            if not elements:
                continue
            if isinstance(elements, str):
                elements = json.loads(elements)

            for img_meta in elements.get("images", []):
                img_id = img_meta.get("id")
                if not img_id:
                    continue
                img_bytes = await self.fs.load_image_bytes(doc_id, img_id)
                if img_bytes:
                    fmt = "jpeg" if img_id.endswith((".jpg", ".jpeg")) else "png"
                    content_blocks.append(_image(img_bytes, fmt))
                    has_images = True

        if has_images:
            return content_blocks
        return "\n\n".join(b.text for b in content_blocks)

    async def _read_spreadsheet_index(self, doc: dict, header: str) -> str:
        """Show sheet index for spreadsheet files."""
        page_rows = await self.fs.get_all_pages(str(doc["id"]))
        if not page_rows:
            return header + (doc.get("content") or "(no data)")

        lines = [header, "**Sheets:**\n"]
        for row in page_rows:
            elements = row.get("elements")
            if isinstance(elements, str):
                elements = json.loads(elements)
            sheet_name = (elements or {}).get("sheet_name", f"Sheet {row['page']}")
            row_count = row["content"].count("\n") if row.get("content") else 0
            lines.append(f"  Page {row['page']}: **{sheet_name}** (~{row_count} rows)")
        lines.append(f"\nUse `pages=\"1\"` to read a specific sheet.")
        return "\n".join(lines)

    async def _read_image(self, doc: dict, header: str, include_images: bool) -> str | list:
        """Load and return an image file."""
        if not include_images:
            return header + "(Image file — set `include_images=true` to view)"
        img_bytes = await self.fs.load_source_bytes(doc)
        if img_bytes:
            file_type = doc.get("file_type", "png")
            fmt = "jpeg" if file_type in ("jpg", "jpeg") else file_type
            return [_text(header), _image(img_bytes, fmt)]
        return header + "(Image could not be loaded)"

    async def _read_batch_pages(self, doc: dict, remaining: int) -> tuple[str, int, int, bool]:
        """Read pages within a char budget. Returns (text, chars, pages_included, truncated)."""
        page_rows = await self.fs.get_all_pages(str(doc["id"]))
        page_parts = []
        doc_chars = 0
        pages_included = 0
        truncated = False

        for r in page_rows:
            page_text = f"**— Page {r['page']} —**\n\n{r['content']}"
            if doc_chars + len(page_text) > remaining:
                page_parts.append(page_text[:remaining - doc_chars] + "\n\n... (truncated)")
                truncated = True
                pages_included += 1
                doc_chars = remaining
                break
            page_parts.append(page_text)
            doc_chars += len(page_text)
            pages_included += 1

        return "\n\n".join(page_parts), doc_chars, pages_included, truncated

    async def _fetch_document(self, path: str) -> dict | None:
        """Fetch document by exact path, with title/filename fallback."""
        dir_path, filename = resolve_path(path)
        doc = await self.fs.get_document(self.kb_id, filename, dir_path)
        if not doc:
            name = path.lstrip("/").split("/")[-1]
            doc = await self.fs.find_document_by_name(self.kb_id, name)
        return doc

    def _build_header(self, doc: dict) -> str:
        """Build the metadata header for a document."""
        tags_str = ", ".join(doc["tags"]) if doc.get("tags") else "none"
        link = deep_link(self.slug, doc["path"], doc["filename"])
        file_type = doc.get("file_type") or ""

        header = (
            f"**{doc.get('title') or doc['filename']}**\n"
            f"Type: {file_type} | Tags: {tags_str} | Version: {doc.get('version', 0)}"
        )
        if doc.get("page_count"):
            header += f" | Pages: {doc['page_count']}"
        header += f"\n[View]({link})\n\n---\n\n"
        return header


def register(mcp: FastMCP, get_user_id, fs_factory) -> None:

    @mcp.tool(
        name="read",
        description=(
            "Read document content from the knowledge vault.\n\n"
            "Accepts a single file path OR a glob pattern to batch-read multiple files:\n"
            "- `path=\"notes.md\"` — read one file\n"
            "- `path=\"*.md\"` — read all markdown files in root\n"
            "- `path=\"/wiki/**\"` — read all wiki pages\n"
            "- `path=\"**/*.md\"` — read all markdown files everywhere\n\n"
            "Batch reads are the PREFERRED way to read multiple documents at once — use them generously.\n"
            "Glob reads sample the first few pages from each document (including PDFs) up to a 120k char budget. "
            "This gives you a broad overview of an entire folder in one call. Read individual files for full content.\n\n"
            "For PDFs and office docs, use `pages` to read specific page ranges (e.g. '1-50', '3', '10-30').\n"
            "You can read up to 50+ pages in a single call — use wide ranges to avoid unnecessary round trips.\n"
            "For spreadsheets, each sheet is a page (call without pages first to see sheet names).\n"
            "Set `include_images=true` to include embedded images (e.g. figures in PDFs, standalone image files). "
            "Off by default to save context — enable when you need to see charts, diagrams, or photos.\n\n"
            "When reading sources to compile wiki pages, note the filename and page ranges for citation."
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
        fs = fs_factory(user_id)
        kb = await fs.resolve_kb(knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        handler = ReadHandler(fs, kb)
        return await handler.read(path, pages, sections, include_images)
