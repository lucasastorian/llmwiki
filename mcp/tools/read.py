import base64
import json
import logging

from mcp.server.fastmcp import FastMCP, Context
from mcp.types import TextContent, ImageContent

from db import scoped_query, scoped_queryrow
from .helpers import (
    get_user_id, resolve_kb, deep_link, resolve_path,
    load_s3_bytes, parse_page_range, glob_match,
)
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


def _text(s: str) -> TextContent:
    return TextContent(type="text", text=s)


def _image(data: bytes, fmt: str) -> ImageContent:
    return ImageContent(
        type="image",
        data=base64.b64encode(data).decode(),
        mimeType=_IMG_MIME.get(fmt, f"image/{fmt}"),
    )


def _extract_sections(content: str, section_names: list[str]) -> str:
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


async def _read_pages(
    doc: dict, kb: dict, header: str, pages_str: str, include_images: bool = False,
) -> str | list:
    max_page = doc["page_count"] or 1
    page_nums = parse_page_range(pages_str, max_page)
    if not page_nums:
        return header + f"Invalid page range: {pages_str} (document has {max_page} pages)"

    user_id = str(doc["user_id"])
    doc_id = str(doc["id"])

    page_rows = await scoped_query(
        user_id,
        "SELECT page, content, elements FROM document_pages "
        "WHERE document_id = $1 AND page = ANY($2) ORDER BY page",
        doc["id"], page_nums,
    )

    if not page_rows:
        return header + f"No page data found for pages {pages_str}."

    content_blocks: list[TextContent | ImageContent] = [_text(header)]
    has_images = False

    for row in page_rows:
        content_blocks.append(_text(f"**— Page {row['page']} —**\n\n{row['content']}"))

        if not include_images:
            continue

        elements = row["elements"]
        if not elements:
            continue
        if isinstance(elements, str):
            elements = json.loads(elements)

        images = elements.get("images", [])
        for img_meta in images:
            img_id = img_meta.get("id")
            if not img_id:
                continue
            s3_key = f"{user_id}/{doc_id}/images/{img_id}"
            img_bytes = await load_s3_bytes(s3_key)
            if img_bytes:
                fmt = "jpeg" if img_id.endswith((".jpg", ".jpeg")) else "png"
                content_blocks.append(_image(img_bytes, fmt))
                has_images = True

    if has_images:
        return content_blocks
    return "\n\n".join(b.text for b in content_blocks)


async def _read_spreadsheet_index(doc: dict, header: str) -> str:
    user_id = str(doc["user_id"])
    page_rows = await scoped_query(
        user_id,
        "SELECT page, content, elements FROM document_pages "
        "WHERE document_id = $1 ORDER BY page",
        doc["id"],
    )
    if not page_rows:
        return header + (doc["content"] or "(no data)")

    lines = [header, "**Sheets:**\n"]
    for row in page_rows:
        elements = row["elements"]
        if isinstance(elements, str):
            elements = json.loads(elements)
        sheet_name = (elements or {}).get("sheet_name", f"Sheet {row['page']}")
        row_count = row["content"].count("\n") if row["content"] else 0
        lines.append(f"  Page {row['page']}: **{sheet_name}** (~{row_count} rows)")
    lines.append(f"\nUse `pages=\"1\"` to read a specific sheet.")
    return "\n".join(lines)


