import re
from datetime import date
from typing import Literal

from mcp.server.fastmcp import FastMCP, Context

from db import scoped_queryrow, scoped_execute
from .helpers import get_user_id, resolve_kb, deep_link, resolve_path

_ASSET_EXTENSIONS = {".svg", ".csv", ".json", ".xml", ".html"}


async def _create_note(
    user_id: str, kb: dict, path: str, title: str, content: str,
    tags: list[str], date_str: str,
) -> str:
    if not title:
        return "Error: title is required when creating a note."
    if not tags:
        return "Error: at least one tag is required when creating a note."

    dir_path = path if path.endswith("/") else path + "/"
    if not dir_path.startswith("/"):
        dir_path = "/" + dir_path

    _title_lower = title.lower()
    asset_ext = None
    for ext in _ASSET_EXTENSIONS:
        if _title_lower.endswith(ext):
            asset_ext = ext
            break

    if asset_ext:
        filename = re.sub(r"[^\w\s\-.]", "", _title_lower.replace(" ", "-"))
        file_type = asset_ext.lstrip(".")
    else:
        filename = re.sub(r"[^\w\s\-.]", "", _title_lower.replace(" ", "-"))
        if not filename.endswith(".md"):
            filename += ".md"
        file_type = "md"

    note_date = date_str or date.today().isoformat()

    doc = await scoped_queryrow(
        user_id,
        "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
        "file_type, status, content, tags, version) "
        "VALUES ($1, auth.uid(), $2, $3, $4, $5, 'ready', $6, $7, 0) "
        "RETURNING id, filename, path",
        kb["id"], filename, title, dir_path, file_type, content, tags,
    )

    link = deep_link(kb["slug"], doc["path"], doc["filename"])

    is_wiki = dir_path.startswith("/wiki/")
    suffix = ""
    if asset_ext:
        suffix = f"\n\nEmbed in wiki pages with: `![{title}]({filename})`"
    elif is_wiki:
        suffix = "\n\nRemember to cite sources using footnotes: `[^1]: source-file.pdf, p.X`"

    return (
        f"Created **{title}** at `{dir_path}{filename}`\n"
        f"Tags: {', '.join(tags)} | Date: {note_date}\n"
        f"[View in Supavault]({link}){suffix}"
    )


async def _edit_note(user_id: str, kb: dict, path: str, old_text: str, new_text: str) -> str:
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

    new_content = content.replace(old_text, new_text, 1)
    await scoped_execute(
        user_id,
        "UPDATE documents SET content = $1, version = version + 1 WHERE id = $2",
        new_content, doc["id"],
    )

    link = deep_link(kb["slug"], dir_path, filename)
    return f"Edited `{path}`. Replaced 1 occurrence.\n[View in Supavault]({link})"


async def _append_note(user_id: str, kb: dict, path: str, content: str) -> str:
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
    await scoped_execute(
        user_id,
        "UPDATE documents SET content = $1, version = version + 1 WHERE id = $2",
        new_content, doc["id"],
    )

    link = deep_link(kb["slug"], dir_path, filename)
    return f"Appended to `{path}`.\n[View in Supavault]({link})"


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
            "- create: create a new page (title and tags are REQUIRED)\n"
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
    ) -> str:
        user_id = get_user_id(ctx)

        kb = await resolve_kb(user_id, knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        if command == "create":
            return await _create_note(user_id, kb, path, title, content, tags or [], date_str)
        elif command == "str_replace":
            return await _edit_note(user_id, kb, path, old_text, new_text)
        elif command == "append":
            return await _append_note(user_id, kb, path, content)

        return f"Unknown command: {command}"
