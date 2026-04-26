"""Local filesystem storage adapter.

Files stored under .llmwiki/cache/ in the workspace.
URLs are local API paths served by the files route.
"""

import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalStorageService:
    def __init__(self, workspace_path: str, api_url: str = "http://localhost:8000"):
        self._root = Path(workspace_path) / ".llmwiki" / "cache"
        self._root.mkdir(parents=True, exist_ok=True)
        self._api_url = api_url.rstrip("/")

    async def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def upload_file(self, key: str, file_path: str, content_type: str = "application/octet-stream") -> None:
        dest = self._root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest)

    async def download_bytes(self, key: str) -> bytes:
        path = self._root / key
        if not path.exists():
            raise FileNotFoundError(f"Local file not found: {key}")
        return path.read_bytes()

    async def download_to_file(self, key: str, file_path: str) -> None:
        src = self._root / key
        if not src.exists():
            raise FileNotFoundError(f"Local file not found: {key}")
        shutil.copy2(src, file_path)

    async def download_json(self, key: str) -> dict:
        data = await self.download_bytes(key)
        return json.loads(data)

    async def generate_url(self, key: str) -> str:
        return f"{self._api_url}/v1/files/{key}"

    async def generate_presigned_get(self, key: str, expires_in: int = 3600) -> str:
        return await self.generate_url(key)

    async def generate_presigned_put(self, key: str, content_type: str = "", expires_in: int = 3600) -> str:
        return await self.generate_url(key)