async def _read_batch(user_id: str, kb: dict, path: str) -> str:
    docs = await scoped_query(
        user_id,
        "SELECT id, filename, title, path, content, tags, file_type, page_count "
        "FROM documents WHERE knowledge_base_id = $1 AND NOT archived AND user_id = $2 "
        "ORDER BY path, filename",
        kb["id"], user_id,
    )

    glob_pat = "/" + path.lstrip("/") if not path.startswith("/") else path
    docs = [d for d in docs if glob_match(d["path"] + d["filename"], glob_pat)]

    if not docs:
        return f"No documents matching `{path}` in {kb['slug']}."

    text_types = {"md", "txt", "csv", "html", "svg", "json", "xml"}
    parts = []
    chars_used = 0
    truncated_docs = 0
    skipped_docs = []

    for doc in docs:
        if chars_used >= MAX_BATCH_CHARS:
            skipped_docs.append(doc)
            continue

        link = deep_link(kb["slug"], doc["path"], doc["filename"])
        ft = doc["file_type"] or ""
        remaining = MAX_BATCH_CHARS - chars_used

        if ft in text_types and doc["content"]:
            content = doc["content"] or ""
            if len(content) > remaining:
                content = content[:remaining] + "\n\n... (truncated)"
                truncated_docs += 1
            parts.append(f"### [{doc['path']}{doc['filename']}]({link})\n\n{content}")
            chars_used += len(content)

        elif (doc.get("page_count") or 0) > 0:
            page_rows = await scoped_query(
                user_id,
                "SELECT page, content FROM document_pages "
                "WHERE document_id = $1 ORDER BY page",
                doc["id"],
            )
            page_parts = []
            doc_chars = 0
            pages_included = 0
            for r in page_rows:
                page_text = f"**— Page {r['page']} —**\n\n{r['content']}"
                if doc_chars + len(page_text) > remaining:
                    page_parts.append(page_text[:remaining - doc_chars] + "\n\n... (truncated)")
                    truncated_docs += 1
                    pages_included += 1
                    doc_chars = remaining
                    break
                page_parts.append(page_text)
                doc_chars += len(page_text)
                pages_included += 1

            total_pages = doc["page_count"]
            remaining_pages = total_pages - pages_included
            suffix = ""
            if remaining_pages > 0:
                suffix = f"\n\n*({remaining_pages} more pages — use `pages=\"{pages_included+1}-{total_pages}\"` to continue)*"
            parts.append(f"### [{doc['path']}{doc['filename']}]({link}) ({total_pages} pages)\n\n" + "\n\n".join(page_parts) + suffix)
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


def register(mcp: FastMCP) -> None:

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

        kb = await resolve_kb(user_id, knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        is_glob = "*" in path or "?" in path
        if is_glob:
            return await _read_batch(user_id, kb, path)

        dir_path, filename = resolve_path(path)

        doc = await scoped_queryrow(
            user_id,
            "SELECT id, user_id, filename, title, path, content, tags, version, file_type, "
            "page_count, created_at, updated_at "
            "FROM documents WHERE knowledge_base_id = $1 AND filename = $2 AND path = $3 AND NOT archived AND user_id = $4",
            kb["id"], filename, dir_path, user_id,
        )
        if not doc:
            doc = await scoped_queryrow(
                user_id,
                "SELECT id, user_id, filename, title, path, content, tags, version, file_type, "
                "page_count, created_at, updated_at "
                "FROM documents WHERE knowledge_base_id = $1 AND (filename = $2 OR title = $2) AND NOT archived AND user_id = $3",
                kb["id"], path.lstrip("/").split("/")[-1], user_id,
            )

        if not doc:
            return f"Document '{path}' not found in {knowledge_base}."

        tags_str = ", ".join(doc["tags"]) if doc["tags"] else "none"
        link = deep_link(kb["slug"], doc["path"], doc["filename"])
        file_type = doc["file_type"] or ""

        header = (
            f"**{doc['title'] or doc['filename']}**\n"
            f"Type: {file_type} | Tags: {tags_str} | Version: {doc['version']} | "
            f"Updated: {doc['updated_at'].strftime('%Y-%m-%d') if doc['updated_at'] else 'unknown'}"
        )
        if doc["page_count"]:
            header += f" | Pages: {doc['page_count']}"
        header += f"\n[View in Supavault]({link})\n\n---\n\n"

        image_types = {"png", "jpg", "jpeg", "webp", "gif"}
        if file_type in image_types:
            if not include_images:
                return header + "(Image file — set `include_images=true` to view)"
            s3_key = f"{doc['user_id']}/{doc['id']}/source.{file_type}"
            img_bytes = await load_s3_bytes(s3_key)
            if img_bytes:
                fmt = "jpeg" if file_type in ("jpg", "jpeg") else file_type
                return [_text(header), _image(img_bytes, fmt)]
            return header + "(Image could not be loaded from storage)"

        has_pages = file_type in ("pdf", "pptx", "ppt", "docx", "doc", "xlsx", "xls", "csv")
        spreadsheet_types = {"xlsx", "xls", "csv"}

        if has_pages and pages:
            return await _read_pages(doc, kb, header, pages, include_images)

        if file_type in spreadsheet_types and not pages:
            return await _read_spreadsheet_index(doc, header)

        content = doc["content"] or ""
        if sections:
            content = _extract_sections(content, sections)

        backlinks = await get_backlinks_summary(user_id, str(doc["id"]))
        return header + content + backlinks
