"""SQLite + local filesystem implementation of VaultFS."""

import json
import logging
import os
import uuid
from datetime import date
from pathlib import Path

import aiosqlite

from services.chunker import chunk_text, store_chunks_sqlite
from .base import VaultFS, DuplicateDocumentError

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent.parent.parent / "shared" / "sqlite_schema.sql"

_db: aiosqlite.Connection | None = None
_workspace_root: Path | None = None

_OVERVIEW_TEMPLATE = """\
---
title: Overview
description: Research hub for {name}.
date: {date}
tags: [overview, wiki]
---

This wiki tracks research on {name}. No sources have been ingested yet.

## Key Findings

No sources ingested yet - add your first source to get started.

## Recent Updates

No activity yet.\
"""

_LOG_TEMPLATE = """\
Chronological record of ingests, queries, and maintenance passes.

## [{date}] created | Wiki Created
- Initialized wiki: {name}\
"""


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
        if "highlights" in d and isinstance(d["highlights"], str):
            try:
                d["highlights"] = json.loads(d["highlights"])
            except (json.JSONDecodeError, TypeError):
                d["highlights"] = []
        if "metadata" in d and isinstance(d["metadata"], str):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
        results.append(d)
    return results


class SqliteVaultFS(VaultFS):
    """SQLite + local filesystem vault."""

    def __init__(self, user_id: str):
        self.user_id = user_id


    @staticmethod
    async def init(workspace_path: str) -> None:
        """Initialize the SQLite connection and workspace root for the given path."""
        global _db, _workspace_root
        _workspace_root = Path(workspace_path).resolve()
        db_path = os.path.join(workspace_path, ".llmwiki", "index.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        _db = await aiosqlite.connect(db_path)
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        if _SCHEMA_PATH.exists():
            await _db.executescript(_SCHEMA_PATH.read_text(encoding='utf-8'))
            await _db.commit()
        logger.info("SQLite initialized: %s", db_path)

    @staticmethod
    async def close() -> None:
        global _db
        if _db:
            await _db.close()
            _db = None

    @staticmethod
    def _db_or_raise() -> aiosqlite.Connection:
        if _db is None:
            raise RuntimeError("SQLite not initialized — call SqliteVaultFS.init() first")
        return _db


    async def resolve_kb(self, slug: str) -> dict | None:
        db = self._db_or_raise()
        cursor = await db.execute("SELECT id, name, user_id FROM workspace LIMIT 1")
        row = await cursor.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cursor.description]
        ws = dict(zip(cols, row))
        return {"id": ws["id"], "name": ws["name"], "slug": ws["name"]}

    async def list_knowledge_bases(self) -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT w.id, w.name, w.name as slug, w.description, w.created_at, "
            "(SELECT count(*) FROM documents WHERE source_kind != 'wiki' AND status != 'failed') as source_count, "
            "(SELECT count(*) FROM documents WHERE source_kind = 'wiki' AND status != 'failed') as wiki_count "
            "FROM workspace w",
        )
        return _rows_to_dicts(cursor, await cursor.fetchall())

    async def create_knowledge_base(self, name: str, description: str | None = None, kind: str = "wiki") -> dict:
        """Create the local singleton workspace, or return it if already initialized."""
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT id, name, name as slug, description, kind, created_at FROM workspace LIMIT 1",
        )
        row = await cursor.fetchone()
        if row:
            existing = _rows_to_dicts(cursor, [row])[0]
            if kind == "course" and existing["kind"] != "course":
                await db.execute("UPDATE workspace SET kind = ? WHERE id = ?", ("course", existing["id"]))
                await db.commit()
                existing["kind"] = "course"
            existing["already_exists"] = True
            existing["local_singleton"] = True
            return existing

        ws_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO workspace (id, name, description, kind, user_id) VALUES (?, ?, ?, ?, ?)",
            (ws_id, name, description or "", kind, self.user_id),
        )
        await db.commit()

        await self._scaffold_wiki(ws_id, name)
        kb = await self.resolve_kb(name)
        return {
            **(kb or {"id": ws_id, "name": name, "slug": name}),
            "description": description or "",
            "already_exists": False,
            "local_singleton": True,
        }

    async def update_knowledge_base(self, kb_id: str, name: str | None = None, description: str | None = None, kind: str | None = None) -> dict | None:
        db = self._db_or_raise()
        sets: list[str] = []
        args: list = []
        if name is not None:
            sets.append("name = ?")
            args.append(name)
        if description is not None:
            sets.append("description = ?")
            args.append(description)
        if kind is not None:
            sets.append("kind = ?")
            args.append(kind)
        if sets:
            args.append(kb_id)
            await db.execute(f"UPDATE workspace SET {', '.join(sets)} WHERE id = ?", tuple(args))
            await db.commit()
        cursor = await db.execute(
            "SELECT id, name, name as slug, description, kind FROM workspace WHERE id = ?", (kb_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return _rows_to_dicts(cursor, [row])[0]


    async def get_document(self, kb_id: str, filename: str, dir_path: str) -> dict | None:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT id, user_id, filename, title, path, content, tags, version, "
            "file_type, page_count, highlights, metadata, date, created_at, updated_at "
            "FROM documents WHERE filename = ? AND path = ? AND status != 'failed'",
            (filename, dir_path),
        )
        rows = _rows_to_dicts(cursor, await cursor.fetchall())
        return rows[0] if rows else None

    async def find_document_by_name(self, kb_id: str, name: str) -> dict | None:
        db = self._db_or_raise()
        name_lower = name.lower()
        cursor = await db.execute(
            "SELECT id, user_id, filename, title, path, content, tags, version, "
            "file_type, page_count, highlights, metadata, date, created_at, updated_at "
            "FROM documents WHERE (lower(filename) = ? OR lower(title) = ?) AND status != 'failed'",
            (name_lower, name_lower),
        )
        rows = _rows_to_dicts(cursor, await cursor.fetchall())
        return rows[0] if rows else None

    async def create_document(self, kb_id: str, filename: str, title: str, dir_path: str, file_type: str, content: str, tags: list[str], date: str | None = None, metadata: dict | None = None) -> dict:
        db = self._db_or_raise()
        doc_id = str(uuid.uuid4())
        relative_path = (dir_path.rstrip("/") + "/" + filename).lstrip("/")
        source_kind = "wiki" if dir_path.strip("/").startswith("wiki") else "source"

        cursor = await db.execute("SELECT COALESCE(MAX(document_number), 0) + 1 FROM documents")
        row = await cursor.fetchone()
        doc_number = row[0]

        try:
            await db.execute(
                "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
                "file_type, status, content, tags, date, metadata, version, document_number) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, 1, ?)",
                (doc_id, self.user_id, filename, title, dir_path, relative_path, source_kind,
                 file_type, content, json.dumps(tags), date,
                 json.dumps(metadata) if metadata else None, doc_number),
            )
            if file_type in ("md", "txt"):
                await store_chunks_sqlite(db, doc_id, chunk_text(content or ""))
            await db.commit()
        except aiosqlite.IntegrityError:
            await db.rollback()
            raise DuplicateDocumentError(dir_path, filename)
        except Exception:
            await db.rollback()
            raise
        return {"id": doc_id, "filename": filename, "path": dir_path}

    async def update_document(self, doc_id: str, content: str, tags: list[str] | None = None, title: str | None = None, date: str | None = None, metadata: dict | None = None) -> dict | None:
        db = self._db_or_raise()
        sets = ["content = ?", "version = COALESCE(version, 0) + 1", "updated_at = datetime('now')"]
        args: list = [content]

        if title is not None:
            sets.append("title = ?")
            args.append(title)
        if tags is not None:
            sets.append("tags = ?")
            args.append(json.dumps(tags))
        if date is not None:
            sets.append("date = ?")
            args.append(date)
        if metadata is not None:
            sets.append("metadata = ?")
            args.append(json.dumps(metadata))

        args.append(doc_id)
        try:
            await db.execute(
                f"UPDATE documents SET {', '.join(sets)} WHERE id = ?",
                tuple(args),
            )

            cursor = await db.execute(
                "SELECT filename, path, file_type FROM documents WHERE id = ?", (doc_id,),
            )
            row = await cursor.fetchone()
            if row and row[2] in ("md", "txt"):
                await store_chunks_sqlite(db, doc_id, chunk_text(content or ""))

            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return {"id": doc_id, "filename": row[0], "path": row[1]} if row else None

    async def archive_documents(self, doc_ids: list[str]) -> int:
        db = self._db_or_raise()
        if not doc_ids:
            return 0
        placeholders = ",".join("?" for _ in doc_ids)
        cursor = await db.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", doc_ids)
        await db.commit()
        return cursor.rowcount


    async def list_documents(self, kb_id: str) -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT id, filename, title, path, file_type, tags, page_count, date, updated_at "
            "FROM documents WHERE status != 'failed' "
            "AND COALESCE(json_extract(metadata, '$.asset'), 0) != 1 "
            "ORDER BY path, filename",
        )
        return _rows_to_dicts(cursor, await cursor.fetchall())

    async def list_documents_with_content(self, kb_id: str) -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT id, filename, title, path, content, tags, file_type, page_count, highlights, metadata, date "
            "FROM documents WHERE status != 'failed' "
            "AND COALESCE(json_extract(metadata, '$.asset'), 0) != 1 "
            "ORDER BY path, filename",
        )
        return _rows_to_dicts(cursor, await cursor.fetchall())


    async def get_pages(self, doc_id: str, page_nums: list[int]) -> list[dict]:
        db = self._db_or_raise()
        if not page_nums:
            return []
        placeholders = ",".join("?" for _ in page_nums)
        cursor = await db.execute(
            f"SELECT page, content, elements FROM document_pages "
            f"WHERE document_id = ? AND page IN ({placeholders}) ORDER BY page",
            [doc_id] + page_nums,
        )
        return _rows_to_dicts(cursor, await cursor.fetchall())

    async def get_all_pages(self, doc_id: str) -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT page, content FROM document_pages WHERE document_id = ? ORDER BY page",
            (doc_id,),
        )
        return _rows_to_dicts(cursor, await cursor.fetchall())


    async def search_chunks(
        self, kb_id: str, query: str, limit: int,
        path_filter: str | None = None,
        annotated_only: bool = False,
        scope: str = "all",
    ) -> list[dict]:
        db = self._db_or_raise()
        # SQLite's chunks_fts only indexes `content` (which already includes
        # annotations after sync). Scope filtering is a Python-side
        # substring check; to avoid scope filters returning fewer rows than
        # requested, over-fetch by 3x when scope narrows the set, then
        # slice to the requested limit. Acceptable at personal scale;
        # production hosted-mode uses Postgres + PGroonga per-column matches.
        sql_limit = limit if scope == "all" else limit * 3
        sql = (
            "SELECT dc.content, dc.source_content, dc.annotations_text, "
            "dc.has_highlight, dc.page, dc.header_breadcrumb, dc.chunk_index, "
            "d.filename, d.title, d.path, d.file_type, d.tags, "
            "rank as score "
            "FROM document_chunks dc "
            "JOIN chunks_fts fts ON dc.rowid = fts.rowid "
            "JOIN documents d ON dc.document_id = d.id "
            "WHERE chunks_fts MATCH ? AND d.status != 'failed' "
        )
        params: list = [query]
        if annotated_only:
            sql += "AND dc.has_highlight = 1 "
        if path_filter == "wiki":
            sql += "AND d.source_kind = 'wiki' "
        elif path_filter == "sources":
            sql += "AND d.source_kind != 'wiki' "
        sql += "ORDER BY rank LIMIT ?"
        params.append(sql_limit)

        cursor = await db.execute(sql, params)
        rows = _rows_to_dicts(cursor, await cursor.fetchall())

        # Label each row + apply scope filter, then slice to `limit`.
        q_lower = query.lower()
        labeled: list[dict] = []
        for r in rows:
            src = (r.get("source_content") or "").lower()
            ann = (r.get("annotations_text") or "").lower()
            source_hit = q_lower in src
            annotation_hit = bool(ann) and q_lower in ann
            if scope == "annotations" and not annotation_hit:
                continue
            if scope == "source" and not source_hit:
                continue
            r["source_hit"] = source_hit
            r["annotation_hit"] = annotation_hit
            labeled.append(r)
            if len(labeled) >= limit:
                break
        return labeled


    async def load_source_bytes(self, doc: dict) -> bytes | None:
        relative = doc.get("relative_path") or (doc["path"].rstrip("/") + "/" + doc["filename"]).lstrip("/")
        return self._load_local_bytes(relative)

    async def load_image_bytes(self, doc_id: str, image_id: str) -> bytes | None:
        return self._load_local_bytes(f"local/{doc_id}/images/{image_id}")

    async def load_asset_bytes(self, asset_doc_id: str) -> bytes | None:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT id, filename, path, file_type, relative_path FROM documents WHERE id = ? AND status != 'failed'",
            (asset_doc_id,),
        )
        rows = _rows_to_dicts(cursor, await cursor.fetchall())
        if not rows:
            return None
        return await self.load_source_bytes(rows[0])

    def _load_local_bytes(self, key: str) -> bytes | None:
        if _workspace_root is None:
            return None
        cache_path = _workspace_root / ".llmwiki" / "cache" / key
        if cache_path.is_file() and cache_path.is_relative_to(_workspace_root):
            return cache_path.read_bytes()
        root_path = _workspace_root / key
        if root_path.is_file() and root_path.is_relative_to(_workspace_root):
            return root_path.read_bytes()
        return None


    def write_to_disk(self, dir_path: str, filename: str, content: str) -> bool:
        file_path = self._resolve_path(dir_path.lstrip("/") + filename)
        if not file_path:
            return False
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return True

    def delete_from_disk(self, docs: list[dict]) -> None:
        for d in docs:
            relative = d["path"].lstrip("/") + d["filename"]
            file_path = self._resolve_path(relative)
            if file_path and file_path.exists():
                file_path.unlink()

    def _resolve_path(self, relative_path: str) -> Path | None:
        if _workspace_root is None:
            return None
        resolved = (_workspace_root / relative_path).resolve()
        if not resolved.is_relative_to(_workspace_root):
            return None
        return resolved

    def _disk_file_exists(self, dir_path: str, filename: str) -> bool:
        path = self._resolve_path(dir_path.lstrip("/") + filename)
        return path is not None and path.exists()


    async def delete_references(self, source_doc_id: str) -> None:
        db = self._db_or_raise()
        await db.execute("DELETE FROM document_references WHERE source_document_id = ?", (source_doc_id,))
        await db.commit()

    async def upsert_reference(self, source_id: str, target_id: str, kb_id: str, ref_type: str, page: int | None) -> None:
        db = self._db_or_raise()
        try:
            await db.execute(
                "INSERT OR REPLACE INTO document_references "
                "(source_document_id, target_document_id, reference_type, page) "
                "VALUES (?, ?, ?, ?)",
                (source_id, target_id, ref_type, page),
            )
            await db.commit()
        except Exception as e:
            logger.warning("Failed to insert reference %s -> %s: %s", source_id[:8], target_id[:8], e)

    async def propagate_staleness(self, doc_id: str) -> None:
        db = self._db_or_raise()
        await db.execute(
            "UPDATE documents SET stale_since = datetime('now') "
            "WHERE id IN ("
            "  SELECT source_document_id FROM document_references "
            "  WHERE target_document_id = ? AND reference_type = 'links_to'"
            ") AND stale_since IS NULL",
            (doc_id,),
        )
        await db.commit()

    async def get_backlinks(self, doc_id: str) -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT d.path, d.filename, d.title, dr.reference_type "
            "FROM document_references dr "
            "JOIN documents d ON dr.source_document_id = d.id "
            "WHERE dr.target_document_id = ? AND d.status != 'failed' "
            "ORDER BY d.path, d.filename",
            (doc_id,),
        )
        return _rows_to_dicts(cursor, await cursor.fetchall())

    async def get_forward_references(self, doc_id: str) -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT d.id, d.filename, d.title, d.path, dr.reference_type, dr.page "
            "FROM document_references dr "
            "JOIN documents d ON dr.target_document_id = d.id "
            "WHERE dr.source_document_id = ? AND d.status != 'failed' "
            "ORDER BY dr.reference_type, d.path, d.filename",
            (doc_id,),
        )
        return _rows_to_dicts(cursor, await cursor.fetchall())

    async def find_uncited_sources(self, kb_id: str) -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT d.filename, d.title, d.path, d.file_type "
            "FROM documents d "
            "WHERE d.source_kind != 'wiki' AND d.status != 'failed' "
            "  AND d.id NOT IN (SELECT target_document_id FROM document_references WHERE reference_type = 'cites') "
            "ORDER BY d.filename",
        )
        return _rows_to_dicts(cursor, await cursor.fetchall())

    async def find_stale_pages(self, kb_id: str) -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT d.filename, d.title, d.path, d.stale_since "
            "FROM documents d "
            "WHERE d.status != 'failed' AND d.stale_since IS NOT NULL "
            "ORDER BY d.stale_since DESC",
        )
        return _rows_to_dicts(cursor, await cursor.fetchall())


    async def get_workspace(self) -> dict | None:
        """Get the workspace record, if it exists."""
        return await self.resolve_kb("")

    async def ensure_workspace(self, workspace_name: str) -> str:
        """Ensure a workspace row exists. Returns the workspace ID."""
        db = self._db_or_raise()
        cursor = await db.execute("SELECT id FROM workspace LIMIT 1")
        row = await cursor.fetchone()
        if row:
            return row[0]
        ws_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO workspace (id, name, description, user_id) VALUES (?, ?, '', ?)",
            (ws_id, workspace_name, self.user_id),
        )
        await db.commit()
        return ws_id

    async def _scaffold_wiki(self, kb_id: str, name: str) -> None:
        today = date.today().isoformat()
        overview = _OVERVIEW_TEMPLATE.format(name=name, date=today)
        log = _LOG_TEMPLATE.format(name=name, date=today)
        # Never overwrite existing local content — a rebuilt index could scaffold over real files.
        if not self._disk_file_exists("/wiki/", "overview.md"):
            await self.create_document(
                kb_id, "overview.md", "Overview", "/wiki/", "md", overview,
                ["overview", "wiki"], date=today,
                metadata={"description": f"Research hub for {name}."},
            )
            self.write_to_disk("/wiki/", "overview.md", overview)
        if not self._disk_file_exists("/wiki/", "log.md"):
            await self.create_document(
                kb_id, "log.md", "Log", "/wiki/", "md", log, ["log"],
            )
            self.write_to_disk("/wiki/", "log.md", log)
