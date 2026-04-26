"""Delete tool — remove documents from the knowledge vault."""

from mcp.server.fastmcp import FastMCP, Context

from vaultfs import VaultFS
from .helpers import glob_match, resolve_path

_PROTECTED_FILES = {("/wiki/", "overview.md"), ("/wiki/", "log.md")}


def _is_protected(doc: dict) -> bool:
    return (doc.get("path", ""), doc.get("filename", "")) in _PROTECTED_FILES


class DeleteHandler:
    """Deletes documents from the knowledge vault."""

    def __init__(self, fs: VaultFS, kb: dict):
        self.fs = fs
        self.kb = kb
        self.kb_id = str(kb["id"])
        self.slug = kb["slug"]

    async def delete(self, path: str) -> str:
        """Delete documents matching a path or glob pattern."""
        if not path or path in ("*", "**", "**/*"):
            return "Error: refusing to delete everything. Use a more specific path."

        matched = await self._find_documents(path)
        if not matched:
            return f"No documents matching `{path}` found in {self.slug}."

        protected = [d for d in matched if _is_protected(d)]
        deletable = [d for d in matched if not _is_protected(d)]

        if not deletable:
            names = ", ".join(f"`{d['path']}{d['filename']}`" for d in protected)
            return f"Cannot delete {names} — these are structural wiki pages. Use `write` to edit their content instead."

        self.fs.delete_from_disk(deletable)

        doc_ids = [str(d["id"]) for d in deletable]
        deleted_count = await self.fs.archive_documents(doc_ids)

        return self._format_response(deleted_count or len(deletable), deletable, protected)

    async def _find_documents(self, path: str) -> list[dict]:
        """Find documents by exact path or glob pattern."""
        if "*" in path or "?" in path:
            docs = await self.fs.list_documents(self.kb_id)
            glob_pat = "/" + path.lstrip("/") if not path.startswith("/") else path
            return [d for d in docs if glob_match(d["path"] + d["filename"], glob_pat)]

        dir_path, filename = resolve_path(path)
        doc = await self.fs.get_document(self.kb_id, filename, dir_path)
        return [doc] if doc else []

    def _format_response(self, deleted_count: int, deletable: list[dict], protected: list[dict]) -> str:
        """Build the response message listing deleted and skipped files."""
        lines = [f"Deleted {deleted_count} document(s):\n"]
        for d in deletable:
            lines.append(f"  {d['path']}{d['filename']}")
        if protected:
            names = ", ".join(f"`{d['path']}{d['filename']}`" for d in protected)
            lines.append(f"\nSkipped (protected): {names}")
        return "\n".join(lines)


def register(mcp: FastMCP, get_user_id, fs_factory) -> None:

    @mcp.tool(
        name="delete",
        description=(
            "Delete documents or wiki pages from the knowledge vault.\n\n"
            "Provide a path to delete a single file, or a glob pattern to delete multiple.\n"
            "Examples:\n"
            "- `path=\"old-notes.md\"` — delete a single file\n"
            "- `path=\"/wiki/drafts/*\"` — delete all files in a folder\n"
            "- `path=\"/wiki/**\"` — delete the entire wiki\n\n"
            "Note: overview.md and log.md are structural pages and cannot be deleted.\n"
            "Returns a list of deleted files. This action cannot be undone."
        ),
    )
    async def delete(ctx: Context, knowledge_base: str, path: str) -> str:
        user_id = get_user_id(ctx)
        fs = fs_factory(user_id)
        kb = await fs.resolve_kb(knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        handler = DeleteHandler(fs, kb)
        return await handler.delete(path)
