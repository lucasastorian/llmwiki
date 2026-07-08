"""Download a public PDF by URL and feed it into the standard ingest pipeline."""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse
from uuid import uuid4

import asyncpg
import httpx
from fastapi import HTTPException

from config import settings
from infra.safe_fetch import build_pinned_request, parse_public_fetch_url, redirect_location, resolve_public_ip
from services.types import DownloadedPdf

if TYPE_CHECKING:
    from services.ocr import OCRService
    from services.s3 import S3Service

MAX_PDF_BYTES = 50 * 1024 * 1024
DOWNLOAD_TIMEOUT = 30
MAX_REDIRECTS = 5
USER_AGENT = "LLMWiki/1.0 (+https://llmwiki.app)"

_ARXIV_ABS_RE = re.compile(r"^(https?://(?:www\.)?arxiv\.org)/abs/(.+)$")
_DISPOSITION_FILENAME_RE = re.compile(r'filename\*?=(?:"([^"]+)"|([^;\s]+))', re.IGNORECASE)


class UrlIngestService:

    def __init__(self, pool: asyncpg.Pool, s3_service: S3Service, ocr_service: OCRService):
        self.pool = pool
        self.s3 = s3_service
        self.ocr = ocr_service

    async def ingest_pdf(self, user_id: str, kb_id: str, url: str, path: str) -> dict:
        url = _normalize_pdf_url(url)
        path = _sanitize_path(path)
        await self._require_kb_owned(user_id, kb_id)

        existing = await self._find_by_source_url(user_id, kb_id, url)
        if existing:
            return {**existing, "already_exists": True}

        pdf = await self._download(url)
        return await self._create_pending_document(user_id, kb_id, url, path, pdf)

    async def _download(self, url: str) -> DownloadedPdf:
        current = url
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                parsed = parse_public_fetch_url(current)
                if not parsed:
                    raise HTTPException(status_code=400, detail="URL must be a public http(s) address")
                ip = resolve_public_ip(parsed.hostname)
                if not ip:
                    raise HTTPException(status_code=400, detail="URL host is not publicly reachable")
                request = build_pinned_request(
                    client, parsed, ip,
                    {"Accept": "application/pdf,*/*", "User-Agent": USER_AGENT},
                )
                try:
                    resp = await client.send(request, stream=True)
                except httpx.HTTPError as e:
                    raise HTTPException(status_code=400, detail=f"Could not fetch URL: {e}")
                try:
                    redirect = redirect_location(resp, current)
                    if redirect:
                        current = redirect
                        continue
                    return self._validate_pdf_response(resp, await self._read_capped(resp), current)
                finally:
                    await resp.aclose()
        raise HTTPException(status_code=400, detail="Too many redirects")

    async def _read_capped(self, resp: httpx.Response) -> bytes:
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"URL returned HTTP {resp.status_code}")
        chunks = bytearray()
        async for chunk in resp.aiter_bytes(chunk_size=65536):
            if len(chunks) + len(chunk) > MAX_PDF_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"PDF exceeds the {MAX_PDF_BYTES // (1024 * 1024)} MB download limit",
                )
            chunks.extend(chunk)
        return bytes(chunks)

    def _validate_pdf_response(self, resp: httpx.Response, data: bytes, final_url: str) -> DownloadedPdf:
        if not data.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=400,
                detail="URL did not return a PDF. For web pages, use the browser extension instead.",
            )
        return DownloadedPdf(data=data, filename=_derive_filename(resp, final_url))

    async def _create_pending_document(
        self, user_id: str, kb_id: str, url: str, path: str, pdf: DownloadedPdf,
    ) -> dict:
        document_id = str(uuid4())
        await self._insert_within_quota(document_id, kb_id, user_id, pdf, path, url)

        s3_key = f"{user_id}/{document_id}/source.pdf"
        try:
            await self.s3.upload_bytes(s3_key, pdf.data, "application/pdf")
        except Exception:
            await self._delete_document_row(document_id)
            raise HTTPException(status_code=502, detail="Could not store the downloaded PDF — try again")

        asyncio.create_task(self.ocr.process_document(document_id, user_id))
        return {
            "id": document_id,
            "filename": pdf.filename,
            "status": "pending",
            "already_exists": False,
        }

    async def _require_kb_owned(self, user_id: str, kb_id: str) -> None:
        owner = await self.pool.fetchval(
            "SELECT user_id::text FROM knowledge_bases WHERE id = $1::uuid",
            kb_id,
        )
        if owner != user_id:
            raise HTTPException(status_code=403, detail="Knowledge base not found or not owned by you")

    async def _insert_within_quota(
        self, document_id: str, kb_id: str, user_id: str, pdf: DownloadedPdf, path: str, url: str,
    ) -> None:
        """Quota check + pending-row insert under a per-user advisory lock, so
        concurrent ingests cannot all pass the same SUM(file_size) read."""
        title = pdf.filename.rsplit(".", 1)[0]
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", user_id)
                await self._check_storage_quota(conn, user_id, len(pdf.data))
                await conn.execute(
                    "INSERT INTO documents (id, knowledge_base_id, user_id, filename, path, title, "
                    "file_type, file_size, status, metadata) "
                    "VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, 'pdf', $7, 'pending', $8::jsonb)",
                    document_id, kb_id, user_id, pdf.filename, path, title,
                    len(pdf.data), json.dumps({"source_url": url}),
                )

    async def _check_storage_quota(self, conn: asyncpg.Connection, user_id: str, incoming_bytes: int) -> None:
        row = await conn.fetchrow(
            "SELECT storage_limit_bytes FROM users WHERE id = $1",
            user_id,
        )
        storage_limit = row["storage_limit_bytes"] if row else settings.QUOTA_MAX_STORAGE_BYTES
        current_bytes = await conn.fetchval(
            "SELECT COALESCE(SUM(file_size), 0) FROM documents WHERE user_id = $1",
            user_id,
        )
        if current_bytes + incoming_bytes > storage_limit:
            used_mb = current_bytes / (1024 * 1024)
            max_mb = storage_limit / (1024 * 1024)
            raise HTTPException(
                status_code=413,
                detail=f"Storage quota exceeded. Using {used_mb:.0f} MB of {max_mb:.0f} MB.",
            )

    async def _find_by_source_url(self, user_id: str, kb_id: str, url: str) -> dict | None:
        row = await self.pool.fetchrow(
            "SELECT id::text, knowledge_base_id::text, title, path, filename, status "
            "FROM documents "
            "WHERE user_id = $1 AND knowledge_base_id = $2::uuid AND file_type = 'pdf' "
            "AND NOT archived AND metadata->>'source_url' = $3 "
            "ORDER BY created_at DESC LIMIT 1",
            user_id, kb_id, url,
        )
        return dict(row) if row else None

    async def _delete_document_row(self, document_id: str) -> None:
        await self.pool.execute("DELETE FROM documents WHERE id = $1::uuid", document_id)


