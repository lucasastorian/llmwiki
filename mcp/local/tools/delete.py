"""Delete tool — remove documents from the local vault."""

from mcp.server.fastmcp import FastMCP, Context

from infra.db.sqlite import list_documents, get_document, archive_documents, get_workspace
from infra.storage.local import resolve_workspace_path
from .helpers import get_user_id, glob_match, resolve_path

_PROTECTED_FILES = {("/wiki/", "overview.md"), ("/wiki/", "log.md")}


def _is_protected(doc: dict) -> bool:
    return (doc.get("path", ""), doc.get("filename", "")) in _PROTECTED_FILES


class DeleteHandler:
    """Deletes documents from the local vault."""

    def __init__(self, user_id: str, kb: dict):
        self.user_id = user_id
        self.kb = kb
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
            return f"Cannot delete {names} — these are structural wiki pages."

        self._delete_from_disk(deletable)
        deleted_count = await self._archive(deletable)
        return self._format_response(deleted_count, deletable, protected)

    async def _find_documents(self, path: str) -> list[dict]:
        """Find documents by exact path or glob pattern."""
        if "*" in path or "?" in path:
            docs = await list_documents(self.user_id, self.slug)
            glob_pat = "/" + path.lstrip("/") if not path.startswith("/") else path
            return [d for d in docs if glob_match(d["path"] + d["filename"], glob_pat)]

        dir_path, filename = resolve_path(path)
        doc = await get_document(self.user_id, self.slug, filename, dir_path)
        return [doc] if doc else []

    def _delete_from_disk(self, deletable: list[dict]) -> None:
        """Remove files from the local filesystem."""
        for d in deletable:
            relative = d["path"].lstrip("/") + d["filename"]
            file_path = resolve_workspace_path(relative)
            if file_path and file_path.exists():
                file_path.unlink()

    async def _archive(self, deletable: list[dict]) -> int:
        """Remove documents from the SQLite index."""
        doc_ids = [str(d["id"]) for d in deletable]
        return await archive_documents(doc_ids, self.user_id)

    def _format_response(self, deleted_count: int, deletable: list[dict], protected: list[dict]) -> str:
        """Build the response message listing deleted and skipped files."""
        lines = [f"Deleted {deleted_count} document(s):\n"]
        for d in deletable:
            lines.append(f"  {d['path']}{d['filename']}")
        if protected:
            names = ", ".join(f"`{d['path']}{d['filename']}`" for d in protected)
            lines.append(f"\nSkipped (protected): {names}")
        return "\n".join(lines)


async def _resolve_local_kb(user_id: str, slug: str) -> dict | None:
    """Resolve a local workspace as a knowledge base."""
    ws = await get_workspace()
    if not ws:
        return None
    return {"id": ws["id"], "name": ws["name"], "slug": ws["name"]}


def register(mcp: FastMCP) -> None:

    @mcp.tool(
        name="delete",
        description=(
            "Delete documents or wiki pages from the knowledge vault.\n\n"
            "Deletes the file from disk and removes it from the index.\n"
            "Note: overview.md and log.md are structural and cannot be deleted."
        ),
    )
    async def delete(ctx: Context, knowledge_base: str, path: str) -> str:
        user_id = get_user_id(ctx)

        kb = await _resolve_local_kb(user_id, knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        handler = DeleteHandler(user_id, kb)
        return await handler.delete(path)
