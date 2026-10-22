import asyncio
import contextlib
import importlib.util
import json
import logging
import os
import uuid
from datetime import date
from pathlib import Path
from types import ModuleType

import aiosqlite

from vaultfs.chunker import chunk_text, store_chunks_sqlite

from .base import DuplicateDocumentError, VaultFS
from .highlights import append_reply, find_highlight, parse_highlights_value

logger = logging.getLogger(__name__)

_MIGRATION_RUNNER_PATH = Path(__file__).parent.parent.parent / "api" / "infra" / "db" / "local_migrations.py"


def _load_migration_runner() -> ModuleType:
    """Load the api migration runner lazily by path; the hosted MCP image ships without api/."""
    spec = importlib.util.spec_from_file_location("local_migrations", _MIGRATION_RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

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

No sources ingested yet - add your first source to get started.\
"""


def _fts5_keywords(query: str) -> str:
    """Quote each term so user text is matched as plain keywords (all must match), never parsed as FTS5 syntax."""
    return " ".join('"' + term.replace('"', '""') + '"' for term in query.split())


def _rows_to_dicts(cursor: aiosqlite.Cursor, rows: list[tuple]) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    results = []
    for row in rows:
        d = dict(zip(cols, row, strict=False))
        if "tags" in d and isinstance(d["tags"], str):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
        if "elements" in d and isinstance(d["elements"], str):
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                d["elements"] = json.loads(d["elements"])
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
    def __init__(self, user_id: str):
        self.user_id = user_id


    @staticmethod
    async def init(workspace_path: str) -> None:
        """Initialize the SQLite connection and workspace root for the given path."""
        global _db, _workspace_root
        _workspace_root = Path(workspace_path).resolve()
        db_path = os.path.join(workspace_path, ".llmwiki", "index.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        await asyncio.to_thread(_load_migration_runner().apply_migrations, db_path)
        _db = await aiosqlite.connect(db_path)
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
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
        ws = dict(zip(cols, row, strict=False))
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

    async def get_document_metadata(self, kb_id: str, filename: str, dir_path: str) -> dict | None:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT id, user_id, filename, title, path, tags, version, file_type, "
            "page_count, highlights, metadata, date, created_at, updated_at "
            "FROM documents WHERE filename = ? AND path = ? AND status != 'failed'",
            (filename, dir_path),
        )
        rows = _rows_to_dicts(cursor, await cursor.fetchall())
        return rows[0] if rows else None

    async def find_document_metadata_by_name(self, kb_id: str, name: str) -> dict | None:
        db = self._db_or_raise()
        name_lower = name.lower()
        cursor = await db.execute(
            "SELECT id, user_id, filename, title, path, tags, version, file_type, "
            "page_count, highlights, metadata, date, created_at, updated_at "
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
                "file_type, file_size, status, content, tags, date, metadata, version, document_number) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, 1, ?)",
                (doc_id, self.user_id, filename, title, dir_path, relative_path, source_kind,
                 file_type, len(content.encode("utf-8")), content, json.dumps(tags), date,
                 json.dumps(metadata) if metadata else None, doc_number),
            )
            if file_type in ("md", "txt"):
                await store_chunks_sqlite(db, doc_id, chunk_text(content or ""))
            await db.commit()
        except aiosqlite.IntegrityError as e:
            await db.rollback()
            raise DuplicateDocumentError(dir_path, filename) from e
        except Exception:
            await db.rollback()
            raise
        return {"id": doc_id, "filename": filename, "path": dir_path}

    async def update_document(self, doc_id: str, content: str, tags: list[str] | None = None, title: str | None = None, date: str | None = None, metadata: dict | None = None) -> dict | None:
        db = self._db_or_raise()
        sets = [
            "content = ?",
            "file_size = ?",
            "version = COALESCE(version, 0) + 1",
            "updated_at = datetime('now')",
            "stale_since = NULL",
        ]
        args: list = [content, len(content.encode("utf-8"))]

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
            sets.append("metadata = json_patch(json_remove(COALESCE(metadata, '{}'), '$.description'), ?)")
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

    async def add_highlight_reply(self, doc_id: str, highlight_id: str, reply: dict) -> dict | None:
        db = self._db_or_raise()
        cursor = await db.execute("SELECT highlights FROM documents WHERE id = ?", (doc_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        highlights = parse_highlights_value(row[0])
        target = find_highlight(highlights, highlight_id)
        if target is None:
            return None
        append_reply(target, reply)
        try:
            await db.execute(
                "UPDATE documents SET highlights = ?, "
                "version = COALESCE(version, 0) + 1, updated_at = datetime('now') "
                "WHERE id = ?",
                (json.dumps(highlights), doc_id),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return target

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

    async def list_documents_with_content(
        self,
        kb_id: str,
        path_glob: str | None = None,
        content_limit: int | None = None,
        wiki_content_only: bool = False,
    ) -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT id, filename, title, path, content, tags, file_type, page_count, highlights, metadata, date "
            "FROM documents WHERE status != 'failed' "
            "AND COALESCE(json_extract(metadata, '$.asset'), 0) != 1 "
            "AND (? IS NULL OR (path || filename) GLOB ?) "
            "ORDER BY path, filename",
            (path_glob, path_glob),
        )
        docs = _rows_to_dicts(cursor, await cursor.fetchall())
        chars_left = content_limit
        batch_text_types = {"md", "txt", "csv", "html", "svg", "json", "xml"}
        for doc in docs:
            allowed = (
                (not wiki_content_only or doc["path"].startswith("/wiki/"))
                and (content_limit is None or doc.get("file_type") in batch_text_types)
            )
            content = doc.get("content") or ""
            if not allowed:
                doc["content"] = None
                doc["content_truncated"] = False
                continue
            if chars_left is None:
                doc["content_truncated"] = False
                continue
            take = max(0, min(len(content), chars_left))
            doc["content"] = content[:take] if take else None
            doc["content_truncated"] = take < len(content)
            chars_left -= take
        return docs


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

    async def get_pages_for_batch(self, doc_id: str, max_chars: int) -> list[dict]:
        if max_chars <= 0:
            return []
        rows = await self.get_all_pages(doc_id)
        result: list[dict] = []
        chars_left = max_chars
        for row in rows:
            content = row.get("content") or ""
            take = max(0, min(len(content), chars_left))
            if take <= 0:
                break
            item = dict(row)
            item["content"] = content[:take]
            item["content_truncated"] = take < len(content)
            result.append(item)
            chars_left -= take + 32
        return result

    async def get_page_index(self, doc_id: str) -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT page, elements, "
            "CASE WHEN content = '' THEN 0 ELSE length(content) - length(replace(content, char(10), '')) + 1 END AS row_count "
            "FROM document_pages WHERE document_id = ? ORDER BY page",
            (doc_id,),
        )
        return _rows_to_dicts(cursor, await cursor.fetchall())


    async def search_chunks(
        self, kb_id: str, query: str, limit: int,
        path_filter: str | None = None,
        annotated_only: bool = False,
        scope: str = "all",
    ) -> list[dict]:
        fts_query = _fts5_keywords(query)
        if not fts_query:
            return []
        # chunks_fts indexes only `content`, so scope filters run in Python; over-fetch 3x so narrow scopes still fill `limit`.
        sql_limit = limit if scope == "all" else limit * 3
        rows = await self._select_chunk_matches(fts_query, path_filter, annotated_only, sql_limit)

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


    def write_to_disk(self, dir_path: str, filename: str, content: str, *, exclusive: bool = False) -> bool:
        """Write a document's file; exclusive refuses to replace anything already on disk (raises FileExistsError)."""
        relative = dir_path.lstrip("/") + filename
        if any(part.startswith(".") for part in relative.split("/")):
            return False
        file_path = self._resolve_path(relative)
        if not file_path:
            return False
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("x" if exclusive else "w", encoding="utf-8") as f:
            f.write(content)
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


    async def replace_references(
        self,
        source_id: str,
        kb_id: str,
        edges: list[tuple[str, str, int | None]],
    ) -> None:
        db = self._db_or_raise()
        try:
            await db.execute(
                "DELETE FROM document_references WHERE source_document_id = ?",
                (source_id,),
            )
            if edges:
                await db.executemany(
                    "INSERT OR REPLACE INTO document_references "
                    "(source_document_id, target_document_id, reference_type, page) "
                    "VALUES (?, ?, ?, ?)",
                    [(source_id, target_id, ref_type, page) for target_id, ref_type, page in edges],
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

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

    async def get_reference_edges(self, kb_id: str) -> list[dict]:
        db = self._db_or_raise()
        cursor = await db.execute(
            "SELECT dr.source_document_id AS source_id, dr.target_document_id AS target_id, "
            "       dr.reference_type, dr.page "
            "FROM document_references dr "
            "JOIN documents source ON source.id = dr.source_document_id "
            "WHERE source.status != 'failed'"
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
        # Never overwrite existing local content — a rebuilt index could scaffold over real files.
        if not self._disk_file_exists("/wiki/", "overview.md"):
            await self.create_document(
                kb_id, "overview.md", "Overview", "/wiki/", "md", overview,
                ["overview", "wiki"], date=today,
                metadata={"description": f"Research hub for {name}."},
            )
            self.write_to_disk("/wiki/", "overview.md", overview)

    async def _select_chunk_matches(
        self, fts_query: str, path_filter: str | None, annotated_only: bool, limit: int,
    ) -> list[dict]:
        db = self._db_or_raise()
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
        params: list = [fts_query]
        if annotated_only:
            sql += "AND dc.has_highlight = 1 "
        if path_filter == "wiki":
            sql += "AND d.source_kind = 'wiki' "
        elif path_filter == "sources":
            sql += "AND d.source_kind != 'wiki' "
        sql += "ORDER BY rank LIMIT ?"
        params.append(limit)
        cursor = await db.execute(sql, params)
        return _rows_to_dicts(cursor, await cursor.fetchall())
