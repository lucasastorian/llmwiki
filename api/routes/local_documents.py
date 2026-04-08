"""Local document routes — SQLite-backed, file-first writes.

Same URL patterns as hosted documents.py but uses SQLite repos
and writes wiki files to disk before updating the index.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from config import settings
from deps import get_user_id
from services.chunker import chunk_text

router = APIRouter(tags=["documents"])

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.+?\n)---[ \t]*\n", re.DOTALL)


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}, content
    if not isinstance(meta, dict):
        return {}, content
    return meta, content[m.end():]


class CreateNote(BaseModel):
    filename: str
    path: str = "/"
    content: str = ""


class UpdateContent(BaseModel):
    content: str


class UpdateMetadata(BaseModel):
    filename: str | None = None
    path: str | None = None
    title: str | None = None
    tags: list[str] | None = None
    date: str | None = None
    metadata: dict | None = None


class BulkDelete(BaseModel):
    ids: list[str]


def _get_repos(request: Request):
    from infra.db.sqlite import (
        SQLiteDocumentRepository, SQLiteChunkRepository,
    )
    db = request.app.state.sqlite_db
    return SQLiteDocumentRepository(db), SQLiteChunkRepository(db)


def _workspace_path() -> Path:
    return Path(settings.WORKSPACE_PATH).resolve()


# ── Read routes ──

@router.get("/v1/knowledge-bases/{kb_id}/documents")
async def list_documents(
    kb_id: str,
    user_id: str = Depends(get_user_id),
    request: Request = None,
    path: str | None = Query(None),
):
    doc_repo, _ = _get_repos(request)
    return await doc_repo.list_by_kb(kb_id, path=path)


@router.get("/v1/documents/{doc_id}")
async def get_document(doc_id: str, user_id: str = Depends(get_user_id), request: Request = None):
    doc_repo, _ = _get_repos(request)
    row = await doc_repo.get(doc_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


@router.get("/v1/documents/{doc_id}/url")
async def get_document_url(doc_id: str, user_id: str = Depends(get_user_id), request: Request = None):
    doc_repo, _ = _get_repos(request)
    row = await doc_repo.get_for_url(doc_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = request.app.state.storage_service
    if not storage:
        raise HTTPException(status_code=501, detail="Storage not configured")

    ext = row["filename"].rsplit(".", 1)[-1].lower() if "." in row["filename"] else row["file_type"]
    s3_key = f"{row.get('user_id', 'local')}/{row['id']}/source.{ext}"
    url = await storage.generate_url(s3_key)
    return {"url": url}


@router.get("/v1/documents/{doc_id}/content")
async def get_document_content(doc_id: str, user_id: str = Depends(get_user_id), request: Request = None):
    doc_repo, _ = _get_repos(request)
    row = await doc_repo.get_content(doc_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


# ── Write routes (file-first) ──

@router.post("/v1/knowledge-bases/{kb_id}/documents/note", status_code=201)
async def create_note(
    kb_id: str,
    body: CreateNote,
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    doc_repo, chunk_repo = _get_repos(request)

    meta, _ = _parse_frontmatter(body.content)

    if isinstance(meta.get("title"), str) and meta["title"].strip():
        title = meta["title"].strip()
    else:
        stem = body.filename.rsplit(".", 1)[0] if "." in body.filename else body.filename
        title = stem.replace("-", " ").replace("_", " ").strip().title()

    tags: list[str] = []
    if isinstance(meta.get("tags"), list):
        tags = [str(t) for t in meta["tags"] if t is not None]

    # Write file to disk first
    relative = (body.path.rstrip("/") + "/" + body.filename).lstrip("/")
    file_path = _workspace_path() / relative
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if body.content:
        file_path.write_text(body.content, encoding="utf-8")

    # Then update index
    row = await doc_repo.create_note(
        kb_id, user_id, body.filename, body.path, title, body.content, tags,
    )

    if body.content:
        chunks = chunk_text(body.content)
        await chunk_repo.store(str(row["id"]), user_id, kb_id, chunks)

    return row


@router.put("/v1/documents/{doc_id}/content")
async def update_document_content(
    doc_id: str,
    body: UpdateContent,
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    doc_repo, chunk_repo = _get_repos(request)

    # Get the doc to find its file path
    doc = await doc_repo.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Write file to disk first
    relative = (doc["path"].rstrip("/") + "/" + doc["filename"]).lstrip("/")
    file_path = _workspace_path() / relative
    if file_path.is_relative_to(_workspace_path()):
        file_path.write_text(body.content, encoding="utf-8")

    # Then update index
    row = await doc_repo.update_content(doc_id, user_id, body.content)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    kb_id = await doc_repo.get_kb_id(doc_id)
    if kb_id:
        chunks = chunk_text(body.content) if body.content else []
        await chunk_repo.store(doc_id, user_id, kb_id, chunks)

    return row


@router.patch("/v1/documents/{doc_id}")
async def update_document_metadata(
    doc_id: str,
    body: UpdateMetadata,
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    doc_repo, _ = _get_repos(request)

    fields = {}
    if body.filename is not None:
        fields["filename"] = body.filename
    if body.path is not None:
        fields["path"] = body.path
    if body.title is not None:
        fields["title"] = body.title
    if body.tags is not None:
        fields["tags"] = body.tags
    if body.date is not None:
        fields["date"] = body.date if body.date else None
    if body.metadata is not None:
        fields["metadata"] = body.metadata

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    row = await doc_repo.update_metadata(doc_id, user_id, **fields)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


@router.post("/v1/documents/bulk-delete", status_code=204)
async def bulk_delete_documents(
    body: BulkDelete,
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    if not body.ids:
        return
    doc_repo, _ = _get_repos(request)

    # Delete files from disk
    for doc_id in body.ids:
        doc = await doc_repo.get(doc_id)
        if doc:
            relative = (doc["path"].rstrip("/") + "/" + doc["filename"]).lstrip("/")
            file_path = _workspace_path() / relative
            if file_path.is_file() and file_path.is_relative_to(_workspace_path()):
                file_path.unlink()

    await doc_repo.bulk_archive(body.ids, user_id)


@router.delete("/v1/documents/{doc_id}", status_code=204)
async def delete_document(
    doc_id: str,
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    doc_repo, _ = _get_repos(request)

    # Delete file from disk
    doc = await doc_repo.get(doc_id)
    if doc:
        relative = (doc["path"].rstrip("/") + "/" + doc["filename"]).lstrip("/")
        file_path = _workspace_path() / relative
        if file_path.is_file() and file_path.is_relative_to(_workspace_path()):
            file_path.unlink()

    deleted = await doc_repo.archive(doc_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
