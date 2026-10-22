import asyncio
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from uuid import UUID

import pytest
from fastapi import HTTPException
from services import converter_client
from services.types import ConverterExtraction


def _import_ocr_module(monkeypatch):
    """Import services.ocr with a stubbed opendataloader dependency."""
    monkeypatch.setitem(
        sys.modules,
        "opendataloader_pdf",
        types.SimpleNamespace(convert=lambda **kwargs: None),
    )
    pdf_extract = importlib.import_module("services.pdf_extract")
    importlib.reload(pdf_extract)
    ocr = importlib.import_module("services.ocr")
    return importlib.reload(ocr)


class RecordingS3:
    def __init__(self):
        self.upload_file_calls = []
        self.upload_bytes_calls = []
        self.download_to_file_calls = []
        self.presigned_get_calls = []
        self.presigned_put_calls = []
        self.delete_prefix_calls = []

    async def upload_file(self, key: str, file_path: str, content_type: str):
        self.upload_file_calls.append((key, file_path, content_type))

    async def upload_bytes(self, key: str, data: bytes, content_type: str):
        self.upload_bytes_calls.append((key, data, content_type))

    async def download_to_file(self, key: str, file_path: str):
        self.download_to_file_calls.append((key, file_path))
        Path(file_path).write_text(key, encoding="utf-8")

    async def generate_presigned_get(self, key: str, expires_in: int = 3600) -> str:
        self.presigned_get_calls.append((key, expires_in))
        return f"https://s3.local/get/{quote(key, safe='')}"

    async def generate_presigned_put(
        self,
        key: str,
        content_type: str = "application/pdf",
        expires_in: int = 3600,
    ) -> str:
        self.presigned_put_calls.append((key, content_type, expires_in))
        return f"https://s3.local/put/{quote(key, safe='')}"

    async def delete_prefix(self, prefix: str):
        self.delete_prefix_calls.append(prefix)


class RecordingPool:
    def __init__(self, *, storage_limit=1_000_000, current_bytes=0):
        self.execute_calls = []
        self.storage_limit = storage_limit
        self.current_bytes = current_bytes

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
        assert "storage_limit_bytes" in query
        return {"storage_limit_bytes": self.storage_limit}

    async def fetchval(self, query: str, *args):
        if "knowledge_bases" in query:
            return "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        if "SUM(file_size)" in query:
            return self.current_bytes
        raise AssertionError(query)


async def test_s3_key_isolation_ignores_filename_and_path_metadata(monkeypatch, tmp_path):
    from infra import tus

    tus._uploads.clear()
    temp_path = tmp_path / "upload.bin"
    # Valid PDF magic bytes, since finalize validates them before upload.
    temp_path.write_bytes(b"%PDF-1.4")

    upload = tus.TusUpload(
        upload_id="upload-1",
        user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        upload_length=8,
        upload_offset=8,
        filename="../../bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/secret.pdf",
        knowledge_base_id="11111111-1111-1111-1111-111111111111",
        temp_path=temp_path,
        path="/../../bob/",
    )
    tus._uploads[upload.upload_id] = upload

    fixed_document_id = UUID("33333333-3333-3333-3333-333333333333")
    monkeypatch.setattr(tus, "uuid4", lambda: fixed_document_id)

    s3 = RecordingS3()
    pool = RecordingPool()
    app_state = SimpleNamespace(s3_service=s3, pool=pool, ocr_service=None)

    document_id = await tus._finalize(upload, app_state)

    assert document_id == str(fixed_document_id)
    assert s3.upload_file_calls == [
        (
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/33333333-3333-3333-3333-333333333333/source.pdf",
            str(temp_path),
            "application/pdf",
        )
    ]
    assert ".." not in s3.upload_file_calls[0][0]
    assert not temp_path.exists()
    assert upload.upload_id not in tus._uploads


