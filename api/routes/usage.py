from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from config import settings
from deps import get_user_id

router = APIRouter(tags=["usage"])


class UsageResponse(BaseModel):
    total_pages: int
    total_storage_bytes: int
    document_count: int
    max_pages: int
    max_storage_bytes: int


@router.get("/v1/usage", response_model=UsageResponse)
async def get_usage(
    user_id: Annotated[str, Depends(get_user_id)],
    request: Request,
):
    pool = request.app.state.pool

    row = await pool.fetchrow(
        "SELECT "
        "  COALESCE(SUM(page_count), 0)::bigint AS total_pages, "
        "  COALESCE(SUM(file_size), 0)::bigint AS total_storage_bytes, "
        "  COUNT(*)::bigint AS document_count "
        "FROM documents WHERE user_id = $1 AND NOT archived",
        user_id,
    )

    limits = await pool.fetchrow(
        "SELECT page_limit, storage_limit_bytes FROM users WHERE id = $1",
        user_id,
    )

    return UsageResponse(
        total_pages=row["total_pages"],
        total_storage_bytes=row["total_storage_bytes"],
        document_count=row["document_count"],
        max_pages=limits["page_limit"] if limits else settings.QUOTA_MAX_PAGES,
        max_storage_bytes=limits["storage_limit_bytes"] if limits else settings.QUOTA_MAX_STORAGE_BYTES,
    )
