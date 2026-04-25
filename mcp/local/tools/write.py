"""Local write tool — file-first writes.

All writes go to disk first, then update the SQLite index.
The filesystem is always the source of truth.
"""

import os
import re
from datetime import date
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP, Context

from infra.db.sqlite import (
    get_document, create_document, update_document_content, get_workspace,
)
from infra.storage.local import resolve_workspace_path
from .helpers import get_user_id, deep_link, resolve_path
from .references import update_references, propagate_staleness, get_impact_surface

_ASSET_EXTENSIONS = {".svg", ".csv", ".json", ".xml", ".html"}

_CONTEXT_LINES = 5


def _edit_context(content: str, replace_start: int, new_text_len: int) -> str:
    lines = content.split("\n")
    char_count = 0
    start_line = 0
    for i, line in enumerate(lines):
        if char_count + len(line) >= replace_start:
            start_line = i
            break
        char_count += len(line) + 1

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


def _derive_filename(title: str) -> tuple[str, str]:
    """Derive filename and file_type from title."""
    title_lower = title.lower()
    for ext in _ASSET_EXTENSIONS:
        if title_lower.endswith(ext):
            filename = re.sub(r"[^\w\s\-.]", "", title_lower.replace(" ", "-"))
            return filename, ext.lstrip(".")

    slug = re.sub(r"\.(md|txt)$", "", title_lower)
    filename = re.sub(r"[^\w\s\-.]", "", slug.replace(" ", "-"))
    if not filename.endswith(".md"):
        filename += ".md"
    return filename, "md"


def _humanize_title(title: str) -> str:
    clean = re.sub(r"\.(md|txt|svg|csv|json|xml|html)$", "", title)
    if clean == clean.lower() and "-" in clean:
        clean = clean.replace("-", " ").replace("_", " ").strip().title()
    return clean


async def _resolve_local_kb(user_id: str, slug: str) -> dict | None:
    ws = await get_workspace()
    if not ws:
        return None
    return {"id": ws["id"], "name": ws["name"], "slug": ws["name"]}


async def _create_note(
    user_id: str, kb: dict, path: str, title: str, content: str,
    tags: list[str], date_str: str, overwrite: bool = False,
) -> str:
    if not title:
        return "Error: title is required when creating a note."
    if not tags:
        return "Error: at least one tag is required when creating a note."

    # Handle full filepath in path param
    _file_ext_pattern = re.compile(r"\.(md|txt|svg|csv|json|xml|html)$", re.IGNORECASE)
    if _file_ext_pattern.search(path):
        last_slash = path.rfind("/")
        dir_path = path[:last_slash + 1] if last_slash >= 0 else "/"
    else:
        dir_path = path if path.endswith("/") else path + "/"

    if not dir_path.startswith("/"):
        dir_path = "/" + dir_path

    filename, file_type = _derive_filename(title)
    title = _humanize_title(title)
    note_date = date_str or date.today().isoformat()

    # Check for existing
    existing = await get_document(user_id, kb["slug"], filename, dir_path)
    if existing and not overwrite:
        return (
            f"Error: `{dir_path}{filename}` already exists. "
            f"Use `command=\"str_replace\"` to edit it, or pass `overwrite=true` to replace."
        )

    # Write to filesystem first
    relative_path = (dir_path.lstrip("/") + filename)
    file_path = resolve_workspace_path(relative_path)
    if not file_path:
        return f"Error: invalid path `{relative_path}`"

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")

    # Then update the index
    if existing and overwrite:
        await update_document_content(str(existing["id"]), user_id, content, tags)
        doc = existing
    else:
        doc = await create_document(
            user_id, kb["id"], filename, title, dir_path, file_type, content, tags,
        )

    doc_id = str(doc["id"])
    link = deep_link(kb["slug"], dir_path, filename)

    is_wiki = dir_path.startswith("/wiki/")
    if is_wiki and filename.endswith(".md"):
        await update_references(user_id, kb["slug"], doc_id, content, dir_path)
        await propagate_staleness(doc_id)

    asset_ext = None
    for ext in _ASSET_EXTENSIONS:
        if filename.endswith(ext):
            asset_ext = ext
            break

    suffix = ""
    if asset_ext:
        suffix = f"\n\nEmbed in wiki pages with: `![{title}]({filename})`"
    elif is_wiki:
        suffix = "\n\nRemember to cite sources using footnotes: `[^1]: source-file.pdf, p.X`"

    impact = await get_impact_surface(user_id, doc_id) if is_wiki else ""

    return (
        f"Created **{title}** at `{dir_path}{filename}`\n"
        f"Tags: {', '.join(tags)} | Date: {note_date}\n"
        f"[View]({link}){suffix}{impact}"
    )


