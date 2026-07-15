"""Hosted service implementations — Postgres + S3."""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

import asyncpg
from config import settings
from fastapi import HTTPException
from services.chunker import chunk_text, store_chunks
from services.webclip_assets import materialize_webclip_assets

from .base import DocumentService, KBService, PublicWikiService, ServiceFactory, UserService
from .highlight_merge import merge_highlights_by_id, preserve_replies
from .parsers import parse_frontmatter, title_from_filename
from .types import MAX_TEXT_CONTENT_BYTES

logger = logging.getLogger(__name__)


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
    "SELECT kb.id, kb.user_id, kb.name, kb.slug, kb.description, kb.kind, "
    "kb.created_at, kb.updated_at, "
    "(SELECT COUNT(*) FROM documents d WHERE d.knowledge_base_id = kb.id AND d.path NOT LIKE '/wiki/%' AND NOT d.archived AND COALESCE((d.metadata->>'hidden')::boolean, false) = false) AS source_count, "
    "(SELECT COUNT(*) FROM documents d WHERE d.knowledge_base_id = kb.id AND d.path LIKE '/wiki/%' AND NOT d.archived) AS wiki_page_count "
    "FROM knowledge_bases kb"
)

_OVERVIEW_TEMPLATE = """\
---
title: Overview
description: Research hub for {name}.
date: {date}
tags: [overview, wiki]
---

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

    def __init__(self, pool, user_id: str, s3=None):
        self.pool = pool
        self.user_id = user_id
        self.s3 = s3

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

    async def create(self, name: str, description: str | None, kind: str | None = None) -> dict:
        await self._check_capacity()
        slug = await self._unique_slug(name)
        row = await self._insert_kb(name, slug, description, kind or "wiki")
        await self._scaffold_wiki(row["id"], name)
        return dict(row)

    async def update(self, kb_id: str, name: str | None, description: str | None, kind: str | None = None) -> dict | None:
        if name is not None:
            slug = await self._unique_slug(name)
            row = await self.pool.fetchrow(
                "UPDATE knowledge_bases SET name = $1, slug = $2, description = COALESCE($3, description), "
                "kind = COALESCE($4, kind), updated_at = now() "
                "WHERE id = $5 AND user_id = $6 "
                "RETURNING id, user_id, name, slug, description, kind, created_at, updated_at",
                name, slug, description, kind, kb_id, self.user_id,
            )
        else:
            row = await self.pool.fetchrow(
                "UPDATE knowledge_bases SET description = COALESCE($1, description), "
                "kind = COALESCE($2, kind), updated_at = now() "
                "WHERE id = $3 AND user_id = $4 "
                "RETURNING id, user_id, name, slug, description, kind, created_at, updated_at",
                description, kind, kb_id, self.user_id,
            )
        return dict(row) if row else None

    async def _check_capacity(self) -> None:
        user_count = await self.pool.fetchval("SELECT COUNT(DISTINCT id) FROM users")
        if user_count and user_count >= settings.GLOBAL_MAX_USERS:
            raise HTTPException(status_code=503, detail="We've reached our user capacity for now. Please try again later.")

    async def _insert_kb(self, name: str, slug: str, description: str | None, kind: str = "wiki") -> dict:
        conn = await self.pool.acquire()
        try:
            async with conn.transaction():
                current_name = name
                for attempt in range(10):
                    try:
                        row = await conn.fetchrow(
                            "INSERT INTO knowledge_bases (user_id, name, slug, description, kind) "
                            "VALUES ($1, $2, $3, $4, $5) "
                            "RETURNING id, user_id, name, slug, description, kind, created_at, updated_at",
                            self.user_id, current_name, slug, description, kind,
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
            "file_type, status, content, tags, date, metadata, version, sort_order) "
            "VALUES ($1, $2, 'overview.md', 'Overview', '/wiki/', 'md', 'ready', $3, $4, $5, $6::jsonb, 0, -100)",
            kb_id,
            self.user_id,
            _OVERVIEW_TEMPLATE.format(name=name, date=today),
            ["overview", "wiki"],
            today,
            json.dumps({"description": f"Research hub for {name}."}),
        )
        await self.pool.execute(
            "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, content, tags, version, sort_order) "
            "VALUES ($1, $2, 'log.md', 'Log', '/wiki/', 'md', 'ready', $3, $4, 0, 100)",
            kb_id, self.user_id, _LOG_TEMPLATE.format(name=name, date=today), ["log"],
        )

    async def update_sharing(
        self, kb_id: str, visibility: str, public_slug: str | None,
    ) -> dict | None:
        if visibility == "public" and public_slug is None:
            existing = await self.pool.fetchval(
                "SELECT public_slug FROM knowledge_bases WHERE id = $1 AND user_id = $2",
                kb_id, self.user_id,
            )
            if existing is None:
                raise HTTPException(
                    status_code=400,
                    detail="public_slug is required when publishing a KB for the first time",
                )

        try:
            row = await self.pool.fetchrow(
                "UPDATE knowledge_bases "
                "SET visibility = $1::kb_visibility, "
                "    public_slug = CASE WHEN $1 = 'public' THEN COALESCE($2, public_slug) ELSE public_slug END, "
                "    visibility_updated_at = now(), "
                "    published_at = CASE WHEN $1 = 'public' AND published_at IS NULL THEN now() ELSE published_at END, "
                "    updated_at = now() "
                "WHERE id = $3 AND user_id = $4 "
                "RETURNING id, user_id, name, slug, description, "
                "          visibility::text AS visibility, public_slug, share_token, "
                "          visibility_updated_at, published_at, created_at, updated_at",
                visibility, public_slug, kb_id, self.user_id,
            )
        except asyncpg.UniqueViolationError as e:
            if e.constraint_name == "idx_knowledge_bases_public_slug":
                raise HTTPException(status_code=409, detail="That public slug is already taken — try another.")
            raise
        except asyncpg.CheckViolationError as e:
            if e.constraint_name == "knowledge_bases_public_slug_format":
                raise HTTPException(status_code=400, detail="Slug must be 2–80 lowercase characters, digits, or hyphens (no leading/trailing hyphen).")
            raise
        return dict(row) if row else None

    async def delete(self, kb_id: str) -> bool:
        doc_ids = await self._kb_document_ids(kb_id)
        result = await self.pool.execute(
            "DELETE FROM knowledge_bases WHERE id = $1 AND user_id = $2",
            kb_id, self.user_id,
        )
        if result == "DELETE 0":
            return False
        await self._purge_document_prefixes(doc_ids)
        return True

    async def _kb_document_ids(self, kb_id: str) -> list[str]:
        rows = await self.pool.fetch(
            "SELECT id::text FROM documents WHERE knowledge_base_id = $1 AND user_id = $2",
            kb_id, self.user_id,
        )
        return [row["id"] for row in rows]

    async def _purge_document_prefixes(self, doc_ids: list[str]) -> None:
        if not self.s3:
            return
        for doc_id in doc_ids:
            try:
                await self.s3.delete_prefix(f"{self.user_id}/{doc_id}/")
            except Exception:
                logger.exception("S3 purge failed for document %s", doc_id)

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


def _doc_dict(row) -> dict:
    """asyncpg returns jsonb as str — decode metadata so responses carry an object."""
    doc = dict(row)
    if isinstance(doc.get("metadata"), str):
        doc["metadata"] = json.loads(doc["metadata"])
    return doc

_WEBCLIP_ROOT = "/webclipper/"


def _normalize_webclip_path(path: str | None) -> str:
    missing = path is None or not path.strip()
    raw = _WEBCLIP_ROOT if missing else path.strip()
    if "\\" in raw or "\x00" in raw:
        raise HTTPException(status_code=400, detail="Invalid folder path")
    raw = "/" + raw.strip("/") + "/"
    raw = re.sub(r"/+", "/", raw)
    parts = [p for p in raw.split("/") if p]
    if not parts and not missing:
        raise HTTPException(status_code=400, detail="Web clips must be stored under /webclipper/")
    if any(p in {".", ".."} for p in parts):
        raise HTTPException(status_code=400, detail="Invalid folder path")
    normalized = "/" + "/".join(parts) + "/" if parts else _WEBCLIP_ROOT
    if normalized != _WEBCLIP_ROOT and not normalized.startswith(_WEBCLIP_ROOT):
        raise HTTPException(status_code=400, detail="Web clips must be stored under /webclipper/")
    return normalized




class HostedDocumentService(DocumentService):

    def __init__(self, pool, user_id: str, s3=None):
        self.pool = pool
        self.user_id = user_id
        self.s3 = s3

    async def list(self, kb_id: str, path: str | None = None) -> list[dict]:
        if path:
            rows = await self.pool.fetch(
                f"SELECT {_DOC_COLUMNS} FROM documents "
                "WHERE knowledge_base_id = $1 AND archived = false AND path = $2 AND user_id = $3 "
                "AND COALESCE(metadata->>'hidden', 'false') <> 'true' "
                "AND COALESCE(metadata->>'asset', 'false') <> 'true' "
                "ORDER BY filename",
                kb_id, path, self.user_id,
            )
        else:
            rows = await self.pool.fetch(
                f"SELECT {_DOC_COLUMNS} FROM documents "
                "WHERE knowledge_base_id = $1 AND archived = false AND user_id = $2 "
                "AND COALESCE(metadata->>'hidden', 'false') <> 'true' "
                "AND COALESCE(metadata->>'asset', 'false') <> 'true' "
                "ORDER BY filename",
                kb_id, self.user_id,
            )
        return [_doc_dict(r) for r in rows]

    async def get(self, doc_id: str) -> dict | None:
        row = await self.pool.fetchrow(
            f"SELECT {_DOC_COLUMNS} FROM documents WHERE id = $1 AND user_id = $2",
            doc_id, self.user_id,
        )
        return _doc_dict(row) if row else None

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
        content_size = len(content.encode("utf-8"))
        if content_size > MAX_TEXT_CONTENT_BYTES:
            raise HTTPException(status_code=413, detail="Text content exceeds the 10 MiB limit")

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
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1::text))",
                    self.user_id,
                )
                await self._check_storage_available(content_size, conn=conn)
                row = await conn.fetchrow(
                    f"INSERT INTO documents (knowledge_base_id, user_id, filename, path, title, "
                    f"file_type, file_size, status, content, tags) "
                    f"VALUES ($1, $2, $3, $4, $5, 'md', $6, 'ready', $7, $8) "
                    f"RETURNING {_DOC_COLUMNS}",
                    kb_id, self.user_id, filename, path, title, content_size, content, tags,
                )
                if content:
                    chunks = chunk_text(content)
                    await store_chunks(conn, str(row["id"]), self.user_id, str(kb_id), chunks)
        finally:
            await self.pool.release(conn)
        return _doc_dict(row)

    async def create_web_clip(
        self, kb_id: str, url: str, title: str, html: str,
        highlights: list[dict] | None = None, path: str = "/webclipper/",
    ) -> dict:
        from html_parser import Parser

        await self._validate_kb(kb_id)
        path = _normalize_webclip_path(path)

        parser = Parser(html, url=url, content_only=True)
        result = parser.parse(highlights=highlights or [])

        existing_preview = await self.pool.fetchrow(
            "SELECT id::text, filename FROM documents "
            "WHERE knowledge_base_id = $1 AND user_id = $2 AND NOT archived "
            "AND metadata->>'source_url' = $3 "
            "AND COALESCE(metadata->>'asset', 'false') <> 'true' "
            "ORDER BY updated_at DESC LIMIT 1",
            kb_id, self.user_id, url,
        )

        if existing_preview:
            filename = existing_preview["filename"]
        else:
            filename = self._slugify_filename(title, "md")
            filename = await self._dedupe_filename(kb_id, path, filename, "md")
        stem = filename.rsplit(".", 1)[0]
        markdown, assets = await materialize_webclip_assets(
            result.content,
            result.images,
            f"{stem}.assets",
        )
        markdown_size = len((markdown or "").encode("utf-8"))
        file_size = markdown_size + sum(len(asset.data) for asset in assets)
        # Best-effort fast-fail for obvious quota errors. The in-transaction
        # check below runs under the advisory lock and is authoritative.
        await self._check_storage_available(file_size)

        enriched = self._merge_text_anchors(highlights or [], result.highlights)
        parent_doc_id = str(existing_preview["id"]) if existing_preview else str(uuid.uuid4())
        for asset in assets:
            asset.document_id = str(uuid.uuid4())

        parent_metadata = {
            "source_url": url,
            "clip_kind": "web",
            "assets": [asset.metadata() for asset in assets],
        }

        if self.s3:
            for asset in assets:
                await self.s3.upload_bytes(
                    f"{self.user_id}/{asset.document_id}/source.{asset.file_type}",
                    asset.data,
                    asset.content_type,
                )

        old_asset_ids: list[str] = []
        conn = await self.pool.acquire()
        try:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", self.user_id)
                await self._check_storage_available(file_size, conn=conn)
                existing = None
                if existing_preview:
                    existing = await conn.fetchrow(
                        "SELECT id::text, version, highlights FROM documents "
                        "WHERE id = $1 AND user_id = $2 FOR UPDATE",
                        parent_doc_id, self.user_id,
                    )
                if not existing:
                    existing = await conn.fetchrow(
                        "SELECT id::text, version, highlights FROM documents "
                        "WHERE knowledge_base_id = $1 AND user_id = $2 AND NOT archived "
                        "AND metadata->>'source_url' = $3 "
                        "AND COALESCE(metadata->>'asset', 'false') <> 'true' "
                        "ORDER BY updated_at DESC LIMIT 1 FOR UPDATE",
                        kb_id, self.user_id, url,
                    )

                if existing:
                    parent_doc_id = str(existing["id"])
                    current_highlights = self._parse_highlights(existing["highlights"])
                    next_highlights = merge_highlights_by_id(current_highlights, enriched)
                    row = await conn.fetchrow(
                        f"UPDATE documents SET path = $1, title = $2, file_size = $3, "
                        f"status = 'ready', content = $4, metadata = $5::jsonb, "
                        f"highlights = $6::jsonb, version = version + 1, updated_at = now() "
                        f"WHERE id = $7 AND user_id = $8 "
                        f"RETURNING {_DOC_COLUMNS}",
                        path, title, markdown_size, markdown, json.dumps(parent_metadata),
                        json.dumps(next_highlights), parent_doc_id, self.user_id,
                    )
                    # Re-clip of the same URL: clear the previous asset docs so
                    # the fresh assets don't collide on (kb, path, filename).
                    old_asset_ids = [
                        r["id"] for r in await conn.fetch(
                            "SELECT id::text FROM documents WHERE user_id = $1 "
                            "AND metadata->>'parent_document_id' = $2",
                            self.user_id, parent_doc_id,
                        )
                    ]
                    if old_asset_ids:
                        await conn.execute(
                            "DELETE FROM documents WHERE id = ANY($1::uuid[]) AND user_id = $2",
                            old_asset_ids, self.user_id,
                        )
                else:
                    next_highlights = enriched
                    row = await conn.fetchrow(
                        f"INSERT INTO documents (id, knowledge_base_id, user_id, filename, path, title, "
                        f"file_type, file_size, status, content, tags, metadata, highlights) "
                        f"VALUES ($1, $2, $3, $4, $5, $6, 'md', $7, 'ready', $8, $9, $10, $11::jsonb) "
                        f"RETURNING {_DOC_COLUMNS}",
                        parent_doc_id, kb_id, self.user_id, filename, path, title, markdown_size, markdown,
                        [], json.dumps(parent_metadata), json.dumps(next_highlights),
                    )
                for asset in assets:
                    await conn.execute(
                        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, path, title, "
                        "file_type, file_size, status, content, tags, metadata) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'ready', NULL, $9, $10::jsonb)",
                        asset.document_id,
                        kb_id,
                        self.user_id,
                        asset.filename,
                        f"{path}{stem}.assets/",
                        asset.filename,
                        asset.file_type,
                        len(asset.data),
                        [],
                        json.dumps({
                            "asset": True,
                            "hidden": True,
                            "parent_document_id": parent_doc_id,
                            "source_url": url,
                            **asset.metadata(),
                        }),
                    )
                chunks = chunk_text(markdown) if markdown else []
                if chunks:
                    await store_chunks(conn, str(row["id"]), self.user_id, str(kb_id), chunks)
                else:
                    await conn.execute("DELETE FROM document_chunks WHERE document_id = $1", str(row["id"]))
                # Materialize the highlights we just persisted into the
                # freshly-created chunks. Without this, comments on a
                # clipped-with-highlights doc would not be searchable until
                # the user touched the highlight again.
                if next_highlights:
                    await self._recompute_chunks_for_doc(
                        conn, str(row["id"]), [], next_highlights,
                    )
        finally:
            await self.pool.release(conn)

        await self._purge_s3(old_asset_ids)

        response = _doc_dict(row)
        response["highlights"] = next_highlights
        return response

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
            "AND COALESCE(metadata->>'asset', 'false') <> 'true' "
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
        conn = await self.pool.acquire()
        try:
            async with conn.transaction():
                # Fetch + lock the doc row so we have OLD highlights inside
                # the same txn that writes the new ones. Required for the
                # (old ∪ new) chunk recomputation downstream — a deletion
                # would otherwise leave stale annotations.
                locked = await conn.fetchrow(
                    "SELECT version, highlights FROM documents "
                    "WHERE id = $1 AND user_id = $2 FOR UPDATE",
                    doc_id, self.user_id,
                )
                if not locked:
                    return None
                if expected_version is not None and locked["version"] != expected_version:
                    return {"conflict": True}

                old_highlights = self._parse_highlights(locked["highlights"])
                preserve_replies(highlights, old_highlights)
                payload = json.dumps(highlights)

                row = await conn.fetchrow(
                    "UPDATE documents SET highlights = $1::jsonb, "
                    "version = version + 1, updated_at = now() "
                    "WHERE id = $2 AND user_id = $3 "
                    "RETURNING id::text, version, highlights",
                    payload, doc_id, self.user_id,
                )
                if not row:
                    return None
                new_highlights = self._parse_highlights(row["highlights"])
                await self._recompute_chunks_for_doc(conn, doc_id, old_highlights, new_highlights)
        finally:
            await self.pool.release(conn)

        result = dict(row)
        result["highlights"] = new_highlights
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
                preserve_replies([highlight], current)
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
                if updated:
                    await self._recompute_chunks_for_doc(
                        conn, doc_id, current, next_list,
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
                if updated:
                    await self._recompute_chunks_for_doc(
                        conn, doc_id, current, next_list,
                    )
        finally:
            await self.pool.release(conn)

        if not updated:
            return None
        result = dict(updated)
        result["highlights"] = self._parse_highlights(result.get("highlights"))
        return result

    async def _recompute_chunks_for_doc(
        self, conn, doc_id: str,
        old_highlights: list[dict], new_highlights: list[dict],
    ) -> None:
        """Update affected chunks' annotations_text + has_highlight + content.

        Affected = chunks touched by old highlights ∪ chunks touched by new
        highlights. The union prevents stale annotations when a highlight is
        deleted or moves to a different chunk.

        Called inside the highlight CRUD transaction so the chunk write and
        the documents.highlights write commit atomically.
        """
        from services.highlight_chunks import (
            ChunkRecord,
            all_affected_chunks,
            iter_chunks_with_annotations,
        )

        rows = await conn.fetch(
            "SELECT id::text AS id, chunk_index, source_content, page, start_char "
            "FROM document_chunks WHERE document_id = $1 "
            "ORDER BY chunk_index",
            doc_id,
        )
        if not rows:
            return
        chunks = [
            ChunkRecord(
                id=r["id"], chunk_index=r["chunk_index"],
                source_content=r["source_content"] or "",
                page=r["page"], start_char=r["start_char"],
            )
            for r in rows
        ]
        affected = all_affected_chunks(chunks, old_highlights, new_highlights)
        if not affected:
            return

        for chunk, anno_text, has_hl, new_content in iter_chunks_with_annotations(
            chunks, affected, new_highlights,
        ):
            await conn.execute(
                "UPDATE document_chunks "
                "SET annotations_text = $1, has_highlight = $2, content = $3 "
                "WHERE id = $4",
                anno_text, has_hl, new_content, chunk.id,
            )

    @staticmethod
    def _reraise_doc_conflict(e: asyncpg.UniqueViolationError):
        """Map a (kb, path, filename) collision to a 409; re-raise anything else."""
        if e.constraint_name == "idx_documents_unique_active":
            raise HTTPException(status_code=409, detail="A document already exists at that path.")
        raise e

    async def _validate_kb(self, kb_id: str) -> None:
        kb = await self.pool.fetchval(
            "SELECT id FROM knowledge_bases WHERE id = $1 AND user_id = $2",
            kb_id, self.user_id,
        )
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

    @staticmethod
    def _slugify_filename(title: str, ext: str) -> str:
        slug = re.sub(r"[^\w\s\-.]", "", title.lower().replace(" ", "-"))[:80].strip("-._")
        slug = slug or "web-clip"
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

    async def _check_storage_available(self, new_bytes: int, conn: Any | None = None) -> None:
        query = (
            "SELECT COALESCE(SUM(file_size), 0) FROM documents "
            "WHERE user_id = $1"
        )
        limit_query = "SELECT storage_limit_bytes FROM users WHERE id = $1"
        db = conn or self.pool
        limits = await db.fetchrow(limit_query, self.user_id)
        storage_limit = (
            limits["storage_limit_bytes"]
            if limits else settings.QUOTA_MAX_STORAGE_BYTES
        )
        current_bytes = await db.fetchval(query, self.user_id)
        current_bytes = current_bytes or 0
        if current_bytes + new_bytes > storage_limit:
            used_mb = current_bytes / (1024 * 1024)
            max_mb = storage_limit / (1024 * 1024)
            raise HTTPException(
                status_code=413,
                detail=f"Storage quota exceeded. Using {used_mb:.0f} MB of {max_mb:.0f} MB.",
            )

    async def update_content(self, doc_id: str, content: str) -> dict | None:
        content_size = len(content.encode("utf-8"))
        if content_size > MAX_TEXT_CONTENT_BYTES:
            raise HTTPException(status_code=413, detail="Text content exceeds the 10 MiB limit")

        conn = await self.pool.acquire()
        try:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1::text))",
                    self.user_id,
                )
                current = await conn.fetchrow(
                    "SELECT file_size, knowledge_base_id::text AS kb_id "
                    "FROM documents WHERE id = $1 AND user_id = $2 FOR UPDATE",
                    doc_id, self.user_id,
                )
                if not current:
                    return None

                await self._check_storage_available(
                    content_size - (current["file_size"] or 0),
                    conn=conn,
                )
                row = await conn.fetchrow(
                    "UPDATE documents SET content = $1, file_size = $2, "
                    "version = version + 1, updated_at = now() "
                    "WHERE id = $3 AND user_id = $4 RETURNING id, content, version",
                    content, content_size, doc_id, self.user_id,
                )

                chunks = chunk_text(content) if content else []
                await store_chunks(
                    conn, str(doc_id), self.user_id, current["kb_id"], chunks,
                )
        finally:
            await self.pool.release(conn)

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
            sets.append(f"metadata = COALESCE(metadata, '{{}}'::jsonb) || ${idx}::jsonb")
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

                    try:
                        row = await conn.fetchrow(move_sql, *move_params)
                    except asyncpg.UniqueViolationError as e:
                        self._reraise_doc_conflict(e)
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
            return _doc_dict(row)

        try:
            row = await self.pool.fetchrow(sql, *params)
        except asyncpg.UniqueViolationError as e:
            self._reraise_doc_conflict(e)
        return _doc_dict(row) if row else None

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
        return await self._hard_delete([doc_id]) > 0

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
        count += await self._hard_delete(source_ids)
        return count

    async def _hard_delete(self, source_ids: list[str]) -> int:
        if not source_ids:
            return 0
        doc_ids = source_ids + await self._child_asset_ids(source_ids)
        result = await self.pool.execute(
            "DELETE FROM documents WHERE id = ANY($1::uuid[]) AND user_id = $2",
            doc_ids, self.user_id,
        )
        deleted = int(result.split()[-1]) if result else 0
        if deleted:
            await self._purge_s3(doc_ids)
        return deleted

    async def _child_asset_ids(self, parent_ids: list[str]) -> list[str]:
        rows = await self.pool.fetch(
            "SELECT id::text FROM documents WHERE user_id = $1 "
            "AND metadata->>'parent_document_id' = ANY($2::text[])",
            self.user_id, parent_ids,
        )
        return [r["id"] for r in rows]

    async def _purge_s3(self, doc_ids: list[str]) -> None:
        if not self.s3:
            return
        for doc_id in doc_ids:
            try:
                await self.s3.delete_prefix(f"{self.user_id}/{doc_id}/")
            except Exception:
                logger.exception("S3 purge failed for document %s", doc_id)


class HostedPublicWikiService(PublicWikiService):
    """Anonymous read-only access to wikis with visibility = 'public'."""

    def __init__(self, pool, s3=None):
        self.pool = pool
        self.s3 = s3

    async def get_by_slug(self, slug: str) -> dict | None:
        # Single LEFT JOIN — visibility, KB metadata, author, and docs all
        # come from one statement. A flip mid-statement is impossible
        # (Postgres reads a consistent snapshot), so there's no TOCTOU
        # window between "is it public" and "what's the content".
        rows = await self.pool.fetch(
            "SELECT kb.id::text AS kb_id, kb.user_id::text AS kb_user_id, "
            "       kb.name AS kb_name, kb.description AS kb_description, "
            "       kb.public_slug AS kb_public_slug, "
            "       kb.published_at AS kb_published_at, "
            "       kb.updated_at AS kb_updated_at, "
            "       u.display_name AS author_name, "
            "       d.id::text AS doc_id, d.document_number, d.filename, "
            "       d.path, d.title, d.content, d.file_type, d.tags, "
            "       d.updated_at AS doc_updated_at "
            "FROM knowledge_bases kb "
            "LEFT JOIN users u ON u.id = kb.user_id "
            "LEFT JOIN documents d ON d.knowledge_base_id = kb.id "
            "  AND d.path LIKE '/wiki/%' "
            "  AND d.status = 'ready' "
            "  AND NOT d.archived "
            "WHERE kb.public_slug = $1 AND kb.visibility = 'public' "
            "ORDER BY d.path, COALESCE(d.sort_order, 0), d.filename",
            slug,
        )
        if not rows:
            return None

        head = rows[0]
        documents = [
            {
                "id": r["doc_id"],
                "document_number": r["document_number"],
                "filename": r["filename"],
                "path": r["path"],
                "title": r["title"],
                "content": r["content"],
                "file_type": r["file_type"],
                "tags": r["tags"],
                "updated_at": r["doc_updated_at"],
            }
            for r in rows if r["doc_id"] is not None
        ]

        return {
            "kb": {
                "id": head["kb_id"],
                "name": head["kb_name"],
                "description": head["kb_description"],
                "public_slug": head["kb_public_slug"],
                "published_at": head["kb_published_at"].isoformat() if head["kb_published_at"] else None,
                "updated_at": head["kb_updated_at"].isoformat() if head["kb_updated_at"] else None,
                "author_name": head["author_name"] or None,
            },
            "documents": documents,
        }

    async def get_asset_key(self, slug: str, document_number: int) -> str | None:
        row = await self.pool.fetchrow(
            "SELECT d.id::text AS doc_id, d.user_id::text AS user_id, "
            "       d.filename, d.file_type "
            "FROM documents d "
            "JOIN knowledge_bases kb ON kb.id = d.knowledge_base_id "
            "WHERE kb.public_slug = $1 "
            "  AND kb.visibility = 'public' "
            "  AND d.document_number = $2 "
            "  AND d.path LIKE '/wiki/%' "
            "  AND d.status = 'ready' "
            "  AND NOT d.archived",
            slug, document_number,
        )
        if not row:
            return None

        ext = (
            row["filename"].rsplit(".", 1)[-1].lower()
            if "." in row["filename"]
            else row["file_type"]
        )
        if ext in {"pptx", "ppt", "docx", "doc"}:
            return f"{row['user_id']}/{row['doc_id']}/converted.pdf"
        if ext in {"html", "htm"}:
            return f"{row['user_id']}/{row['doc_id']}/tagged.html"
        return f"{row['user_id']}/{row['doc_id']}/source.{ext}"


class HostedServiceFactory(ServiceFactory):

    def __init__(self, pool, s3=None, ocr=None):
        self.pool = pool
        self.s3 = s3
        self.ocr = ocr

    def user_service(self, user_id: str) -> HostedUserService:
        return HostedUserService(self.pool, user_id)

    def kb_service(self, user_id: str) -> HostedKBService:
        return HostedKBService(self.pool, user_id, self.s3)

    def document_service(self, user_id: str) -> HostedDocumentService:
        return HostedDocumentService(self.pool, user_id, self.s3)

    def public_wiki_service(self) -> HostedPublicWikiService:
        return HostedPublicWikiService(self.pool, self.s3)