def _normalize_pdf_url(url: str) -> str:
    """arXiv abstract pages link to a canonical PDF — fetch that directly."""
    match = _ARXIV_ABS_RE.match(url.strip())
    if match:
        return f"{match.group(1)}/pdf/{match.group(2)}"
    return url.strip()


def _derive_filename(resp: httpx.Response, final_url: str) -> str:
    disposition = resp.headers.get("content-disposition", "")
    match = _DISPOSITION_FILENAME_RE.search(disposition)
    raw = (match.group(1) or match.group(2)) if match else ""
    if not raw:
        raw = unquote(urlparse(final_url).path.rsplit("/", 1)[-1])
    return _sanitize_filename(raw)


def _sanitize_filename(raw: str) -> str:
    name = re.sub(r"[^\w.\- ]", "", raw.replace("\\", "/").rsplit("/", 1)[-1]).strip()
    name = name[:120].rstrip(". ")
    if not name:
        name = "document"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name


def _sanitize_path(raw_path: str) -> str:
    path = re.sub(r"[\x00-\x1f\x7f]", "", raw_path or "/")
    path = "/" + path.replace("\\", "/").strip("/") + "/"
    path = re.sub(r"/\.\.(/|$)", "/", path)
    path = re.sub(r"/+", "/", path)
    return "/" if path == "//" else path
