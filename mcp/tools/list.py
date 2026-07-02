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
        name="set_course_mode",
        description=(
            "Convert an existing knowledge base into a course (kind='course') or back "
            "into a plain wiki (kind='wiki'). A course renders its pages as ordered "
            "lessons with progress tracking; a wiki is free-form. Reversible — this only "
            "changes how the app renders the knowledge base, never its content."
        ),
    )
    async def set_course_mode(ctx: Context, knowledge_base: str, kind: str) -> str:
        if kind not in ("wiki", "course"):
            return "Error: kind must be 'wiki' or 'course'."

        user_id = get_user_id(ctx)
        fs = fs_factory(user_id)
        kb = await fs.resolve_kb(knowledge_base)
        if not kb:
            return f"Error: knowledge base '{knowledge_base}' not found."

        updated = await fs.set_knowledge_base_kind(kb["id"], kind)
        if not updated:
            return f"Error: could not update '{knowledge_base}'."

        label = "course" if kind == "course" else "wiki"
        return f"**{updated['name']}** (`{updated['slug']}`) is now a {label}."

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
