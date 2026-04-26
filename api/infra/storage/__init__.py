"""Storage service protocol definition."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageService(Protocol):

    async def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        ...

    async def upload_file(self, key: str, file_path: str, content_type: str = "application/octet-stream") -> None:
        ...

    async def download_bytes(self, key: str) -> bytes:
        ...

    async def download_to_file(self, key: str, file_path: str) -> None:
        ...

    async def generate_url(self, key: str) -> str:
        """Return a URL to access the file. Presigned S3 URL or local API path."""
        ...
