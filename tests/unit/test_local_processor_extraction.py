import asyncio
import sys
import threading
import types
import uuid
from pathlib import Path

import aiosqlite
import pytest


def _stub_pdf_extract(monkeypatch, extract_fn) -> None:
    """Stub services.pdf_extract so _process_pdf's lazy import skips the heavy opendataloader_pdf dependency."""
    module = types.ModuleType("services.pdf_extract")
    module.extract_pdf = extract_fn
    monkeypatch.setitem(sys.modules, "services.pdf_extract", module)

SCHEMA_PATH = Path(__file__).parents[2] / "shared" / "sqlite_migrations" / "0001_baseline.sql"
USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


async def _init_db(workspace: Path) -> aiosqlite.Connection:
    (workspace / ".llmwiki").mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(workspace / ".llmwiki" / "index.db"))
    await db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await db.execute(
        "INSERT INTO workspace (id, name, description, user_id) VALUES (?, 'ws', '', ?)",
        (str(uuid.uuid4()), USER_ID),
    )
    await db.commit()
    return db


async def _insert_doc(
    db: aiosqlite.Connection, *, filename: str, file_type: str,
    relative_path: str, status: str = "pending",
) -> str:
    doc_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
        "file_type, status, tags, version, document_number) "
        "VALUES (?, ?, ?, ?, '/', ?, 'source', ?, ?, '[]', 0, 1)",
        (doc_id, USER_ID, filename, filename, relative_path, file_type, status),
    )
    await db.commit()
    return doc_id


async def _chunk_count(db: aiosqlite.Connection, doc_id: str) -> int:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM document_chunks WHERE document_id = ?", (doc_id,),
    )
    return (await cursor.fetchone())[0]


async def _page_count(db: aiosqlite.Connection, doc_id: str) -> int:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM document_pages WHERE document_id = ?", (doc_id,),
    )
    return (await cursor.fetchone())[0]


async def _doc_row(db: aiosqlite.Connection, doc_id: str) -> dict:
    cursor = await db.execute(
        "SELECT status, parser, error_message, page_count FROM documents WHERE id = ?",
        (doc_id,),
    )
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, await cursor.fetchone()))


def _pdf_fixture() -> list[tuple[int, str, list[dict]]]:
    """(page_num, markdown, images=[]) — no images so no asset side-effects."""
    return [
        (1, "# Attention\n\n" + ("Self-attention scales with sequence length. " * 30), []),
        (2, "## Decoder\n\n" + ("Cross-attention reads the encoder memory. " * 30), []),
    ]


