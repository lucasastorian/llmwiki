import json
import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from deps import get_scoped_db, get_user_id
from scoped_db import ScopedDB
from services.chunker import chunk_text, store_chunks

router = APIRouter(tags=["documents"])

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.+?\n)---[ \t]*\n", re.DOTALL)

_DOC_COLUMNS = (
    "id, knowledge_base_id, user_id, filename, path, title, "
    "file_type, status, tags, date, metadata, error_message, "
    "version, document_number, archived, created_at, updated_at"
)


def parse_frontmatter(content: str) -> tuple[dict, str]:
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


class DocumentOut(BaseModel):
    id: UUID
    knowledge_base_id: UUID
    user_id: UUID
    filename: str
    path: str
    title: str | None
    file_type: str
    status: str
    tags: list[str]
    date: str | None = None
    metadata: dict | None = None
    error_message: str | None = None
    version: int
    document_number: int | None
    archived: bool
    created_at: datetime
    updated_at: datetime


class DocumentContent(BaseModel):
    id: UUID
    content: str | None
    version: int


class BulkDelete(BaseModel):
    ids: list[UUID]


# ── Read routes (RLS-enforced via ScopedDB) ──

@router.get("/v1/knowledge-bases/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    kb_id: UUID,
    db: Annotated[ScopedDB, Depends(get_scoped_db)],
    path: str | None = Query(None),
):
    if path:
        rows = await db.fetch(
            f"SELECT {_DOC_COLUMNS} "
            "FROM documents WHERE knowledge_base_id = $1 AND archived = false AND path = $2 "
            "AND user_id = $3 ORDER BY filename",
            kb_id, path, db.user_id,
        )
    else:
        rows = await db.fetch(
            f"SELECT {_DOC_COLUMNS} "
            "FROM documents WHERE knowledge_base_id = $1 AND archived = false "
            "AND user_id = $2 ORDER BY filename",
            kb_id, db.user_id,
        )
    return rows


