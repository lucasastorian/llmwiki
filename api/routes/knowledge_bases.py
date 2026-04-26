from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from deps import get_kb_service
from services.base import KBService
from services.types import CreateKB, UpdateKB

router = APIRouter(prefix="/v1/knowledge-bases", tags=["knowledge-bases"])


@router.get("")
async def list_knowledge_bases(service: Annotated[KBService, Depends(get_kb_service)]):
    return await service.list()


@router.get("/{kb_id}")
async def get_knowledge_base(kb_id: UUID, service: Annotated[KBService, Depends(get_kb_service)]):
    row = await service.get(str(kb_id))
    if not row:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return row


@router.post("", status_code=201)
async def create_knowledge_base(body: CreateKB, service: Annotated[KBService, Depends(get_kb_service)]):
    return await service.create(body.name, body.description)


@router.patch("/{kb_id}")
async def update_knowledge_base(kb_id: UUID, body: UpdateKB, service: Annotated[KBService, Depends(get_kb_service)]):
    if not body.name and not body.description:
        raise HTTPException(status_code=400, detail="No fields to update")
    row = await service.update(str(kb_id), body.name, body.description)
    if not row:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return row


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(kb_id: UUID, service: Annotated[KBService, Depends(get_kb_service)]):
    if not await service.delete(str(kb_id)):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
