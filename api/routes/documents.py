from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from deps import get_document_service
from services.base import DocumentService
from services.types import (
    BulkDelete, CreateNote, CreateWebClip,
    ReplaceHighlights, UpdateContent, UpdateMetadata, UpsertHighlight,
)

router = APIRouter(tags=["documents"])


@router.get("/v1/knowledge-bases/{kb_id}/documents")
async def list_documents(
    kb_id: UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
    path: str | None = Query(None),
):
    return await service.list(str(kb_id), path)


@router.get("/v1/documents/by-url")
async def get_document_by_url(
    service: Annotated[DocumentService, Depends(get_document_service)],
    url: str = Query(..., max_length=2048),
):
    row = await service.get_by_source_url(url)
    if not row:
        raise HTTPException(status_code=404, detail="No document found for URL")
    return row


@router.get("/v1/documents/{doc_id}")
async def get_document(doc_id: UUID, service: Annotated[DocumentService, Depends(get_document_service)]):
    row = await service.get(str(doc_id))
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


@router.get("/v1/documents/{doc_id}/url")
async def get_document_url(doc_id: UUID, service: Annotated[DocumentService, Depends(get_document_service)]):
    result = await service.get_url(str(doc_id))
    if not result:
        raise HTTPException(status_code=404, detail="Document not found")
    return result


@router.get("/v1/documents/{doc_id}/content")
async def get_document_content(doc_id: UUID, service: Annotated[DocumentService, Depends(get_document_service)]):
    row = await service.get_content(str(doc_id))
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


@router.post("/v1/knowledge-bases/{kb_id}/documents/note", status_code=201)
async def create_note(
    kb_id: UUID,
    body: CreateNote,
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    return await service.create_note(str(kb_id), body.filename, body.path, body.content)


@router.post("/v1/knowledge-bases/{kb_id}/documents/web", status_code=201)
async def create_web_clip(
    kb_id: UUID,
    body: CreateWebClip,
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    highlights = [h.model_dump() for h in body.highlights] if body.highlights else None
    return await service.create_web_clip(
        str(kb_id), body.url, body.title, body.html, highlights,
    )


@router.get("/v1/documents/{doc_id}/highlights")
async def get_document_highlights(
    doc_id: UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    row = await service.get_highlights(str(doc_id))
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


@router.patch("/v1/documents/{doc_id}/highlights")
async def replace_document_highlights(
    doc_id: UUID,
    body: ReplaceHighlights,
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    highlights = [h.model_dump() for h in body.highlights]
    row = await service.replace_highlights(
        str(doc_id), highlights, body.expectedVersion,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    if row.get("conflict"):
        raise HTTPException(
            status_code=409,
            detail="Version mismatch — refetch and retry",
        )
    return row


@router.post("/v1/documents/{doc_id}/highlights", status_code=200)
async def upsert_document_highlight(
    doc_id: UUID,
    body: UpsertHighlight,
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    """Idempotent single-highlight upsert. Re-posting the same {id, payload}
    is safe; the wire-level retry behavior on dropped connections matters more
    than strict deduplication."""
    row = await service.upsert_highlight(
        str(doc_id), body.highlight.model_dump(), body.expectedVersion,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    if row.get("conflict"):
        raise HTTPException(
            status_code=409,
            detail="Version mismatch — refetch and retry",
        )
    if row.get("limit_exceeded"):
        raise HTTPException(
            status_code=413,
            detail="Highlight limit reached (500 per document)",
        )
    return row


@router.delete("/v1/documents/{doc_id}/highlights/{highlight_id}", status_code=200)
async def delete_document_highlight(
    doc_id: UUID,
    highlight_id: str,
    service: Annotated[DocumentService, Depends(get_document_service)],
    expectedVersion: int | None = Query(None),
):
    """Idempotent single-highlight delete. Removing an absent id returns the
    current state without bumping the version (200 either way).
    `expectedVersion` is a query param (DELETE bodies are awkward in some
    proxies/clients)."""
    row = await service.delete_highlight(str(doc_id), highlight_id, expectedVersion)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    if row.get("conflict"):
        raise HTTPException(
            status_code=409,
            detail="Version mismatch — refetch and retry",
        )
    return row


@router.put("/v1/documents/{doc_id}/content")
async def update_document_content(
    doc_id: UUID,
    body: UpdateContent,
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    row = await service.update_content(str(doc_id), body.content)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


@router.patch("/v1/documents/{doc_id}")
async def update_document_metadata(
    doc_id: UUID,
    body: UpdateMetadata,
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    row = await service.update_metadata(str(doc_id), fields)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row


_BULK_DELETE_MAX_IDS = 100


@router.post("/v1/documents/bulk-delete", status_code=204)
async def bulk_delete_documents(
    body: BulkDelete,
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    if not body.ids:
        return
    if len(body.ids) > _BULK_DELETE_MAX_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many ids: max {_BULK_DELETE_MAX_IDS} per request",
        )
    await service.bulk_delete(body.ids)


@router.delete("/v1/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: UUID, service: Annotated[DocumentService, Depends(get_document_service)]):
    if not await service.delete(str(doc_id)):
        raise HTTPException(status_code=404, detail="Document not found")
