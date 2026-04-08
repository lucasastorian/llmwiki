"""SQLite database layer for local MCP tools.

Provides high-level query functions matching what each tool needs.
No raw SQL passes through from tool code — all queries are here.
"""

import json
import logging
import os
import uuid
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None

_SCHEMA_PATH = Path(__file__).parent.parent.parent.parent / "api" / "infra" / "db" / "sqlite_schema.sql"


def _rows_to_dicts(cursor: aiosqlite.Cursor, rows: list[tuple]) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    results = []
    for row in rows:
        d = dict(zip(cols, row))
        if "tags" in d and isinstance(d["tags"], str):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
        if "elements" in d and isinstance(d["elements"], str):
            try:
                d["elements"] = json.loads(d["elements"])
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(d)
    return results


async def init(workspace_path: str) -> None:
    """Initialize the SQLite connection for the given workspace."""
    global _db
    db_path = os.path.join(workspace_path, ".llmwiki", "index.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _db = await aiosqlite.connect(db_path)
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    if _SCHEMA_PATH.exists():
        await _db.executescript(_SCHEMA_PATH.read_text())
        await _db.commit()


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("SQLite not initialized — call init() first")
    return _db


async def get_workspace() -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT id, name, user_id FROM workspace LIMIT 1")
    row = await cursor.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))


async def list_knowledge_bases(user_id: str) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT w.name, w.name as slug, "
        "(SELECT count(*) FROM documents WHERE source_kind != 'wiki' AND status != 'failed') as source_count, "
        "(SELECT count(*) FROM documents WHERE source_kind = 'wiki' AND status != 'failed') as wiki_count "
        "FROM workspace w",
    )
    return _rows_to_dicts(cursor, await cursor.fetchall())


async def list_documents(user_id: str, kb_slug: str, path_filter: str | None = None) -> list[dict]:
    db = await get_db()
    sql = (
        "SELECT id, filename, title, path, file_type, tags, page_count, updated_at "
        "FROM documents WHERE status != 'failed' "
    )
    params = []
    if path_filter:
        sql += "AND path = ? "
        params.append(path_filter)
    sql += "ORDER BY path, filename"
    cursor = await db.execute(sql, params)
    return _rows_to_dicts(cursor, await cursor.fetchall())


async def get_document(user_id: str, kb_slug: str, filename: str, dir_path: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, user_id, filename, title, path, content, tags, version, "
        "file_type, page_count, created_at, updated_at "
        "FROM documents WHERE filename = ? AND path = ? AND status != 'failed'",
        (filename, dir_path),
    )
    rows = _rows_to_dicts(cursor, await cursor.fetchall())
    return rows[0] if rows else None


async def get_document_by_id(doc_id: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, user_id, filename, title, path, content, tags, version, "
        "file_type, page_count, created_at, updated_at "
        "FROM documents WHERE id = ?",
        (doc_id,),
    )
    rows = _rows_to_dicts(cursor, await cursor.fetchall())
    return rows[0] if rows else None


async def fuzzy_find_document(user_id: str, kb_slug: str, name: str) -> dict | None:
    db = await get_db()
    name_lower = name.lower()
    cursor = await db.execute(
        "SELECT id, user_id, filename, title, path, content, tags, version, "
        "file_type, page_count, created_at, updated_at "
        "FROM documents WHERE (lower(filename) = ? OR lower(title) = ?) AND status != 'failed'",
        (name_lower, name_lower),
    )
    rows = _rows_to_dicts(cursor, await cursor.fetchall())
    return rows[0] if rows else None


async def get_pages(doc_id: str, page_numbers: list[int]) -> list[dict]:
    db = await get_db()
    if not page_numbers:
        return []
    placeholders = ",".join("?" for _ in page_numbers)
    cursor = await db.execute(
        f"SELECT page, content, elements FROM document_pages "
        f"WHERE document_id = ? AND page IN ({placeholders}) ORDER BY page",
        [doc_id] + page_numbers,
    )
    return _rows_to_dicts(cursor, await cursor.fetchall())


async def get_all_pages(doc_id: str) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT page, content FROM document_pages WHERE document_id = ? ORDER BY page",
        (doc_id,),
    )
    return _rows_to_dicts(cursor, await cursor.fetchall())


async def search_chunks(
    user_id: str, kb_slug: str, query: str, *,
    limit: int = 20, path_filter: str | None = None,
) -> list[dict]:
    db = await get_db()
    sql = (
        "SELECT dc.content, dc.page, dc.header_breadcrumb, dc.chunk_index, "
        "d.filename, d.title, d.path, d.file_type, d.tags, "
        "rank as score "
        "FROM document_chunks dc "
        "JOIN chunks_fts fts ON dc.rowid = fts.rowid "
        "JOIN documents d ON dc.document_id = d.id "
        "WHERE chunks_fts MATCH ? AND d.status != 'failed' "
    )
    params: list = [query]

    if path_filter == "wiki":
        sql += "AND d.source_kind = 'wiki' "
    elif path_filter == "sources":
        sql += "AND d.source_kind != 'wiki' "

    sql += "ORDER BY rank LIMIT ?"
    params.append(limit)

    cursor = await db.execute(sql, params)
    return _rows_to_dicts(cursor, await cursor.fetchall())


async def create_document(
    user_id: str, kb_id: str, filename: str, title: str, dir_path: str,
    file_type: str, content: str, tags: list[str],
) -> dict:
    db = await get_db()
    doc_id = str(uuid.uuid4())
    relative_path = (dir_path.rstrip("/") + "/" + filename).lstrip("/")
    source_kind = "wiki" if dir_path.strip("/").startswith("wiki") else "source"

    cursor = await db.execute("SELECT COALESCE(MAX(document_number), 0) + 1 FROM documents")
    row = await cursor.fetchone()
    doc_number = row[0]

    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
        "file_type, status, content, tags, version, document_number) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, 0, ?)",
        (doc_id, user_id, filename, title, dir_path, relative_path, source_kind,
         file_type, content, json.dumps(tags), doc_number),
    )
    await db.commit()
    return {"id": doc_id, "filename": filename, "path": dir_path}


async def update_document_content(doc_id: str, user_id: str, content: str, tags: list[str] | None = None) -> None:
    db = await get_db()
    if tags is not None:
        await db.execute(
            "UPDATE documents SET content = ?, tags = ?, version = version + 1, "
            "updated_at = datetime('now') WHERE id = ?",
            (content, json.dumps(tags), doc_id),
        )
    else:
        await db.execute(
            "UPDATE documents SET content = ?, version = version + 1, "
            "updated_at = datetime('now') WHERE id = ?",
            (content, doc_id),
        )
    await db.commit()


async def archive_documents(doc_ids: list[str], user_id: str) -> int:
    db = await get_db()
    if not doc_ids:
        return 0
    placeholders = ",".join("?" for _ in doc_ids)
    cursor = await db.execute(
        f"DELETE FROM documents WHERE id IN ({placeholders})", doc_ids,
    )
    await db.commit()
    return cursor.rowcount


async def batch_list_documents(user_id: str, kb_slug: str) -> list[dict]:
    """List all documents with content for batch reading."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, filename, title, path, content, tags, file_type, page_count "
        "FROM documents WHERE status != 'failed' ORDER BY path, filename",
    )
    return _rows_to_dicts(cursor, await cursor.fetchall())
