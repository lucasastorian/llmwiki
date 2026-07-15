"""Regression tests for resumable-upload serialization and disk streaming."""

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class _PatchRequest:
    def __init__(self, offset: int = 0):
        self.headers = {
            "Tus-Resumable": "1.0.0",
            "Content-Type": "application/offset+octet-stream",
            "Upload-Offset": str(offset),
        }
        self.app = SimpleNamespace(state=SimpleNamespace())


async def test_html_tus_uploads_have_parser_safe_size_limit(monkeypatch):
    from infra import tus

    async def fake_user_id(request):
        return "user-a"

    filename = base64.b64encode(b"oversized.html").decode()
    request = SimpleNamespace(
        headers={
            "Tus-Resumable": tus.TUS_VERSION,
            "Upload-Length": str(tus.MAX_HTML_SIZE + 1),
            "Upload-Metadata": f"filename {filename}",
        },
    )
    monkeypatch.setattr(tus, "_get_user_id", fake_user_id)

    with pytest.raises(HTTPException) as excinfo:
        await tus.tus_create(request)

    assert excinfo.value.status_code == 413


async def test_concurrent_tus_patches_cannot_append_at_the_same_offset(
    monkeypatch,
    tmp_path,
):
    from infra import tus

    tus._uploads.clear()
    upload = tus.TusUpload(
        upload_id="upload-race",
        user_id="user-a",
        upload_length=2,
        upload_offset=0,
        filename="sample.pdf",
        knowledge_base_id="11111111-1111-1111-1111-111111111111",
        temp_path=tmp_path / "upload-race",
    )
    upload.temp_path.touch()
    tus._uploads[upload.upload_id] = upload

    entered_drain = asyncio.Event()
    release_drain = asyncio.Event()
    drain_calls = 0

    async def fake_user_id(request):
        return "user-a"

    async def controlled_drain(request, temp_path, remaining):
        nonlocal drain_calls
        drain_calls += 1
        entered_drain.set()
        await release_drain.wait()
        return tus._StreamResult(
            bytes_written=1,
            overflow=False,
            disconnected=True,
        )

    monkeypatch.setattr(tus, "_get_user_id", fake_user_id)
    monkeypatch.setattr(tus, "_drain_to_temp", controlled_drain)

    first = asyncio.create_task(tus.tus_patch(upload.upload_id, _PatchRequest()))
    await entered_drain.wait()
    second = asyncio.create_task(tus.tus_patch(upload.upload_id, _PatchRequest()))
    await asyncio.sleep(0)
    release_drain.set()

    first_response = await first
    with pytest.raises(HTTPException) as excinfo:
        await second

    assert first_response.status_code == 204
    assert first_response.headers["Upload-Offset"] == "1"
    assert excinfo.value.status_code == 409
    assert upload.upload_offset == 1
    assert drain_calls == 1

    tus._uploads.clear()


async def test_s3_upload_file_streams_from_disk(monkeypatch, tmp_path):
    from services.s3 import S3Service

    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    calls = []

    class FakeS3Client:
        async def upload_file(self, filename, bucket, key, ExtraArgs):
            calls.append((filename, bucket, key, ExtraArgs))

    class ClientContext:
        async def __aenter__(self):
            return FakeS3Client()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSession:
        def client(self, name):
            assert name == "s3"
            return ClientContext()

    def fail_if_materialized(path):
        raise AssertionError("upload_file must not read the whole file into memory")

    monkeypatch.setattr(Path, "read_bytes", fail_if_materialized)

    service = object.__new__(S3Service)
    service._session = FakeSession()
    service._bucket = "test-bucket"

    await service.upload_file("user/doc/source.bin", str(source), "application/octet-stream")

    assert calls == [
        (
            str(source),
            "test-bucket",
            "user/doc/source.bin",
            {"ContentType": "application/octet-stream"},
        )
    ]


async def test_s3_download_file_streams_to_disk(monkeypatch, tmp_path):
    from services.s3 import S3Service

    destination = tmp_path / "destination.bin"
    calls = []

    class FakeS3Client:
        async def download_file(self, bucket, key, filename):
            calls.append((bucket, key, filename))

    class ClientContext:
        async def __aenter__(self):
            return FakeS3Client()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSession:
        def client(self, name):
            assert name == "s3"
            return ClientContext()

    def fail_if_materialized(path, data):
        raise AssertionError("download_to_file must not buffer the whole object")

    monkeypatch.setattr(Path, "write_bytes", fail_if_materialized)

    service = object.__new__(S3Service)
    service._session = FakeSession()
    service._bucket = "test-bucket"

    await service.download_to_file("user/doc/source.bin", str(destination))

    assert calls == [
        ("test-bucket", "user/doc/source.bin", str(destination)),
    ]
