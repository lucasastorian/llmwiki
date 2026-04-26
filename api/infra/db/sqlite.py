"""SQLite repository implementations for local mode.

Single-user, no RLS. FTS5 for full-text search.
All queries use native SQLite syntax — no translation layer.
"""

import json
import logging
import uuid
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent.parent.parent.parent / "shared" / "sqlite_schema.sql"

_DOC_COLUMNS = (
    "id, user_id, filename, title, path, relative_path, source_kind, "
    "file_type, file_size, document_number, status, page_count, content, "
    "tags, date, metadata, error_message, version, parser, "
    "content_hash, mtime_ns, last_indexed_at, stale_since, "
    "created_at, updated_at"
)


def _row_to_dict(cursor: aiosqlite.Cursor, row: tuple) -> dict:
    cols = [d[0] for d in cursor.description]
    d = dict(zip(cols, row))
    if "tags" in d and isinstance(d["tags"], str):
        d["tags"] = json.loads(d["tags"])
    if "metadata" in d and isinstance(d["metadata"], str):
        try:
            d["metadata"] = json.loads(d["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass
    if "elements" in d and isinstance(d["elements"], str):
        try:
            d["elements"] = json.loads(d["elements"])
        except (json.JSONDecodeError, TypeError):
            pass
    # Compatibility: add archived=False for local docs (never archived, just deleted)
    if "status" in d:
        d.setdefault("archived", False)
    return d


async def create_pool(db_path: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(db_path)
    db.row_factory = None
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    schema = _SCHEMA_PATH.read_text()
    await db.executescript(schema)
    await db.commit()
    return db


class SQLiteDocumentRepository:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    async def list_by_kb(self, kb_id: str, *, path: str | None = None, archived: bool = False) -> list[dict]:
        if path:
            cursor = await self._db.execute(
                f"SELECT {_DOC_COLUMNS} FROM documents "
                "WHERE path = ? AND status != 'failed' "
                "ORDER BY filename",
                (path,),
            )
        else:
            cursor = await self._db.execute(
                f"SELECT {_DOC_COLUMNS} FROM documents "
                "WHERE status != 'failed' ORDER BY filename",
            )
        rows = await cursor.fetchall()
        return [_row_to_dict(cursor, r) for r in rows]

    async def get(self, doc_id: str) -> dict | None:
        cursor = await self._db.execute(
            f"SELECT {_DOC_COLUMNS} FROM documents WHERE id = ?", (doc_id,),
        )
        row = await cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None

    async def get_content(self, doc_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT id, content, version FROM documents WHERE id = ?", (doc_id,),
        )
        row = await cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None

    async def get_for_url(self, doc_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT id, user_id, filename, file_type FROM documents WHERE id = ?",
            (doc_id,),
        )
        row = await cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None

    async def find_by_path(
        self, kb_id: str, user_id: str, filename: str, path: str,
    ) -> dict | None:
        cursor = await self._db.execute(
            "SELECT * FROM documents WHERE knowledge_base_id = ? AND user_id = ? "
            "AND filename = ? AND path = ? AND NOT archived",
            (kb_id, user_id, filename, path),
        )
        row = await cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None

    async def create_note(
        self, kb_id: str, user_id: str, filename: str, path: str,
        title: str, content: str, tags: list[str],
    ) -> dict:
        doc_id = str(uuid.uuid4())
        relative_path = (path.rstrip("/") + "/" + filename).lstrip("/")
        source_kind = "wiki" if path.strip("/").startswith("wiki") else "source"

        cursor = await self._db.execute(
            "SELECT COALESCE(MAX(document_number), 0) + 1 FROM documents",
        )
        row = await cursor.fetchone()
        doc_number = row[0]

        await self._db.execute(
            "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
            "file_type, status, content, tags, version, document_number) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'md', 'ready', ?, ?, 0, ?)",
            (doc_id, user_id, filename, title, path, relative_path, source_kind,
             content, json.dumps(tags), doc_number),
        )
        await self._db.commit()
        return await self.get(doc_id)

    async def update_content(self, doc_id: str, user_id: str, content: str) -> dict | None:
        cursor = await self._db.execute(
            "UPDATE documents SET content = ?, version = version + 1, "
            "updated_at = datetime('now') WHERE id = ? "
            "RETURNING id, content, version",
            (content, doc_id),
        )
        row = await cursor.fetchone()
        await self._db.commit()
        return _row_to_dict(cursor, row) if row else None

    async def update_metadata(self, doc_id: str, user_id: str, **fields) -> dict | None:
        updates = []
        params = []
        for key, value in fields.items():
            if key == "tags":
                updates.append("tags = ?")
                params.append(json.dumps(value))
            elif key == "metadata":
                updates.append("metadata = ?")
                params.append(json.dumps(value))
            else:
                updates.append(f"{key} = ?")
                params.append(value)

        if not updates:
            return None

        updates.append("updated_at = datetime('now')")
        params.append(doc_id)

        sql = f"UPDATE documents SET {', '.join(updates)} WHERE id = ?"
        await self._db.execute(sql, params)
        await self._db.commit()
        return await self.get(doc_id)

    async def archive(self, doc_id: str, user_id: str) -> bool:
        await self._db.execute("DELETE FROM document_pages WHERE document_id = ?", (doc_id,))
        await self._db.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))
        cursor = await self._db.execute(
            "DELETE FROM documents WHERE id = ?", (doc_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def bulk_archive(self, doc_ids: list[str], user_id: str) -> None:
        if not doc_ids:
            return
        placeholders = ",".join("?" for _ in doc_ids)
        await self._db.execute(f"DELETE FROM document_pages WHERE document_id IN ({placeholders})", doc_ids)
        await self._db.execute(f"DELETE FROM document_chunks WHERE document_id IN ({placeholders})", doc_ids)
        await self._db.execute(
            f"DELETE FROM documents WHERE id IN ({placeholders})", doc_ids,
        )
        await self._db.commit()

    async def get_kb_id(self, doc_id: str) -> str | None:
        cursor = await self._db.execute(
            "SELECT id FROM workspace LIMIT 1",
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def update_status(self, doc_id: str, status: str, **fields) -> None:
        updates = ["status = ?"]
        params = [status]
        for key, value in fields.items():
            updates.append(f"{key} = ?")
            params.append(value)
        updates.append("updated_at = datetime('now')")
        params.append(doc_id)

        await self._db.execute(
            f"UPDATE documents SET {', '.join(updates)} WHERE id = ?", params,
        )
        await self._db.commit()

    async def get_for_processing(self, doc_id: str, user_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT filename, file_type, "
            "(SELECT id FROM workspace LIMIT 1) as knowledge_base_id "
            "FROM documents WHERE id = ?",
            (doc_id,),
        )
        row = await cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None

    async def create_upload(
        self, doc_id: str, kb_id: str, user_id: str, filename: str,
        path: str, title: str, file_type: str, file_size: int,
    ) -> None:
        relative_path = (path.rstrip("/") + "/" + filename).lstrip("/")
        source_kind = "wiki" if path.strip("/").startswith("wiki") else "source"

        cursor = await self._db.execute(
            "SELECT COALESCE(MAX(document_number), 0) + 1 FROM documents",
        )
        row = await cursor.fetchone()
        doc_number = row[0]

        await self._db.execute(
            "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
            "file_type, file_size, status, document_number) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (doc_id, user_id, filename, title, path, relative_path, source_kind,
             file_type, file_size, doc_number),
        )
        await self._db.commit()


class SQLiteKBRepository:
    """Singleton KB compatibility layer. One workspace = one KB."""

    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    async def list_all(self, user_id: str) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT w.id, w.user_id, w.name, w.name as slug, w.description, "
            "w.created_at, w.created_at as updated_at, "
            "(SELECT count(*) FROM documents WHERE source_kind != 'wiki' AND status != 'failed') as source_count, "
            "(SELECT count(*) FROM documents WHERE source_kind = 'wiki' AND status != 'failed') as wiki_page_count "
            "FROM workspace w",
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(cursor, r) for r in rows]

    async def get(self, kb_id: str, user_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT w.id, w.user_id, w.name, w.name as slug, w.description, "
            "w.created_at, w.created_at as updated_at, "
            "(SELECT count(*) FROM documents WHERE source_kind != 'wiki' AND status != 'failed') as source_count, "
            "(SELECT count(*) FROM documents WHERE source_kind = 'wiki' AND status != 'failed') as wiki_page_count "
            "FROM workspace w WHERE w.id = ?",
            (kb_id,),
        )
        row = await cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None

    async def get_owner(self, kb_id: str) -> str | None:
        cursor = await self._db.execute(
            "SELECT user_id FROM workspace LIMIT 1",
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def create(self, user_id: str, name: str, slug: str, description: str | None) -> dict:
        # Enforce singleton: return existing workspace if one exists
        cursor = await self._db.execute("SELECT id FROM workspace LIMIT 1")
        existing = await cursor.fetchone()
        if existing:
            return await self.get(existing[0], user_id)

        ws_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO workspace (id, name, description, user_id) VALUES (?, ?, ?, ?)",
            (ws_id, name, description or "", user_id),
        )
        await self._db.commit()
        return await self.get(ws_id, user_id)

    async def update(self, kb_id: str, user_id: str, **fields) -> dict | None:
        allowed = {"name", "description"}
        updates = []
        params = []
        for key, value in fields.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(value)
        if not updates:
            return None
        params.append(kb_id)
        await self._db.execute(
            f"UPDATE workspace SET {', '.join(updates)} WHERE id = ?", params,
        )
        await self._db.commit()
        return await self.get(kb_id, user_id)

    async def delete(self, kb_id: str, user_id: str) -> bool:
        return False  # Cannot delete the workspace KB in local mode

    async def count_users(self) -> int:
        return 1  # Single user in local mode


class SQLiteChunkRepository:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    async def store(self, doc_id: str, user_id: str, kb_id: str, chunks: list) -> None:
        await self._db.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))
        if not chunks:
            await self._db.commit()
            return

        await self._db.executemany(
            "INSERT INTO document_chunks "
            "(id, document_id, chunk_index, content, page, start_char, token_count, header_breadcrumb) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (str(uuid.uuid4()), doc_id, c.index, c.content, c.page,
                 c.start_char, c.token_count, c.header_breadcrumb)
                for c in chunks
            ],
        )
        await self._db.commit()
        logger.info("Stored %d chunks for doc %s", len(chunks), doc_id[:8])

    async def search_fulltext(
        self, kb_id: str, query: str, *, limit: int = 20,
        path_filter: str | None = None, user_id: str | None = None,
    ) -> list[dict]:
        sql = (
            "SELECT dc.content, dc.page, dc.header_breadcrumb, dc.chunk_index, "
            "d.filename, d.title, d.path, d.file_type, d.tags, "
            "rank "
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

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_dict(cursor, r) for r in rows]


