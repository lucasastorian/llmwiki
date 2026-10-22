"""Local stdio MCP server for one workspace: the filesystem is truth, SQLite is the index."""

import argparse
import asyncio
import logging
import os
import sys
import uuid
from datetime import date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("llmwiki.local")

_LOCAL_USER_ID = os.environ.get("LLMWIKI_USER_ID", str(uuid.uuid5(uuid.NAMESPACE_DNS, "local")))
os.environ["SUPAVAULT_USER_ID"] = _LOCAL_USER_ID


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM Wiki local MCP server")
    parser.add_argument("workspace", nargs="?", default=".", help="Path to workspace folder")
    parser.add_argument("--workspace", dest="workspace_flag", default=None, help="Path to workspace folder")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--port", type=int, default=8100, help="Port for streamable-http transport")
    return parser.parse_args()


async def _init_workspace(workspace_path: str) -> None:
    """Initialize workspace: create dirs, SQLite, default workspace row, scaffold wiki files."""
    ws = Path(workspace_path).resolve()

    (ws / "wiki").mkdir(parents=True, exist_ok=True)
    (ws / ".llmwiki").mkdir(parents=True, exist_ok=True)
    (ws / ".llmwiki" / "cache").mkdir(parents=True, exist_ok=True)

    from vaultfs import SqliteVaultFS
    await SqliteVaultFS.init(str(ws))

    fs = SqliteVaultFS(_LOCAL_USER_ID)
    existing = await fs.get_workspace()
    if not existing:
        ws_name = ws.name
        ws_id = await fs.ensure_workspace(ws_name)
        today = date.today().isoformat()
        overview_content = (
            "---\n"
            "title: Overview\n"
            f"description: Research hub for {ws_name}.\n"
            f"date: {today}\n"
            "tags: [overview, wiki]\n"
            "---\n\n"
            f"This wiki tracks research on {ws_name}.\n\n"
            "## Key Findings\n\n"
            "No sources ingested yet."
        )

        await fs.create_document(
            ws_id, "overview.md", "Overview", "/wiki/", "md",
            overview_content,
            ["overview", "wiki"],
            date=today,
            metadata={"description": f"Research hub for {ws_name}."},
        )
        overview_path = ws / "wiki" / "overview.md"
        if not overview_path.exists():
            overview_path.write_text(overview_content + "\n", encoding="utf-8")

        logger.info("Initialized workspace: %s", ws)
    else:
        logger.info("Workspace ready: %s", ws)


def main():
    args = _parse_args()
    workspace = args.workspace_flag or args.workspace
    workspace = str(Path(workspace).resolve())

    sys.modules["local_server"] = sys.modules[__name__]

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_init_workspace(workspace))

    from tools import register
    from vaultfs import SqliteVaultFS

    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        name="LLM Wiki",
        instructions=(
            "You are connected to an LLM Wiki workspace. The user has uploaded files, notes, "
            "and documents that you can read, search, edit, and organize. "
            "Call the `guide` tool first to see available knowledge bases and learn the full workflow."
        ),
    )

    def _get_user_id(ctx):
        return _LOCAL_USER_ID

    register(mcp, _get_user_id, lambda user_id: SqliteVaultFS(user_id))

    @mcp.tool(name="ping", description="Test connectivity")
    async def ping() -> str:
        return "pong"

    logger.info("Local MCP server ready — workspace: %s", workspace)
    if args.transport == "streamable-http":
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = args.port
        asyncio.run(mcp.run_streamable_http_async())
    else:
        asyncio.run(mcp.run_stdio_async())


if __name__ == "__main__":
    main()
