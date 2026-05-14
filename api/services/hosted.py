"""Hosted service implementations — Postgres + S3."""

from __future__ import annotations

import json
import re
from datetime import datetime

import asyncpg
from fastapi import HTTPException

from config import settings
from services.chunker import chunk_text, store_chunks
from .base import UserService, KBService, DocumentService, ServiceFactory
from .types import parse_frontmatter, title_from_filename, extract_tags


class HostedUserService(UserService):

    def __init__(self, pool, user_id: str):
        self.pool = pool
        self.user_id = user_id

    async def get_profile(self) -> dict:
        row = await self.pool.fetchrow(
            "SELECT id::text, email, display_name, onboarded FROM users WHERE id = $1",
            self.user_id,
        )
        if not row:
            return {"id": "", "email": "", "display_name": None, "onboarded": False}
        return dict(row)

    async def complete_onboarding(self) -> None:
        await self.pool.execute(
            "UPDATE users SET onboarded = true, updated_at = now() WHERE id = $1",
            self.user_id,
        )

    async def get_usage(self) -> dict:
        row = await self.pool.fetchrow(
            "SELECT "
            "  COALESCE(SUM(page_count), 0)::bigint AS total_pages, "
            "  COALESCE(SUM(file_size), 0)::bigint AS total_storage_bytes, "
            "  COUNT(*)::bigint AS document_count "
            "FROM documents WHERE user_id = $1 AND NOT archived",
            self.user_id,
        )

        limits = await self.pool.fetchrow(
            "SELECT page_limit, storage_limit_bytes FROM users WHERE id = $1",
            self.user_id,
        )

        return {
            "total_pages": row["total_pages"],
            "total_storage_bytes": row["total_storage_bytes"],
            "document_count": row["document_count"],
            "max_pages": limits["page_limit"] if limits else 0,
            "max_storage_bytes": limits["storage_limit_bytes"] if limits else settings.QUOTA_MAX_STORAGE_BYTES,
        }


_KB_LIST_QUERY = (
    "SELECT kb.id, kb.user_id, kb.name, kb.slug, kb.description, "
    "kb.created_at, kb.updated_at, "
    "(SELECT COUNT(*) FROM documents d WHERE d.knowledge_base_id = kb.id AND d.path NOT LIKE '/wiki/%%' AND NOT d.archived) AS source_count, "
    "(SELECT COUNT(*) FROM documents d WHERE d.knowledge_base_id = kb.id AND d.path LIKE '/wiki/%%' AND NOT d.archived) AS wiki_page_count "
    "FROM knowledge_bases kb"
)

_OVERVIEW_TEMPLATE = """\
This wiki tracks research on {name}. No sources have been ingested yet.

## Key Findings

No sources ingested yet — add your first source to get started.

## Recent Updates

No activity yet.\
"""

_LOG_TEMPLATE = """\
Chronological record of ingests, queries, and maintenance passes.

## [{date}] created | Wiki Created
- Initialized wiki: {name}\
"""


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug).strip("-")
    return slug or "kb"


