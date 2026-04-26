"""Local file upload route — simple multipart, no TUS.

Copies uploaded files directly into the workspace and indexes them.
"""

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form

from config import settings
from deps import get_user_id
from domain.watcher import mark_written

router = APIRouter(tags=["upload"])


def _workspace_root() -> Path:
    return Path(settings.WORKSPACE_PATH).resolve()


def _safe_resolve(relative: str) -> Path:
    ws = _workspace_root()
    resolved = (ws / relative).resolve()
    if not resolved.is_relative_to(ws):
        raise HTTPException(status_code=400, detail="Path escapes workspace")
    return resolved


@router.post("/v1/upload", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    path: str = Form(default="/"),
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    """Upload a file directly into the workspace and index it."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")

    filename = file.filename
    relative = (path.rstrip("/") + "/" + filename).lstrip("/")
    dest = _safe_resolve(relative)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Read file content
    content_bytes = await file.read()
    mark_written(str(dest))
    dest.write_bytes(content_bytes)

    # Determine metadata
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    title = stem.replace("-", " ").replace("_", " ").strip().title()

    dir_path = "/" + "/".join(relative.split("/")[:-1]) + "/" if "/" in relative else "/"
    source_kind = "wiki" if relative.startswith("wiki/") else "source"
    content_hash = hashlib.sha256(content_bytes).hexdigest()

    # Read text content for simple indexable types (not HTML — that goes through webmd)
    text_content = None
    simple_text_types = {"md", "txt", "csv", "svg", "json", "xml"}
    needs_processing = ext in {"pdf", "pptx", "ppt", "docx", "doc", "xlsx", "xls", "html", "htm"}
    if ext in simple_text_types:
        try:
            text_content = content_bytes.decode("utf-8", errors="replace")
        except Exception:
            pass

    # Index into SQLite
    from infra.db.sqlite import SQLiteDocumentRepository, SQLiteChunkRepository
    db = request.app.state.sqlite_db
    doc_repo = SQLiteDocumentRepository(db)
    chunk_repo = SQLiteChunkRepository(db)

    doc_id = str(uuid.uuid4())

    # Auto-assign document_number
    cursor = await db.execute("SELECT COALESCE(MAX(document_number), 0) + 1 FROM documents")
    row = await cursor.fetchone()
    doc_number = row[0]

    import json
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, "
        "source_kind, file_type, file_size, status, content, tags, version, "
        "content_hash, mtime_ns, last_indexed_at, document_number) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', 0, ?, ?, datetime('now'), ?)",
        (doc_id, user_id, filename, title, dir_path, relative, source_kind,
         ext or "bin", len(content_bytes),
         "ready" if text_content is not None else "pending",
         text_content, content_hash,
         int(dest.stat().st_mtime_ns), doc_number),
    )
    await db.commit()

    # Chunk text content or kick off processing for non-text files
    if text_content:
        from services.chunker import chunk_text
        ws_row = await db.execute("SELECT id FROM workspace LIMIT 1")
        ws = await ws_row.fetchone()
        kb_id = ws[0] if ws else ""
        chunks = chunk_text(text_content)
        await chunk_repo.store(doc_id, user_id, kb_id, chunks)
    elif needs_processing:
        # PDF, Office, spreadsheet, HTML: process in background
        import asyncio
        from pathlib import Path as P
        from domain.local_processor import process_document
        asyncio.create_task(process_document(db, doc_id, P(settings.WORKSPACE_PATH).resolve()))

    doc = await doc_repo.get(doc_id)
    return doc
