from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from deps import get_scoped_db, get_user_id
from scoped_db import ScopedDB

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    id: str
    email: str
    display_name: str | None
    onboarded: bool


@router.get("/v1/me", response_model=MeResponse)
async def get_me(
    db: Annotated[ScopedDB, Depends(get_scoped_db)],
):
    row = await db.fetchrow(
        "SELECT id::text, email, display_name, onboarded FROM users WHERE id = auth.uid()"
    )
    if not row:
        return MeResponse(id="", email="", display_name=None, onboarded=False)
    return row


@router.post("/v1/onboarding/complete", status_code=204)
async def complete_onboarding(
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool
    await pool.execute(
        "UPDATE users SET onboarded = true, updated_at = now() WHERE id = $1",
        user_id,
    )
