"""Local service implementations — SQLite + filesystem."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import HTTPException

from config import settings
from domain.watcher import mark_written
from infra.db.sqlite import SQLiteDocumentRepository, SQLiteChunkRepository
from services.chunker import chunk_text
from services.webclip_assets import materialize_webclip_assets
from .base import UserService, KBService, DocumentService, ServiceFactory
from .parsers import parse_frontmatter, title_from_filename, extract_tags


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
            "SELECT w.id, w.user_id, w.name, w.name as slug, w.description, "
            "w.created_at, w.created_at as updated_at, "
            "(SELECT count(*) FROM documents WHERE source_kind = 'source' AND status != 'failed') as source_count, "
            "(SELECT count(*) FROM documents WHERE source_kind = 'wiki' AND status != 'failed') as wiki_page_count "
            "FROM workspace w",
        )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, r)) for r in rows]

    async def get(self, kb_id: str) -> dict | None:
        kbs = await self.list()
        return kbs[0] if kbs else None

    async def create(self, name: str, description: str | None) -> dict:
        kbs = await self.list()
        if kbs:
            return kbs[0]
        raise HTTPException(status_code=400, detail="No workspace initialized")

    async def update(self, kb_id: str, name: str | None, description: str | None) -> dict | None:
        sets = []
        params = []
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if description is not None:
            sets.append("description = ?")
            params.append(description)
        if not sets:
            return None
        params.append(kb_id)
        await self.db.execute(f"UPDATE workspace SET {', '.join(sets)} WHERE id = ?", tuple(params))
        await self.db.commit()
        return await self.get(kb_id)

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


def _merge_text_anchors(payloads: list[dict], mapped) -> list[dict]:
    """Same as the hosted helper — merge parser-computed text_anchors back
    onto incoming highlight payloads."""
    out: list[dict] = []
    for i, h in enumerate(payloads):
        if not isinstance(h, dict):
            continue
        entry = dict(h)
        if i < len(mapped) and mapped[i].text_anchor is not None:
            ta = mapped[i].text_anchor
            entry["textAnchor"] = {
                "textStart": ta.text_start,
                "textEnd": ta.text_end,
                "textContent": ta.text_content,
                "prefix": ta.prefix,
                "suffix": ta.suffix,
            }
        out.append(entry)
    return out


def _merge_highlights_by_id(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    order: list[str] = []
    for highlight in [*existing, *incoming]:
        if not isinstance(highlight, dict):
            continue
        highlight_id = highlight.get("id")
        if not highlight_id:
            continue
        if highlight_id not in merged:
            order.append(highlight_id)
        current = merged.get(highlight_id, {})
        merged[highlight_id] = {**current, **highlight}
    return [merged[highlight_id] for highlight_id in order]


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
        meta = parse_frontmatter(content)
        title = meta.get("title", "").strip() or title_from_filename(filename)
        tags = extract_tags(meta)

        existing = await self.doc_repo.find_by_path(kb_id, self.user_id, filename, path)
        if existing:
            raise HTTPException(status_code=409, detail=f"'{filename}' already exists at {path}")

        relative = (path.rstrip("/") + "/" + filename).lstrip("/")
        file_path = _safe_resolve(relative)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        mark_written(str(file_path))
        file_path.write_text(content or "", encoding="utf-8")

        row = await self.doc_repo.create_note(kb_id, self.user_id, filename, path, title, content, tags)
        
        if content:
            chunks = chunk_text(content)
            await self.chunk_repo.store(str(row["id"]), self.user_id, kb_id, chunks)

        return row

    async def create_web_clip(
        self, kb_id: str, url: str, title: str, html: str,
        highlights: list[dict] | None = None, path: str = "/webclipper/",
    ) -> dict:
        from html_parser import Parser

        path = _normalize_webclip_path(path)
        parser = Parser(html, url=url, content_only=True)
        result = parser.parse(highlights=highlights or [])
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
                local_asset.parent.mkdir(parents=True, exist_ok=True)
                mark_written(str(local_asset))
                local_asset.write_bytes(asset.data)
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
            enriched = _merge_text_anchors(highlights or [], result.highlights)
            merged_highlights = _merge_highlights_by_id(current_highlights, enriched)
            if merged_highlights or current_highlights:
                await self.doc_repo.replace_highlights(parent_id, self.user_id, merged_highlights)

            doc = await self.doc_repo.get(parent_id) or existing
            fresh_highlights = await self.doc_repo.get_highlights(parent_id)
            if fresh_highlights:
                doc["version"] = fresh_highlights["version"]
                doc["highlights"] = fresh_highlights["highlights"]
            return doc

        file_path.parent.mkdir(parents=True, exist_ok=True)
        mark_written(str(file_path))
        file_path.write_text(markdown or "", encoding="utf-8")

        try:
            row = await self.doc_repo.create_note(kb_id, self.user_id, filename, path, title, markdown, [])
        except Exception:
            file_path.unlink(missing_ok=True)
            raise

        parent_id = str(row["id"])
        asset_metadata: list[dict] = []
        for asset in assets:
            asset_id = str(uuid.uuid4())
            asset.document_id = asset_id
            asset_path = f"{path}{asset_dir_name}/"
            relative_asset = f"{relative_dir}/{asset.src}" if relative_dir else asset.src
            local_asset = _safe_resolve(relative_asset)
            local_asset.parent.mkdir(parents=True, exist_ok=True)
            mark_written(str(local_asset))
            local_asset.write_bytes(asset.data)
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
            chunks = chunk_text(markdown)
            await self.chunk_repo.store(parent_id, self.user_id, kb_id, chunks)

        # replace_highlights AFTER chunks exist so the repo-level
        # _recompute_chunks_for_doc can materialize annotations onto the
        # freshly-created chunks. Running it before chunks exist would be a
        # no-op materialization.
        if highlights:
            enriched = _merge_text_anchors(highlights, result.highlights)
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

    async def replace_highlights(
        self, doc_id: str, highlights: list[dict],
        expected_version: int | None = None,
    ) -> dict | None:
        return await self.doc_repo.replace_highlights(
            doc_id, self.user_id, highlights, expected_version,
        )

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
        doc = await self.doc_repo.get(doc_id)
        if not doc:
            return None

        file_path = _doc_to_disk_path(doc)
        if file_path:
            mark_written(str(file_path))
            file_path.write_text(content, encoding="utf-8")

        row = await self.doc_repo.update_content(doc_id, self.user_id, content)

        kb_id = await self.doc_repo.get_kb_id(doc_id)
        if kb_id:
            chunks = chunk_text(content) if content else []
            await self.chunk_repo.store(doc_id, self.user_id, kb_id, chunks)

        return row

    async def update_metadata(self, doc_id: str, fields: dict) -> dict | None:
        doc = await self.doc_repo.get(doc_id)
        if not doc:
            return None

        # Local mode has a singleton workspace — there's nowhere to move to.
        # Drop the field if the client sent one rather than failing the call.
        fields = {k: v for k, v in fields.items() if k != "knowledge_base_id"}
        if not fields:
            return doc

        old_path = _doc_to_disk_path(doc)
        needs_move = "filename" in fields or "path" in fields

        if needs_move and old_path and old_path.is_file():
            new_filename = fields.get("filename", doc["filename"])
            new_dir = fields.get("path", doc["path"])
            new_relative = (new_dir.rstrip("/") + "/" + new_filename).lstrip("/")
            new_path = _safe_resolve(new_relative)
            new_path.parent.mkdir(parents=True, exist_ok=True)
            mark_written(str(old_path))
            mark_written(str(new_path))
            old_path.rename(new_path)
            fields["relative_path"] = new_relative
            fields["source_kind"] = "wiki" if new_dir.strip("/").startswith("wiki") else "source"

        return await self.doc_repo.update_metadata(doc_id, self.user_id, **fields)

    async def delete(self, doc_id: str) -> bool:
        doc = await self.doc_repo.get(doc_id)
        if doc:
            file_path = _doc_to_disk_path(doc)
            if file_path and file_path.is_file():
                mark_written(str(file_path))
                file_path.unlink()
        return await self.doc_repo.archive(doc_id, self.user_id)

    async def bulk_delete(self, doc_ids: list[str]) -> int:
        for doc_id in doc_ids:
            doc = await self.doc_repo.get(doc_id)
            if doc:
                file_path = _doc_to_disk_path(doc)
                if file_path and file_path.is_file():
                    mark_written(str(file_path))
                    file_path.unlink()
        return await self.doc_repo.bulk_archive(doc_ids, self.user_id)


class LocalServiceFactory(ServiceFactory):

    def __init__(self, db, storage=None, user_id: str = ""):
        self.db = db
        self.storage = storage
        self.user_id = user_id

    def user_service(self, user_id: str) -> LocalUserService:
        return LocalUserService(self.db, user_id)

    def kb_service(self, user_id: str) -> LocalKBService:
        return LocalKBService(self.db, user_id)

    def document_service(self, user_id: str) -> LocalDocumentService:
        return LocalDocumentService(self.db, user_id)

    def public_wiki_service(self):
        raise HTTPException(status_code=404, detail="Public wikis aren't available in local mode.")
