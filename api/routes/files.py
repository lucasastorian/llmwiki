"""Local file serving route with Range support and path traversal protection.

Only active in local mode. Serves files from .llmwiki/cache/ (derived artifacts)
and from the workspace root (source files).
"""

import mimetypes
import os
import platform
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

router = APIRouter(tags=["files"])

_workspace_root: Path | None = None


def set_workspace_root(path: str) -> None:
    global _workspace_root
    _workspace_root = Path(path).resolve()


def _resolve_safe(key: str) -> Path:
    """Resolve a key to a safe path under the workspace. Rejects traversal."""
    if _workspace_root is None:
        raise HTTPException(status_code=501, detail="Local file serving not configured")

    # Try .llmwiki/cache/ first (derived artifacts), then workspace root (source files)
    cache_path = (_workspace_root / ".llmwiki" / "cache" / key).resolve()
    if cache_path.is_file() and cache_path.is_relative_to(_workspace_root):
        return cache_path

    root_path = (_workspace_root / key).resolve()
    if root_path.is_file() and root_path.is_relative_to(_workspace_root):
        return root_path

    raise HTTPException(status_code=404, detail="File not found")


@router.get("/v1/files/{key:path}")
async def serve_file(key: str, request: Request):
    path = _resolve_safe(key)

    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    file_size = path.stat().st_size
    mtime = path.stat().st_mtime
    etag = f'"{hash((path, mtime, file_size)):x}"'

    # Check If-None-Match for caching
    if_none_match = request.headers.get("if-none-match")
    if if_none_match == etag:
        return StreamingResponse(content=iter([]), status_code=304, headers={"ETag": etag})

    range_header = request.headers.get("range")

    if range_header and range_header.startswith("bytes="):
        ranges = range_header[6:]
        start_str, end_str = ranges.split("-", 1)
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        end = min(end, file_size - 1)
        length = end - start + 1

        def iter_range():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(8192, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            content=iter_range(),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(length),
                "Accept-Ranges": "bytes",
                "ETag": etag,
            },
        )

    return FileResponse(
        path=str(path),
        media_type=content_type,
        headers={
            "Accept-Ranges": "bytes",
            "ETag": etag,
            "Content-Length": str(file_size),
        },
    )


class OpenFileRequest(BaseModel):
    path: str


@router.post("/v1/files/open")
async def open_file_externally(body: OpenFileRequest):
    """Open a file in the user's default application."""
    resolved = _resolve_safe(body.path)

    system = platform.system()
    if system == "Darwin":
        cmd = ["open", str(resolved)]
    elif system == "Linux":
        cmd = ["xdg-open", str(resolved)]
    elif system == "Windows":
        cmd = ["start", "", str(resolved)]
    else:
        raise HTTPException(status_code=501, detail=f"Unsupported platform: {system}")

    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to open file: {e}")

    return {"status": "opened", "path": body.path}
