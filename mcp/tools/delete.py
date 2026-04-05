from mcp.server.fastmcp import FastMCP, Context

from db import scoped_query, scoped_queryrow, scoped_execute
from .helpers import get_user_id, resolve_kb, glob_match, resolve_path


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
            "Returns a list of deleted files. This action cannot be undone."
        ),
    )
    async def delete(
        ctx: Context,
        knowledge_base: str,
        path: str,
    ) -> str:
        user_id = get_user_id(ctx)

        kb = await resolve_kb(user_id, knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        if not path or path in ("*", "**", "**/*"):
            return "Error: refusing to delete everything. Use a more specific path."

        is_glob = "*" in path or "?" in path

        if is_glob:
            docs = await scoped_query(
                user_id,
                "SELECT id, filename, title, path FROM documents "
                "WHERE knowledge_base_id = $1 AND NOT archived ORDER BY path, filename",
                kb["id"],
            )
            glob_pat = "/" + path.lstrip("/") if not path.startswith("/") else path
            matched = [d for d in docs if glob_match(d["path"] + d["filename"], glob_pat)]
        else:
            dir_path, filename = resolve_path(path)

            doc = await scoped_queryrow(
                user_id,
                "SELECT id, filename, title, path FROM documents "
                "WHERE knowledge_base_id = $1 AND filename = $2 AND path = $3 AND NOT archived",
                kb["id"], filename, dir_path,
            )
            matched = [doc] if doc else []

        if not matched:
            return f"No documents matching `{path}` found in {knowledge_base}."

        doc_ids = [str(d["id"]) for d in matched]
        await scoped_execute(
            user_id,
            "UPDATE documents SET archived = true, updated_at = now() "
            "WHERE id = ANY($1::uuid[])",
            doc_ids,
        )

        lines = [f"Deleted {len(matched)} document(s):\n"]
        for d in matched:
            lines.append(f"  {d['path']}{d['filename']}")
        return "\n".join(lines)
