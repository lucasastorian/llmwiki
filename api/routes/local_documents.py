"""Local document routes — SQLite-backed, file-first writes.

Same URL patterns as hosted documents.py but uses SQLite repos
and writes wiki files to disk before updating the index.
"""

import re
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from config import settings
from deps import get_user_id
from services.chunker import chunk_text
from domain.watcher import mark_written

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


def _workspace_root() -> Path:
    return Path(settings.WORKSPACE_PATH).resolve()


def _safe_resolve(relative: str) -> Path:
    """Resolve a relative path safely within the workspace. Raises 400 on traversal."""
    ws = _workspace_root()
    resolved = (ws / relative).resolve()
    if not resolved.is_relative_to(ws):
        raise HTTPException(status_code=400, detail="Path escapes workspace")
    return resolved


def _doc_to_disk_path(doc: dict) -> Path | None:
    """Get the resolved disk path for a document. Returns None if outside workspace."""
    relative = (doc["path"].rstrip("/") + "/" + doc["filename"]).lstrip("/")
    ws = _workspace_root()
    resolved = (ws / relative).resolve()
    if resolved.is_relative_to(ws):
        return resolved
    return None


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
    """Return a local file URL for viewing the document.

    For workspace files, serves the actual file via /v1/files/.
    For processed artifacts (converted PDFs, tagged HTML), serves from .llmwiki/cache/.
    """
    doc_repo, _ = _get_repos(request)
    doc = await doc_repo.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    api_url = settings.API_URL.rstrip("/")

    # Check for converted/processed versions in cache first
    ext = doc["filename"].rsplit(".", 1)[-1].lower() if "." in doc["filename"] else doc.get("file_type", "")
    office_types = {"pptx", "ppt", "docx", "doc"}
    html_types = {"html", "htm"}

    if ext in office_types:
        cache_key = f"{doc.get('user_id', 'local')}/{doc['id']}/converted.pdf"
        cache_path = _workspace_root() / ".llmwiki" / "cache" / cache_key
        if cache_path.is_file():
            return {"url": f"{api_url}/v1/files/{cache_key}"}
    elif ext in html_types:
        cache_key = f"{doc.get('user_id', 'local')}/{doc['id']}/tagged.html"
        cache_path = _workspace_root() / ".llmwiki" / "cache" / cache_key
        if cache_path.is_file():
            return {"url": f"{api_url}/v1/files/{cache_key}"}

    # Fall back to the actual workspace file
    relative = doc.get("relative_path") or (doc["path"].rstrip("/") + "/" + doc["filename"]).lstrip("/")
    return {"url": f"{api_url}/v1/files/{relative}"}


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

    # Check for duplicate
    existing = await doc_repo.find_by_path(kb_id, user_id, body.filename, body.path)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"'{body.filename}' already exists at {body.path}",
        )

    # Write file to disk first — resolve safely
    relative = (body.path.rstrip("/") + "/" + body.filename).lstrip("/")
    file_path = _safe_resolve(relative)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    mark_written(str(file_path))
    file_path.write_text(body.content or "", encoding="utf-8")

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

    doc = await doc_repo.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Write file to disk first
    file_path = _doc_to_disk_path(doc)
    if file_path:
        mark_written(str(file_path))
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

    doc = await doc_repo.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    fields = {}
    if body.title is not None:
        fields["title"] = body.title
    if body.tags is not None:
        fields["tags"] = body.tags
    if body.date is not None:
        fields["date"] = body.date if body.date else None
    if body.metadata is not None:
        fields["metadata"] = body.metadata

    # Handle filename/path rename — move the actual file
    old_path = _doc_to_disk_path(doc)
    needs_move = False

    if body.filename is not None:
        fields["filename"] = body.filename
        needs_move = True
    if body.path is not None:
        fields["path"] = body.path
        needs_move = True

    if needs_move and old_path and old_path.is_file():
        new_filename = body.filename or doc["filename"]
        new_dir = body.path or doc["path"]
        new_relative = (new_dir.rstrip("/") + "/" + new_filename).lstrip("/")
        new_path = _safe_resolve(new_relative)
        new_path.parent.mkdir(parents=True, exist_ok=True)
        mark_written(str(old_path))
        mark_written(str(new_path))
        old_path.rename(new_path)
        # Update relative_path in fields
        fields["relative_path"] = new_relative
        # Recompute source_kind
        fields["source_kind"] = "wiki" if new_dir.strip("/").startswith("wiki") else "source"

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

    for doc_id in body.ids:
        doc = await doc_repo.get(doc_id)
        if doc:
            file_path = _doc_to_disk_path(doc)
            if file_path and file_path.is_file():
                mark_written(str(file_path))
                file_path.unlink()

    await doc_repo.bulk_archive(body.ids, user_id)


@router.delete("/v1/documents/{doc_id}", status_code=204)
async def delete_document(
    doc_id: str,
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    doc_repo, _ = _get_repos(request)

    doc = await doc_repo.get(doc_id)
    if doc:
        file_path = _doc_to_disk_path(doc)
        if file_path and file_path.is_file():
            mark_written(str(file_path))
            file_path.unlink()

    deleted = await doc_repo.archive(doc_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
