"""The migration runner must converge any pre-versioning local DB shape onto the current schema and stamp user_version."""

import json
import sqlite3
import uuid

USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

LEGACY_CHUNKS_DDL = """
CREATE TABLE document_chunks (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    page INTEGER,
    start_char INTEGER,
    token_count INTEGER NOT NULL,
    header_breadcrumb TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(document_id, chunk_index)
)
"""

LEGACY_DOCUMENTS_DDL = """
CREATE TABLE documents (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    title TEXT,
    path TEXT DEFAULT '/' NOT NULL,
    relative_path TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    content TEXT,
    tags TEXT DEFAULT '[]',
    version INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(relative_path)
)
"""


def _latest_version() -> int:
    from infra.db.local_migrations import _load_migrations

    return _load_migrations()[-1].version


async def _seed_doc(db, metadata: dict | None = None, *, filename: str = "doc.md") -> str:
    doc_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
        "file_type, status, content, metadata, tags, version, document_number) "
        "VALUES (?, ?, ?, 'Doc', '/', ?, 'source', 'md', 'ready', 'body', ?, '[]', 0, 1)",
        (doc_id, USER_ID, filename, filename, json.dumps(metadata or {})),
    )
    await db.commit()
    return doc_id


async def _seed_workspace(db) -> str:
    ws_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO workspace (id, name, description, user_id) VALUES (?, 'ws', '', ?)",
        (ws_id, USER_ID),
    )
    await db.commit()
    return ws_id


def test_fresh_db_gets_full_schema_and_version_stamp(tmp_path):
    from infra.db.local_migrations import apply_migrations

    path = str(tmp_path / "index.db")
    apply_migrations(path)

    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == _latest_version()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"workspace", "documents", "document_chunks", "knowledge_base_events"} <= tables
    conn.close()


def test_legacy_chunks_table_converges(tmp_path):
    from infra.db.local_migrations import apply_migrations

    path = str(tmp_path / "index.db")
    legacy = sqlite3.connect(path)
    legacy.execute(LEGACY_DOCUMENTS_DDL)
    legacy.execute(LEGACY_CHUNKS_DDL)
    legacy.execute(
        "INSERT INTO document_chunks (document_id, chunk_index, content, token_count) "
        "VALUES ('d1', 0, 'hello world', 3)",
    )
    legacy.commit()
    legacy.close()

    apply_migrations(path)

    conn = sqlite3.connect(path)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(document_chunks)")}
    assert {"source_content", "annotations_text", "has_highlight"} <= columns
    source_content, has_highlight = conn.execute(
        "SELECT source_content, has_highlight FROM document_chunks WHERE document_id = 'd1'",
    ).fetchone()
    assert source_content == "hello world"
    assert has_highlight == 0
    assert conn.execute("PRAGMA user_version").fetchone()[0] == _latest_version()
    conn.close()


def test_legacy_documents_gain_every_missing_column(tmp_path):
    from infra.db.local_migrations import apply_migrations

    path = str(tmp_path / "index.db")
    legacy = sqlite3.connect(path)
    legacy.execute(LEGACY_DOCUMENTS_DDL)
    legacy.execute(
        "INSERT INTO documents (id, user_id, filename, relative_path, source_kind, file_type) "
        "VALUES ('d1', ?, 'a.md', 'a.md', 'source', 'md')",
        (USER_ID,),
    )
    legacy.commit()
    legacy.close()

    apply_migrations(path)

    conn = sqlite3.connect(path)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    assert {"highlights", "metadata", "document_number", "content_hash", "stale_since"} <= columns
    assert conn.execute("SELECT highlights FROM documents WHERE id = 'd1'").fetchone()[0] == "[]"
    conn.close()


def test_apply_migrations_is_idempotent(tmp_path):
    from infra.db.local_migrations import apply_migrations

    path = str(tmp_path / "index.db")
    apply_migrations(path)
    apply_migrations(path)

    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == _latest_version()
    conn.close()


async def test_event_backfill_runs_once_for_legacy_workspaces(tmp_path):
    from infra.db.sqlite import create_pool

    path = str(tmp_path / "index.db")
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE workspace (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "description TEXT DEFAULT '', user_id TEXT NOT NULL, "
        "created_at TEXT DEFAULT (datetime('now')), UNIQUE(user_id))",
    )
    legacy.execute(LEGACY_DOCUMENTS_DDL)
    legacy.execute(
        "INSERT INTO workspace (id, name, user_id) VALUES ('ws1', 'ws', ?)", (USER_ID,),
    )
    legacy.execute(
        "INSERT INTO documents (id, user_id, filename, relative_path, source_kind, file_type) "
        "VALUES ('d1', ?, 'a.md', 'a.md', 'source', 'md')",
        (USER_ID,),
    )
    legacy.commit()
    legacy.close()

    db = await create_pool(path)
    cursor = await db.execute("SELECT event_type FROM knowledge_base_events ORDER BY event_type")
    events = [r[0] for r in await cursor.fetchall()]
    assert events == ["source.added", "tracking.started", "wiki.created"]
    await db.close()


def test_concurrent_runners_serialize_on_legacy_db(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from infra.db.local_migrations import apply_migrations

    path = str(tmp_path / "index.db")
    legacy = sqlite3.connect(path)
    legacy.execute(LEGACY_DOCUMENTS_DDL)
    legacy.commit()
    legacy.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in [pool.submit(apply_migrations, path) for _ in range(4)]:
            future.result()

    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == _latest_version()
    columns = [r[1] for r in conn.execute("PRAGMA table_info(documents)")]
    assert len(columns) == len(set(columns))
    conn.close()


def test_non_constant_default_requires_explicit_migration():
    import pytest
    from infra.db.local_migrations import _column_ddl

    with pytest.raises(ValueError, match="non-constant default"):
        _column_ddl("documents", "created_at", "TEXT", 0, "datetime('now')")
    assert _column_ddl("documents", "tags", "TEXT", 0, "'[]'") == "\"tags\" TEXT DEFAULT '[]'"


async def test_find_by_path_uses_local_schema(tmp_path):
    from infra.db.sqlite import SQLiteDocumentRepository, create_pool

    db = await create_pool(str(tmp_path / "index.db"))
    await _seed_workspace(db)
    doc_id = await _seed_doc(db)
    repo = SQLiteDocumentRepository(db)

    found = await repo.find_by_path("ignored-kb-id", USER_ID, "doc.md", "/")
    assert found is not None
    assert found["id"] == doc_id

    assert await repo.find_by_path("ignored-kb-id", USER_ID, "missing.md", "/") is None

    await db.close()


async def test_get_by_source_url_skips_assets_and_resolves_kb_id(tmp_path):
    from infra.db.sqlite import SQLiteDocumentRepository, create_pool

    db = await create_pool(str(tmp_path / "index.db"))
    ws_id = await _seed_workspace(db)
    doc_id = await _seed_doc(db, metadata={"source_url": "https://example.com/a"})
    await _seed_doc(
        db,
        metadata={"source_url": "https://example.com/a", "asset": True, "hidden": True},
        filename="img.png",
    )
    repo = SQLiteDocumentRepository(db)

    found = await repo.get_by_source_url("https://example.com/a")
    assert found is not None
    assert found["id"] == doc_id
    assert found["knowledge_base_id"] == ws_id

    await db.close()
