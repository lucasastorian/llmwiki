"""Orchestrates one /extract job: validate, download, convert, extract, bound the response."""

import logging
import tempfile
from pathlib import Path

from fastapi import HTTPException

from converter.bounds import ensure_bounded_json
from converter.config import OFFICE_EXTENSIONS, PDF_INSPECTOR_ENGINE, SUPPORTED_EXTENSIONS, ConverterConfig
from converter.executor import to_thread_joined
from converter.extraction_slots import ExtractionSlots
from converter.markdown_renderer import MarkdownRenderer
from converter.models import ExtractRequest
from converter.office_pdf_converter import OfficePdfConverter
from converter.opendataloader_engine import OpendataloaderEngine
from converter.pdf_inspector_engine import PdfInspectorEngine
from converter.pdf_uploader import PdfUploader
from converter.s3_url_validator import S3UrlValidator
from converter.source_downloader import SourceDownloader

logger = logging.getLogger(__name__)


class ExtractionService:
    def __init__(self, config: ConverterConfig) -> None:
        self._config = config
        self._slots = ExtractionSlots(config.max_concurrent_extractions)
        self._url_validator = S3UrlValidator(config.s3_bucket, config.s3_region)
        self._downloader = SourceDownloader(config.max_source_bytes)
        self._office_converter = OfficePdfConverter(config)
        self._pdf_uploader = PdfUploader()
        self._engine = self._build_engine(config)

    async def extract(self, request: ExtractRequest) -> dict:
        ext = request.source_ext.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(400, f"Unsupported extension: {ext}")
        self._url_validator.validate(request.source_url)
        if request.pdf_upload_url:
            self._url_validator.validate(request.pdf_upload_url)

        request_id = request.request_id or "none"
        with self._slots.acquire():
            logger.info("extract start: ext=%s active=%d request_id=%s", ext, self._slots.active, request_id)
            pages = await self._extract_from_source(request, ext, request_id)

        logger.info(
            "extract done: ext=%s engine=%s pages=%d request_id=%s",
            ext, self._engine.name, len(pages), request_id,
        )
        return self._build_response(request, pages)

    async def _extract_from_source(self, request: ExtractRequest, ext: str, request_id: str) -> list[dict]:
        try:
            with tempfile.TemporaryDirectory(prefix="conversion-") as tmpdir:
                source_path = Path(tmpdir) / f"source.{ext}"
                await self._downloader.download(request.source_url, source_path, request_id)
                pdf_path = await self._to_pdf(source_path, ext, tmpdir, request_id)
                if ext in OFFICE_EXTENSIONS and request.pdf_upload_url:
                    await self._pdf_uploader.upload(request.pdf_upload_url, pdf_path, request_id)
                return await self._run_extraction(pdf_path, tmpdir, request_id)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("extract failed: ext=%s request_id=%s", ext, request_id)
            raise HTTPException(500, "Extraction failed") from e

    async def _to_pdf(self, source_path: Path, ext: str, tmpdir: str, request_id: str) -> Path:
        if ext not in OFFICE_EXTENSIONS:
            return source_path
        try:
            return await to_thread_joined(self._office_converter.convert, source_path, tmpdir)
        except TimeoutError as e:
            logger.error(
                "office->pdf conversion timed out after %ds request_id=%s",
                self._config.convert_timeout_seconds, request_id,
            )
            raise HTTPException(504, "Office conversion timed out") from e
        except RuntimeError as e:
            logger.error("office->pdf conversion failed: %s request_id=%s", e, request_id)
            raise HTTPException(500, "Office conversion failed") from e

    async def _run_extraction(self, pdf_path: Path, tmpdir: str, request_id: str) -> list[dict]:
        extract_dir = Path(tmpdir) / "extract"
        extract_dir.mkdir()
        try:
            return await to_thread_joined(self._engine.extract_pages, str(pdf_path), str(extract_dir))
        except TimeoutError as e:
            logger.error(
                "pdf extraction timed out after %ds request_id=%s",
                self._config.extract_timeout_seconds, request_id,
            )
            raise HTTPException(
                504, f"PDF extraction exceeded {self._config.extract_timeout_seconds}s timeout",
            ) from e

    def _build_response(self, request: ExtractRequest, pages: list[dict]) -> dict:
        response: dict = {"pages": pages, "page_count": len(pages), "engine": self._engine.name}
        if request.request_id:
            response["request_id"] = request.request_id
        try:
            ensure_bounded_json(response, self._config.max_extraction_response_bytes, "extraction response")
        except RuntimeError as e:
            logger.error("extraction response exceeds safe size limit request_id=%s", request.request_id)
            raise HTTPException(500, "Extraction output exceeded safe response limit") from e
        return response

    def _build_engine(self, config: ConverterConfig) -> OpendataloaderEngine | PdfInspectorEngine:
        if config.pdf_engine == PDF_INSPECTOR_ENGINE:
            return PdfInspectorEngine(config)
        return OpendataloaderEngine(config, MarkdownRenderer(config))
