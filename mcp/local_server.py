"""Local MCP server for stdio (Claude Desktop / Claude Code / Cursor).

One workspace = one MCP server. Filesystem is truth. SQLite is the index.

Usage:
    python -m local_server --workspace ~/research
    python -m local_server ~/research
"""

import argparse
import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("llmwiki.local")

_LOCAL_USER_ID = os.environ.get("LLMWIKI_USER_ID", str(uuid.uuid5(uuid.NAMESPACE_DNS, "local")))
os.environ["SUPAVAULT_USER_ID"] = _LOCAL_USER_ID


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM Wiki local MCP server")
    parser.add_argument("workspace", nargs="?", default=".", help="Path to workspace folder")
    parser.add_argument("--workspace", dest="workspace_flag", default=None, help="Path to workspace folder")
    return parser.parse_args()


async def _init_workspace(workspace_path: str) -> None:
    """Initialize workspace: create dirs, SQLite, default user + workspace row."""
    ws = Path(workspace_path).resolve()

    (ws / "wiki").mkdir(parents=True, exist_ok=True)
    (ws / ".llmwiki").mkdir(parents=True, exist_ok=True)
    (ws / ".llmwiki" / "cache").mkdir(parents=True, exist_ok=True)

    from infra.db import sqlite as local_db
    await local_db.init(str(ws))

    from infra.storage import local as local_storage
    local_storage.init(str(ws))

    existing = await local_db.get_workspace()
    if not existing:
        ws_name = ws.name
        db = await local_db.get_db()
        ws_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO workspace (id, name, description, user_id) VALUES (?, ?, '', ?)",
            (ws_id, ws_name, _LOCAL_USER_ID),
        )

        await local_db.create_document(
            _LOCAL_USER_ID, ws_id, "overview.md", "Overview", "/wiki/",
            "md",
            f"This wiki tracks research on {ws_name}.\n\n## Key Findings\n\nNo sources ingested yet.\n\n## Recent Updates\n\nNo activity yet.",
            ["overview"],
        )
        await local_db.create_document(
            _LOCAL_USER_ID, ws_id, "log.md", "Log", "/wiki/",
            "md",
            "Chronological record of ingests, queries, and maintenance passes.",
            ["log"],
        )

        overview_path = ws / "wiki" / "overview.md"
        if not overview_path.exists():
            overview_path.write_text(
                f"This wiki tracks research on {ws_name}.\n\n## Key Findings\n\n"
                "No sources ingested yet.\n\n## Recent Updates\n\nNo activity yet.\n"
            )
        log_path = ws / "wiki" / "log.md"
        if not log_path.exists():
            log_path.write_text("Chronological record of ingests, queries, and maintenance passes.\n")

        await db.commit()
        logger.info("Initialized workspace: %s", ws)
    else:
        logger.info("Workspace ready: %s", ws)


def _inject_local_db(workspace_path: str) -> None:
    """Replace the 'db' module with our SQLite compat layer before tools import it.

    This is a temporary bridge — the existing tools import from 'db' and use
    Postgres-style SQL. The compat layer translates $1→? params and handles
    basic syntax differences. Long-term, tools should call high-level query
    functions from infra.db.sqlite instead of raw SQL.
    """
    from infra.db import local_compat
    sys.modules["db"] = local_compat

    # Also patch helpers to use local storage
    from infra.storage import local as local_storage
    import tools.helpers as helpers
    helpers._get_s3_session = lambda: None
    _original_load_s3 = helpers.load_s3_bytes

    async def _load_local(key: str) -> bytes | None:
        return await local_storage.load_bytes(key)

    helpers.load_s3_bytes = _load_local


def main():
    args = _parse_args()
    workspace = args.workspace_flag or args.workspace
    workspace = str(Path(workspace).resolve())

    # Mark as local_server mode (for get_user_id bypass)
    sys.modules["local_server"] = sys.modules[__name__]

    # Initialize workspace synchronously
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_init_workspace(workspace))

    # Inject local DB compat layer BEFORE tool imports
    from infra.db import sqlite as local_db
    from infra.db.local_compat import set_connection
    set_connection(loop.run_until_complete(local_db.get_db()))
    _inject_local_db(workspace)

    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        name="LLM Wiki",
        instructions=(
            "You are connected to an LLM Wiki workspace. The user has uploaded files, notes, "
            "and documents that you can read, search, edit, and organize. "
            "Call the `guide` tool first to see available knowledge bases and learn the full workflow."
        ),
    )

    from tools import register
    register(mcp)

    @mcp.tool(name="ping", description="Test connectivity")
    async def ping() -> str:
        return "pong"

    logger.info("Local MCP server ready — workspace: %s", workspace)
    asyncio.run(mcp.run_stdio_async())


if __name__ == "__main__":
    main()
