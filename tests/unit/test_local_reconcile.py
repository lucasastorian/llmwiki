"""Reconcile backfills search chunks for files that `llmwiki init` only listed."""

import uuid
from pathlib import Path

import aiosqlite

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


async def _insert_indexed_text(db: aiosqlite.Connection, content: str) -> str:
    """Mimic `init`: a text source listed in the index, ready, but never chunked."""
    doc_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
        "file_type, status, content, tags, version, document_number) "
        "VALUES (?, ?, 'notes.md', 'Notes', '/', 'notes.md', 'source', 'md', 'ready', ?, '[]', 0, 1)",
        (doc_id, USER_ID, content),
    )
    await db.commit()
    return doc_id


async def _chunk_count(db: aiosqlite.Connection, doc_id: str) -> int:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM document_chunks WHERE document_id = ?", (doc_id,),
    )
    return (await cursor.fetchone())[0]


async def _fts_hits(db: aiosqlite.Connection, term: str) -> int:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?", (term,),
    )
    return (await cursor.fetchone())[0]


async def _insert_indexed_html(db: aiosqlite.Connection, workspace: Path, html: str) -> str:
    """Mimic `init`: an HTML source listed in the index, on disk, never processed."""
    (workspace / "page.html").write_text(html, encoding="utf-8")
    doc_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
        "file_type, status, content, tags, version, document_number) "
        "VALUES (?, ?, 'page.html', 'Page', '/', 'page.html', 'source', 'html', 'ready', NULL, '[]', 0, 2)",
        (doc_id, USER_ID),
    )
    await db.commit()
    return doc_id


async def test_reconcile_routes_html_through_webmd(tmp_path):
    from domain.local_processor import reconcile_workspace

    workspace = tmp_path / "research"
    workspace.mkdir()
    db = await _init_db(workspace)
    html = (
        "<html><body><h1>Quantum Annealing</h1><p>"
        + ("Tunneling explores the energy landscape. " * 20)
        + "</p></body></html>"
    )
    doc_id = await _insert_indexed_html(db, workspace, html)

    await reconcile_workspace(db, workspace)

    cursor = await db.execute("SELECT parser, status FROM documents WHERE id = ?", (doc_id,))
    parser, status = await cursor.fetchone()
    assert parser == "webmd"  # routed through the HTML parser, not chunked as raw text ('text')
    assert status == "ready"
    assert await _chunk_count(db, doc_id) > 0
    assert await _fts_hits(db, "tunneling") > 0

    await db.close()


async def test_reconcile_backfills_chunks_for_indexed_text(tmp_path):
    from domain.local_processor import reconcile_workspace

    workspace = tmp_path / "research"
    workspace.mkdir()
    db = await _init_db(workspace)
    content = "# Reinforcement Learning\n\n" + (
        "Policy gradient methods optimize the expected return directly. " * 40
    )
    doc_id = await _insert_indexed_text(db, content)

    # A file init only listed has no chunks or FTS rows, so it is unsearchable.
    assert await _chunk_count(db, doc_id) == 0
    assert await _fts_hits(db, "policy") == 0

    await reconcile_workspace(db, workspace)

    chunks_after_first = await _chunk_count(db, doc_id)
    assert chunks_after_first > 0
    assert await _fts_hits(db, "policy") > 0

    # Idempotent: the `parser` marker keeps a second pass from re-chunking.
    from domain.local_processor import _unchunked_text_docs
    assert await _unchunked_text_docs(db) == []
    await reconcile_workspace(db, workspace)
    assert await _chunk_count(db, doc_id) == chunks_after_first

    await db.close()


async def test_reconcile_recovers_interrupted_processing_with_stale_chunks(tmp_path):
    """A hard exit can leave processing + old chunks; startup must retry it."""
    from domain.local_processor import reconcile_workspace

    workspace = tmp_path / "research"
    workspace.mkdir()
    db = await _init_db(workspace)
    html = (
        "<html><body><h1>Recovered Document</h1><p>"
        + ("Interruption recovery makes extraction retryable. " * 25)
        + "</p></body></html>"
    )
    doc_id = await _insert_indexed_html(db, workspace, html)
    await db.execute(
        "UPDATE documents SET status = 'processing', parser = 'webmd', content = 'stale', "
        "updated_at = datetime('now', '-1 minute') "
        "WHERE id = ?",
        (doc_id,),
    )
    await db.execute(
        "INSERT INTO document_chunks "
        "(id, document_id, chunk_index, content, source_content, token_count) "
        "VALUES (?, ?, 0, 'stale chunk', 'stale chunk', 2)",
        (str(uuid.uuid4()), doc_id),
    )
    await db.commit()

    await reconcile_workspace(db, workspace)

    cursor = await db.execute(
        "SELECT status, parser, content FROM documents WHERE id = ?",
        (doc_id,),
    )
    status, parser, content = await cursor.fetchone()
    assert status == "ready"
    assert parser == "webmd"
    assert "Interruption recovery" in content
    assert await _fts_hits(db, "retryable") > 0
    assert await _fts_hits(db, "stale") == 0

    await db.close()


async def test_interrupted_recovery_does_not_reclaim_post_cutoff_work(tmp_path):
    from domain.local_processor import _recover_interrupted_documents

    workspace = tmp_path / "research"
    workspace.mkdir()
    db = await _init_db(workspace)
    doc_id = await _insert_indexed_html(db, workspace, "<p>Active extraction</p>")
    await db.execute(
        "UPDATE documents SET status = 'processing', updated_at = '2029-12-31 23:59:59' "
        "WHERE id = ?",
        (doc_id,),
    )
    await db.commit()

    recovered = await _recover_interrupted_documents(
        db,
        "2029-12-31 23:59:59",
    )

    cursor = await db.execute("SELECT status FROM documents WHERE id = ?", (doc_id,))
    assert recovered == []
    assert (await cursor.fetchone())[0] == "processing"

    await db.close()


async def test_reconcile_finalizes_pending_image(tmp_path):
    from domain.local_processor import reconcile_workspace

    workspace = tmp_path / "research"
    workspace.mkdir()
    (workspace / "diagram.png").write_bytes(b"not-decoded-by-native-handler")
    db = await _init_db(workspace)
    doc_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, "
        "source_kind, file_type, status, tags, version, document_number) "
        "VALUES (?, ?, 'diagram.png', 'Diagram', '/', 'diagram.png', 'source', "
        "'png', 'pending', '[]', 0, 3)",
        (doc_id, USER_ID),
    )
    await db.commit()

    await reconcile_workspace(db, workspace)

    cursor = await db.execute(
        "SELECT status, parser, page_count FROM documents WHERE id = ?",
        (doc_id,),
    )
    assert await cursor.fetchone() == ("ready", "native", 1)
    await db.close()
