"""Write tool — create, edit, and append wiki pages and notes (local mode)."""

import re
from datetime import date
from typing import Literal

from mcp.server.fastmcp import FastMCP, Context

from infra.db.sqlite import get_document, create_document, update_document_content, get_workspace
from infra.storage.local import resolve_workspace_path
from .helpers import get_user_id, deep_link, resolve_path
from .references import update_references, propagate_staleness, get_impact_surface

_ASSET_EXTENSIONS = {".svg", ".csv", ".json", ".xml", ".html"}
_FILE_EXT_RE = re.compile(r"\.(md|txt|svg|csv|json|xml|html)$", re.IGNORECASE)
_CONTEXT_LINES = 5


class WriteHandler:
    """Executes create, edit, and append operations on local documents."""

    def __init__(self, user_id: str, kb: dict):
        self.user_id = user_id
        self.kb = kb
        self.slug = kb["slug"]

    async def create(self, path: str, title: str, content: str, tags: list[str], date_str: str, overwrite: bool) -> str:
        """Create a new document or overwrite an existing one."""
        if not title:
            return "Error: title is required when creating a note."
        if not tags:
            return "Error: at least one tag is required when creating a note."

        dir_path = self._to_dir_path(path)
        filename, file_type = self._title_to_filename(title)
        title = self._humanize_title(title)

        existing = await get_document(self.user_id, self.slug, filename, dir_path)

        if existing and not overwrite:
            return (
                f"Error: `{dir_path}{filename}` already exists. "
                f"Use `command=\"str_replace\"` to edit it, or pass `overwrite=true` to replace."
            )

        if not self._write_to_disk(dir_path, filename, content):
            return f"Error: invalid path `{dir_path.lstrip('/') + filename}`"

        doc = await self._upsert_document(existing, dir_path, filename, file_type, title, content, tags)
        doc_id = str(doc["id"])
        await self._sync_references(doc_id, content, dir_path, file_type)

        impact = await self._get_wiki_impact(doc_id, dir_path)
        return self._format_create_response(title, tags, dir_path, filename, file_type, date_str) + impact

    async def edit(self, path: str, old_text: str, new_text: str, tags: list[str] | None) -> str:
        """Replace exact text in an existing document."""
        if not old_text:
            return "Error: old_text is required for str_replace."

        dir_path, filename = resolve_path(path)
        doc = await get_document(self.user_id, self.slug, filename, dir_path)
        if not doc:
            return f"Document '{path}' not found."

        content = doc.get("content") or ""
        error = self._validate_single_match(content, old_text)
        if error:
            return error

        replace_start = content.index(old_text)
        new_content = content.replace(old_text, new_text, 1)

        self._write_to_disk(dir_path, filename, new_content)

        doc_id = str(doc["id"])
        await update_document_content(doc_id, self.user_id, new_content, tags)
        await self._sync_references(doc_id, new_content, dir_path)

        snippet = self._extract_context(new_content, replace_start, len(new_text))
        impact = await self._get_wiki_impact(doc_id, dir_path)
        return self._format_edit_response(path, dir_path, filename, snippet) + impact

    async def append(self, path: str, content: str, tags: list[str] | None) -> str:
        """Append content to the end of an existing document."""
        dir_path, filename = resolve_path(path)
        doc = await get_document(self.user_id, self.slug, filename, dir_path)
        if not doc:
            return f"Document '{path}' not found."

        new_content = (doc.get("content") or "") + "\n\n" + content

        self._write_to_disk(dir_path, filename, new_content)

        doc_id = str(doc["id"])
        await update_document_content(doc_id, self.user_id, new_content, tags)
        await self._sync_references(doc_id, new_content, dir_path)

        impact = await self._get_wiki_impact(doc_id, dir_path)
        return self._format_append_response(path, dir_path, filename) + impact

    async def _upsert_document(self, existing: dict | None, dir_path: str, filename: str, file_type: str, title: str, content: str, tags: list[str]) -> dict:
        """Insert a new document or overwrite an existing one in the index."""
        if existing:
            await update_document_content(str(existing["id"]), self.user_id, content, tags)
            return existing
        return await create_document(self.user_id, self.kb["id"], filename, title, dir_path, file_type, content, tags)

    async def _sync_references(self, doc_id: str, content: str, dir_path: str, file_type: str = "md") -> None:
        """Update citation graph and propagate staleness for wiki pages."""
        if dir_path.startswith("/wiki/") and file_type == "md":
            await update_references(self.user_id, self.slug, doc_id, content, dir_path)
            await propagate_staleness(doc_id)

    async def _get_wiki_impact(self, doc_id: str, dir_path: str) -> str:
        """Return impact surface text for wiki pages, empty string otherwise."""
        if dir_path.startswith("/wiki/"):
            return await get_impact_surface(self.user_id, doc_id)
        return ""

    def _write_to_disk(self, dir_path: str, filename: str, content: str) -> bool:
        """Write content to the filesystem. Returns False if path is invalid."""
        relative_path = dir_path.lstrip("/") + filename
        file_path = resolve_workspace_path(relative_path)
        if not file_path:
            return False
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return True

    def _to_dir_path(self, path: str) -> str:
        """Normalize a raw path into a directory path."""
        if _FILE_EXT_RE.search(path):
            last_slash = path.rfind("/")
            return path[:last_slash + 1] if last_slash >= 0 else "/"
        dir_path = path if path.endswith("/") else path + "/"
        if not dir_path.startswith("/"):
            dir_path = "/" + dir_path
        return dir_path

    def _title_to_filename(self, title: str) -> tuple[str, str]:
        """Derive (filename, file_type) from a document title."""
        lower = title.lower()
        for ext in _ASSET_EXTENSIONS:
            if lower.endswith(ext):
                return self._slugify_filename(lower), ext.lstrip(".")
        slug = re.sub(r"\.(md|txt)$", "", lower)
        filename = self._slugify_filename(slug)
        if not filename.endswith(".md"):
            filename += ".md"
        return filename, "md"

    def _humanize_title(self, title: str) -> str:
        """Convert a slug-style title into a readable title."""
        clean = re.sub(r"\.(md|txt|svg|csv|json|xml|html)$", "", title)
        if clean == clean.lower() and "-" in clean:
            clean = clean.replace("-", " ").replace("_", " ").strip().title()
        return clean

    def _slugify_filename(self, name: str) -> str:
        """Strip non-word characters and replace spaces with dashes."""
        return re.sub(r"[^\w\s\-.]", "", name.replace(" ", "-"))

    def _validate_single_match(self, content: str, old_text: str) -> str | None:
        """Return an error string if old_text doesn't match exactly once, else None."""
        count = content.count(old_text)
        if count == 0:
            return "Error: no match found for old_text."
        if count > 1:
            return f"Error: found {count} matches for old_text. Provide more context to match exactly once."
        return None

    def _format_create_response(self, title: str, tags: list[str], dir_path: str, filename: str, file_type: str, date_str: str) -> str:
        """Build the response message for a create operation."""
        link = deep_link(self.slug, dir_path, filename)
        note_date = date_str or date.today().isoformat()
        suffix = self._embed_hint(title, filename, dir_path, file_type)
        return (
            f"Created **{title}** at `{dir_path}{filename}`\n"
            f"Tags: {', '.join(tags)} | Date: {note_date}\n"
            f"[View]({link}){suffix}"
        )

    def _format_edit_response(self, path: str, dir_path: str, filename: str, snippet: str) -> str:
        """Build the response message for an edit operation."""
        link = deep_link(self.slug, dir_path, filename)
        return (
            f"Edited `{path}`. Replaced 1 occurrence.\n[View]({link})\n\n"
            f"**Context after edit:**\n```\n{snippet}\n```"
        )

    def _format_append_response(self, path: str, dir_path: str, filename: str) -> str:
        """Build the response message for an append operation."""
        link = deep_link(self.slug, dir_path, filename)
        return f"Appended to `{path}`.\n[View]({link})"

    def _embed_hint(self, title: str, filename: str, dir_path: str, file_type: str) -> str:
        """Return an embed or citation hint for the create response."""
        if file_type != "md":
            return f"\n\nEmbed in wiki pages with: `![{title}]({filename})`"
        if dir_path.startswith("/wiki/"):
            return "\n\nRemember to cite sources using footnotes: `[^1]: source-file.pdf, p.X`"
        return ""

    def _extract_context(self, content: str, replace_start: int, new_text_len: int) -> str:
        """Return ~5 lines above and below the edited region."""
        lines = content.split("\n")
        start_line = self._char_offset_to_line(lines, replace_start)
        end_line = self._char_offset_to_line(lines, replace_start + new_text_len)
        ctx_start = max(0, start_line - _CONTEXT_LINES)
        ctx_end = min(len(lines), end_line + _CONTEXT_LINES + 1)
        prefix = "..." if ctx_start > 0 else ""
        suffix = "..." if ctx_end < len(lines) else ""
        return prefix + "\n".join(lines[ctx_start:ctx_end]) + suffix

    def _char_offset_to_line(self, lines: list[str], offset: int) -> int:
        """Map a character offset to its line number."""
        char_count = 0
        for i, line in enumerate(lines):
            if char_count + len(line) >= offset:
                return i
            char_count += len(line) + 1
        return len(lines) - 1


async def _resolve_local_kb(user_id: str, slug: str) -> dict | None:
    """Resolve a local workspace as a knowledge base."""
    ws = await get_workspace()
    if not ws:
        return None
    return {"id": ws["id"], "name": ws["name"], "slug": ws["name"]}


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

        handler = WriteHandler(user_id, kb)

        if command == "create":
            return await handler.create(path, title, content, tags or [], date_str, overwrite)
        elif command == "str_replace":
            return await handler.edit(path, old_text, new_text, tags)
        elif command == "append":
            return await handler.append(path, content, tags)

        return f"Unknown command: {command}"
