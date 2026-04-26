"""Local knowledge base routes — singleton workspace facade.

One workspace = one KB in local mode. Create/delete are no-ops or disabled.
Same URL patterns as hosted knowledge_bases.py.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from deps import get_user_id

router = APIRouter(prefix="/v1/knowledge-bases", tags=["knowledge-bases"])


class UpdateKnowledgeBase(BaseModel):
    name: str | None = None
    description: str | None = None


def _get_kb_repo(request: Request):
    from infra.db.sqlite import SQLiteKBRepository
    return SQLiteKBRepository(request.app.state.sqlite_db)


@router.get("")
async def list_knowledge_bases(user_id: str = Depends(get_user_id), request: Request = None):
    repo = _get_kb_repo(request)
    return await repo.list_all(user_id)


@router.get("/{kb_id}")
async def get_knowledge_base(kb_id: str, user_id: str = Depends(get_user_id), request: Request = None):
    repo = _get_kb_repo(request)
    row = await repo.get(kb_id, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return row


@router.post("", status_code=201)
async def create_knowledge_base(user_id: str = Depends(get_user_id), request: Request = None):
    """In local mode, return the existing workspace. Cannot create additional KBs."""
    repo = _get_kb_repo(request)
    kbs = await repo.list_all(user_id)
    if kbs:
        return kbs[0]
    raise HTTPException(status_code=400, detail="No workspace initialized")


@router.patch("/{kb_id}")
async def update_knowledge_base(
    kb_id: str,
    body: UpdateKnowledgeBase,
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    repo = _get_kb_repo(request)
    fields = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.description is not None:
        fields["description"] = body.description
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    row = await repo.update(kb_id, user_id, **fields)
    if not row:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return row


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(kb_id: str, user_id: str = Depends(get_user_id)):
    """Cannot delete the workspace in local mode."""
    raise HTTPException(status_code=400, detail="Cannot delete the workspace in local mode")
