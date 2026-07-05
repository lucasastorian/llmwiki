"""Knowledge base tools — create and enumerate knowledge bases."""

from mcp.server.fastmcp import FastMCP, Context

from config import settings


def register(mcp: FastMCP, get_user_id, fs_factory) -> None:

    @mcp.tool(
        name="create_knowledge_base",
        description=(
            "Create a new knowledge base and scaffold starter overview/log pages.\n\n"
            "Set kind='course' to create a course instead of a wiki — same structure, but the "
            "app renders lesson progress (mark-complete, current/locked lessons). Default 'wiki'.\n\n"
            "In hosted mode this creates a separate knowledge base with a unique slug. "
            "In local MCP mode there is one workspace per server, so this returns the "
            "existing workspace if it has already been initialized."
        ),
    )
    async def create_knowledge_base(
        ctx: Context,
        name: str,
        description: str = "",
        kind: str = "wiki",
    ) -> str:
        name = name.strip()
        description = description.strip()
        if not name:
            return "Error: name is required when creating a knowledge base."
        if len(name) > 120:
            return "Error: knowledge base name must be 120 characters or fewer."
        if kind not in ("wiki", "course"):
            return "Error: kind must be 'wiki' or 'course'."

        user_id = get_user_id(ctx)
        fs = fs_factory(user_id)
        kb = await fs.create_knowledge_base(name, description or None, kind)

        if kb.get("already_exists"):
            if kb.get("local_singleton"):
                label = "course" if kb.get("kind") == "course" else "knowledge base"
                return (
                    "Local MCP mode uses one workspace per server. "
                    f"Existing {label}: **{kb['name']}** (`{kb['slug']}`). "
                    "Use that slug with the other tools."
                )
            return f"Knowledge base already exists: **{kb['name']}** (`{kb['slug']}`)."

        label = "course" if kind == "course" else "knowledge base"
        return (
            f"Created {label} **{kb['name']}** (`{kb['slug']}`). "
            "Starter pages were added at `/wiki/overview.md` and `/wiki/log.md`. "
            f"Use `knowledge_base=\"{kb['slug']}\"` with the other tools."
        )

    @mcp.tool(
        name="update_knowledge_base",
        description=(
            "Update a knowledge base's name, description, or kind. Provide only the "
            "fields to change.\n\n"
            "kind='course' renders pages as ordered lessons with progress tracking; "
            "kind='wiki' is free-form. Switching kind is reversible and never touches "
            "content.\n\n"
            "Renaming regenerates the slug — the response includes the new slug; use "
            "it in all subsequent tool calls."
        ),
    )
    async def update_knowledge_base(
        ctx: Context,
        knowledge_base: str,
        name: str = "",
        description: str = "",
        kind: str = "",
    ) -> str:
        name = name.strip()
        description = description.strip()
        kind = kind.strip()
        if not (name or description or kind):
            return "Error: provide at least one of name, description, or kind."
        if len(name) > 120:
            return "Error: knowledge base name must be 120 characters or fewer."
        if kind and kind not in ("wiki", "course"):
            return "Error: kind must be 'wiki' or 'course'."

        user_id = get_user_id(ctx)
        fs = fs_factory(user_id)
        kb = await fs.resolve_kb(knowledge_base)
        if not kb:
            return f"Error: knowledge base '{knowledge_base}' not found."

        updated = await fs.update_knowledge_base(
            kb["id"],
            name=name or None,
            description=description or None,
            kind=kind or None,
        )
        if not updated:
            return f"Error: could not update '{knowledge_base}'."

        changes = [label for label, value in (("name", name), ("description", description), (f"kind={kind}", kind)) if value]
        summary = f"Updated {', '.join(changes)} for **{updated['name']}** (`{updated['slug']}`)."
        if updated["slug"] != kb["slug"]:
            summary += (
                f" Slug changed: `{kb['slug']}` → `{updated['slug']}` — "
                "use the new slug in all subsequent tool calls."
            )
        return summary

    @mcp.tool(
        name="list_knowledge_bases",
        description=(
            "List the user's knowledge bases with their names and slugs.\n\n"
            "Every other tool takes a `knowledge_base` slug — call this first to "
            "discover the valid slugs, or whenever you need to confirm which "
            "knowledge bases exist."
        ),
    )
    async def list_knowledge_bases(ctx: Context) -> str:
        user_id = get_user_id(ctx)
        fs = fs_factory(user_id)
        kbs = await fs.list_knowledge_bases()
        if not kbs:
            return (
                "No knowledge bases yet. Use `create_knowledge_base`, "
                f"or create one at {settings.APP_URL}/wikis."
            )

        lines = [f"- **{kb['name']}** (`{kb['slug']}`)" for kb in kbs]
        return "\n".join(lines)
