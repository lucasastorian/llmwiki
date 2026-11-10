import re
from dataclasses import replace
from datetime import date

import yaml
from vaultfs import VaultFS
from vaultfs.base import DuplicateDocumentError, StorageQuotaExceededError

from mcp.server.fastmcp import Context, FastMCP

from .helpers import deep_link, resolve_path
from .patch import FileUpdate, PatchError, PatchParser, apply_hunks, render_diff
from .quiz_lint import QUIZ_SCHEMA_HINT, lint_quiz_blocks
from .references import update_references
from .types import PlannedPage

_ASSET_EXTENSIONS = {".svg", ".csv", ".json", ".xml", ".html"}
_FILE_EXT_RE = re.compile(r"\.(md|txt|svg|csv|json|xml|html)$", re.IGNORECASE)
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.+?\n)---[ \t]*\n", re.DOTALL)
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:", re.MULTILINE)
_MAX_TEXT_CONTENT_BYTES = 10 * 1024 * 1024
TEXT_BACKED_TYPES = frozenset({"md", "txt", "svg", "csv", "json", "xml"})


def _content_size_error(content: str) -> str | None:
    if len(content.encode("utf-8")) > _MAX_TEXT_CONTENT_BYTES:
        return "Error: content exceeds the 10 MiB text-document limit."
    return None


def _read_only_source_error(path: str, doc: dict) -> str | None:
    if doc["file_type"] in TEXT_BACKED_TYPES:
        return None
    return (
        f"Error: '{path}' is a {doc['file_type']} source, and sources are read-only. "
        "Write your notes into a wiki page instead."
    )


def _quiz_block_error(content: str) -> str | None:
    errors = lint_quiz_blocks(content)
    if not errors:
        return None
    details = "\n".join(f"- {error}" for error in errors)
    return f"Error: invalid ```quiz block(s) — nothing was written.\n{details}\n{QUIZ_SCHEMA_HINT}"


def _content_error(content: str) -> str | None:
    return _content_size_error(content) or _quiz_block_error(content)


