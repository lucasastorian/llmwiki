"""HTTP client for the isolated converter service's /extract endpoint."""

import asyncio
import logging
import uuid

import httpx
from config import settings
from services.types import ConverterExtraction

logger = logging.getLogger(__name__)


class ConverterClient:
    MAX_RETRIES = 3
    RETRY_BACKOFF = [1, 2]

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(settings.CONVERTER_MAX_CONCURRENCY)

    async def extract(self, source_url: str, ext: str, pdf_upload_url: str | None = None) -> ConverterExtraction:
        """Fetch per-page markdown for a source file (optionally storing its PDF rendition), verifying the request_id echo."""
        request_id = str(uuid.uuid4())
        payload = {"source_url": source_url, "source_ext": ext, "request_id": request_id}
        if pdf_upload_url:
            payload["pdf_upload_url"] = pdf_upload_url
        async with (
            self._semaphore,
            httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client,
        ):
            data = await self._post_with_capacity_retries(client, payload, request_id)

        self._verify_request_binding(data, request_id)
        pages = data.get("pages", [])
        if not pages:
            raise ValueError("Converter returned empty pages — extraction may have failed silently")
        return ConverterExtraction(
            pages=[(p["page"], p["content"]) for p in pages],
            engine=data.get("engine") or "opendataloader",
        )

    async def _post_with_capacity_retries(
        self, client: httpx.AsyncClient, payload: dict, request_id: str,
    ) -> dict:
        for attempt in range(self.MAX_RETRIES):
            resp = await client.post(
                f"{settings.CONVERTER_URL}/extract",
                json=payload,
                headers=self._auth_headers(),
            )
            if resp.status_code != 503 or attempt == self.MAX_RETRIES - 1:
                break
            delay = self._retry_delay(
                resp.headers.get("retry-after"),
                self.RETRY_BACKOFF[min(attempt, len(self.RETRY_BACKOFF) - 1)],
            )
            logger.warning(
                "Converter at capacity; retrying request_id=%s attempt=%d/%d in %.1fs",
                request_id, attempt + 2, self.MAX_RETRIES, delay,
            )
            await asyncio.sleep(delay)

        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _verify_request_binding(data: dict, request_id: str) -> None:
        """Reject responses bound to a different request; tolerate converters that don't echo."""
        echoed_id = data.get("request_id")
        if echoed_id is not None and echoed_id != request_id:
            raise ValueError(
                f"Converter response binding mismatch: sent {request_id}, got {echoed_id}. "
                "Possible stale cache or cross-request contamination."
            )
        if echoed_id is None:
            logger.warning("Converter did not echo request_id — source binding not verified")

    @staticmethod
    def _auth_headers() -> dict:
        if settings.CONVERTER_SECRET:
            return {"Authorization": f"Bearer {settings.CONVERTER_SECRET}"}
        return {}

    @staticmethod
    def _retry_delay(retry_after: str | None, default: float) -> float:
        if not retry_after:
            return default
        try:
            return max(0.0, min(float(retry_after), 30.0))
        except ValueError:
            return default
