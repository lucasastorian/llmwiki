"""OCRService._do_process routing: which backend each extension reaches, and failure marking."""

import pytest
from services.types import ConverterExtraction

from tests.integration.test_converter_isolation import RecordingS3, _import_ocr_module

USER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DOC = "33333333-3333-3333-3333-333333333333"
KB = "11111111-1111-1111-1111-111111111111"


class RoutingPool:
    """asyncpg stand-in: answers the document/quota reads, records every write."""

    def __init__(self, filename: str | None):
        self.filename = filename
        self.execute_calls: list[tuple[str, tuple]] = []

    async def acquire(self):
        return self

    async def release(self, conn):
        assert conn is self

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, query: str, *args):
        self.execute_calls.append((query, args))

    async def fetchrow(self, query: str, *args):
        if "FROM documents WHERE id = $1 AND user_id = $2" in query:
            if self.filename is None:
                return None
            ext = self.filename.rsplit(".", 1)[-1]
            return {"filename": self.filename, "file_type": ext, "path": "/", "kb_id": KB}
        if "page_limit" in query:
            return None
        raise AssertionError(query)

    async def fetchval(self, query: str, *args):
        assert "SUM(page_count)" in query
        return 0

    def statuses(self) -> list[str]:
        return [args[1] for query, args in self.execute_calls if "SET status = $2" in query]

    def failure(self) -> str | None:
        for query, args in self.execute_calls:
            if "status = 'failed'" in query:
                return args[1]
        return None


@pytest.fixture
def ocr(monkeypatch):
    module = _import_ocr_module(monkeypatch)
    monkeypatch.setattr(module.settings, "MODE", "hosted")
    monkeypatch.setattr(module.settings, "PDF_BACKEND", "opendataloader")
    monkeypatch.setattr(module.settings, "CONVERTER_URL", "https://converter.test")
    monkeypatch.setattr(module.settings, "MISTRAL_API_KEY", "")
    monkeypatch.setattr(module.settings, "GLOBAL_OCR_ENABLED", True)
    return module


def _service(ocr, filename: str | None):
    pool = RoutingPool(filename)
    service = ocr.OCRService(RecordingS3(), pool)
    return service, pool


def _fake_extract(calls: list):
    async def extract(source_url: str, ext: str, pdf_upload_url: str | None = None) -> ConverterExtraction:
        calls.append((source_url, ext) if pdf_upload_url is None else (source_url, ext, pdf_upload_url))
        return ConverterExtraction(pages=[(1, "md")], engine="pdf-inspector")
    return extract


def _capture(stored: list):
    async def store(*args, **kwargs):
        stored.append((args, kwargs))
    return store


async def test_pdf_routes_to_converter(ocr, monkeypatch):
    service, pool = _service(ocr, "paper.PDF")
    extract_calls, stored = [], []
    monkeypatch.setattr(service._converter, "extract", _fake_extract(extract_calls))
    monkeypatch.setattr(service._pages, "store_extracted_pages", _capture(stored))

    await service.process_document(DOC, USER)

    assert pool.statuses() == ["processing"]
    assert extract_calls == [(f"https://s3.local/get/{USER}%2F{DOC}%2Fsource.pdf", "pdf")]
    assert stored[0][0] == (DOC, USER, KB, [(1, "md")], "pdf-inspector")
    assert pool.failure() is None


async def test_office_routes_to_converter_with_libreoffice_prefix(ocr, monkeypatch):
    service, pool = _service(ocr, "deck.pptx")
    extract_calls, stored = [], []
    monkeypatch.setattr(service._converter, "extract", _fake_extract(extract_calls))
    monkeypatch.setattr(service._pages, "store_extracted_pages", _capture(stored))

    await service.process_document(DOC, USER)

    assert extract_calls == [(
        f"https://s3.local/get/{USER}%2F{DOC}%2Fsource.pptx",
        "pptx",
        f"https://s3.local/put/{USER}%2F{DOC}%2Fconverted.pdf",
    )]
    assert stored[0][0][4] == "libreoffice+pdf-inspector"
    assert pool.failure() is None


async def test_image_marks_ready_without_extraction(ocr, monkeypatch):
    service, pool = _service(ocr, "photo.png")
    extract_calls = []
    monkeypatch.setattr(service._converter, "extract", _fake_extract(extract_calls))

    await service.process_document(DOC, USER)

    assert extract_calls == []
    assert any("SET status = 'ready'" in query for query, _ in pool.execute_calls)
    assert pool.failure() is None


