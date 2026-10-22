"""Local service implementations — SQLite + filesystem."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import uuid
from pathlib import Path

from config import settings
from domain.file_types import SIMPLE_TEXT_TYPES
from domain.watcher import mark_written
from fastapi import HTTPException
from infra.db.sqlite import SQLiteChunkRepository, SQLiteDocumentRepository, serialized_write
from services.chunker import chunk_text
from services.webclip_assets import materialize_webclip_assets

from .base import DocumentService, KBService, ServiceFactory, UserService
from .highlight_merge import merge_highlights_by_id, merge_text_anchors
from .parsers import extract_tags, parse_frontmatter, title_from_filename
from .types import MAX_TEXT_CONTENT_BYTES

# Mirrors the web's lesson definition (wikiTree.ts): wiki pages minus the structural hub/log/index.
_LESSON_FILTER = (
    "source_kind = 'wiki' AND status != 'failed' "
    "AND (path || filename) NOT IN ('/wiki/overview.md', '/wiki/log.md', '/wiki/index.json')"
)


class LocalUserService(UserService):

    def __init__(self, db, user_id: str):
        self.db = db
        self.user_id = user_id

    async def get_profile(self) -> dict:
        return {
            "id": self.user_id,
            "email": "local@localhost",
            "display_name": "Local User",
            "onboarded": True,
        }

    async def complete_onboarding(self) -> None:
        pass

    async def get_usage(self) -> dict:
        cursor = await self.db.execute(
            "SELECT count(*) as doc_count, "
            "COALESCE(SUM(page_count), 0) as total_pages, "
            "COALESCE(SUM(file_size), 0) as total_storage "
            "FROM documents WHERE status != 'failed'",
        )
        row = await cursor.fetchone()
        return {
            "total_pages": row[1] if row else 0,
            "total_storage_bytes": row[2] if row else 0,
            "document_count": row[0] if row else 0,
            "max_pages": 999999,
            "max_storage_bytes": 999999999999,
        }


class LocalKBService(KBService):

    def __init__(self, db, user_id: str):
        self.db = db
        self.user_id = user_id

    async def list(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT w.id, w.user_id, w.name, w.name as slug, w.description, w.kind, "
            "w.created_at, w.created_at as updated_at, "
            "(SELECT count(*) FROM documents WHERE source_kind = 'source' AND status != 'failed') as source_count, "
            "(SELECT count(*) FROM documents WHERE source_kind = 'wiki' AND status != 'failed') as wiki_page_count, "
            f"(SELECT count(*) FROM documents WHERE {_LESSON_FILTER}) as lesson_count, "
            f"(SELECT count(*) FROM documents WHERE {_LESSON_FILTER} "
            "AND json_extract(metadata, '$.course.status') = 'complete') as lessons_completed "
            "FROM workspace w",
        )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r, strict=False)) for r in rows]

    async def _workspace(self) -> dict | None:
        kbs = await self.list()
        return kbs[0] if kbs else None

    async def create(self, name: str, description: str | None, kind: str | None = None) -> dict:
        kbs = await self.list()
        if kbs:
            existing = kbs[0]
            if kind == "course" and existing["kind"] != "course":
                return await self.update(existing["id"], None, None, "course")
            return existing
        raise HTTPException(status_code=400, detail="No workspace initialized")

    async def update(self, kb_id: str, name: str | None, description: str | None, kind: str | None = None) -> dict | None:
        sets = []
        params = []
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if description is not None:
            sets.append("description = ?")
            params.append(description)
        if kind is not None:
            sets.append("kind = ?")
            params.append(kind)
        if not sets:
            return None
        params.append(kb_id)
        async with serialized_write():
            try:
                await self.db.execute(f"UPDATE workspace SET {', '.join(sets)} WHERE id = ?", tuple(params))
                await self.db.commit()
            except Exception:
                await self.db.rollback()
                raise
        return await self._workspace()

    async def update_sharing(
        self, kb_id: str, visibility: str, public_slug: str | None,
    ) -> dict | None:
        raise HTTPException(
            status_code=400,
            detail="Wiki sharing isn't available in local mode. Run the hosted "
            "version (or use llmwiki.app) to publish a wiki.",
        )

    async def delete(self, kb_id: str) -> bool:
        raise HTTPException(status_code=400, detail="Cannot delete the workspace in local mode")


def _workspace_root() -> Path:
    return Path(settings.WORKSPACE_PATH).resolve()


def _safe_resolve(relative: str) -> Path:
    ws = _workspace_root()
    resolved = (ws / relative).resolve()
    if not resolved.is_relative_to(ws):
        raise HTTPException(status_code=400, detail="Path escapes workspace")
    return resolved


def _normalize_dir(path: str) -> str:
    """Canonical '/a/b/' directory form, so DB paths always match disk paths."""
    parts = [part for part in path.split("/") if part]
    if any(part in (".", "..") for part in parts):
        raise HTTPException(status_code=400, detail="Path segments '.' and '..' are not allowed")
    return "/" + "/".join(parts) + "/" if parts else "/"


def _resolve_writable(dir_path: str, filename: str) -> tuple[str, Path]:
    """Resolve a normalized dir + filename to (relative_path, disk path), refusing hidden targets like .llmwiki/."""
    if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    relative = (dir_path + filename).lstrip("/")
    if any(part.startswith(".") for part in relative.split("/")):
        raise HTTPException(status_code=400, detail="Hidden files and folders are not writable")
    return relative, _safe_resolve(relative)


def _doc_to_disk_path(doc: dict) -> Path | None:
    relative = (doc["path"].rstrip("/") + "/" + doc["filename"]).lstrip("/")
    ws = _workspace_root()
    resolved = (ws / relative).resolve()
    return resolved if resolved.is_relative_to(ws) else None


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


def _parse_web_clip(html: str, url: str, highlights: list[dict]):
    """Run the synchronous HTML parser from a worker thread."""
    from html_parser import ParseLimitExceededError, Parser

    parser = Parser(html, url=url, content_only=True)
    try:
        return parser.parse(highlights=highlights)
    except ParseLimitExceededError as e:
        raise HTTPException(status_code=413, detail=str(e)) from e


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bytes_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _create_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        f.write(content)


def _move_file(old_path: Path, new_path: Path) -> None:
    """Move a file without ever replacing an existing destination (raises FileExistsError)."""
    new_path.parent.mkdir(parents=True, exist_ok=True)
    if new_path.exists() and new_path.samefile(old_path):
        old_path.rename(new_path)  # case-only rename on a case-insensitive filesystem
        return
    _place_without_replacing(old_path, new_path)
    try:
        old_path.unlink()
    except BaseException:
        new_path.unlink(missing_ok=True)
        raise


def _place_without_replacing(old_path: Path, new_path: Path) -> None:
    """Create new_path from old_path atomically refusing an existing target: hard link, else exclusive copy."""
    try:
        os.link(old_path, new_path)
        return
    except FileExistsError:
        raise
    except OSError:
        pass  # filesystem without hard links (FAT/exFAT, some SMB/FUSE mounts)
    with old_path.open("rb") as source:
        target = new_path.open("xb")
        try:
            with target:
                shutil.copyfileobj(source, target)
            shutil.copystat(old_path, new_path)
        except BaseException:
            new_path.unlink(missing_ok=True)
            raise


def _unlink_file(path: Path) -> None:
    path.unlink(missing_ok=True)


class LocalDocumentService(DocumentService):

    def __init__(self, db, user_id: str):
        self.db = db
        self.user_id = user_id
        self.doc_repo = SQLiteDocumentRepository(db)
        self.chunk_repo = SQLiteChunkRepository(db)

    async def list(self, kb_id: str, path: str | None = None) -> list[dict]:
        return await self.doc_repo.list_by_kb(kb_id, path=path)

    async def get(self, doc_id: str) -> dict | None:
        return await self.doc_repo.get(doc_id)

    async def get_content(self, doc_id: str) -> dict | None:
        return await self.doc_repo.get_content(doc_id)

    async def get_url(self, doc_id: str) -> dict | None:
        doc = await self.doc_repo.get(doc_id)
        if not doc:
            return None
        api_url = settings.API_URL.rstrip("/")
        ext = doc["filename"].rsplit(".", 1)[-1].lower() if "." in doc["filename"] else doc.get("file_type", "")

        for check_ext, cache_suffix in [
            ({"pptx", "ppt", "docx", "doc"}, "converted.pdf"),
            ({"html", "htm"}, "tagged.html"),
        ]:
            if ext in check_ext:
                cache_key = f"{doc.get('user_id', 'local')}/{doc['id']}/{cache_suffix}"
                if (_workspace_root() / ".llmwiki" / "cache" / cache_key).is_file():
                    return {"url": f"{api_url}/v1/files/{cache_key}"}

        relative = doc.get("relative_path") or (doc["path"].rstrip("/") + "/" + doc["filename"]).lstrip("/")
        return {"url": f"{api_url}/v1/files/{relative}"}

    async def create_note(self, kb_id: str, filename: str, path: str, content: str) -> dict:
        if len(content.encode("utf-8")) > MAX_TEXT_CONTENT_BYTES:
            raise HTTPException(status_code=413, detail="Text content exceeds the 10 MiB limit")

        meta = await asyncio.to_thread(parse_frontmatter, content)
        title = meta.get("title", "").strip() or title_from_filename(filename)
        tags = extract_tags(meta)

        path = _normalize_dir(path)
        _, file_path = _resolve_writable(path, filename)
        existing = await self.doc_repo.find_by_path(kb_id, self.user_id, filename, path)
        if existing or file_path.exists():
            raise HTTPException(status_code=409, detail=f"'{filename}' already exists at {path}")

        mark_written(str(file_path))
        try:
            await asyncio.to_thread(_create_text_file, file_path, content or "")
        except FileExistsError as e:
            raise HTTPException(status_code=409, detail=f"'{filename}' already exists at {path}") from e

        try:
            row = await self.doc_repo.create_note(kb_id, self.user_id, filename, path, title, content, tags)
        except BaseException:
            await asyncio.to_thread(_unlink_file, file_path)
            raise

        if content:
            chunks = await asyncio.to_thread(chunk_text, content)
            await self.chunk_repo.store(str(row["id"]), self.user_id, kb_id, chunks)

        return row

    async def create_web_clip(
        self, kb_id: str, url: str, title: str, html: str,
        highlights: list[dict] | None = None, path: str = "/webclipper/",
    ) -> dict:
        path = _normalize_webclip_path(path)
        result = await asyncio.to_thread(
            _parse_web_clip,
            html,
            url,
            highlights or [],
        )
        markdown = result.content

        base_name = re.sub(r"[^\w\s\-.]", "", title.lower().replace(" ", "-"))[:80].strip("-._")
        filename = f"{base_name or 'web-clip'}.md"

        relative_dir = path.strip("/")
        relative = f"{relative_dir}/{filename}" if relative_dir else filename
        file_path = _safe_resolve(relative)
        if file_path.exists():
            base = filename.rsplit(".", 1)[0]
            for i in range(2, 100):
                candidate = f"{base}-{i}.md"
                candidate_relative = f"{relative_dir}/{candidate}" if relative_dir else candidate
                candidate_path = _safe_resolve(candidate_relative)
                if not candidate_path.exists():
                    filename = candidate
                    file_path = candidate_path
                    break

        stem = filename.rsplit(".", 1)[0]
        asset_dir_name = f"{stem}.assets"
        markdown, assets = await materialize_webclip_assets(markdown, result.images, asset_dir_name)

        existing = await self.doc_repo.get_by_source_url(url)
        if existing:
            parent_id = str(existing["id"])
            parent_doc = await self.doc_repo.get(parent_id)
            if parent_doc and (parent_doc.get("path") != path or parent_doc.get("title") != title):
                await self.update_metadata(parent_id, {"path": path, "title": title})

            await self.update_content(parent_id, markdown or "")

            asset_metadata: list[dict] = []
            for asset in assets:
                asset_id = str(uuid.uuid4())
                asset.document_id = asset_id
                asset_path = f"{path}{asset_dir_name}/"
                relative_asset = f"{relative_dir}/{asset.src}" if relative_dir else asset.src
                local_asset = _safe_resolve(relative_asset)
                mark_written(str(local_asset))
                await asyncio.to_thread(_write_bytes_file, local_asset, asset.data)
                await self.doc_repo.create_asset(
                    asset_id,
                    self.user_id,
                    asset.filename,
                    asset_path,
                    asset.filename,
                    asset.file_type,
                    len(asset.data),
                    {
                        "asset": True,
                        "hidden": True,
                        "parent_document_id": parent_id,
                        "source_url": url,
                        **asset.metadata(),
                    },
                )
                asset_metadata.append(asset.metadata())

            await self.doc_repo.set_metadata_field(parent_id, "source_url", url)
            await self.doc_repo.set_metadata_field(parent_id, "clip_kind", "web")
            await self.doc_repo.set_metadata_field(parent_id, "assets", asset_metadata)

            current = await self.doc_repo.get_highlights(parent_id)
            current_highlights = current["highlights"] if current else []
            enriched = merge_text_anchors(highlights or [], result.highlights)
            merged_highlights = merge_highlights_by_id(current_highlights, enriched)
            if merged_highlights or current_highlights:
                await self.doc_repo.replace_highlights(parent_id, self.user_id, merged_highlights)

            doc = await self.doc_repo.get(parent_id) or existing
            fresh_highlights = await self.doc_repo.get_highlights(parent_id)
            if fresh_highlights:
                doc["version"] = fresh_highlights["version"]
                doc["highlights"] = fresh_highlights["highlights"]
            return doc

        mark_written(str(file_path))
        await asyncio.to_thread(_write_text_file, file_path, markdown or "")

        try:
            row = await self.doc_repo.create_note(kb_id, self.user_id, filename, path, title, markdown, [])
        except Exception:
            await asyncio.to_thread(_unlink_file, file_path)
            raise

        parent_id = str(row["id"])
        asset_metadata: list[dict] = []
        for asset in assets:
            asset_id = str(uuid.uuid4())
            asset.document_id = asset_id
            asset_path = f"{path}{asset_dir_name}/"
            relative_asset = f"{relative_dir}/{asset.src}" if relative_dir else asset.src
            local_asset = _safe_resolve(relative_asset)
            mark_written(str(local_asset))
            await asyncio.to_thread(_write_bytes_file, local_asset, asset.data)
            await self.doc_repo.create_asset(
                asset_id,
                self.user_id,
                asset.filename,
                asset_path,
                asset.filename,
                asset.file_type,
                len(asset.data),
                {
                    "asset": True,
                    "hidden": True,
                    "parent_document_id": parent_id,
                    "source_url": url,
                    **asset.metadata(),
                },
            )
            asset_metadata.append(asset.metadata())

        await self.doc_repo.set_metadata_field(parent_id, "source_url", url)
        await self.doc_repo.set_metadata_field(parent_id, "clip_kind", "web")
        if asset_metadata:
            await self.doc_repo.set_metadata_field(parent_id, "assets", asset_metadata)

        if markdown:
            chunks = await asyncio.to_thread(chunk_text, markdown)
            await self.chunk_repo.store(parent_id, self.user_id, kb_id, chunks)

        # Only after chunks exist can the highlight write materialize annotations onto them.
        if highlights:
            enriched = merge_text_anchors(highlights, result.highlights)
            await self.doc_repo.replace_highlights(parent_id, self.user_id, enriched)

        doc = await self.doc_repo.get(parent_id) or row
        fresh_highlights = await self.doc_repo.get_highlights(parent_id)
        if fresh_highlights:
            doc["version"] = fresh_highlights["version"]
            doc["highlights"] = fresh_highlights["highlights"]
        return doc

    async def get_by_source_url(self, url: str) -> dict | None:
        return await self.doc_repo.get_by_source_url(url)

    async def get_highlights(self, doc_id: str) -> dict | None:
        return await self.doc_repo.get_highlights(doc_id)

    async def upsert_highlight(
        self, doc_id: str, highlight: dict,
        expected_version: int | None = None,
    ) -> dict | None:
        return await self.doc_repo.upsert_highlight(
            doc_id, self.user_id, highlight, expected_version,
        )

    async def delete_highlight(
        self, doc_id: str, highlight_id: str,
        expected_version: int | None = None,
    ) -> dict | None:
        return await self.doc_repo.delete_highlight(
            doc_id, self.user_id, highlight_id, expected_version,
        )

    async def update_content(self, doc_id: str, content: str) -> dict | None:
        if len(content.encode("utf-8")) > MAX_TEXT_CONTENT_BYTES:
            raise HTTPException(status_code=413, detail="Text content exceeds the 10 MiB limit")

        doc = await self.doc_repo.get(doc_id)
        if not doc:
            return None

        file_path = _doc_to_disk_path(doc) if doc["file_type"] in SIMPLE_TEXT_TYPES else None
        if file_path:
            mark_written(str(file_path))
            await asyncio.to_thread(_write_text_file, file_path, content)

        row = await self.doc_repo.update_content(doc_id, self.user_id, content)

        kb_id = await self.doc_repo.get_kb_id(doc_id)
        if kb_id:
            chunks = await asyncio.to_thread(chunk_text, content) if content else []
            await self.chunk_repo.store(doc_id, self.user_id, kb_id, chunks)
            await self.doc_repo.reapply_highlights(doc_id)

        return row

    async def update_metadata(self, doc_id: str, fields: dict) -> dict | None:
        doc = await self.doc_repo.get(doc_id)
        if not doc:
            return None

        # Single workspace, nowhere to move to: ignore the field rather than fail the call.
        fields = {k: v for k, v in fields.items() if k != "knowledge_base_id"}
        if not fields:
            return doc

        old_path = _doc_to_disk_path(doc)
        needs_move = "filename" in fields or "path" in fields
        if not (needs_move and old_path and old_path.is_file()):
            return await self.doc_repo.update_metadata(doc_id, self.user_id, **fields)

        new_dir = _normalize_dir(fields.get("path", doc["path"]))
        new_filename = fields.get("filename", doc["filename"])
        new_relative, new_path = _resolve_writable(new_dir, new_filename)
        mark_written(str(old_path))
        mark_written(str(new_path))
        try:
            await asyncio.to_thread(_move_file, old_path, new_path)
        except FileExistsError as e:
            raise HTTPException(status_code=409, detail=f"'{new_filename}' already exists at {new_dir}") from e
        fields["path"] = new_dir
        fields["relative_path"] = new_relative
        fields["source_kind"] = "wiki" if new_dir.startswith("/wiki/") else "source"
        try:
            return await self.doc_repo.update_metadata(doc_id, self.user_id, **fields)
        except BaseException:
            await asyncio.to_thread(_move_file, new_path, old_path)
            raise

    async def delete(self, doc_id: str) -> bool:
        doc = await self.doc_repo.get(doc_id)
        if doc:
            file_path = _doc_to_disk_path(doc)
            if file_path and file_path.is_file():
                mark_written(str(file_path))
                await asyncio.to_thread(_unlink_file, file_path)
        return await self.doc_repo.archive(doc_id, self.user_id)

    async def bulk_delete(self, doc_ids: list[str]) -> int:
        for doc_id in doc_ids:
            doc = await self.doc_repo.get(doc_id)
            if doc:
                file_path = _doc_to_disk_path(doc)
                if file_path and file_path.is_file():
                    mark_written(str(file_path))
                    await asyncio.to_thread(_unlink_file, file_path)
        return await self.doc_repo.bulk_archive(doc_ids, self.user_id)


class LocalServiceFactory(ServiceFactory):

    def __init__(self, db):
        self.db = db

    def user_service(self, user_id: str) -> LocalUserService:
        return LocalUserService(self.db, user_id)

    def kb_service(self, user_id: str) -> LocalKBService:
        return LocalKBService(self.db, user_id)

    def document_service(self, user_id: str) -> LocalDocumentService:
        return LocalDocumentService(self.db, user_id)

    def public_wiki_service(self):
        raise HTTPException(status_code=404, detail="Public wikis aren't available in local mode.")
