"""Write tool — create, edit, and append wiki pages and notes."""

import re
from datetime import date
from typing import Literal

from mcp.server.fastmcp import FastMCP, Context

from db import scoped_queryrow, service_queryrow, service_execute
from .helpers import get_user_id, resolve_kb, deep_link, resolve_path
from .references import update_references, propagate_staleness, get_impact_surface

_ASSET_EXTENSIONS = {".svg", ".csv", ".json", ".xml", ".html"}
_FILE_EXT_RE = re.compile(r"\.(md|txt|svg|csv|json|xml|html)$", re.IGNORECASE)
_CONTEXT_LINES = 5


class WriteHandler:
    """Executes create, edit, and append operations on documents."""

    def __init__(self, user_id: str, kb: dict):
        self.user_id = user_id
        self.kb = kb
        self.kb_id = str(kb["id"])

    async def create(self, path: str, title: str, content: str, tags: list[str], date_str: str, overwrite: bool) -> str:
        """Create a new document or overwrite an existing one."""
        if not title:
            return "Error: title is required when creating a note."
        if not tags:
            return "Error: at least one tag is required when creating a note."

        dir_path = self._to_dir_path(path)
        filename, file_type = self._title_to_filename(title)
        title = self._humanize_title(title)

        existing = await self._fetch_document(dir_path, filename)

        if existing and not overwrite:
            return (
                f"Error: `{dir_path}{filename}` already exists. "
                f"Use `command=\"str_replace\"` to edit it, or pass `overwrite=true` to replace it entirely."
            )

        doc = await self._upsert_document(existing, dir_path, filename, file_type, title, content, tags)
        doc_id = str(doc["id"])
        await self._sync_references(doc_id, content, dir_path, file_type)

        return self._format_create_response(doc, title, tags, dir_path, filename, file_type, date_str)

    async def edit(self, path: str, old_text: str, new_text: str, tags: list[str] | None) -> str:
        """Replace exact text in an existing document."""
        if not old_text:
            return "Error: old_text is required for str_replace."

        dir_path, filename = resolve_path(path)
        doc = await self._fetch_document(dir_path, filename)
        if not doc:
            return f"Document '{path}' not found."

        content = doc["content"] or ""
        error = self._validate_single_match(content, old_text)
        if error:
            return error

        replace_start = content.index(old_text)
        new_content = content.replace(old_text, new_text, 1)

        await self._save_content(doc["id"], new_content, tags)

        doc_id = str(doc["id"])
        await self._sync_references(doc_id, new_content, dir_path)

        snippet = self._extract_context(new_content, replace_start, len(new_text))
        return self._format_edit_response(path, dir_path, filename, doc_id, snippet)

    async def append(self, path: str, content: str, tags: list[str] | None) -> str:
        """Append content to the end of an existing document."""
        dir_path, filename = resolve_path(path)
        doc = await self._fetch_document(dir_path, filename)
        if not doc:
            return f"Document '{path}' not found."

        new_content = (doc["content"] or "") + "\n\n" + content

        await self._save_content(doc["id"], new_content, tags)

        doc_id = str(doc["id"])
        await self._sync_references(doc_id, new_content, dir_path)

        return self._format_append_response(path, dir_path, filename, doc_id)

    async def _fetch_document(self, dir_path: str, filename: str) -> dict | None:
        """Fetch a document by path and filename."""
        return await scoped_queryrow(
            self.user_id,
            "SELECT id, content FROM documents "
            "WHERE knowledge_base_id = $1 AND filename = $2 AND path = $3 AND NOT archived AND user_id = $4",
            self.kb["id"], filename, dir_path, self.user_id,
        )

    async def _upsert_document(self, existing: dict | None, dir_path: str, filename: str, file_type: str, title: str, content: str, tags: list[str]) -> dict:
        """Insert a new document or overwrite an existing one."""
        if existing:
            return await service_queryrow(
                "UPDATE documents SET title = $3, content = $4, tags = $5, "
                "version = version + 1, updated_at = now() "
                "WHERE id = $1 AND user_id = $2 RETURNING id, filename, path",
                existing["id"], self.user_id, title, content, tags,
            )
        return await service_queryrow(
            "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, content, tags, version) "
            "VALUES ($1, $2, $3, $4, $5, $6, 'ready', $7, $8, 0) RETURNING id, filename, path",
            self.kb["id"], self.user_id, filename, title, dir_path, file_type, content, tags,
        )

    async def _save_content(self, doc_id: str, content: str, tags: list[str] | None) -> None:
        """Persist updated content and optionally tags."""
        if tags is not None:
            await service_execute(
                "UPDATE documents SET content = $1, tags = $4, version = version + 1 WHERE id = $2 AND user_id = $3",
                content, doc_id, self.user_id, tags,
            )
        else:
            await service_execute(
                "UPDATE documents SET content = $1, version = version + 1 WHERE id = $2 AND user_id = $3",
                content, doc_id, self.user_id,
            )

    async def _sync_references(self, doc_id: str, content: str, dir_path: str, file_type: str = "md") -> None:
        """Update citation graph and propagate staleness for wiki pages."""
        if dir_path.startswith("/wiki/") and file_type == "md":
            await update_references(self.user_id, self.kb_id, doc_id, content, dir_path)
            await propagate_staleness(self.user_id, doc_id)

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

    async def _get_wiki_impact(self, doc_id: str, dir_path: str) -> str:
        """Return impact surface text for wiki pages, empty string otherwise."""
        if dir_path.startswith("/wiki/"):
            return await get_impact_surface(self.user_id, doc_id)
        return ""

    def _format_create_response(self, doc: dict, title: str, tags: list[str], dir_path: str, filename: str, file_type: str, date_str: str) -> str:
        """Build the response message for a create operation."""
        link = deep_link(self.kb["slug"], doc["path"], doc["filename"])
        note_date = date_str or date.today().isoformat()
        suffix = self._embed_hint(title, filename, dir_path, file_type)
        return (
            f"Created **{title}** at `{dir_path}{filename}`\n"
            f"Tags: {', '.join(tags)} | Date: {note_date}\n"
            f"[View in Supavault]({link}){suffix}"
        )

    def _format_edit_response(self, path: str, dir_path: str, filename: str, doc_id: str, snippet: str) -> str:
        """Build the response message for an edit operation."""
        link = deep_link(self.kb["slug"], dir_path, filename)
        return (
            f"Edited `{path}`. Replaced 1 occurrence.\n[View in Supavault]({link})\n\n"
            f"**Context after edit:**\n```\n{snippet}\n```"
        )

    def _format_append_response(self, path: str, dir_path: str, filename: str, doc_id: str) -> str:
        """Build the response message for an append operation."""
        link = deep_link(self.kb["slug"], dir_path, filename)
        return f"Appended to `{path}`.\n[View in Supavault]({link})"

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

        handler = WriteHandler(user_id, kb)

        if command == "create":
            return await handler.create(path, title, content, tags or [], date_str, overwrite)
        elif command == "str_replace":
            return await handler.edit(path, old_text, new_text, tags)
        elif command == "append":
            return await handler.append(path, content, tags)

        return f"Unknown command: {command}"