async def _edit_note(user_id: str, kb: dict, path: str, old_text: str, new_text: str, tags: list[str] | None = None) -> str:
    if not old_text:
        return "Error: old_text is required for str_replace."

    dir_path, filename = resolve_path(path)

    doc = await get_document(user_id, kb["slug"], filename, dir_path)
    if not doc:
        return f"Document '{path}' not found."

    content = doc.get("content") or ""
    count = content.count(old_text)
    if count == 0:
        return "Error: no match found for old_text."
    if count > 1:
        return f"Error: found {count} matches for old_text. Provide more context to match exactly once."

    replace_start = content.index(old_text)
    new_content = content.replace(old_text, new_text, 1)

    # Write to filesystem first
    relative_path = (dir_path.lstrip("/") + filename)
    file_path = resolve_workspace_path(relative_path)
    if file_path:
        file_path.write_text(new_content, encoding="utf-8")

    # Then update index
    doc_id = str(doc["id"])
    await update_document_content(doc_id, user_id, new_content, tags)

    if dir_path.startswith("/wiki/"):
        await update_references(user_id, kb["slug"], doc_id, new_content, dir_path)
        await propagate_staleness(doc_id)

    context_snippet = _edit_context(new_content, replace_start, len(new_text))
    impact = await get_impact_surface(user_id, doc_id) if dir_path.startswith("/wiki/") else ""

    link = deep_link(kb["slug"], dir_path, filename)
    return (
        f"Edited `{path}`. Replaced 1 occurrence.\n[View]({link})\n\n"
        f"**Context after edit:**\n```\n{context_snippet}\n```{impact}"
    )


async def _append_note(user_id: str, kb: dict, path: str, content: str, tags: list[str] | None = None) -> str:
    dir_path, filename = resolve_path(path)

    doc = await get_document(user_id, kb["slug"], filename, dir_path)
    if not doc:
        return f"Document '{path}' not found."

    new_content = (doc.get("content") or "") + "\n\n" + content

    # Write to filesystem first
    relative_path = (dir_path.lstrip("/") + filename)
    file_path = resolve_workspace_path(relative_path)
    if file_path:
        file_path.write_text(new_content, encoding="utf-8")

    # Then update index
    doc_id = str(doc["id"])
    await update_document_content(doc_id, user_id, new_content, tags)

    if dir_path.startswith("/wiki/"):
        await update_references(user_id, kb["slug"], doc_id, new_content, dir_path)
        await propagate_staleness(doc_id)

    impact = await get_impact_surface(user_id, doc_id) if dir_path.startswith("/wiki/") else ""

    link = deep_link(kb["slug"], dir_path, filename)
    return f"Appended to `{path}`.\n[View]({link}){impact}"


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        name="write",
        description=(
            "Create or edit notes and wiki pages in the knowledge vault.\n\n"
            "Wiki pages should be created under `/wiki/` and should cite their sources.\n\n"
            "Commands:\n"
            "- create: create a new page (title and tags REQUIRED)\n"
            "- str_replace: replace exact text in an existing page\n"
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

        kb = await _resolve_local_kb(user_id, knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        if command == "create":
            return await _create_note(user_id, kb, path, title, content, tags or [], date_str, overwrite)
        elif command == "str_replace":
            return await _edit_note(user_id, kb, path, old_text, new_text, tags)
        elif command == "append":
            return await _append_note(user_id, kb, path, content, tags)

        return f"Unknown command: {command}"
