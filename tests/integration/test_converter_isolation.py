import asyncio
import importlib
import sys
import tempfile
import time
import types
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from uuid import UUID

import pytest
from fastapi import HTTPException


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
    # 8 bytes, valid PDF magic — finalize now magic-byte-validates before upload.
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


async def test_presigned_urls_are_scoped_to_exact_document_keys(monkeypatch):
    ocr = _import_ocr_module(monkeypatch)
    s3 = RecordingS3()
    service = ocr.OCRService(s3, pool=None)
    calls = []

    class FakeResponse:
        headers = {"content-type": "application/json"}
        def raise_for_status(self):
            return None
        def json(self):
            return {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            calls.append((url, json, headers))
            return FakeResponse()

    monkeypatch.setattr(ocr.settings, "CONVERTER_URL", "https://converter.test")
    monkeypatch.setattr(ocr.settings, "CONVERTER_SECRET", "secret-token")
    monkeypatch.setattr(ocr.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    pdf_key_a = await service._convert_to_pdf_s3(
        document_id="doc-a",
        user_id="user-a",
        s3_source_key="user-a/doc-a/source.docx",
        ext="docx",
    )
    pdf_key_b = await service._convert_to_pdf_s3(
        document_id="doc-b",
        user_id="user-b",
        s3_source_key="user-b/doc-b/source.docx",
        ext="docx",
    )

    assert pdf_key_a == "user-a/doc-a/converted.pdf"
    assert pdf_key_b == "user-b/doc-b/converted.pdf"
    assert calls[0][1]["source_url"] == "https://s3.local/get/user-a%2Fdoc-a%2Fsource.docx"
    assert calls[0][1]["result_url"] == "https://s3.local/put/user-a%2Fdoc-a%2Fconverted.pdf"
    assert calls[0][1]["source_ext"] == "docx"
    assert "request_id" in calls[0][1]
    assert calls[1][1]["source_url"] == "https://s3.local/get/user-b%2Fdoc-b%2Fsource.docx"
    assert calls[1][1]["result_url"] == "https://s3.local/put/user-b%2Fdoc-b%2Fconverted.pdf"
    assert calls[1][1]["source_ext"] == "docx"
    assert calls[0][1]["request_id"] != calls[1][1]["request_id"]
    assert s3.presigned_get_calls == [
        ("user-a/doc-a/source.docx", 3600),
        ("user-b/doc-b/source.docx", 3600),
    ]
    assert s3.presigned_put_calls == [
        ("user-a/doc-a/converted.pdf", "application/pdf", 3600),
        ("user-b/doc-b/converted.pdf", "application/pdf", 3600),
    ]


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
        return [(1, f"{ext}:{source_url}")]

    async def fake_store_extracted_pages(document_id, user_id, kb_id, page_contents, parser, page_elements=None):
        stored.append((document_id, user_id, kb_id, page_contents, parser))

    monkeypatch.setattr(service, "_call_converter_extract", fake_call_converter_extract)
    monkeypatch.setattr(service, "_store_extracted_pages", fake_store_extracted_pages)

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
    with pytest.raises(RuntimeError, match="isolated converter"):
        await service._convert_to_pdf_s3(
            "doc-a", "user-a", "user-a/doc-a/source.docx", "docx",
        )

    assert s3.download_to_file_calls == []


async def test_process_opendataloader_uses_isolated_tempdirs_under_concurrency(monkeypatch):
    ocr = _import_ocr_module(monkeypatch)
    s3 = RecordingS3()
    service = ocr.OCRService(s3, pool=None)
    stored = []
    created_dirs = []
    seen_pdf_paths = []
    real_tempdir = tempfile.TemporaryDirectory

    class RecordingTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            self._ctx = real_tempdir(*args, **kwargs)

        def __enter__(self):
            path = self._ctx.__enter__()
            created_dirs.append(path)
            return path

        def __exit__(self, exc_type, exc, tb):
            return self._ctx.__exit__(exc_type, exc, tb)

    def fake_extract_pdf(pdf_path: str):
        seen_pdf_paths.append(pdf_path)
        assert Path(pdf_path).exists()
        time.sleep(0.02)
        return [(1, Path(pdf_path).read_text(encoding="utf-8"), [])]

    async def fake_store_extracted_pages(document_id, user_id, kb_id, page_contents, parser, page_elements=None, assets=None):
        stored.append((document_id, user_id, page_contents, parser))

    async def fake_build_pdf_assets(document_id, pages_with_images):
        return [], {}

    async def fake_upload_assets(user_id, assets):
        return None

    monkeypatch.setattr(ocr.tempfile, "TemporaryDirectory", RecordingTemporaryDirectory)
    monkeypatch.setattr(ocr, "_extract_pdf_in_process", fake_extract_pdf)
    monkeypatch.setattr(service, "_store_extracted_pages", fake_store_extracted_pages)
    monkeypatch.setattr(service, "_build_pdf_assets", fake_build_pdf_assets)
    monkeypatch.setattr(service, "_upload_assets", fake_upload_assets)

    await asyncio.gather(
        service._process_opendataloader("doc-a", "user-a", "kb-a", "user-a/doc-a/source.pdf"),
        service._process_opendataloader("doc-b", "user-b", "kb-b", "user-b/doc-b/source.pdf"),
    )

    assert len(created_dirs) == 2
    assert len(set(created_dirs)) == 2
    assert {str(Path(path).parent) for path in seen_pdf_paths} == set(created_dirs)
    assert all(not Path(path).exists() for path in created_dirs)
    assert sorted(stored) == [
        ("doc-a", "user-a", [(1, "user-a/doc-a/source.pdf")], "opendataloader"),
        ("doc-b", "user-b", [(1, "user-b/doc-b/source.pdf")], "opendataloader"),
    ]
