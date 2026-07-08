"""SQLite repository implementations for local mode.

Single-user, no RLS. FTS5 for full-text search.
All queries use native SQLite syntax — no translation layer.
"""

import asyncio
import functools
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "sqlite_schema.sql"

_DOC_COLUMNS = (
    "id, user_id, filename, title, path, relative_path, source_kind, "
    "file_type, file_size, document_number, status, page_count, "
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


def rows_to_dicts(cursor: aiosqlite.Cursor, rows: list[tuple]) -> list[dict]:
    """Map a fetched result set to dicts, decoding JSON columns like _row_to_dict."""
    return [_row_to_dict(cursor, r) for r in rows]


# Local-mode requests share one aiosqlite connection, so a committing write
# in one request could otherwise flush another's open transaction. This lock
# serializes write spans; reads don't take it.
_write_lock = asyncio.Lock()


def _serialized(method):
    """Hold the write lock for the full span of a committing repo method.

    Rolls back on failure so a crashed write never leaves an open transaction
    for the next writer to commit.
    """
    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        async with _write_lock:
            try:
                return await method(self, *args, **kwargs)
            except Exception:
                try:
                    await self._db.rollback()
                except Exception:
                    pass
                raise
    return wrapper


@asynccontextmanager
async def serialized_write():
    """Hold the local write lock around a multi-statement write outside the repos."""
    async with _write_lock:
        yield


async def create_pool(db_path: str, init_schema: bool = True) -> aiosqlite.Connection:
    db = await aiosqlite.connect(db_path)
    db.row_factory = None
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA busy_timeout=5000")
    if init_schema:
        schema = _SCHEMA_PATH.read_text(encoding='utf-8')
        await db.executescript(schema)
        # No migration runner: add workspace.kind to pre-existing DBs.
        cur = await db.execute("PRAGMA table_info(workspace)")
        if "kind" not in {row[1] for row in await cur.fetchall()}:
            await db.execute("ALTER TABLE workspace ADD COLUMN kind TEXT NOT NULL DEFAULT 'wiki'")
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

    @_serialized
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

    @_serialized
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

    @_serialized
    async def update_metadata(self, doc_id: str, user_id: str, **fields) -> dict | None:
        updates = []
        params = []
        for key, value in fields.items():
            if key == "tags":
                updates.append("tags = ?")
                params.append(json.dumps(value))
            elif key == "metadata":
                updates.append("metadata = json_patch(COALESCE(metadata, '{}'), ?)")
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

    @_serialized
    async def archive(self, doc_id: str, user_id: str) -> bool:
        await self._db.execute("DELETE FROM document_pages WHERE document_id = ?", (doc_id,))
        await self._db.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))
        cursor = await self._db.execute(
            "DELETE FROM documents WHERE id = ?", (doc_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    @_serialized
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

    async def get_by_source_url(self, url: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT id, knowledge_base_id, title, path, filename, version, highlights "
            "FROM documents "
            "WHERE status != 'failed' "
            "AND json_extract(metadata, '$.source_url') = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (url,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        result = _row_to_dict(cursor, row)
        result["highlights"] = self._parse_highlights(result.get("highlights"))
        return result

    async def get_highlights(self, doc_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT id, version, highlights FROM documents WHERE id = ?", (doc_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        result = _row_to_dict(cursor, row)
        result["highlights"] = self._parse_highlights(result.get("highlights"))
        return result

    @_serialized
    async def replace_highlights(
        self, doc_id: str, user_id: str, highlights: list[dict],
        expected_version: int | None = None,
    ) -> dict | None:
        # BEGIN IMMEDIATE grabs a RESERVED lock up front so concurrent
        # writers wait instead of stale-reading the highlights JSON below.
        # Without this, two interleaved upserts could clobber each other.
        await self._db.execute("BEGIN IMMEDIATE")
        try:
            check = await self._db.execute(
                "SELECT version, highlights FROM documents WHERE id = ?", (doc_id,),
            )
            existing = await check.fetchone()
            if not existing:
                await self._db.rollback()
                return None
            if expected_version is not None and existing[0] != expected_version:
                await self._db.rollback()
                return {"conflict": True}
            old_highlights = self._parse_highlights(existing[1])

            payload = json.dumps(highlights)
            cursor = await self._db.execute(
                "UPDATE documents SET highlights = ?, "
                "version = version + 1, updated_at = datetime('now') "
                "WHERE id = ? "
                "RETURNING id, version, highlights",
                (payload, doc_id),
            )
            row = await cursor.fetchone()
            if not row:
                await self._db.rollback()
                return None
            result = _row_to_dict(cursor, row)
            new_highlights = self._parse_highlights(result.get("highlights"))
            result["highlights"] = new_highlights
            await self._recompute_chunks_for_doc(doc_id, old_highlights, new_highlights)
            await self._db.commit()
            return result
        except Exception:
            try:
                await self._db.rollback()
            except Exception:
                pass
            raise

    @_serialized
    async def upsert_highlight(
        self, doc_id: str, user_id: str, highlight: dict,
        expected_version: int | None = None,
    ) -> dict | None:
        """Atomic single-entry upsert by id."""
        new_id = highlight.get("id")
        if not new_id:
            return None

        await self._db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await self._db.execute(
                "SELECT version, highlights FROM documents WHERE id = ?", (doc_id,),
            )
            row = await cursor.fetchone()
            if not row:
                await self._db.rollback()
                return None
            version, highlights_raw = row[0], row[1]
            if expected_version is not None and version != expected_version:
                await self._db.rollback()
                return {"conflict": True}

            current = self._parse_highlights(highlights_raw)
            replaced = False
            next_list: list[dict] = []
            for h in current:
                if isinstance(h, dict) and h.get("id") == new_id:
                    next_list.append(highlight)
                    replaced = True
                else:
                    next_list.append(h)
            if not replaced:
                if len(current) >= 500:
                    await self._db.rollback()
                    return {"limit_exceeded": True}
                next_list.append(highlight)

            payload = json.dumps(next_list)
            cursor = await self._db.execute(
                "UPDATE documents SET highlights = ?, "
                "version = version + 1, updated_at = datetime('now') "
                "WHERE id = ? "
                "RETURNING id, version, highlights",
                (payload, doc_id),
            )
            result_row = await cursor.fetchone()
            if not result_row:
                await self._db.rollback()
                return None
            result = _row_to_dict(cursor, result_row)
            new_highlights = self._parse_highlights(result.get("highlights"))
            result["highlights"] = new_highlights
            await self._recompute_chunks_for_doc(doc_id, current, new_highlights)
            await self._db.commit()
            return result
        except Exception:
            try:
                await self._db.rollback()
            except Exception:
                pass
            raise

    @_serialized
    async def delete_highlight(
        self, doc_id: str, user_id: str, highlight_id: str,
        expected_version: int | None = None,
    ) -> dict | None:
        await self._db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await self._db.execute(
                "SELECT version, highlights FROM documents WHERE id = ?", (doc_id,),
            )
            row = await cursor.fetchone()
            if not row:
                await self._db.rollback()
                return None
            version, highlights_raw = row[0], row[1]
            if expected_version is not None and version != expected_version:
                await self._db.rollback()
                return {"conflict": True}

            current = self._parse_highlights(highlights_raw)
            next_list = [
                h for h in current
                if not (isinstance(h, dict) and h.get("id") == highlight_id)
            ]
            if len(next_list) == len(current):
                # Idempotent no-op: nothing to write, release the lock cleanly.
                await self._db.rollback()
                return {"id": doc_id, "version": version, "highlights": current}

            payload = json.dumps(next_list)
            cursor = await self._db.execute(
                "UPDATE documents SET highlights = ?, "
                "version = version + 1, updated_at = datetime('now') "
                "WHERE id = ? "
                "RETURNING id, version, highlights",
                (payload, doc_id),
            )
            result_row = await cursor.fetchone()
            if not result_row:
                await self._db.rollback()
                return None
            result = _row_to_dict(cursor, result_row)
            new_highlights = self._parse_highlights(result.get("highlights"))
            result["highlights"] = new_highlights
            await self._recompute_chunks_for_doc(doc_id, current, new_highlights)
            await self._db.commit()
            return result
        except Exception:
            try:
                await self._db.rollback()
            except Exception:
                pass
            raise

    async def _recompute_chunks_for_doc(
        self, doc_id: str,
        old_highlights: list[dict], new_highlights: list[dict],
    ) -> None:
        """Update affected chunks' annotations_text + has_highlight + content
        in the same implicit txn as the highlights write.

        Affected = (chunks touched by old) ∪ (chunks touched by new). The
        union covers the deletion case where a highlight's prior chunk would
        otherwise keep its stale annotation.
        """
        from services.highlight_chunks import (
            ChunkRecord, all_affected_chunks, iter_chunks_with_annotations,
        )

        cursor = await self._db.execute(
            "SELECT id, chunk_index, source_content, page, start_char "
            "FROM document_chunks WHERE document_id = ? "
            "ORDER BY chunk_index",
            (doc_id,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return
        chunks = [
            ChunkRecord(
                id=r[0], chunk_index=r[1],
                source_content=r[2] or "",
                page=r[3], start_char=r[4],
            )
            for r in rows
        ]
        affected = all_affected_chunks(chunks, old_highlights, new_highlights)
        if not affected:
            return

        for chunk, anno_text, has_hl, new_content in iter_chunks_with_annotations(
            chunks, affected, new_highlights,
        ):
            await self._db.execute(
                "UPDATE document_chunks "
                "SET annotations_text = ?, has_highlight = ?, content = ? "
                "WHERE id = ?",
                (anno_text, 1 if has_hl else 0, new_content, chunk.id),
            )

    @_serialized
    async def set_metadata_field(self, doc_id: str, key: str, value) -> None:
        cursor = await self._db.execute(
            "SELECT metadata FROM documents WHERE id = ?", (doc_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return
        meta = {}
        if row[0]:
            try:
                meta = json.loads(row[0]) or {}
            except (json.JSONDecodeError, TypeError):
                meta = {}
        meta[key] = value
        await self._db.execute(
            "UPDATE documents SET metadata = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(meta), doc_id),
        )
        await self._db.commit()

    @staticmethod
    def _parse_highlights(value):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []

    @_serialized
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

    @_serialized
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

    @_serialized
    async def create_asset(
        self, doc_id: str, user_id: str, filename: str, path: str,
        title: str, file_type: str, file_size: int, metadata: dict,
    ) -> dict | None:
        relative_path = (path.rstrip("/") + "/" + filename).lstrip("/")

        cursor = await self._db.execute(
            "SELECT COALESCE(MAX(document_number), 0) + 1 FROM documents",
        )
        row = await cursor.fetchone()
        doc_number = row[0]

        await self._db.execute(
            "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
            "file_type, file_size, status, content, tags, version, document_number, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, 'asset', ?, ?, 'ready', NULL, '[]', 0, ?, ?)",
            (doc_id, user_id, filename, title, path, relative_path, file_type,
             file_size, doc_number, json.dumps(metadata)),
        )
        await self._db.commit()
        return await self.get(doc_id)


class SQLiteKBRepository:
    """Singleton KB compatibility layer. One workspace = one KB."""

    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    async def list_all(self, user_id: str) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT w.id, w.user_id, w.name, w.name as slug, w.description, "
            "w.created_at, w.created_at as updated_at, "
            "(SELECT count(*) FROM documents WHERE source_kind = 'source' AND status != 'failed') as source_count, "
            "(SELECT count(*) FROM documents WHERE source_kind = 'wiki' AND status != 'failed') as wiki_page_count "
            "FROM workspace w",
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(cursor, r) for r in rows]

    async def get(self, kb_id: str, user_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT w.id, w.user_id, w.name, w.name as slug, w.description, "
            "w.created_at, w.created_at as updated_at, "
            "(SELECT count(*) FROM documents WHERE source_kind = 'source' AND status != 'failed') as source_count, "
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

    @_serialized
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

    @_serialized
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

    @_serialized
    async def store(self, doc_id: str, user_id: str, kb_id: str, chunks: list) -> None:
        await self._db.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))
        if not chunks:
            await self._db.commit()
            return

        # source_content seeds the immutable raw text; content starts
        # identical and only diverges if highlight CRUD writes annotations
        # into the chunk later. See api/services/highlight_chunks.
        await self._db.executemany(
            "INSERT INTO document_chunks "
            "(id, document_id, chunk_index, content, source_content, page, start_char, token_count, header_breadcrumb) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (str(uuid.uuid4()), doc_id, c.index, c.content, c.content, c.page,
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

    @_serialized
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

    @_serialized
    async def ensure_exists(self, user_id: str, email: str = "local@localhost") -> None:
        cursor = await self._db.execute("SELECT id FROM workspace LIMIT 1")
        if not await cursor.fetchone():
            ws_id = str(uuid.uuid4())
            await self._db.execute(
                "INSERT INTO workspace (id, name, description, user_id) VALUES (?, 'My Wiki', '', ?)",
                (ws_id, user_id),
            )
            await self._db.commit()
