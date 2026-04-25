import re
from datetime import date
from typing import Literal

from mcp.server.fastmcp import FastMCP, Context

from db import scoped_queryrow, service_queryrow, service_execute
from .helpers import get_user_id, resolve_kb, deep_link, resolve_path
from .references import update_references, propagate_staleness, get_impact_surface

_ASSET_EXTENSIONS = {".svg", ".csv", ".json", ".xml", ".html"}

_CONTEXT_LINES = 5


def _edit_context(content: str, replace_start: int, new_text_len: int) -> str:
    """Return ~5 lines above and below the edited region."""
    lines = content.split("\n")
    # Find which line the edit starts and ends on
    char_count = 0
    start_line = 0
    for i, line in enumerate(lines):
        if char_count + len(line) >= replace_start:
            start_line = i
            break
        char_count += len(line) + 1  # +1 for newline

    replace_end = replace_start + new_text_len
    char_count = 0
    end_line = start_line
    for i, line in enumerate(lines):
        if char_count >= replace_end:
            end_line = i
            break
        char_count += len(line) + 1
        end_line = i

    ctx_start = max(0, start_line - _CONTEXT_LINES)
    ctx_end = min(len(lines), end_line + _CONTEXT_LINES + 1)

    snippet_lines = lines[ctx_start:ctx_end]
    prefix = "..." if ctx_start > 0 else ""
    suffix = "..." if ctx_end < len(lines) else ""
    return prefix + "\n".join(snippet_lines) + suffix


async def _create_note(
    user_id: str, kb: dict, path: str, title: str, content: str,
    tags: list[str], date_str: str, overwrite: bool = False,
) -> str:
    if not title:
        return "Error: title is required when creating a note."
    if not tags:
        return "Error: at least one tag is required when creating a note."

    # If path looks like a full filepath (ends with a file extension), split it
    _file_ext_pattern = re.compile(r"\.(md|txt|svg|csv|json|xml|html)$", re.IGNORECASE)
    if _file_ext_pattern.search(path):
        last_slash = path.rfind("/")
        if last_slash >= 0:
            dir_path = path[:last_slash + 1]
            # Use the filename from the path as a hint for the title slug
            path_filename = path[last_slash + 1:]
        else:
            dir_path = "/"
            path_filename = path
        # If no title was provided, derive from the path filename
        if not title:
            title = path_filename
    else:
        dir_path = path if path.endswith("/") else path + "/"
        path_filename = None

    if not dir_path.startswith("/"):
        dir_path = "/" + dir_path

    # Detect asset extensions
    _title_lower = title.lower()
    asset_ext = None
    for ext in _ASSET_EXTENSIONS:
        if _title_lower.endswith(ext):
            asset_ext = ext
            break

    # Derive filename (slug) from title
    if asset_ext:
        filename = re.sub(r"[^\w\s\-.]", "", _title_lower.replace(" ", "-"))
        file_type = asset_ext.lstrip(".")
    else:
        slug = _title_lower
        slug = re.sub(r"\.(md|txt)$", "", slug)
        filename = re.sub(r"[^\w\s\-.]", "", slug.replace(" ", "-"))
        if not filename.endswith(".md"):
            filename += ".md"
        file_type = "md"

    # Ensure title is human-readable, not a slug
    # "operating-leverage.md" → "Operating Leverage"
    clean_title = re.sub(r"\.(md|txt|svg|csv|json|xml|html)$", "", title)
    if clean_title == clean_title.lower() and "-" in clean_title:
        clean_title = clean_title.replace("-", " ").replace("_", " ").strip().title()
    title = clean_title

    note_date = date_str or date.today().isoformat()

    # Check for existing document at the same path
    existing = await scoped_queryrow(
        user_id,
        "SELECT id FROM documents "
        "WHERE knowledge_base_id = $1 AND filename = $2 AND path = $3 AND NOT archived",
        kb["id"], filename, dir_path,
    )
    if existing and not overwrite:
        return (
            f"Error: `{dir_path}{filename}` already exists. "
            f"Use `command=\"str_replace\"` to edit it, or pass `overwrite=true` to replace it entirely."
        )

    if existing and overwrite:
        doc = await service_queryrow(
            "UPDATE documents SET title = $3, content = $4, tags = $5, "
            "version = version + 1, updated_at = now() "
            "WHERE id = $1 AND user_id = $2 "
            "RETURNING id, filename, path",
            existing["id"], user_id, title, content, tags,
        )
    else:
        doc = await service_queryrow(
            "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, content, tags, version) "
            "VALUES ($1, $2, $3, $4, $5, $6, 'ready', $7, $8, 0) "
            "RETURNING id, filename, path",
            kb["id"], user_id, filename, title, dir_path, file_type, content, tags,
        )

    doc_id = str(doc["id"])
    link = deep_link(kb["slug"], doc["path"], doc["filename"])

    # Update reference graph and propagate staleness
    if dir_path.startswith("/wiki/") and file_type == "md":
        await update_references(user_id, str(kb["id"]), doc_id, content, dir_path)
        await propagate_staleness(doc_id)

    is_wiki = dir_path.startswith("/wiki/")
    suffix = ""
    if asset_ext:
        suffix = f"\n\nEmbed in wiki pages with: `![{title}]({filename})`"
    elif is_wiki:
        suffix = "\n\nRemember to cite sources using footnotes: `[^1]: source-file.pdf, p.X`"

    impact = await get_impact_surface(user_id, doc_id) if is_wiki else ""

    return (
        f"Created **{title}** at `{dir_path}{filename}`\n"
        f"Tags: {', '.join(tags)} | Date: {note_date}\n"
        f"[View in Supavault]({link}){suffix}{impact}"
    )


