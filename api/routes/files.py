"""Local-mode file serving (cache artifacts and workspace sources) with Range support and traversal protection."""

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

router = APIRouter(tags=["files"])

ACTIVE_CONTENT_TYPES = frozenset({"text/html", "image/svg+xml", "application/xhtml+xml", "text/xml", "application/xml"})

_workspace_root: Path | None = None


def set_workspace_root(path: str) -> None:
    global _workspace_root
    _workspace_root = Path(path).resolve()


def _resolve_safe(key: str) -> Path:
    """Resolve a key to a servable file under the workspace, rejecting traversal and hidden paths."""
    if _workspace_root is None:
        raise HTTPException(status_code=501, detail="Local file serving not configured")

    cache_root = _workspace_root / ".llmwiki" / "cache"
    cache_path = (cache_root / key).resolve()
    if cache_path.is_file() and cache_path.is_relative_to(cache_root.resolve()):
        return cache_path

    root_path = (_workspace_root / key).resolve()
    if root_path.is_file() and root_path.is_relative_to(_workspace_root) and not _is_hidden(root_path):
        return root_path

    raise HTTPException(status_code=404, detail="File not found")


def _is_hidden(path: Path) -> bool:
    """True when any segment below the workspace root is a dotfile or dot-directory (incl. .llmwiki/)."""
    return any(part.startswith(".") for part in path.relative_to(_workspace_root).parts)


@router.get("/v1/files/{key:path}")
async def serve_file(key: str, request: Request) -> Response:
    path = _resolve_safe(key)

    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    stat = path.stat()
    etag = f'"{hash((path, stat.st_mtime, stat.st_size)):x}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    headers = {"ETag": etag}
    if content_type in ACTIVE_CONTENT_TYPES:
        headers["Content-Security-Policy"] = "sandbox"
    return FileResponse(path=str(path), media_type=content_type, headers=headers)