class SQLitePageRepository:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    async def get_pages(self, doc_id: str, pages: list[int]) -> list[dict]:
        if not pages:
            return []
        placeholders = ",".join("?" for _ in pages)
        cursor = await self._db.execute(
            f"SELECT page, content, elements FROM document_pages "
            f"WHERE document_id = ? AND page IN ({placeholders}) ORDER BY page",
            [doc_id] + pages,
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(cursor, r) for r in rows]

    async def get_all_pages(self, doc_id: str) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT page, content, elements FROM document_pages "
            "WHERE document_id = ? ORDER BY page",
            (doc_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(cursor, r) for r in rows]

    async def store_pages(self, doc_id: str, pages: list[tuple]) -> None:
        await self._db.execute("DELETE FROM document_pages WHERE document_id = ?", (doc_id,))
        if not pages:
            await self._db.commit()
            return

        await self._db.executemany(
            "INSERT INTO document_pages (id, document_id, page, content, elements) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (str(uuid.uuid4()), doc_id, page_num, content,
                 json.dumps(elements) if elements else None)
                for page_num, content, *rest in pages
                for elements in [rest[0] if rest else None]
            ],
        )
        await self._db.commit()


class SQLiteUserRepository:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    async def get(self, user_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT user_id as id, name as display_name, 'local@localhost' as email, 1 as onboarded "
            "FROM workspace WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None

    async def get_limits(self, user_id: str) -> dict | None:
        return {"page_limit": 999999, "storage_limit_bytes": 107374182400}

    async def get_usage(self, user_id: str) -> dict:
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(page_count), 0) as total_pages, "
            "COALESCE(SUM(file_size), 0) as total_storage_bytes "
            "FROM documents WHERE status != 'failed'",
        )
        row = await cursor.fetchone()
        return _row_to_dict(cursor, row) if row else {"total_pages": 0, "total_storage_bytes": 0}

    async def set_onboarded(self, user_id: str) -> None:
        pass  # Always onboarded in local mode

    async def ensure_exists(self, user_id: str, email: str = "local@localhost") -> None:
        cursor = await self._db.execute("SELECT id FROM workspace LIMIT 1")
        if not await cursor.fetchone():
            ws_id = str(uuid.uuid4())
            await self._db.execute(
                "INSERT INTO workspace (id, name, description, user_id) VALUES (?, 'My Wiki', '', ?)",
                (ws_id, user_id),
            )
            await self._db.commit()