async def test_tus_finalize_rechecks_quota_and_cleans_uploaded_object(monkeypatch, tmp_path):
    from infra import tus

    tus._uploads.clear()
    temp_path = tmp_path / "quota-upload.pdf"
    temp_path.write_bytes(b"%PDF-1.4")
    upload = tus.TusUpload(
        upload_id="quota-upload",
        user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        upload_length=8,
        upload_offset=8,
        filename="quota.pdf",
        knowledge_base_id="11111111-1111-1111-1111-111111111111",
        temp_path=temp_path,
    )
    tus._uploads[upload.upload_id] = upload
    fixed_document_id = UUID("33333333-3333-3333-3333-333333333333")
    monkeypatch.setattr(tus, "uuid4", lambda: fixed_document_id)

    s3 = RecordingS3()
    pool = RecordingPool(storage_limit=10, current_bytes=4)
    app_state = SimpleNamespace(s3_service=s3, pool=pool, ocr_service=None)

    with pytest.raises(HTTPException) as excinfo:
        await tus._finalize(upload, app_state)

    assert excinfo.value.status_code == 413
    assert s3.delete_prefix_calls == [
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/"
        "33333333-3333-3333-3333-333333333333/"
    ]
    assert not temp_path.exists()
    assert upload.upload_id not in tus._uploads


async def test_office_with_mistral_backend_and_converter_uses_extract(monkeypatch):
    """PDF_BACKEND=mistral + CONVERTER_URL must route Office files through /extract."""
    ocr = _import_ocr_module(monkeypatch)
    s3 = RecordingS3()
    service = ocr.OCRService(s3, pool=None)
    calls = []
    stored = []

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def __init__(self, request_id: str):
            self._request_id = request_id

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "request_id": self._request_id,
                "pages": [{"page": 1, "content": "office md"}],
                "engine": "opendataloader",
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            calls.append((url, json, headers))
            return FakeResponse(json["request_id"])

    async def fake_store_extracted_pages(document_id, user_id, kb_id, page_contents, parser, page_elements=None, assets=None):
        stored.append((document_id, kb_id, page_contents, parser))

    monkeypatch.setattr(ocr.settings, "PDF_BACKEND", "mistral")
    monkeypatch.setattr(ocr.settings, "CONVERTER_URL", "https://converter.test")
    monkeypatch.setattr(ocr.settings, "CONVERTER_SECRET", "secret-token")
    monkeypatch.setattr(converter_client.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())
    monkeypatch.setattr(service._pages, "store_extracted_pages", fake_store_extracted_pages)

    await service._process_office(
        "doc-a", "user-a", "kb-a", "user-a/doc-a/source.docx", "docx",
    )

    assert calls[0][0] == "https://converter.test/extract"
    assert calls[0][1]["source_url"] == "https://s3.local/get/user-a%2Fdoc-a%2Fsource.docx"
    assert calls[0][1]["source_ext"] == "docx"
    assert calls[0][1]["pdf_upload_url"] == "https://s3.local/put/user-a%2Fdoc-a%2Fconverted.pdf"
    assert stored == [("doc-a", "kb-a", [(1, "office md")], "libreoffice+opendataloader")]
    assert s3.presigned_put_calls == [("user-a/doc-a/converted.pdf", "application/pdf", 3600)]


