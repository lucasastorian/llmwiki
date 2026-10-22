from typing import Annotated
from uuid import UUID

from deps import get_kb_service
from fastapi import APIRouter, Depends, HTTPException
from services.base import KBService
from services.types import CreateKB, UpdateKB, UpdateSharing

router = APIRouter(prefix="/v1/knowledge-bases", tags=["knowledge-bases"])


@router.get("")
async def list_knowledge_bases(service: Annotated[KBService, Depends(get_kb_service)]):
    return await service.list()


@router.post("", status_code=201)
async def create_knowledge_base(body: CreateKB, service: Annotated[KBService, Depends(get_kb_service)]):
    return await service.create(body.name, body.description, body.kind)


@router.patch("/{kb_id}")
async def update_knowledge_base(kb_id: UUID, body: UpdateKB, service: Annotated[KBService, Depends(get_kb_service)]):
    if not body.name and not body.description and not body.kind:
        raise HTTPException(status_code=400, detail="No fields to update")
    row = await service.update(str(kb_id), body.name, body.description, body.kind)
    if not row:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return row


@router.patch("/{kb_id}/sharing")
async def update_knowledge_base_sharing(
    kb_id: UUID,
    body: UpdateSharing,
    service: Annotated[KBService, Depends(get_kb_service)],
):
    slug = body.validated_slug()
    if body.public_slug is not None and slug is None:
        raise HTTPException(
            status_code=400,
            detail="Slug must be 2–80 lowercase characters, digits, or hyphens (no leading/trailing hyphen).",
        )
    row = await service.update_sharing(str(kb_id), body.visibility, slug)
    if not row:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return row


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(kb_id: UUID, service: Annotated[KBService, Depends(get_kb_service)]):
    if not await service.delete(str(kb_id)):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