def _parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter metadata from content. Returns empty dict if none."""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}
    try:
        meta = yaml.safe_load(m.group(1))
        return meta if isinstance(meta, dict) else {}
    except yaml.YAMLError:
        return {}


def _extract_metadata(meta: dict) -> tuple[str | None, dict]:
    """Extract the date and the frontmatter-owned metadata keys (description) to merge into the document."""
    date_str = None
    if "date" in meta:
        d = meta["date"]
        date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)

    metadata: dict = {}
    if isinstance(meta.get("description"), str) and meta["description"].strip():
        metadata["description"] = meta["description"].strip()

    return date_str, metadata


def _extract_frontmatter_tags(meta: dict) -> list[str] | None:
    """Return normalized frontmatter tags, or None when frontmatter has no tags."""
    if "tags" not in meta:
        return None
    raw_tags = meta.get("tags")
    if isinstance(raw_tags, list):
        return [str(t).strip() for t in raw_tags if str(t).strip()]
    if isinstance(raw_tags, str):
        return [t.strip() for t in raw_tags.split(",") if t.strip()]
    return []


def _effective_tags(content: str, provided: list[str] | None) -> list[str] | None:
    """Use frontmatter tags as canonical when present; otherwise fallback."""
    fm_tags = _extract_frontmatter_tags(_parse_frontmatter(content))
    if fm_tags is not None:
        return fm_tags
    return provided


def _effective_date(content: str, provided: str | None = None) -> str | None:
    """Use frontmatter date as canonical when present; otherwise fallback."""
    fm_date, _ = _extract_metadata(_parse_frontmatter(content))
    return fm_date or provided or None


def _ensure_wiki_frontmatter(
    content: str,
    title: str,
    tags: list[str],
    date_str: str,
    dir_path: str,
    filename: str,
    file_type: str,
) -> str:
    """Add required wiki frontmatter when the caller supplied metadata as args."""
    if file_type != "md" or not dir_path.startswith("/wiki/"):
        return content
    if dir_path == "/wiki/" and filename == "log.md":
        return content
    if _FRONTMATTER_RE.match(content):
        return content

    metadata = {
        "title": title,
        "description": _default_description(content, title),
        "date": date_str.strip() or date.today().isoformat(),
        "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
    }
    frontmatter = yaml.safe_dump(
        metadata,
        sort_keys=False,
        allow_unicode=False,
        default_flow_style=False,
    ).strip()
    body = content.lstrip("\n")
    return f"---\n{frontmatter}\n---\n\n{body}"


def _default_description(content: str, title: str) -> str:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("[^"):
            continue
        line = re.sub(r"^#+\s*", "", line).strip()
        if line:
            return line[:180]
    return f"Notes about {title}."


def _is_footnote_suffix_line(line: str) -> bool:
    return line.strip() == "" or line.startswith((" ", "\t")) or bool(_FOOTNOTE_DEF_RE.match(line))


def _split_trailing_footnotes(content: str) -> tuple[str, str]:
    """Split markdown into body and the trailing footnote-definition block, which conventionally lives at EOF."""
    stripped = content.rstrip()
    if not stripped:
        return "", ""

    lines = stripped.splitlines()
    for idx, line in enumerate(lines):
        if _FOOTNOTE_DEF_RE.match(line) and all(
            _is_footnote_suffix_line(suffix_line)
            for suffix_line in lines[idx:]
        ):
            return "\n".join(lines[:idx]).rstrip(), "\n".join(lines[idx:]).rstrip()
    return stripped, ""


def _append_markdown_section(existing: str, addition: str) -> str:
    """Append markdown while keeping trailing footnote definitions at EOF."""
    addition = _renumber_colliding_footnotes(existing, addition.strip("\n"))
    body, footnotes = _split_trailing_footnotes(existing)
    parts = [part for part in (body, addition, footnotes) if part]
    return "\n\n".join(parts)


def _renumber_colliding_footnotes(existing: str, addition: str) -> str:
    """Avoid duplicate page-local footnote ids when appending markdown."""
    existing_ids = set(_FOOTNOTE_DEF_RE.findall(existing))
    incoming_ids = _FOOTNOTE_DEF_RE.findall(addition)
    if not existing_ids or not incoming_ids:
        return addition

    numeric_ids = [
        int(i)
        for i in existing_ids.union(incoming_ids)
        if i.isdigit()
    ]
    next_id = max(numeric_ids, default=0) + 1
    used = set(existing_ids)
    replacements: dict[str, str] = {}

    for footnote_id in incoming_ids:
        if footnote_id not in used:
            used.add(footnote_id)
            continue
        while str(next_id) in used:
            next_id += 1
        replacement = str(next_id)
        replacements[footnote_id] = replacement
        used.add(replacement)
        next_id += 1

    for old, new in replacements.items():
        addition = re.sub(
            rf"\[\^{re.escape(old)}\]",
            f"[^{new}]",
            addition,
        )
    return addition


class WriteHandler:
    def __init__(self, fs: VaultFS, kb: dict):
        self.fs = fs
        self.kb = kb
        self.kb_id = str(kb["id"])

    async def create(self, path: str, title: str, content: str, tags: list[str], date_str: str, overwrite: bool) -> str:
        """Create a new document or overwrite an existing one."""
        if not title:
            return "Error: title is required when creating a note."

        dir_path = self._to_dir_path(path)
        filename, file_type = self._explicit_filename(path) or self._title_to_filename(title)
        title = self._humanize_title(title)
        content = _ensure_wiki_frontmatter(content, title, tags, date_str, dir_path, filename, file_type)

        content_error = _content_error(content)
        if content_error:
            return content_error

        effective_tags = _effective_tags(content, tags) or []
        if not effective_tags:
            return "Error: at least one tag is required when creating a note."

        existing = await self.fs.get_document(self.kb_id, filename, dir_path)

        if existing and not overwrite:
            return (
                f"Error: `{dir_path}{filename}` already exists. "
                f"Use the `patch` tool to modify it, or pass `overwrite=true` to replace it entirely."
            )

        try:
            written = self.fs.write_to_disk(dir_path, filename, content, exclusive=existing is None)
        except FileExistsError:
            return (
                f"Error: a file already exists on disk at `{dir_path}{filename}` but isn't in the wiki index. "
                "Choose a different title or path."
            )
        if not written:
            return f"Error: invalid path `{dir_path.lstrip('/') + filename}` (hidden folders and paths outside the workspace are not writable)"

        meta = _parse_frontmatter(content)
        fm_date, fm_metadata = _extract_metadata(meta)
        saved_date = _effective_date(content, date_str)

        if existing:
            try:
                await self.fs.update_document(
                    str(existing["id"]),
                    content,
                    effective_tags,
                    title=title,
                    date=saved_date,
                    metadata=fm_metadata,
                )
            except StorageQuotaExceededError as e:
                return f"Error: {e}"
            doc = existing
        else:
            try:
                doc = await self.fs.create_document(
                    self.kb_id,
                    filename,
                    title,
                    dir_path,
                    file_type,
                    content,
                    effective_tags,
                    date=saved_date,
                    metadata=fm_metadata,
                )
            except DuplicateDocumentError:
                return (
                    f"Error: `{dir_path}{filename}` already exists. "
                    f"Use the `patch` tool to modify it, or pass `overwrite=true` to replace it entirely."
                )
            except StorageQuotaExceededError as e:
                return f"Error: {e}"

        doc_id = str(doc["id"])
        await self._sync_references(doc_id, content, dir_path, file_type)

        impact = await self._get_wiki_impact(doc_id, dir_path)
        return self._format_create_response(
            title,
            effective_tags,
            dir_path,
            filename,
            file_type,
            saved_date,
        ) + impact

    async def patch(self, patch_text: str, dry_run: bool) -> str:
        """Apply a patch to one or more pages, writing only after every hunk has matched."""
        try:
            pages, notes = await self._plan_patch(PatchParser().parse(patch_text))
        except PatchError as e:
            return f"Error: {e}\nNo pages were changed."
        if dry_run:
            return self._format_patch_response(pages, notes, "Dry run — no pages were changed. This patch would make:")

        saved: list[PlannedPage] = []
        for page in pages:
            error = await self._save(page.doc, page.dir_path, page.filename, page.after)
            if error:
                return self._format_partial_patch_error(error, page, saved)
            saved.append(page)

        impact = "".join([
            await self._get_wiki_impact(str(page.doc["id"]), page.dir_path, f"`{page.path}`")
            for page in pages
        ])
        return self._format_patch_response(pages, notes, f"Patched {len(pages)} page(s):") + impact

    async def append(self, path: str, content: str) -> str:
        """Append content to the end of an existing document."""
        dir_path, filename = resolve_path(path)
        doc = await self.fs.get_document(self.kb_id, filename, dir_path)
        if not doc:
            return f"Document '{path}' not found."

        read_only_error = _read_only_source_error(path, doc)
        if read_only_error:
            return read_only_error

        new_content = _append_markdown_section(doc.get("content") or "", content)
        content_error = _content_error(new_content)
        if content_error:
            return content_error

        save_error = await self._save(doc, dir_path, filename, new_content)
        if save_error:
            return save_error

        impact = await self._get_wiki_impact(str(doc["id"]), dir_path)
        return self._format_append_response(path, dir_path, filename) + impact

    async def _plan_patch(self, updates: list[FileUpdate]) -> tuple[list[PlannedPage], list[str]]:
        """Patch every page in memory and validate the results; raise PatchError on the first failure."""
        pages: dict[str, PlannedPage] = {}
        notes: list[str] = []
        for update in updates:
            dir_path, filename = resolve_path(update.path)
            key = dir_path + filename
            page = pages.get(key) or await self._load_patch_page(update.path, dir_path, filename)
            patched = apply_hunks(key, page.after, update.hunks)
            notes.extend(patched.notes)
            pages[key] = replace(page, after=patched.content)

        for page in pages.values():
            error = _content_error(page.after)
            if error:
                raise PatchError(f"{page.path}: {error.removeprefix('Error: ')}")
        return list(pages.values()), notes

    async def _load_patch_page(self, path: str, dir_path: str, filename: str) -> PlannedPage:
        doc = await self.fs.get_document(self.kb_id, filename, dir_path)
        if not doc:
            raise PatchError(f"page '{path}' not found")
        read_only_error = _read_only_source_error(path, doc)
        if read_only_error:
            raise PatchError(read_only_error.removeprefix("Error: "))
        content = doc.get("content") or ""
        return PlannedPage(
            path=dir_path + filename,
            dir_path=dir_path,
            filename=filename,
            doc=doc,
            before=content,
            after=content,
        )

    async def _save(self, doc: dict, dir_path: str, filename: str, content: str) -> str | None:
        """Write validated content to disk and the index, then refresh citations; return an error or None."""
        self.fs.write_to_disk(dir_path, filename, content)
        fm_date, fm_metadata = _extract_metadata(_parse_frontmatter(content))
        try:
            await self.fs.update_document(
                str(doc["id"]),
                content,
                _effective_tags(content, None),
                date=fm_date,
                metadata=fm_metadata,
            )
        except StorageQuotaExceededError as e:
            return f"Error: {e}"
        await self._sync_references(str(doc["id"]), content, dir_path)
        return None

    async def _sync_references(self, doc_id: str, content: str, dir_path: str, file_type: str = "md") -> None:
        """Update citation graph and propagate staleness for wiki pages."""
        if dir_path.startswith("/wiki/") and file_type == "md":
            await update_references(self.fs, self.kb_id, doc_id, content, dir_path)
            await self.fs.propagate_staleness(doc_id)

    async def _get_wiki_impact(self, doc_id: str, dir_path: str, subject: str = "this document") -> str:
        """Return impact surface text for wiki pages, empty string otherwise."""
        if not dir_path.startswith("/wiki/"):
            return ""
        rows = await self.fs.get_backlinks(doc_id)
        if not rows:
            return ""
        lines = [f"\n**{len(rows)} page(s) reference {subject}** — consider updating:"]
        for r in rows:
            path = f"{r['path']}{r['filename']}"
            title = r["title"] or r["filename"]
            ref = "cites" if r["reference_type"] == "cites" else "links to"
            lines.append(f"  - `{path}` ({title}) — {ref} this page")
        return "\n".join(lines)

    def _to_dir_path(self, path: str) -> str:
        """Normalize a folder or file path into a '/dir/' directory path."""
        if _FILE_EXT_RE.search(path):
            path = path[:path.rfind("/") + 1]
        dir_path = path if path.endswith("/") else path + "/"
        return dir_path if dir_path.startswith("/") else "/" + dir_path

    def _explicit_filename(self, path: str) -> tuple[str, str] | None:
        """(filename, file_type) when `path` names a file, kept exactly as given; None for a folder path."""
        if not _FILE_EXT_RE.search(path):
            return None
        filename = path.rsplit("/", 1)[-1]
        return filename, filename.rsplit(".", 1)[-1].lower()

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

    def _format_create_response(self, title: str, tags: list[str], dir_path: str, filename: str, file_type: str, date_str: str | None) -> str:
        link = deep_link(self.kb["slug"], dir_path, filename)
        note_date = date_str or date.today().isoformat()
        suffix = self._embed_hint(title, filename, dir_path, file_type)
        return (
            f"Created **{title}** at `{dir_path}{filename}`\n"
            f"Tags: {', '.join(tags)} | Date: {note_date}\n"
            f"[View]({link}){suffix}"
        )

    def _format_patch_response(self, pages: list[PlannedPage], notes: list[str], heading: str) -> str:
        parts = [heading]
        for page in pages:
            link = deep_link(self.kb["slug"], page.dir_path, page.filename)
            diff = render_diff(page.path, page.before, page.after)
            parts.append(f"\n`{page.path}` — [View]({link})\n```diff\n{diff}\n```")
        if notes:
            parts.append("\n**Notes:**\n" + "\n".join(f"- {note}" for note in notes))
        return "\n".join(parts)

    def _format_partial_patch_error(self, error: str, failed: PlannedPage, saved: list[PlannedPage]) -> str:
        if not saved:
            return f"{error} (while saving `{failed.path}`)\nNo pages were changed."
        saved_paths = ", ".join(f"`{page.path}`" for page in saved)
        return (
            f"{error} (while saving `{failed.path}`)\n"
            f"Already saved and live: {saved_paths}. `{failed.path}` and any later pages were not changed."
        )

    def _format_append_response(self, path: str, dir_path: str, filename: str) -> str:
        link = deep_link(self.kb["slug"], dir_path, filename)
        return f"Appended to `{path}`.\n[View]({link})"

    def _embed_hint(self, title: str, filename: str, dir_path: str, file_type: str) -> str:
        """Return an embed or citation hint for the create response."""
        if file_type != "md":
            return f"\n\nEmbed in wiki pages with: `![{title}]({filename})`"
        if dir_path.startswith("/wiki/"):
            return "\n\nRemember to cite sources using footnotes: `[^1]: source-file.pdf, p.X`"
        return ""


def register(mcp: FastMCP, get_user_id, fs_factory) -> None:

    async def _resolve(ctx: Context, knowledge_base: str):
        user_id = get_user_id(ctx)
        fs = fs_factory(user_id)
        kb = await fs.resolve_kb(knowledge_base)
        return (WriteHandler(fs, kb), None) if kb else (None, f"Knowledge base '{knowledge_base}' not found.")

    @mcp.tool(
        name="create",
        description=(
            "Create a new wiki page, note, or asset in the knowledge vault.\n\n"
            "Wiki pages should be created under `/wiki/` and should cite their sources using "
            "markdown footnotes (e.g. `[^1]: paper.pdf, p.3`). If markdown wiki content "
            "does not include YAML frontmatter, this tool adds it from `title`, `tags`, and `date_str`.\n\n"
            "You can also create SVG diagrams and CSV data files as wiki assets:\n"
            "- `create(path=\"/wiki/\", title=\"architecture-diagram.svg\", content=\"<svg>...</svg>\", tags=[\"diagram\"])`\n"
            "- `create(path=\"/wiki/\", title=\"data-table.csv\", content=\"col1,col2\\nval1,val2\", tags=[\"data\"])`\n"
            "SVGs and other assets can be embedded in wiki pages via `![Architecture](architecture-diagram.svg)`\n\n"
            "`path` is either a folder (`/wiki/concepts/`, filename derived from `title`) or a full file path "
            "(`/wiki/concepts/attention.md`, filename used as given).\n\n"
            "Rejects if the page already exists — use `overwrite=true` to replace, or use the `patch` tool to modify."
        ),
    )
    async def create(
        ctx: Context,
        knowledge_base: str,
        title: str,
        content: str,
        tags: list[str],
        path: str = "/wiki/",
        date_str: str = "",
        overwrite: bool = False,
    ) -> str:
        handler, err = await _resolve(ctx, knowledge_base)
        if err:
            return err
        return await handler.create(path, title, content, tags, date_str, overwrite)

    @mcp.tool(
        name="patch",
        description=(
            "Change existing wiki pages or notes with a patch — several edits across several pages in one call.\n\n"
            "```\n"
            "*** Begin Patch\n"
            "*** Update File: /wiki/concepts/attention.md\n"
            "@@ ## Scaling\n"
            " An unchanged context line (leading space)\n"
            "-A line to remove\n"
            "+A line to add\n"
            "*** Update File: /wiki/overview.md\n"
            "@@\n"
            "-Old line\n"
            "+New line\n"
            "*** End Patch\n"
            "```\n\n"
            "- Hunk lines start with ' ' (context), '-' (remove) or '+' (add) and match whole lines. "
            "Matching tolerates surrounding whitespace and curly-quote, dash and non-breaking-space variants.\n"
            "- `@@ <line>` first finds a line matching <line> (e.g. a heading) and searches after it; use it "
            "when lines repeat. A hunk with only '+' lines is inserted right after its @@ line, or at the end "
            "of the page without one. `*** End of File` after a hunk pins it to the end of the page.\n"
            "- Hunks for one page apply top to bottom.\n"
            "- Every hunk is checked before anything is written: if one fails, no page changes. "
            "`dry_run=true` returns the diff without writing.\n"
            "- New pages: `create`. Removing pages: `delete`. Adding to the end of a page: `append`.\n\n"
            "Read the page first so removed and context lines match its current text."
        ),
    )
    async def patch(
        ctx: Context,
        knowledge_base: str,
        patch: str,
        dry_run: bool = False,
    ) -> str:
        handler, err = await _resolve(ctx, knowledge_base)
        if err:
            return err
        return await handler.patch(patch, dry_run)

    @mcp.tool(
        name="append",
        description=(
            "Append content to the end of an existing wiki page or note.\n\n"
            "Useful for adding new sections, log entries, or additional findings "
            "to a page without reading and rewriting the entire document."
        ),
    )
    async def append(
        ctx: Context,
        knowledge_base: str,
        path: str,
        content: str,
    ) -> str:
        handler, err = await _resolve(ctx, knowledge_base)
        if err:
            return err
        return await handler.append(path, content)
