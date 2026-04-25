"""Delete tool — remove documents from the knowledge vault."""

from mcp.server.fastmcp import FastMCP, Context

from db import scoped_query, scoped_queryrow, service_execute
from .helpers import get_user_id, resolve_kb, glob_match, resolve_path

_PROTECTED_FILES = {("/wiki/", "overview.md"), ("/wiki/", "log.md")}


def _is_protected(doc: dict) -> bool:
    return (doc["path"], doc["filename"]) in _PROTECTED_FILES


class DeleteHandler:
    """Deletes documents from the knowledge vault."""

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
            return f"Cannot delete {names} — these are structural wiki pages. Use `write` to edit their content instead."

        await self._archive(deletable)
        return self._format_response(deletable, protected)

    async def _find_documents(self, path: str) -> list[dict]:
        """Find documents by exact path or glob pattern."""
        if "*" in path or "?" in path:
            docs = await scoped_query(
                self.user_id,
                "SELECT id, filename, title, path FROM documents "
                "WHERE knowledge_base_id = $1 AND NOT archived AND user_id = $2 ORDER BY path, filename",
                self.kb["id"], self.user_id,
            )
            glob_pat = "/" + path.lstrip("/") if not path.startswith("/") else path
            return [d for d in docs if glob_match(d["path"] + d["filename"], glob_pat)]

        dir_path, filename = resolve_path(path)
        doc = await scoped_queryrow(
            self.user_id,
            "SELECT id, filename, title, path FROM documents "
            "WHERE knowledge_base_id = $1 AND filename = $2 AND path = $3 AND NOT archived AND user_id = $4",
            self.kb["id"], filename, dir_path, self.user_id,
        )
        return [doc] if doc else []

    async def _archive(self, deletable: list[dict]) -> None:
        """Soft-delete documents by setting archived flag."""
        doc_ids = [str(d["id"]) for d in deletable]
        await service_execute(
            "UPDATE documents SET archived = true, updated_at = now() "
            "WHERE id = ANY($1::uuid[]) AND user_id = $2",
            doc_ids, self.user_id,
        )

    def _format_response(self, deletable: list[dict], protected: list[dict]) -> str:
        """Build the response message listing deleted and skipped files."""
        lines = [f"Deleted {len(deletable)} document(s):\n"]
        for d in deletable:
            lines.append(f"  {d['path']}{d['filename']}")
        if protected:
            names = ", ".join(f"`{d['path']}{d['filename']}`" for d in protected)
            lines.append(f"\nSkipped (protected): {names}")
        return "\n".join(lines)


def register(mcp: FastMCP) -> None:

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

        kb = await resolve_kb(user_id, knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        handler = DeleteHandler(user_id, kb)
        return await handler.delete(path)