class HostedKBService(KBService):

    def __init__(self, pool, user_id: str):
        self.pool = pool
        self.user_id = user_id

    async def list(self) -> list[dict]:
        rows = await self.pool.fetch(
            f"{_KB_LIST_QUERY} WHERE kb.user_id = $1 ORDER BY kb.updated_at DESC",
            self.user_id,
        )
        return [dict(r) for r in rows]

    async def get(self, kb_id: str) -> dict | None:
        row = await self.pool.fetchrow(
            f"{_KB_LIST_QUERY} WHERE kb.id = $1 AND kb.user_id = $2",
            kb_id, self.user_id,
        )
        return dict(row) if row else None

    async def create(self, name: str, description: str | None) -> dict:
        await self._check_capacity()
        slug = await self._unique_slug(name)
        row = await self._insert_kb(name, slug, description)
        await self._scaffold_wiki(row["id"], name)
        return dict(row)

    async def update(self, kb_id: str, name: str | None, description: str | None) -> dict | None:
        if name is not None:
            slug = await self._unique_slug(name)
            row = await self.pool.fetchrow(
                "UPDATE knowledge_bases SET name = $1, slug = $2, description = COALESCE($3, description), updated_at = now() "
                "WHERE id = $4 AND user_id = $5 "
                "RETURNING id, user_id, name, slug, description, created_at, updated_at",
                name, slug, description, kb_id, self.user_id,
            )
        else:
            row = await self.pool.fetchrow(
                "UPDATE knowledge_bases SET description = $1, updated_at = now() "
                "WHERE id = $2 AND user_id = $3 "
                "RETURNING id, user_id, name, slug, description, created_at, updated_at",
                description, kb_id, self.user_id,
            )
        return dict(row) if row else None

    async def _check_capacity(self) -> None:
        user_count = await self.pool.fetchval("SELECT COUNT(DISTINCT id) FROM users")
        if user_count and user_count >= settings.GLOBAL_MAX_USERS:
            raise HTTPException(status_code=503, detail="We've reached our user capacity for now. Please try again later.")

    async def _insert_kb(self, name: str, slug: str, description: str | None) -> dict:
        conn = await self.pool.acquire()
        try:
            async with conn.transaction():
                current_name = name
                for attempt in range(10):
                    try:
                        row = await conn.fetchrow(
                            "INSERT INTO knowledge_bases (user_id, name, slug, description) "
                            "VALUES ($1, $2, $3, $4) "
                            "RETURNING id, user_id, name, slug, description, created_at, updated_at",
                            self.user_id, current_name, slug, description,
                        )
                        return dict(row)
                    except asyncpg.UniqueViolationError:
                        current_name = f"{name} ({attempt + 2})"
                        slug = await self._unique_slug(current_name)
        finally:
            await self.pool.release(conn)
        raise HTTPException(status_code=409, detail="Could not create wiki — too many duplicates.")

    async def _scaffold_wiki(self, kb_id, name: str) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        await self.pool.execute(
            "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, content, tags, version, sort_order) "
            "VALUES ($1, $2, 'overview.md', 'Overview', '/wiki/', 'md', 'ready', $3, $4, 0, -100)",
            kb_id, self.user_id, _OVERVIEW_TEMPLATE.format(name=name), ["overview"],
        )
        await self.pool.execute(
            "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, content, tags, version, sort_order) "
            "VALUES ($1, $2, 'log.md', 'Log', '/wiki/', 'md', 'ready', $3, $4, 0, 100)",
            kb_id, self.user_id, _LOG_TEMPLATE.format(name=name, date=today), ["log"],
        )

    async def delete(self, kb_id: str) -> bool:
        result = await self.pool.execute(
            "DELETE FROM knowledge_bases WHERE id = $1 AND user_id = $2",
            kb_id, self.user_id,
        )
        return result != "DELETE 0"

    async def _unique_slug(self, name: str) -> str:
        base = _slugify(name)
        slug = base
        counter = 2
        while await self.pool.fetchval(
            "SELECT 1 FROM knowledge_bases WHERE slug = $1 AND user_id = $2",
            slug, self.user_id,
        ):
            slug = f"{base}-{counter}"
            counter += 1
        return slug


_DOC_COLUMNS = (
    "id, knowledge_base_id, user_id, filename, path, title, "
    "file_type, status, tags, date, metadata, error_message, "
    "version, document_number, archived, created_at, updated_at"
)