async def test_converter_extract_retries_capacity_response(monkeypatch):
    ocr = _import_ocr_module(monkeypatch)
    service = ocr.OCRService(RecordingS3(), pool=None)
    statuses = [503, 503, 200]
    attempts: list[str] = []
    sleeps: list[float] = []

    class FakeResponse:
        def __init__(self, status_code: int, request_id: str):
            self.status_code = status_code
            self.headers = {"retry-after": "0"}
            self._request_id = request_id

        def raise_for_status(self):
            if self.status_code != 200:
                raise AssertionError("retryable response was not retried")

        def json(self):
            return {
                "request_id": self._request_id,
                "pages": [{"page": 1, "content": "recovered"}],
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            attempts.append(json["request_id"])
            return FakeResponse(statuses.pop(0), json["request_id"])

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    monkeypatch.setattr(ocr.settings, "CONVERTER_URL", "https://converter.test")
    monkeypatch.setattr(converter_client.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())
    monkeypatch.setattr(converter_client.asyncio, "sleep", fake_sleep)

    extraction = await service._converter.extract("https://s3.test/source.pdf", "pdf")

    assert extraction.pages == [(1, "recovered")]
    assert extraction.engine == "opendataloader"
    assert len(attempts) == 3
    assert len(set(attempts)) == 1
    assert sleeps == [0.0, 0.0]


@pytest.mark.parametrize("max_concurrency", [1, 2])
async def test_converter_extract_requests_are_bounded(monkeypatch, max_concurrency):
    ocr = _import_ocr_module(monkeypatch)
    monkeypatch.setattr(ocr.settings, "CONVERTER_MAX_CONCURRENCY", max_concurrency)
    service = ocr.OCRService(RecordingS3(), pool=None)
    active = 0
    peak = 0

    class FakeResponse:
        status_code = 200
        headers = {}

        def __init__(self, request_id: str):
            self._request_id = request_id

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "request_id": self._request_id,
                "pages": [{"page": 1, "content": "ok"}],
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return FakeResponse(json["request_id"])

    monkeypatch.setattr(ocr.settings, "CONVERTER_URL", "https://converter.test")
    monkeypatch.setattr(converter_client.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    await asyncio.gather(*(
        service._converter.extract(f"https://s3.test/{i}.pdf", "pdf")
        for i in range(5)
    ))

    assert peak == max_concurrency


def test_tus_upload_namespace_isolation():
    from infra import tus

    tus._uploads.clear()
    upload = tus.TusUpload(
        upload_id="upload-tenant-a",
        user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        upload_length=5,
        upload_offset=0,
        filename="test.pdf",
        knowledge_base_id="11111111-1111-1111-1111-111111111111",
        temp_path=Path("/tmp/upload-tenant-a"),
    )
    tus._uploads[upload.upload_id] = upload

    assert tus._get_upload(upload.upload_id, upload.user_id) is upload

    with pytest.raises(HTTPException) as excinfo:
        tus._get_upload(upload.upload_id, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    assert excinfo.value.status_code == 404
    tus._uploads.clear()


async def test_ocr_service_has_no_shared_mutable_state_between_requests(monkeypatch):
    ocr = _import_ocr_module(monkeypatch)
    s3 = RecordingS3()
    service = ocr.OCRService(s3, pool=None)
    stored = []

    monkeypatch.setattr(ocr.settings, "PDF_BACKEND", "opendataloader")
    monkeypatch.setattr(ocr.settings, "CONVERTER_URL", "https://converter.test")

    async def fake_call_converter_extract(source_url: str, ext: str):
        await asyncio.sleep(0.01)
        return ConverterExtraction(
            pages=[(1, f"{ext}:{source_url}")],
            engine="opendataloader",
        )

    async def fake_store_extracted_pages(document_id, user_id, kb_id, page_contents, parser, page_elements=None):
        stored.append((document_id, user_id, kb_id, page_contents, parser))

    monkeypatch.setattr(service._converter, "extract", fake_call_converter_extract)
    monkeypatch.setattr(service._pages, "store_extracted_pages", fake_store_extracted_pages)

    before_state = dict(service.__dict__)

    await asyncio.gather(
        service._process_pdf("doc-a", "user-a", "kb-a", "user-a/doc-a/source.pdf"),
        service._process_pdf("doc-b", "user-b", "kb-b", "user-b/doc-b/source.pdf"),
    )

    assert service.__dict__ == before_state
    assert sorted(stored) == [
        (
            "doc-a",
            "user-a",
            "kb-a",
            [(1, "pdf:https://s3.local/get/user-a%2Fdoc-a%2Fsource.pdf")],
            "opendataloader",
        ),
        (
            "doc-b",
            "user-b",
            "kb-b",
            [(1, "pdf:https://s3.local/get/user-b%2Fdoc-b%2Fsource.pdf")],
            "opendataloader",
        ),
    ]


async def test_hosted_ocr_refuses_all_in_process_parser_fallbacks(monkeypatch):
    ocr = _import_ocr_module(monkeypatch)
    s3 = RecordingS3()
    service = ocr.OCRService(s3, pool=None)

    monkeypatch.setattr(ocr.settings, "MODE", "hosted")
    monkeypatch.setattr(ocr.settings, "PDF_BACKEND", "opendataloader")
    monkeypatch.setattr(ocr.settings, "CONVERTER_URL", "")

    with pytest.raises(RuntimeError, match="isolated converter"):
        await service._process_pdf(
            "doc-a", "user-a", "kb-a", "user-a/doc-a/source.pdf",
        )
    with pytest.raises(RuntimeError, match="isolated converter"):
        await service._process_office(
            "doc-a", "user-a", "kb-a", "user-a/doc-a/source.docx", "docx",
        )

    assert s3.download_to_file_calls == []