@router.get("/v1/documents/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: UUID,
    db: Annotated[ScopedDB, Depends(get_scoped_db)],
):
    row = await db.fetchrow(
        f"SELECT {_DOC_COLUMNS} FROM documents WHERE id = $1 AND user_id = $2",
        doc_id, db.user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


@router.get("/v1/documents/{doc_id}/url")
async def get_document_url(
    doc_id: UUID,
    db: Annotated[ScopedDB, Depends(get_scoped_db)],
    request: Request,
):
    row = await db.fetchrow(
        "SELECT id, user_id, filename, file_type FROM documents WHERE id = $1 AND user_id = $2",
        doc_id, db.user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    s3_service = request.app.state.s3_service
    if not s3_service:
        raise HTTPException(status_code=501, detail="File storage not configured")

    ext = row["filename"].rsplit(".", 1)[-1].lower() if "." in row["filename"] else row["file_type"]
    office_types = {"pptx", "ppt", "docx", "doc"}
    html_types = {"html", "htm"}
    if ext in office_types:
        s3_key = f"{row['user_id']}/{row['id']}/converted.pdf"
    elif ext in html_types:
        s3_key = f"{row['user_id']}/{row['id']}/tagged.html"
    else:
        s3_key = f"{row['user_id']}/{row['id']}/source.{ext}"
    url = await s3_service.generate_presigned_get(s3_key)
    return {"url": url}


@router.get("/v1/documents/{doc_id}/content", response_model=DocumentContent)
async def get_document_content(
    doc_id: UUID,
    db: Annotated[ScopedDB, Depends(get_scoped_db)],
):
    row = await db.fetchrow(
        "SELECT id, content, version FROM documents WHERE id = $1 AND user_id = $2",
        doc_id, db.user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


# ── Write routes (service role via pool, explicit user_id auth) ──

@router.post("/v1/knowledge-bases/{kb_id}/documents/note", response_model=DocumentOut, status_code=201)
async def create_note(
    kb_id: UUID,
    body: CreateNote,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool

    kb = await pool.fetchval(
        "SELECT id FROM knowledge_bases WHERE id = $1 AND user_id = $2",
        kb_id, user_id,
    )
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    meta, _ = parse_frontmatter(body.content)

    if isinstance(meta.get("title"), str) and meta["title"].strip():
        title = meta["title"].strip()
    else:
        # Humanize filename: "operating-leverage.md" → "Operating Leverage"
        stem = body.filename.rsplit(".", 1)[0] if "." in body.filename else body.filename
        title = stem.replace("-", " ").replace("_", " ").strip().title()

    tags: list[str] = []
    if isinstance(meta.get("tags"), list):
        tags = [str(t) for t in meta["tags"] if t is not None]

    # Check for duplicate filename at the same path
    existing = await pool.fetchval(
        "SELECT id FROM documents WHERE knowledge_base_id = $1 AND user_id = $2 "
        "AND filename = $3 AND path = $4 AND NOT archived",
        kb_id, user_id, body.filename, body.path,
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"'{body.filename}' already exists at {body.path}",
        )

    conn = await pool.acquire()
    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                "INSERT INTO documents (knowledge_base_id, user_id, filename, path, title, "
                "file_type, status, content, tags) "
                "VALUES ($1, $2, $3, $4, $5, 'md', 'ready', $6, $7) "
                f"RETURNING {_DOC_COLUMNS}",
                kb_id, user_id, body.filename, body.path, title, body.content, tags,
            )
            if body.content:
                chunks = chunk_text(body.content)
                await store_chunks(conn, str(row["id"]), user_id, str(kb_id), chunks)
    finally:
        await pool.release(conn)

    return dict(row)


@router.put("/v1/documents/{doc_id}/content", response_model=DocumentContent)
async def update_document_content(
    doc_id: UUID,
    body: UpdateContent,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool

    row = await pool.fetchrow(
        "UPDATE documents SET content = $1, version = version + 1, updated_at = now() "
        "WHERE id = $2 AND user_id = $3 "
        "RETURNING id, content, version",
        body.content, doc_id, user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    kb_id = await pool.fetchval(
        "SELECT knowledge_base_id::text FROM documents WHERE id = $1 AND user_id = $2",
        doc_id, user_id,
    )
    if kb_id:
        chunks = chunk_text(body.content) if body.content else []
        await store_chunks(pool, str(doc_id), user_id, kb_id, chunks)

    return dict(row)


@router.patch("/v1/documents/{doc_id}", response_model=DocumentOut)
async def update_document_metadata(
    doc_id: UUID,
    body: UpdateMetadata,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool

    updates = []
    params = []
    idx = 1

    if body.filename is not None:
        updates.append(f"filename = ${idx}")
        params.append(body.filename)
        idx += 1
    if body.path is not None:
        updates.append(f"path = ${idx}")
        params.append(body.path)
        idx += 1
    if body.title is not None:
        updates.append(f"title = ${idx}")
        params.append(body.title)
        idx += 1
    if body.tags is not None:
        updates.append(f"tags = ${idx}")
        params.append(body.tags)
        idx += 1
    if body.date is not None:
        updates.append(f"date = ${idx}")
        params.append(body.date if body.date else None)
        idx += 1
    if body.metadata is not None:
        updates.append(f"metadata = ${idx}")
        params.append(json.dumps(body.metadata))
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = now()")
    params.append(doc_id)
    params.append(user_id)

    sql = (
        f"UPDATE documents SET {', '.join(updates)} "
        f"WHERE id = ${idx} AND user_id = ${idx + 1} "
        f"RETURNING {_DOC_COLUMNS}"
    )
    row = await pool.fetchrow(sql, *params)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return dict(row)


@router.post("/v1/documents/bulk-delete", status_code=204)
async def bulk_delete_documents(
    body: BulkDelete,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    if not body.ids:
        return
    pool = request.app.state.pool
    await pool.execute(
        "UPDATE documents SET archived = true, updated_at = now() "
        "WHERE id = ANY($1::uuid[]) AND user_id = $2",
        [str(i) for i in body.ids], user_id,
    )


@router.delete("/v1/documents/{doc_id}", status_code=204)
async def delete_document(
    doc_id: UUID,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool
    result = await pool.execute(
        "UPDATE documents SET archived = true, updated_at = now() "
        "WHERE id = $1 AND user_id = $2",
        doc_id, user_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Document not found")
