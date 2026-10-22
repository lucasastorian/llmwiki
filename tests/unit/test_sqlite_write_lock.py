"""Concurrent writes on the shared local connection must serialize without losing an update."""

import asyncio
import uuid

USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


async def _seed_doc(db) -> str:
    await db.execute(
        "INSERT INTO workspace (id, name, description, user_id) VALUES (?, 'ws', '', ?)",
        (str(uuid.uuid4()), USER_ID),
    )
    doc_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
        "file_type, status, content, highlights, tags, version, document_number) "
        "VALUES (?, ?, 'doc.md', 'Doc', '/', 'doc.md', 'source', 'md', 'ready', 'body', '[]', '[]', 0, 1)",
        (doc_id, USER_ID),
    )
    await db.commit()
    return doc_id


async def test_concurrent_highlight_upserts_serialize(tmp_path):
    from infra.db.sqlite import SQLiteDocumentRepository, create_pool

    db = await create_pool(str(tmp_path / "index.db"))
    doc_id = await _seed_doc(db)
    repo = SQLiteDocumentRepository(db)

    h1 = {"id": "h1", "text": "first", "textAnchor": {"exact": "a"}}
    h2 = {"id": "h2", "text": "second", "textAnchor": {"exact": "b"}}

    # Same connection: without the write lock the two BEGIN IMMEDIATE spans collide.
    await asyncio.gather(
        repo.upsert_highlight(doc_id, USER_ID, h1),
        repo.upsert_highlight(doc_id, USER_ID, h2),
    )

    final = await repo.get_highlights(doc_id)
    ids = {h["id"] for h in final["highlights"]}
    assert ids == {"h1", "h2"}
    assert final["version"] == 2

    await db.close()
