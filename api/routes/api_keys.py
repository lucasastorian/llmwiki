import hashlib
import secrets
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from deps import get_scoped_db, get_user_id
from scoped_db import ScopedDB

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])


class CreateAPIKey(BaseModel):
    name: str = "Default"


class APIKeyOut(BaseModel):
    id: UUID
    name: str | None
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class APIKeyCreated(APIKeyOut):
    key: str


# ── Read routes (RLS-enforced via ScopedDB) ──

@router.get("", response_model=list[APIKeyOut])
async def list_api_keys(db: Annotated[ScopedDB, Depends(get_scoped_db)]):
    rows = await db.fetch(
        "SELECT id, name, key_prefix, created_at, last_used_at, revoked_at "
        "FROM api_keys WHERE revoked_at IS NULL ORDER BY created_at DESC"
    )
    return rows


# ── Write routes (service role via pool) ──

@router.post("", response_model=APIKeyCreated, status_code=201)
async def create_api_key(
    body: CreateAPIKey,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool
    raw_key = "sv_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:11]

    row = await pool.fetchrow(
        "INSERT INTO api_keys (user_id, name, key_hash, key_prefix) "
        "VALUES ($1, $2, $3, $4) "
        "RETURNING id, name, key_prefix, created_at, last_used_at, revoked_at",
        user_id, body.name, key_hash, key_prefix,
    )
    return {**dict(row), "key": raw_key}


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: UUID,
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool
    result = await pool.execute(
        "UPDATE api_keys SET revoked_at = now() WHERE id = $1 AND user_id = $2 AND revoked_at IS NULL",
        key_id, user_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="API key not found")
