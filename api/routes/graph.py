"""Hosted graph routes — thin HTTP layer, delegates to services/graph.py."""

from uuid import UUID

from fastapi import APIRouter, Depends

from deps import get_scoped_db
from scoped_db import ScopedDB
from services.graph import get_graph_hosted, rebuild_hosted

router = APIRouter(tags=["graph"])


@router.get("/v1/knowledge-bases/{kb_id}/graph")
async def get_kb_graph(
    kb_id: UUID,
    db: ScopedDB = Depends(get_scoped_db),
):
    return await get_graph_hosted(db.conn, kb_id, db.user_id)


@router.post("/v1/knowledge-bases/{kb_id}/graph/rebuild")
async def rebuild_references(
    kb_id: UUID,
    db: ScopedDB = Depends(get_scoped_db),
):
    return await rebuild_hosted(db.conn, kb_id, db.user_id)