class HostedDocumentService(DocumentService):

    def __init__(self, pool, user_id: str, s3=None):
        self.pool = pool
        self.user_id = user_id
        self.s3 = s3

    async def list(self, kb_id: str, path: str | None = None) -> list[dict]:
        if path:
            rows = await self.pool.fetch(
                f"SELECT {_DOC_COLUMNS} FROM documents "
                "WHERE knowledge_base_id = $1 AND archived = false AND path = $2 AND user_id = $3 ORDER BY filename",
                kb_id, path, self.user_id,
            )
        else:
            rows = await self.pool.fetch(
                f"SELECT {_DOC_COLUMNS} FROM documents "
                "WHERE knowledge_base_id = $1 AND archived = false AND user_id = $2 ORDER BY filename",
                kb_id, self.user_id,
            )
        return [dict(r) for r in rows]

    async def get(self, doc_id: str) -> dict | None:
        row = await self.pool.fetchrow(
            f"SELECT {_DOC_COLUMNS} FROM documents WHERE id = $1 AND user_id = $2",
            doc_id, self.user_id,
        )
        return dict(row) if row else None

    async def get_content(self, doc_id: str) -> dict | None:
        row = await self.pool.fetchrow(
            "SELECT id, content, version FROM documents WHERE id = $1 AND user_id = $2",
            doc_id, self.user_id,
        )
        return dict(row) if row else None

    async def get_url(self, doc_id: str) -> dict | None:
        row = await self.pool.fetchrow(
            "SELECT id, user_id, filename, file_type FROM documents WHERE id = $1 AND user_id = $2",
            doc_id, self.user_id,
        )
        if not row:
            return None
        if not self.s3:
            raise HTTPException(status_code=501, detail="File storage not configured")

        ext = row["filename"].rsplit(".", 1)[-1].lower() if "." in row["filename"] else row["file_type"]
        if ext in {"pptx", "ppt", "docx", "doc"}:
            s3_key = f"{row['user_id']}/{row['id']}/converted.pdf"
        elif ext in {"html", "htm"}:
            s3_key = f"{row['user_id']}/{row['id']}/tagged.html"
        else:
            s3_key = f"{row['user_id']}/{row['id']}/source.{ext}"
        url = await self.s3.generate_presigned_get(s3_key)
        return {"url": url}

    async def create_note(self, kb_id: str, filename: str, path: str, content: str) -> dict:
        await self._validate_kb(kb_id)

        meta = parse_frontmatter(content)
        title = meta.get("title", "").strip() or title_from_filename(filename)
        tags = [str(t) for t in meta.get("tags", []) if t is not None] if isinstance(meta.get("tags"), list) else []

        existing = await self.pool.fetchval(
            "SELECT id FROM documents WHERE knowledge_base_id = $1 AND user_id = $2 "
            "AND filename = $3 AND path = $4 AND NOT archived",
            kb_id, self.user_id, filename, path,
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"'{filename}' already exists at {path}")

        conn = await self.pool.acquire()
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"INSERT INTO documents (knowledge_base_id, user_id, filename, path, title, "
                    f"file_type, status, content, tags) "
                    f"VALUES ($1, $2, $3, $4, $5, 'md', 'ready', $6, $7) "
                    f"RETURNING {_DOC_COLUMNS}",
                    kb_id, self.user_id, filename, path, title, content, tags,
                )
                if content:
                    chunks = chunk_text(content)
                    await store_chunks(conn, str(row["id"]), self.user_id, str(kb_id), chunks)
        finally:
            await self.pool.release(conn)
        return dict(row)

    async def create_web_clip(
        self, kb_id: str, url: str, title: str, html: str,
        highlights: list[dict] | None = None,
    ) -> dict:
        from html_parser import Parser

        await self._validate_kb(kb_id)

        parser = Parser(html, url=url, content_only=True)
        result = parser.parse(highlights=highlights or [])
        markdown = result.content

        filename = self._slugify_filename(title, "html")
        filename = await self._dedupe_filename(kb_id, "/webclipper/", filename, "html")

        enriched = self._merge_text_anchors(highlights or [], result.highlights)
        highlights_json = json.dumps(enriched)

        conn = await self.pool.acquire()
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"INSERT INTO documents (knowledge_base_id, user_id, filename, path, title, "
                    f"file_type, status, content, tags, metadata, highlights) "
                    f"VALUES ($1, $2, $3, '/webclipper/', $4, 'html', 'ready', $5, $6, $7, $8::jsonb) "
                    f"RETURNING {_DOC_COLUMNS}",
                    kb_id, self.user_id, filename, title, markdown,
                    [], json.dumps({"source_url": url}), highlights_json,
                )
                if markdown:
                    chunks = chunk_text(markdown)
                    await store_chunks(conn, str(row["id"]), self.user_id, str(kb_id), chunks)
        finally:
            await self.pool.release(conn)

        if self.s3:
            await self._store_tagged_html(str(row["id"]), parser)

        return dict(row)

    @staticmethod
    def _merge_text_anchors(payloads: list[dict], mapped) -> list[dict]:
        """Merge parser-computed text_anchors back onto the original highlight
        payloads. Preserves all incoming fields (id, type, anchor, comment,
        color, createdAt) and adds `textAnchor` when located. Highlights that
        couldn't be located still persist — the wiki viewer can fall back to
        text search at render time."""
        anchor_by_index = {i: m.text_anchor for i, m in enumerate(mapped)}
        merged: list[dict] = []
        for i, h in enumerate(payloads):
            if not isinstance(h, dict):
                continue
            entry = dict(h)
            ta = anchor_by_index.get(i)
            if ta is not None:
                entry["textAnchor"] = {
                    "textStart": ta.text_start,
                    "textEnd": ta.text_end,
                    "textContent": ta.text_content,
                    "prefix": ta.prefix,
                    "suffix": ta.suffix,
                }
            merged.append(entry)
        return merged

    async def get_by_source_url(self, url: str) -> dict | None:
        row = await self.pool.fetchrow(
            "SELECT id::text, knowledge_base_id::text, title, path, filename, "
            "version, highlights "
            "FROM documents "
            "WHERE user_id = $1 AND NOT archived "
            "AND metadata->>'source_url' = $2 "
            "ORDER BY updated_at DESC LIMIT 1",
            self.user_id, url,
        )
        if not row:
            return None
        result = dict(row)
        result["highlights"] = self._parse_highlights(result.get("highlights"))
        return result

    async def get_highlights(self, doc_id: str) -> dict | None:
        row = await self.pool.fetchrow(
            "SELECT id::text, version, highlights FROM documents "
            "WHERE id = $1 AND user_id = $2",
            doc_id, self.user_id,
        )
        if not row:
            return None
        result = dict(row)
        result["highlights"] = self._parse_highlights(result.get("highlights"))
        return result

    async def replace_highlights(
        self, doc_id: str, highlights: list[dict],
        expected_version: int | None = None,
    ) -> dict | None:
        payload = json.dumps(highlights)
        if expected_version is None:
            row = await self.pool.fetchrow(
                "UPDATE documents SET highlights = $1::jsonb, "
                "version = version + 1, updated_at = now() "
                "WHERE id = $2 AND user_id = $3 "
                "RETURNING id::text, version, highlights",
                payload, doc_id, self.user_id,
            )
        else:
            row = await self.pool.fetchrow(
                "UPDATE documents SET highlights = $1::jsonb, "
                "version = version + 1, updated_at = now() "
                "WHERE id = $2 AND user_id = $3 AND version = $4 "
                "RETURNING id::text, version, highlights",
                payload, doc_id, self.user_id, expected_version,
            )
            if not row:
                # Check whether the doc exists at all (404) vs just stale (409)
                exists = await self.pool.fetchval(
                    "SELECT 1 FROM documents WHERE id = $1 AND user_id = $2",
                    doc_id, self.user_id,
                )
                if exists:
                    return {"conflict": True}
                return None
        result = dict(row)
        result["highlights"] = self._parse_highlights(result.get("highlights"))
        return result

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

    async def upsert_highlight(
        self, doc_id: str, highlight: dict,
        expected_version: int | None = None,
    ) -> dict | None:
        """Atomic single-entry upsert by `id`. Idempotent: re-posting the same
        highlight is safe; the client may use it as a retry-friendly op."""
        new_id = highlight.get("id")
        if not new_id:
            return None

        conn = await self.pool.acquire()
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT version, highlights FROM documents "
                    "WHERE id = $1 AND user_id = $2 FOR UPDATE",
                    doc_id, self.user_id,
                )
                if not row:
                    return None
                if expected_version is not None and row["version"] != expected_version:
                    return {"conflict": True}

                current = self._parse_highlights(row["highlights"])
                # Replace existing entry with the same id, else append.
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
                        raise HTTPException(
                            status_code=413,
                            detail="Highlight limit reached (500 per document)",
                        )
                    next_list.append(highlight)

                updated = await conn.fetchrow(
                    "UPDATE documents SET highlights = $1::jsonb, "
                    "version = version + 1, updated_at = now() "
                    "WHERE id = $2 AND user_id = $3 "
                    "RETURNING id::text, version, highlights",
                    json.dumps(next_list), doc_id, self.user_id,
                )
        finally:
            await self.pool.release(conn)

        if not updated:
            return None
        result = dict(updated)
        result["highlights"] = self._parse_highlights(result.get("highlights"))
        return result

    async def delete_highlight(
        self, doc_id: str, highlight_id: str,
        expected_version: int | None = None,
    ) -> dict | None:
        """Atomic single-entry delete by `id`. Idempotent: deleting an absent
        id is a no-op (returns the current state with version unchanged)."""
        conn = await self.pool.acquire()
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT version, highlights FROM documents "
                    "WHERE id = $1 AND user_id = $2 FOR UPDATE",
                    doc_id, self.user_id,
                )
                if not row:
                    return None
                if expected_version is not None and row["version"] != expected_version:
                    return {"conflict": True}

                current = self._parse_highlights(row["highlights"])
                next_list = [
                    h for h in current
                    if not (isinstance(h, dict) and h.get("id") == highlight_id)
                ]
                if len(next_list) == len(current):
                    # No-op: nothing to delete. Return current state without
                    # bumping the version (idempotent semantics).
                    return {
                        "id": doc_id,
                        "version": row["version"],
                        "highlights": current,
                    }

                updated = await conn.fetchrow(
                    "UPDATE documents SET highlights = $1::jsonb, "
                    "version = version + 1, updated_at = now() "
                    "WHERE id = $2 AND user_id = $3 "
                    "RETURNING id::text, version, highlights",
                    json.dumps(next_list), doc_id, self.user_id,
                )
        finally:
            await self.pool.release(conn)

        if not updated:
            return None
        result = dict(updated)
        result["highlights"] = self._parse_highlights(result.get("highlights"))
        return result

    async def _validate_kb(self, kb_id: str) -> None:
        kb = await self.pool.fetchval(
            "SELECT id FROM knowledge_bases WHERE id = $1 AND user_id = $2",
            kb_id, self.user_id,
        )
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

    @staticmethod
    def _slugify_filename(title: str, ext: str) -> str:
        slug = re.sub(r"[^\w\s\-.]", "", title.lower().replace(" ", "-"))[:80]
        return f"{slug}.{ext}"

    async def _dedupe_filename(self, kb_id: str, path: str, filename: str, ext: str) -> str:
        exists = await self.pool.fetchval(
            "SELECT id FROM documents WHERE knowledge_base_id = $1 AND user_id = $2 "
            "AND filename = $3 AND path = $4 AND NOT archived",
            kb_id, self.user_id, filename, path,
        )
        if not exists:
            return filename
        base = filename.rsplit(".", 1)[0]
        for i in range(2, 100):
            candidate = f"{base}-{i}.{ext}"
            dup = await self.pool.fetchval(
                "SELECT id FROM documents WHERE knowledge_base_id = $1 AND user_id = $2 "
                "AND filename = $3 AND path = $4 AND NOT archived",
                kb_id, self.user_id, candidate, path,
            )
            if not dup:
                return candidate
        return filename

    async def _store_tagged_html(self, doc_id: str, parser) -> None:
        try:
            await parser.embed_images()
            tagged = parser.html()
            await self.s3.upload_bytes(
                f"{self.user_id}/{doc_id}/tagged.html",
                tagged.encode("utf-8"),
                "text/html",
            )
        except Exception:
            pass

    async def update_content(self, doc_id: str, content: str) -> dict | None:
        row = await self.pool.fetchrow(
            "UPDATE documents SET content = $1, version = version + 1, updated_at = now() "
            "WHERE id = $2 AND user_id = $3 RETURNING id, content, version",
            content, doc_id, self.user_id,
        )
        if not row:
            return None

        kb_id = await self.pool.fetchval(
            "SELECT knowledge_base_id::text FROM documents WHERE id = $1 AND user_id = $2",
            doc_id, self.user_id,
        )
        if kb_id:
            chunks = chunk_text(content) if content else []
            await store_chunks(self.pool, str(doc_id), self.user_id, kb_id, chunks)

        return dict(row)

    async def update_metadata(self, doc_id: str, fields: dict) -> dict | None:
        import json as _json

        sets = []
        params = []
        idx = 1
        for key in ("filename", "path", "title", "date"):
            if key in fields:
                sets.append(f"{key} = ${idx}")
                params.append(fields[key])
                idx += 1
        if "knowledge_base_id" in fields:
            sets.append(f"knowledge_base_id = ${idx}")
            params.append(fields["knowledge_base_id"])
            idx += 1
        if "tags" in fields:
            sets.append(f"tags = ${idx}")
            params.append(fields["tags"])
            idx += 1
        if "metadata" in fields:
            sets.append(f"metadata = ${idx}")
            params.append(_json.dumps(fields["metadata"]))
            idx += 1

        if not sets:
            return None

        sets.append("updated_at = now()")
        params.extend([doc_id, self.user_id])
        sql = (
            f"UPDATE documents SET {', '.join(sets)} "
            f"WHERE id = ${idx} AND user_id = ${idx + 1} "
            f"RETURNING {_DOC_COLUMNS}"
        )

        # If we're moving the doc to a different KB, run the doc update +
        # chunk cascade + reference prune as one transaction. Otherwise,
        # one-shot update is fine.
        if "knowledge_base_id" in fields:
            new_kb_id = fields["knowledge_base_id"]

            # `documents` has UNIQUE(knowledge_base_id, document_number) and
            # the assignment trigger only fires on INSERT. On a move we have
            # to compute a fresh document_number for the target KB and bake
            # it into the UPDATE — otherwise moving doc #N into a KB that
            # already has #N raises a unique-violation.
            #
            # We need to inject `document_number = $X` into `sets` and an
            # advisory lock around the SELECT MAX/UPDATE pair. Easiest: build
            # a fresh SQL string that adds the document_number assignment.

            conn = await self.pool.acquire()
            try:
                async with conn.transaction():
                    # Verify ownership of the target KB INSIDE the
                    # transaction with FOR SHARE so a concurrent transfer
                    # can't flip ownership between check and update. The
                    # FOR SHARE lock blocks competing UPDATE/DELETE on the
                    # KB row until we commit.
                    owns_target = await conn.fetchval(
                        "SELECT 1 FROM knowledge_bases "
                        "WHERE id = $1 AND user_id = $2 FOR SHARE",
                        new_kb_id, self.user_id,
                    )
                    if not owns_target:
                        raise HTTPException(
                            status_code=404,
                            detail="Target knowledge base not found",
                        )
                    # Serialize concurrent moves into the same target KB so
                    # two simultaneous moves can't pick the same number.
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtext($1::text))",
                        new_kb_id,
                    )
                    next_number = await conn.fetchval(
                        "SELECT COALESCE(MAX(document_number), 0) + 1 "
                        "FROM documents WHERE knowledge_base_id = $1",
                        new_kb_id,
                    )

                    # Inject document_number into the UPDATE before the
                    # WHERE/RETURNING tail. The base SQL has the form:
                    #   UPDATE documents SET <sets>, updated_at = now()
                    #   WHERE id = $N AND user_id = $N+1
                    #   RETURNING ...
                    # We add ", document_number = $K" with a new param.
                    move_params = list(params)
                    move_params.insert(idx - 1, next_number)
                    # The `idx`/`idx+1` tail params are doc_id and user_id;
                    # bump them by one because we've inserted a param before.
                    new_idx = idx + 1
                    move_sets = list(sets)
                    # `sets` already had updated_at appended; insert the
                    # document_number assignment before it.
                    insert_at = len(move_sets) - 1
                    move_sets.insert(insert_at, f"document_number = ${idx}")
                    move_sql = (
                        f"UPDATE documents SET {', '.join(move_sets)} "
                        f"WHERE id = ${new_idx} AND user_id = ${new_idx + 1} "
                        f"RETURNING {_DOC_COLUMNS}"
                    )

                    row = await conn.fetchrow(move_sql, *move_params)
                    if not row:
                        return None
                    # Chunks carry their own kb_id for FTS path; cascade.
                    await conn.execute(
                        "UPDATE document_chunks SET knowledge_base_id = $1 "
                        "WHERE document_id = $2",
                        new_kb_id, doc_id,
                    )
                    # References are KB-scoped. Drop edges touching the
                    # moved doc; the graph rebuilder will re-derive them in
                    # the new KB on next /graph/rebuild call.
                    await conn.execute(
                        "DELETE FROM document_references "
                        "WHERE source_document_id = $1 OR target_document_id = $1",
                        doc_id,
                    )
            finally:
                await self.pool.release(conn)
            return dict(row)

        row = await self.pool.fetchrow(sql, *params)
        return dict(row) if row else None

    async def delete(self, doc_id: str) -> bool:
        # Wiki pages are archived to preserve slugs and cross-references;
        # source documents are hard-deleted so the filename can be re-used.
        row = await self.pool.fetchrow(
            "SELECT path FROM documents WHERE id = $1 AND user_id = $2",
            doc_id, self.user_id,
        )
        if not row:
            return False
        if (row["path"] or "").startswith("/wiki/"):
            result = await self.pool.execute(
                "UPDATE documents SET archived = true, updated_at = now() WHERE id = $1 AND user_id = $2",
                doc_id, self.user_id,
            )
            return result != "UPDATE 0"
        await self.pool.execute("DELETE FROM document_pages WHERE document_id = $1", doc_id)
        await self.pool.execute("DELETE FROM document_chunks WHERE document_id = $1", doc_id)
        await self.pool.execute("DELETE FROM document_references WHERE source_document_id = $1 OR target_document_id = $1", doc_id)
        result = await self.pool.execute(
            "DELETE FROM documents WHERE id = $1 AND user_id = $2",
            doc_id, self.user_id,
        )
        return result != "DELETE 0"

    async def bulk_delete(self, doc_ids: list[str]) -> int:
        if not doc_ids:
            return 0
        rows = await self.pool.fetch(
            "SELECT id::text, path FROM documents WHERE id = ANY($1::uuid[]) AND user_id = $2",
            doc_ids, self.user_id,
        )
        wiki_ids = [r["id"] for r in rows if (r["path"] or "").startswith("/wiki/")]
        source_ids = [r["id"] for r in rows if not (r["path"] or "").startswith("/wiki/")]
        count = 0
        if wiki_ids:
            result = await self.pool.execute(
                "UPDATE documents SET archived = true, updated_at = now() WHERE id = ANY($1::uuid[]) AND user_id = $2",
                wiki_ids, self.user_id,
            )
            count += int(result.split()[-1]) if result else 0
        if source_ids:
            await self.pool.execute("DELETE FROM document_pages WHERE document_id = ANY($1::uuid[])", source_ids)
            await self.pool.execute("DELETE FROM document_chunks WHERE document_id = ANY($1::uuid[])", source_ids)
            await self.pool.execute("DELETE FROM document_references WHERE source_document_id = ANY($1::uuid[]) OR target_document_id = ANY($1::uuid[])", source_ids)
            result = await self.pool.execute(
                "DELETE FROM documents WHERE id = ANY($1::uuid[]) AND user_id = $2",
                source_ids, self.user_id,
            )
            count += int(result.split()[-1]) if result else 0
        return count


class HostedServiceFactory(ServiceFactory):

    def __init__(self, pool, s3=None, ocr=None):
        self.pool = pool
        self.s3 = s3
        self.ocr = ocr

    def user_service(self, user_id: str) -> HostedUserService:
        return HostedUserService(self.pool, user_id)

    def kb_service(self, user_id: str) -> "HostedKBService":
        return HostedKBService(self.pool, user_id)

    def document_service(self, user_id: str) -> HostedDocumentService:
        return HostedDocumentService(self.pool, user_id, self.s3)