async def test_pdf_happy_path_stores_pages_and_chunks(tmp_path, monkeypatch):
    from domain.local_processor import process_document

    workspace = tmp_path / "ws"
    workspace.mkdir()
    db = await _init_db(workspace)

    (workspace / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    doc_id = await _insert_doc(
        db, filename="paper.pdf", file_type="pdf", relative_path="paper.pdf",
    )

    fixture = _pdf_fixture()
    _stub_pdf_extract(monkeypatch, lambda path: fixture)

    await process_document(db, doc_id, workspace)

    row = await _doc_row(db, doc_id)
    assert row["status"] == "ready"
    assert row["parser"] == "opendataloader"
    assert row["page_count"] == 2
    assert await _page_count(db, doc_id) == 2
    assert await _chunk_count(db, doc_id) > 0

    await db.close()


async def test_processing_doc_is_not_reclaimed(tmp_path, monkeypatch):
    """A doc already 'processing' must not be reprocessed: the pending-claim matches 0 rows."""
    from domain.local_processor import process_document

    workspace = tmp_path / "ws"
    workspace.mkdir()
    db = await _init_db(workspace)

    (workspace / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    doc_id = await _insert_doc(
        db, filename="paper.pdf", file_type="pdf", relative_path="paper.pdf",
        status="processing",
    )

    called = False

    def _spy(path: str):
        nonlocal called
        called = True
        return _pdf_fixture()

    _stub_pdf_extract(monkeypatch, _spy)

    await process_document(db, doc_id, workspace)

    assert called is False
    assert await _chunk_count(db, doc_id) == 0
    row = await _doc_row(db, doc_id)
    assert row["status"] == "processing"

    await db.close()


async def test_cancelled_processing_is_restored_to_pending(tmp_path, monkeypatch):
    """Shutdown cancellation after a claim must not strand a processing row."""
    import domain.local_processor as processor

    workspace = tmp_path / "ws"
    workspace.mkdir()
    db = await _init_db(workspace)

    (workspace / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    doc_id = await _insert_doc(
        db, filename="paper.pdf", file_type="pdf", relative_path="paper.pdf",
    )
    extraction_started = asyncio.Event()

    async def stalled_extraction(*args, **kwargs):
        extraction_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(processor, "_process_pdf", stalled_extraction)
    task = asyncio.create_task(processor.process_document(db, doc_id, workspace))
    await asyncio.wait_for(extraction_started.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    row = await _doc_row(db, doc_id)
    assert row["status"] == "pending"
    assert row["error_message"] is None

    await db.close()


async def test_isolated_cancellation_joins_worker_before_status_and_cleanup(
    tmp_path,
    monkeypatch,
):
    """A cancelled extraction keeps its claim/resources until its thread exits."""
    import domain.local_processor as processor

    workspace = tmp_path / "ws"
    workspace.mkdir()
    db = await _init_db(workspace)
    (workspace / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    doc_id = await _insert_doc(
        db, filename="paper.pdf", file_type="pdf", relative_path="paper.pdf",
    )

    worker_started = threading.Event()
    worker_release = threading.Event()

    def blocked_extract(path: str):
        worker_started.set()
        if not worker_release.wait(timeout=5):
            raise TimeoutError("test worker was never released")
        return _pdf_fixture()

    _stub_pdf_extract(monkeypatch, blocked_extract)
    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(processor, "_process_semaphore", semaphore)

    connection_closed = asyncio.Event()
    original_create_pool = processor.create_pool

    class TrackingConnection:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def close(self):
            await self._inner.close()
            connection_closed.set()

    async def tracking_create_pool(*args, **kwargs):
        inner = await original_create_pool(*args, **kwargs)
        return TrackingConnection(inner)

    monkeypatch.setattr(processor, "create_pool", tracking_create_pool)
    task = asyncio.create_task(processor.process_document_isolated(workspace, doc_id))
    started = await asyncio.wait_for(
        asyncio.get_running_loop().run_in_executor(None, worker_started.wait, 1),
        timeout=2,
    )
    assert started is True

    task.cancel()
    await asyncio.sleep(0)
    try:
        row = await _doc_row(db, doc_id)
        assert row["status"] == "processing"
        assert semaphore.locked()
        assert not connection_closed.is_set()
        assert not task.done()
    finally:
        worker_release.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)

    row = await _doc_row(db, doc_id)
    assert row["status"] == "pending"
    assert not semaphore.locked()
    assert connection_closed.is_set()

    await db.close()


async def test_missing_file_marks_failed(tmp_path):
    from domain.local_processor import process_document

    workspace = tmp_path / "ws"
    workspace.mkdir()
    db = await _init_db(workspace)

    doc_id = await _insert_doc(
        db, filename="ghost.pdf", file_type="pdf", relative_path="ghost.pdf",
    )

    await process_document(db, doc_id, workspace)

    row = await _doc_row(db, doc_id)
    assert row["status"] == "failed"
    assert row["error_message"] == "File not found"

    await db.close()


async def test_office_without_libreoffice_marks_failed(tmp_path, monkeypatch):
    import domain.local_processor as lp
    from domain.local_processor import process_document

    workspace = tmp_path / "ws"
    workspace.mkdir()
    db = await _init_db(workspace)

    (workspace / "deck.docx").write_bytes(b"PK fake docx")
    doc_id = await _insert_doc(
        db, filename="deck.docx", file_type="docx", relative_path="deck.docx",
    )

    monkeypatch.setattr(lp.shutil, "which", lambda name: None)

    await process_document(db, doc_id, workspace)

    row = await _doc_row(db, doc_id)
    assert row["status"] == "failed"
    assert "LibreOffice not installed" in row["error_message"]
    assert await _chunk_count(db, doc_id) == 0

    await db.close()


def test_office_timeout_kills_conversion_process_group(monkeypatch):
    import domain.local_processor as lp

    killed: list[tuple[int, int]] = []

    class StalledProcess:
        pid = 9812
        returncode = None

        def communicate(self, timeout):
            raise lp.subprocess.TimeoutExpired("libreoffice", timeout)

        def poll(self):
            return self.returncode

        def wait(self):
            self.returncode = -9
            return self.returncode

    process = StalledProcess()
    monkeypatch.setattr(lp.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(lp.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        lp.os,
        "killpg",
        lambda process_group, sig: killed.append((process_group, sig)),
    )

    with pytest.raises(TimeoutError, match="timed out"):
        lp._run_process_group(["libreoffice", "source.docx"], timeout=1)

    assert killed == [(process.pid, lp.signal.SIGKILL)]
    assert process.returncode == -9


async def test_pdf_mistral_backend_stores_pages(tmp_path, monkeypatch):
    """settings.PDF_BACKEND='mistral' routes through the OCR API; httpx is stubbed."""
    from config import settings
    from domain.local_processor import process_document

    workspace = tmp_path / "ws"
    workspace.mkdir()
    db = await _init_db(workspace)

    (workspace / "scan.pdf").write_bytes(b"%PDF-1.4 fake")
    doc_id = await _insert_doc(
        db, filename="scan.pdf", file_type="pdf", relative_path="scan.pdf",
    )

    monkeypatch.setattr(settings, "PDF_BACKEND", "mistral")
    monkeypatch.setattr(settings, "MISTRAL_API_KEY", "sk-test")

    ocr_payload = {
        "pages": [
            {"markdown": "# Invoice\n\n" + ("Line item total due on receipt. " * 30)},
            {"markdown": "## Terms\n\n" + ("Net thirty applies to all balances. " * 30)},
        ]
    }

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return ocr_payload

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url: str, **kwargs) -> "_FakeResponse":
            assert url == "https://api.mistral.ai/v1/ocr"
            assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
            return _FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    await process_document(db, doc_id, workspace)

    row = await _doc_row(db, doc_id)
    assert row["status"] == "ready"
    assert row["parser"] == "mistral"
    assert row["page_count"] == 2
    assert await _page_count(db, doc_id) == 2
    assert await _chunk_count(db, doc_id) > 0

    await db.close()


async def test_html_that_fails_to_parse_marks_failed_instead_of_storing_raw_html(tmp_path, monkeypatch):
    from domain.local_processor import process_document

    monkeypatch.setattr("html_parser.parser.MAX_OUTPUT_CHARS", 50)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "page.html").write_text("<p>" + "word " * 100 + "</p>", encoding="utf-8")
    db = await _init_db(workspace)
    doc_id = await _insert_doc(db, filename="page.html", file_type="html", relative_path="page.html")

    await process_document(db, doc_id, workspace)

    row = await _doc_row(db, doc_id)
    cursor = await db.execute("SELECT content FROM documents WHERE id = ?", (doc_id,))
    content = (await cursor.fetchone())[0]
    assert row["status"] == "failed"
    assert "too large" in row["error_message"]
    assert content is None
    await db.close()
