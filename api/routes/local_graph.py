"""Local graph routes — thin HTTP layer, delegates to services/graph.py."""

from fastapi import APIRouter, Depends, Request

from deps import get_user_id
from services.graph import get_graph_local, rebuild_local

router = APIRouter(tags=["graph"])


@router.get("/v1/knowledge-bases/{kb_id}/graph")
async def get_kb_graph(
    kb_id: str,
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    db = request.app.state.sqlite_db
    return await get_graph_local(db, user_id)


@router.post("/v1/knowledge-bases/{kb_id}/graph/rebuild")
async def rebuild_references(
    kb_id: str,
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    db = request.app.state.sqlite_db
    return await rebuild_local(db, user_id)
