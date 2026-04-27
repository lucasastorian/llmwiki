from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from deps import get_document_service
from services.base import DocumentService
from services.types import CreateNote, CreateWebClip, UpdateContent, UpdateMetadata, BulkDelete

router = APIRouter(tags=["documents"])


@router.get("/v1/knowledge-bases/{kb_id}/documents")
async def list_documents(
    kb_id: UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
    path: str | None = Query(None),
):
    return await service.list(str(kb_id), path)


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
    return await service.create_web_clip(str(kb_id), body.url, body.title, body.html)


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


@router.post("/v1/documents/bulk-delete", status_code=204)
async def bulk_delete_documents(
    body: BulkDelete,
    service: Annotated[DocumentService, Depends(get_document_service)],
):
    if not body.ids:
        return
    await service.bulk_delete(body.ids)


@router.delete("/v1/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: UUID, service: Annotated[DocumentService, Depends(get_document_service)]):
    if not await service.delete(str(doc_id)):
        raise HTTPException(status_code=404, detail="Document not found")