async def test_html_parses_and_uploads_tagged_html(ocr, monkeypatch):
    service, pool = _service(ocr, "clip.html")
    s3 = service._s3
    stored = []
    monkeypatch.setattr(service._pages, "store_html", _capture(stored))

    async def download_bytes(key: str) -> bytes:
        return b"<html><body><article><h1>Title</h1><p>Body text here.</p></article></body></html>"
    s3.download_bytes = download_bytes

    await service.process_document(DOC, USER)

    (args, _), = stored
    assert args[:3] == (DOC, USER, KB)
    assert "Body text here." in args[3]
    assert s3.upload_bytes_calls[0][0] == f"{USER}/{DOC}/tagged.html"
    assert pool.failure() is None


async def test_spreadsheet_routes_to_sheet_store(ocr, monkeypatch):
    service, pool = _service(ocr, "data.csv")
    stored = []
    monkeypatch.setattr(service._pages, "store_sheets", _capture(stored))
    monkeypatch.setattr(ocr, "parse_sheets", lambda path, ext: [("Sheet1", "| a |\n|---|\n| 1 |")])

    await service.process_document(DOC, USER)

    assert stored[0][0] == (DOC, USER, KB, [("Sheet1", "| a |\n|---|\n| 1 |")])
    assert service._s3.download_to_file_calls[0][0] == f"{USER}/{DOC}/source.csv"
    assert pool.failure() is None


async def test_mistral_backend_routes_pdf_to_mistral(ocr, monkeypatch):
    monkeypatch.setattr(ocr.settings, "PDF_BACKEND", "mistral")
    monkeypatch.setattr(ocr.settings, "MISTRAL_API_KEY", "key")
    service, pool = _service(ocr, "paper.pdf")
    ocr_calls, stored = [], []

    async def fake_ocr(url: str, url_type: str = "document_url") -> dict:
        ocr_calls.append(url)
        return {"pages": [{"index": 0, "markdown": "md"}]}
    monkeypatch.setattr(service._mistral, "ocr", fake_ocr)
    monkeypatch.setattr(service._pages, "store_mistral_result", _capture(stored))

    await service.process_document(DOC, USER)

    assert ocr_calls == [f"https://s3.local/get/{USER}%2F{DOC}%2Fsource.pdf"]
    assert stored[0][0][:3] == (DOC, USER, KB)
    assert pool.failure() is None


async def test_mistral_backend_without_key_marks_failed(ocr, monkeypatch):
    monkeypatch.setattr(ocr.settings, "PDF_BACKEND", "mistral")
    service, pool = _service(ocr, "paper.pdf")

    await service.process_document(DOC, USER)

    assert "MISTRAL_API_KEY" in pool.failure()


async def test_unsupported_extension_marks_failed(ocr):
    service, pool = _service(ocr, "archive.zip")

    await service.process_document(DOC, USER)

    assert pool.statuses() == ["processing"]
    assert pool.failure() == "Unsupported file type: zip"


async def test_backend_error_marks_failed_with_truncated_message(ocr, monkeypatch):
    service, pool = _service(ocr, "paper.pdf")

    async def boom(source_url: str, ext: str):
        raise RuntimeError("x" * 900)
    monkeypatch.setattr(service._converter, "extract", boom)

    await service.process_document(DOC, USER)

    assert pool.failure() == "x" * 500


async def test_global_kill_switch_fails_before_reading_document(ocr, monkeypatch):
    monkeypatch.setattr(ocr.settings, "GLOBAL_OCR_ENABLED", False)
    service, pool = _service(ocr, "paper.pdf")

    await service.process_document(DOC, USER)

    assert pool.statuses() == []
    assert "temporarily disabled" in pool.failure()


async def test_missing_document_is_not_marked_failed(ocr, monkeypatch):
    service, pool = _service(ocr, None)
    extract_calls = []
    monkeypatch.setattr(service._converter, "extract", _fake_extract(extract_calls))

    await service.process_document(DOC, USER)

    assert extract_calls == []
    assert pool.failure() is None


async def test_html_over_the_output_budget_marks_failed(ocr, monkeypatch):
    monkeypatch.setattr("html_parser.parser.MAX_OUTPUT_CHARS", 50)
    service, pool = _service(ocr, "clip.html")

    async def download_bytes(key: str) -> bytes:
        return ("<p>" + "word " * 100 + "</p>").encode()
    service._s3.download_bytes = download_bytes

    await service.process_document(DOC, USER)

    assert "too large" in pool.failure()
    assert service._s3.upload_bytes_calls == []
