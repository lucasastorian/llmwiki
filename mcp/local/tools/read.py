"""Local read tool — reads documents from SQLite index and local filesystem."""

import logging

from mcp.server.fastmcp import FastMCP, Context

from infra.db.sqlite import (
    get_document, fuzzy_find_document, get_pages, get_all_pages,
    batch_list_documents, get_workspace,
)
from infra.storage.local import load_bytes
from .helpers import get_user_id, deep_link, resolve_path, parse_page_range, glob_match
from .references import get_backlinks_summary
from tools.read import (
    _text, _image, _extract_sections, _IMG_MIME,
    MAX_BATCH_CHARS,
)

logger = logging.getLogger(__name__)


async def _resolve_local_kb(user_id: str, slug: str) -> dict | None:
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

        is_glob = "*" in path or "?" in path
        if is_glob:
            return await _read_batch_local(user_id, kb, path)

        dir_path, filename = resolve_path(path)

        doc = await get_document(user_id, kb["slug"], filename, dir_path)
        if not doc:
            search_name = path.lstrip("/").split("/")[-1]
            doc = await fuzzy_find_document(user_id, kb["slug"], search_name)

        if not doc:
            return f"Document '{path}' not found in {knowledge_base}."

        tags_str = ", ".join(doc["tags"]) if doc.get("tags") else "none"
        link = deep_link(kb["slug"], doc["path"], doc["filename"])
        file_type = doc.get("file_type", "")

        header = (
            f"**{doc.get('title') or doc['filename']}**\n"
            f"Type: {file_type} | Tags: {tags_str} | Version: {doc.get('version', 0)}"
        )
        if doc.get("page_count"):
            header += f" | Pages: {doc['page_count']}"
        header += f"\n[View]({link})\n\n---\n\n"

        # Image files — load from workspace-relative path
        image_types = {"png", "jpg", "jpeg", "webp", "gif"}
        if file_type in image_types:
            if not include_images:
                return header + "(Image file — set `include_images=true` to view)"
            relative = doc.get("relative_path") or (doc["path"].rstrip("/") + "/" + doc["filename"]).lstrip("/")
            img_bytes = await load_bytes(relative)
            if img_bytes:
                fmt = "jpeg" if file_type in ("jpg", "jpeg") else file_type
                return [_text(header), _image(img_bytes, fmt)]
            return header + "(Image could not be loaded)"

        # Multi-page docs with page request
        if pages and doc.get("page_count"):
            max_page = doc["page_count"]
            page_nums = parse_page_range(pages, max_page)
            if not page_nums:
                return header + f"Invalid page range: {pages} (document has {max_page} pages)"

            page_rows = await get_pages(str(doc["id"]), page_nums)
            if not page_rows:
                return header + f"No page data found for pages {pages}."

            parts = [header]
            for row in page_rows:
                parts.append(f"**— Page {row['page']} —**\n\n{row['content']}")
            return "\n\n".join(parts)

        # Spreadsheet index
        spreadsheet_types = {"xlsx", "xls", "csv"}
        if file_type in spreadsheet_types and not pages:
            page_rows = await get_all_pages(str(doc["id"]))
            if not page_rows:
                return header + (doc.get("content") or "(no data)")
            lines = [header, "**Sheets:**\n"]
            for row in page_rows:
                lines.append(f"  Page {row['page']}")
            lines.append(f"\nUse `pages=\"1\"` to read a specific sheet.")
            return "\n".join(lines)

        # Default: return content
        content = doc.get("content") or ""
        if sections:
            content = _extract_sections(content, sections)

        backlinks = await get_backlinks_summary(user_id, str(doc["id"]))
        return header + content + backlinks


async def _read_batch_local(user_id: str, kb: dict, path: str) -> str:
    docs = await batch_list_documents(user_id, kb["slug"])

    glob_pat = "/" + path.lstrip("/") if not path.startswith("/") else path
    docs = [d for d in docs if glob_match(d["path"] + d["filename"], glob_pat)]

    if not docs:
        return f"No documents matching `{path}` in {kb['slug']}."

    text_types = {"md", "txt", "csv", "html", "svg", "json", "xml"}
    parts = []
    chars_used = 0
    skipped = []

    for doc in docs:
        if chars_used >= MAX_BATCH_CHARS:
            skipped.append(doc)
            continue

        ft = doc.get("file_type", "")
        remaining = MAX_BATCH_CHARS - chars_used
        link = deep_link(kb["slug"], doc["path"], doc["filename"])

        if ft in text_types and doc.get("content"):
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
