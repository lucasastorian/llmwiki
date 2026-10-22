"""Hosted graph routes — thin HTTP layer, delegates to services/graph.py."""

import asyncio
import time
from uuid import UUID

from deps import get_scoped_db
from fastapi import APIRouter, Depends, HTTPException
from scoped_db import ScopedDB
from services.graph import get_graph_hosted, rebuild_hosted

router = APIRouter(tags=["graph"])

# Rebuild is O(docs × wiki pages) and rewrites document_references, so throttle and serialize it per KB.
_REBUILD_COOLDOWN_SECONDS = 5 * 60
_rebuild_locks: dict[str, asyncio.Lock] = {}
_rebuild_last_run: dict[str, float] = {}


def _rebuild_lock_for(kb_id: str) -> asyncio.Lock:
    lock = _rebuild_locks.get(kb_id)
    if lock is None:
        lock = asyncio.Lock()
        _rebuild_locks[kb_id] = lock
    return lock


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
    key = str(kb_id)
    last = _rebuild_last_run.get(key, 0.0)
    elapsed = time.monotonic() - last
    if elapsed < _REBUILD_COOLDOWN_SECONDS:
        wait = int(_REBUILD_COOLDOWN_SECONDS - elapsed)
        raise HTTPException(
            status_code=429,
            detail=f"Graph rebuild on cooldown; retry in {wait}s",
        )
    lock = _rebuild_lock_for(key)
    if lock.locked():
        raise HTTPException(
            status_code=429,
            detail="Graph rebuild already in progress for this knowledge base",
        )
    async with lock:
        result = await rebuild_hosted(db.conn, kb_id, db.user_id)
        _rebuild_last_run[key] = time.monotonic()
        return result
