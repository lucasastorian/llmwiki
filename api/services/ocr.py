"""Routes uploaded documents to the right extraction backend and stores the results."""

import asyncio
import logging
import tempfile
from pathlib import Path

import asyncpg
from config import settings
from domain.file_types import IMAGE_TYPES, OFFICE_TYPES
from html_parser import Parser
from services.chunker import chunk_text
from services.converter_client import ConverterClient
from services.mistral_ocr_client import MistralOcrClient
from services.page_quota import PageQuota
from services.page_store import PageStore
from services.s3 import S3Service
from services.spreadsheet_extract import parse_sheets

logger = logging.getLogger(__name__)


class OCRService:
    PROCESS_CONCURRENCY = 3

    def __init__(self, s3: S3Service, pool: asyncpg.Pool):
        self._s3 = s3
        self._pool = pool
        self._semaphore = asyncio.Semaphore(self.PROCESS_CONCURRENCY)
        self._quota = PageQuota(pool)
        self._pages = PageStore(pool, s3, self._quota)
        self._converter = ConverterClient()
        self._mistral = MistralOcrClient()

    async def process_document(self, document_id: str, user_id: str):
        async with self._semaphore:
            await self._do_process(document_id, user_id)

    async def _do_process(self, document_id: str, user_id: str):
        try:
            await self._quota.check_global_limits()
            await self._pages.set_status(document_id, "processing")

            doc = await self._fetch_document(document_id, user_id)
            if not doc:
                logger.error("Document %s not found for user %s", document_id, user_id)
                return

            ext = doc["filename"].rsplit(".", 1)[-1].lower() if "." in doc["filename"] else doc["file_type"]
            kb_id = doc["kb_id"]
            s3_source_key = f"{user_id}/{document_id}/source.{ext}"

            if ext in OFFICE_TYPES:
                await self._process_office(document_id, user_id, kb_id, s3_source_key, ext)
            elif ext in IMAGE_TYPES:
                await self._pages.mark_image_ready(document_id, user_id)
            elif ext == "pdf":
                await self._process_pdf(document_id, user_id, kb_id, s3_source_key)
            elif ext in ("html", "htm"):
                await self._process_html(document_id, user_id, kb_id, s3_source_key)
            elif ext in ("xlsx", "csv"):
                await self._process_spreadsheet(document_id, user_id, kb_id, s3_source_key, ext)
            else:
                raise ValueError(f"Unsupported file type: {ext}")

        except Exception as e:
            logger.exception("Processing failed for document %s", document_id)
            await self._mark_failed(document_id, str(e)[:500])

    async def _process_pdf(self, document_id: str, user_id: str, kb_id: str, s3_source_key: str):
        if settings.PDF_BACKEND == "mistral":
            if not settings.MISTRAL_API_KEY:
                raise ValueError("MISTRAL_API_KEY not configured — cannot process PDFs")
            # Fail before paying for the Mistral call if already over quota.
            await self._quota.check_user_page_limit(user_id, 1)
            presigned_url = await self._s3.generate_presigned_get(s3_source_key)
            ocr_result = await self._mistral.ocr(presigned_url)
            await self._pages.store_mistral_result(document_id, user_id, kb_id, ocr_result)
        elif settings.CONVERTER_URL:
            presigned_url = await self._s3.generate_presigned_get(s3_source_key)
            extraction = await self._converter.extract(presigned_url, "pdf")
            await self._pages.store_extracted_pages(
                document_id, user_id, kb_id, extraction.pages, extraction.engine,
            )
        else:
            raise RuntimeError("Hosted PDF parsing requires the isolated converter service")

    async def _process_office(self, document_id: str, user_id: str, kb_id: str, s3_source_key: str, ext: str):
        if not settings.CONVERTER_URL:
            raise RuntimeError("Hosted Office parsing requires the isolated converter service")
        presigned_url = await self._s3.generate_presigned_get(s3_source_key)
        pdf_upload_url = await self._s3.generate_presigned_put(f"{user_id}/{document_id}/converted.pdf")
        extraction = await self._converter.extract(presigned_url, ext, pdf_upload_url)
        await self._pages.store_extracted_pages(
            document_id, user_id, kb_id, extraction.pages, f"libreoffice+{extraction.engine}",
        )

    async def _process_html(self, document_id: str, user_id: str, kb_id: str, s3_source_key: str):
        """Parse HTML with the webmd parser, store markdown + tagged HTML."""
        html_bytes = await self._s3.download_bytes(s3_source_key)
        raw_html = html_bytes.decode("utf-8", errors="replace")

        parser = await asyncio.to_thread(Parser, raw_html, content_only=True)
        result = await asyncio.to_thread(parser.parse)

        await parser.embed_images()
        tagged_html = await asyncio.to_thread(parser.html, sanitize=True)
        await self._s3.upload_bytes(
            f"{user_id}/{document_id}/tagged.html",
            tagged_html.encode("utf-8"),
            "text/html",
        )

        chunks = await asyncio.to_thread(chunk_text, result.content)
        await self._pages.store_html(document_id, user_id, kb_id, result.content, chunks)

    async def _process_spreadsheet(self, document_id: str, user_id: str, kb_id: str, s3_source_key: str, ext: str):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / f"source.{ext}"
            await self._s3.download_to_file(s3_source_key, str(source_path))
            sheets = await asyncio.to_thread(parse_sheets, str(source_path), ext)

        await self._pages.store_sheets(document_id, user_id, kb_id, sheets)

    async def _fetch_document(self, document_id: str, user_id: str) -> asyncpg.Record | None:
        return await self._pool.fetchrow(
            "SELECT filename, file_type, path, knowledge_base_id::text as kb_id "
            "FROM documents WHERE id = $1 AND user_id = $2",
            document_id, user_id,
        )

    async def _mark_failed(self, document_id: str, error_message: str) -> None:
        try:
            await self._pool.execute(
                "UPDATE documents SET status = 'failed', error_message = $2, updated_at = now() "
                "WHERE id = $1",
                document_id, error_message,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to update status to failed for %s", document_id)