async def _edit_note(user_id: str, kb: dict, path: str, old_text: str, new_text: str, tags: list[str] | None = None) -> str:
    if not old_text:
        return "Error: old_text is required for str_replace."

    dir_path, filename = resolve_path(path)

    doc = await scoped_queryrow(
        user_id,
        "SELECT id, content FROM documents "
        "WHERE knowledge_base_id = $1 AND filename = $2 AND path = $3 AND NOT archived",
        kb["id"], filename, dir_path,
    )
    if not doc:
        return f"Document '{path}' not found."

    content = doc["content"] or ""
    count = content.count(old_text)
    if count == 0:
        return "Error: no match found for old_text."
    if count > 1:
        return f"Error: found {count} matches for old_text. Provide more context to match exactly once."

    # Find where the replacement lands so we can return surrounding context
    replace_start = content.index(old_text)
    new_content = content.replace(old_text, new_text, 1)

    if tags is not None:
        await service_execute(
            "UPDATE documents SET content = $1, tags = $4, version = version + 1 "
            "WHERE id = $2 AND user_id = $3",
            new_content, doc["id"], user_id, tags,
        )
    else:
        await service_execute(
            "UPDATE documents SET content = $1, version = version + 1 "
            "WHERE id = $2 AND user_id = $3",
            new_content, doc["id"], user_id,
        )

    # Update reference graph and propagate staleness
    doc_id = str(doc["id"])
    if dir_path.startswith("/wiki/"):
        await update_references(user_id, str(kb["id"]), doc_id, new_content, dir_path)
        await propagate_staleness(doc_id)

    # Return context window around the edit (5 lines above/below)
    context_snippet = _edit_context(new_content, replace_start, len(new_text))

    link = deep_link(kb["slug"], dir_path, filename)
    impact = await get_impact_surface(user_id, doc_id) if dir_path.startswith("/wiki/") else ""
    return (
        f"Edited `{path}`. Replaced 1 occurrence.\n[View in Supavault]({link})\n\n"
        f"**Context after edit:**\n```\n{context_snippet}\n```{impact}"
    )


async def _append_note(user_id: str, kb: dict, path: str, content: str, tags: list[str] | None = None) -> str:
    dir_path, filename = resolve_path(path)

    doc = await scoped_queryrow(
        user_id,
        "SELECT id, content FROM documents "
        "WHERE knowledge_base_id = $1 AND filename = $2 AND path = $3 AND NOT archived",
        kb["id"], filename, dir_path,
    )
    if not doc:
        return f"Document '{path}' not found."

    new_content = (doc["content"] or "") + "\n\n" + content
    if tags is not None:
        await service_execute(
            "UPDATE documents SET content = $1, tags = $4, version = version + 1 "
            "WHERE id = $2 AND user_id = $3",
            new_content, doc["id"], user_id, tags,
        )
    else:
        await service_execute(
            "UPDATE documents SET content = $1, version = version + 1 "
            "WHERE id = $2 AND user_id = $3",
            new_content, doc["id"], user_id,
        )

    # Update reference graph and propagate staleness
    doc_id = str(doc["id"])
    if dir_path.startswith("/wiki/"):
        await update_references(user_id, str(kb["id"]), doc_id, new_content, dir_path)
        await propagate_staleness(doc_id)

    link = deep_link(kb["slug"], dir_path, filename)
    impact = await get_impact_surface(user_id, doc_id) if dir_path.startswith("/wiki/") else ""
    return f"Appended to `{path}`.\n[View in Supavault]({link}){impact}"


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        name="write",
        description=(
            "Create or edit notes and wiki pages in the knowledge vault.\n\n"
            "Wiki pages should be created under `/wiki/` and should cite their sources using "
            "markdown footnotes (e.g. `[^1]: paper.pdf, p.3`).\n\n"
            "You can also create SVG diagrams and CSV data files as wiki assets:\n"
            "- `write(command=\"create\", path=\"/wiki/\", title=\"architecture-diagram.svg\", content=\"<svg>...</svg>\", tags=[\"diagram\"])`\n"
            "- `write(command=\"create\", path=\"/wiki/\", title=\"data-table.csv\", content=\"col1,col2\\nval1,val2\", tags=[\"data\"])`\n"
            "SVGs and other assets can be embedded in wiki pages via `![Architecture](architecture-diagram.svg)`\n\n"
            "Commands:\n"
            "- create: create a new page (title and tags are REQUIRED). Rejects if page already exists — use overwrite=true to replace.\n"
            "- str_replace: replace exact text in an existing page (read first)\n"
            "- append: add content to the end of an existing page"
        ),
    )
    async def write(
        ctx: Context,
        knowledge_base: str,
        command: Literal["create", "str_replace", "append"],
        path: str = "/",
        title: str = "",
        content: str = "",
        tags: list[str] | None = None,
        date_str: str = "",
        old_text: str = "",
        new_text: str = "",
        overwrite: bool = False,
    ) -> str:
        user_id = get_user_id(ctx)

        kb = await resolve_kb(user_id, knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        if command == "create":
            return await _create_note(user_id, kb, path, title, content, tags or [], date_str, overwrite)
        elif command == "str_replace":
            return await _edit_note(user_id, kb, path, old_text, new_text, tags)
        elif command == "append":
            return await _append_note(user_id, kb, path, content, tags)

        return f"Unknown command: {command}"
