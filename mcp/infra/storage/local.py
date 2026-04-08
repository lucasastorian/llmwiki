"""Local filesystem storage for MCP tools.

Reads files from workspace root or .llmwiki/cache/.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_workspace_root: Path | None = None


def init(workspace_path: str) -> None:
    global _workspace_root
    _workspace_root = Path(workspace_path).resolve()


async def load_bytes(key: str) -> bytes | None:
    """Load file bytes by key. Checks .llmwiki/cache/ then workspace root."""
    if _workspace_root is None:
        return None

    cache_path = _workspace_root / ".llmwiki" / "cache" / key
    if cache_path.is_file() and cache_path.is_relative_to(_workspace_root):
        return cache_path.read_bytes()

    root_path = _workspace_root / key
    if root_path.is_file() and root_path.is_relative_to(_workspace_root):
        return root_path.read_bytes()

    logger.warning("Local file not found: %s", key)
    return None


def resolve_workspace_path(relative_path: str) -> Path | None:
    """Resolve a relative path to an absolute workspace path. Returns None if outside workspace."""
    if _workspace_root is None:
        return None
    resolved = (_workspace_root / relative_path).resolve()
    if not resolved.is_relative_to(_workspace_root):
        return None
    return resolved
