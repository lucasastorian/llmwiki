from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config import settings
from deps import get_scoped_db
from scoped_db import ScopedDB

router = APIRouter(tags=["usage"])


class UsageResponse(BaseModel):
    total_pages: int
    total_storage_bytes: int
    document_count: int
    max_pages: int
    max_storage_bytes: int


@router.get("/v1/usage", response_model=UsageResponse)
async def get_usage(
    db: Annotated[ScopedDB, Depends(get_scoped_db)],
):
    row = await db.fetchrow(
        "SELECT "
        "  COALESCE(SUM(page_count), 0)::bigint AS total_pages, "
        "  COALESCE(SUM(file_size), 0)::bigint AS total_storage_bytes, "
        "  COUNT(*)::bigint AS document_count "
        "FROM documents WHERE NOT archived"
    )
    return UsageResponse(
        total_pages=row["total_pages"],
        total_storage_bytes=row["total_storage_bytes"],
        document_count=row["document_count"],
        max_pages=settings.QUOTA_MAX_PAGES,
        max_storage_bytes=settings.QUOTA_MAX_STORAGE_BYTES,
    )
