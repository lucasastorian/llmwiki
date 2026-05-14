import asyncio
import importlib
import json
import sys
import tempfile
import types
from collections.abc import MutableMapping, MutableSequence, MutableSet
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient as HTTPXAsyncClient


@pytest.fixture
def converter_module(monkeypatch):
    Path("/tmp/conversions").mkdir(parents=True, exist_ok=True)

    fake_module = types.SimpleNamespace(convert=lambda **kwargs: None)
    monkeypatch.setitem(sys.modules, "opendataloader_pdf", fake_module)

    module = importlib.import_module("converter.main")
    return importlib.reload(module)


def _install_mocks(monkeypatch, converter_module):
    class FakeDownloadResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str):
            if "alpha" in url:
                return FakeDownloadResponse(b"alpha document")
            if "beta" in url:
                return FakeDownloadResponse(b"beta document")
            return FakeDownloadResponse(b"default document")

    def fake_convert(*, input_path: str, output_dir: str, format: str, quiet: bool):
        source_path = Path(input_path)
        source_text = source_path.read_text(encoding="utf-8")
        marker = source_path.parent.name
        payload = {
            "number of pages": 1,
            "kids": [
                {
                    "type": "paragraph",
                    "page number": 1,
                    "content": f"{source_text} :: {marker}",
                }
            ],
        }
        Path(output_dir, "result.json").write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(converter_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(converter_module.opendataloader_pdf, "convert", fake_convert)


async def _post_extract(converter_module, payload: dict, headers: dict | None = None):
    transport = ASGITransport(app=converter_module.app)
    async with HTTPXAsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/extract", json=payload, headers=headers or {})


async def test_request_id_echo_and_absence(monkeypatch, converter_module):
    _install_mocks(monkeypatch, converter_module)

    with_id = await _post_extract(
        converter_module,
        {
            "source_url": "https://bucket.s3.amazonaws.com/alpha.pdf",
            "source_ext": "pdf",
            "request_id": "req-alpha",
        },
    )
    without_id = await _post_extract(
        converter_module,
        {
            "source_url": "https://bucket.s3.amazonaws.com/beta.pdf",
            "source_ext": "pdf",
        },
    )

    assert with_id.status_code == 200
    assert with_id.json()["request_id"] == "req-alpha"
    assert with_id.json()["pages"][0]["content"].startswith("alpha document")

    assert without_id.status_code == 200
    assert "request_id" not in without_id.json()
    assert without_id.json()["pages"][0]["content"].startswith("beta document")


async def test_concurrent_request_isolation(monkeypatch, converter_module):
    _install_mocks(monkeypatch, converter_module)

    resp_a, resp_b = await asyncio.gather(
        _post_extract(
            converter_module,
            {
                "source_url": "https://bucket.s3.amazonaws.com/alpha.pdf",
                "source_ext": "pdf",
                "request_id": "req-a",
            },
        ),
        _post_extract(
            converter_module,
            {
                "source_url": "https://bucket.s3.amazonaws.com/beta.pdf",
                "source_ext": "pdf",
                "request_id": "req-b",
            },
        ),
    )

    body_a = resp_a.json()
    body_b = resp_b.json()

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert body_a["request_id"] == "req-a"
    assert body_b["request_id"] == "req-b"
    assert body_a["pages"] == [{"page": 1, "content": body_a["pages"][0]["content"]}]
    assert body_b["pages"] == [{"page": 1, "content": body_b["pages"][0]["content"]}]
    assert body_a["pages"][0]["content"].startswith("alpha document")
    assert body_b["pages"][0]["content"].startswith("beta document")
    assert body_a["pages"][0]["content"] != body_b["pages"][0]["content"]


async def test_temp_directory_cleanup(monkeypatch, converter_module):
    _install_mocks(monkeypatch, converter_module)

    created_paths = []
    real_tempdir = tempfile.TemporaryDirectory

    class RecordingTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            self._ctx = real_tempdir(*args, **kwargs)

        def __enter__(self):
            path = self._ctx.__enter__()
            created_paths.append(path)
            return path

        def __exit__(self, exc_type, exc, tb):
            return self._ctx.__exit__(exc_type, exc, tb)

    monkeypatch.setattr(converter_module.tempfile, "TemporaryDirectory", RecordingTemporaryDirectory)

    resp = await _post_extract(
        converter_module,
        {
            "source_url": "https://bucket.s3.amazonaws.com/alpha.pdf",
            "source_ext": "pdf",
            "request_id": "cleanup-check",
        },
    )

    assert resp.status_code == 200
    assert len(created_paths) == 1
    temp_path = Path(created_paths[0])
    assert not temp_path.exists()
    assert not list(Path("/tmp/conversions").glob(f"{temp_path.name}*"))


async def test_auth_enforcement(monkeypatch, converter_module):
    _install_mocks(monkeypatch, converter_module)
    monkeypatch.setattr(converter_module, "CONVERTER_SECRET", "top-secret")

    payload = {
        "source_url": "https://bucket.s3.amazonaws.com/alpha.pdf",
        "source_ext": "pdf",
    }

    missing = await _post_extract(converter_module, payload)
    wrong = await _post_extract(converter_module, payload, headers={"Authorization": "Bearer nope"})
    correct = await _post_extract(converter_module, payload, headers={"Authorization": "Bearer top-secret"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert correct.status_code == 200


async def test_s3_url_validation(monkeypatch, converter_module):
    _install_mocks(monkeypatch, converter_module)

    resp = await _post_extract(
        converter_module,
        {
            "source_url": "https://example.com/not-s3.pdf",
            "source_ext": "pdf",
            "request_id": "bad-url",
        },
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "URLs must point to S3"


async def test_no_persistent_state_between_requests(monkeypatch, converter_module):
    _install_mocks(monkeypatch, converter_module)

    def mutable_globals():
        result = {}
        for name, value in vars(converter_module).items():
            if name.startswith("__") or name == "app":
                continue
            if isinstance(value, (MutableMapping, MutableSequence)):
                result[name] = type(value).__name__
            elif isinstance(value, MutableSet) and name not in {
                "OFFICE_EXTENSIONS",
                "PDF_EXTENSIONS",
                "SUPPORTED_EXTENSIONS",
            }:
                result[name] = type(value).__name__
        return result

    before = mutable_globals()
    assert before == {}
    assert converter_module.app.state._state == {}

    first = await _post_extract(
        converter_module,
        {
            "source_url": "https://bucket.s3.amazonaws.com/alpha.pdf",
            "source_ext": "pdf",
            "request_id": "state-a",
        },
    )
    second = await _post_extract(
        converter_module,
        {
            "source_url": "https://bucket.s3.amazonaws.com/beta.pdf",
            "source_ext": "pdf",
            "request_id": "state-b",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert mutable_globals() == before
    assert converter_module.app.state._state == {}
