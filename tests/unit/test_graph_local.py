"""rebuild_local is atomic: a mid-rebuild failure rolls back instead of leaving the graph wiped."""

import uuid
from pathlib import Path

import aiosqlite
import pytest

SCHEMA_PATH = Path(__file__).parents[2] / "shared" / "sqlite_migrations" / "0001_baseline.sql"
USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


async def _init_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    await db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await db.execute(
        "INSERT INTO workspace (id, name, description, user_id) VALUES (?, 'ws', '', ?)",
        (str(uuid.uuid4()), USER_ID),
    )
    await db.commit()
    return db


async def _insert_doc(
    db: aiosqlite.Connection, filename: str, path: str, source_kind: str,
    file_type: str, content: str | None, number: int,
) -> str:
    doc_id = str(uuid.uuid4())
    title = filename.rsplit(".", 1)[0].title()
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
        "file_type, status, content, tags, version, document_number) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, '[]', 0, ?)",
        (doc_id, USER_ID, filename, title, path, filename, source_kind, file_type, content, number),
    )
    await db.commit()
    return doc_id


async def _ref_count(db: aiosqlite.Connection) -> int:
    cursor = await db.execute("SELECT COUNT(*) FROM document_references")
    return (await cursor.fetchone())[0]


async def test_rebuild_local_builds_citation_edges():
    from services.graph import rebuild_local

    db = await _init_db()
    paper = await _insert_doc(db, "paper.pdf", "/", "source", "pdf", None, 1)
    await _insert_doc(
        db, "a.md", "/wiki/", "wiki", "md",
        "Intro text.\n\n[^1]: paper.pdf, p.3", 2,
    )

    result = await rebuild_local(db, USER_ID)

    assert result == {"citations": 1, "links": 0}
    cursor = await db.execute(
        "SELECT target_document_id, reference_type, page FROM document_references"
    )
    rows = await cursor.fetchall()
    assert rows == [(paper, "cites", 3)]

    await db.close()


async def test_rebuild_local_rolls_back_on_failure(monkeypatch):
    import services.graph as graph
    from services.graph import rebuild_local

    db = await _init_db()
    wiki = await _insert_doc(db, "a.md", "/wiki/", "wiki", "md", "links to [b](./b.md)", 1)
    target = await _insert_doc(db, "b.md", "/wiki/", "wiki", "md", "target", 2)

    # A pre-existing graph that a failed rebuild must not destroy.
    await db.execute(
        "INSERT INTO document_references (id, source_document_id, target_document_id, reference_type) "
        "VALUES (?, ?, ?, 'links_to')",
        (str(uuid.uuid4()), wiki, target),
    )
    await db.commit()
    assert await _ref_count(db) == 1

    def _boom(*args, **kwargs):
        raise RuntimeError("parser exploded mid-rebuild")

    monkeypatch.setattr(graph, "extract_references", _boom)

    with pytest.raises(RuntimeError):
        await rebuild_local(db, USER_ID)

    assert await _ref_count(db) == 1

    await db.close()
