from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from deps import get_scoped_db
from config import settings
from scoped_db import ScopedDB

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class GlobalStatsResponse(BaseModel):
    total_users: int
    total_documents: int
    total_pages: int
    total_storage_bytes: int
    global_max_users: int
    global_max_pages: int
    global_ocr_enabled: bool
    quota_max_storage_per_user: int


@router.get("/stats", response_model=GlobalStatsResponse)
async def global_stats(db: Annotated[ScopedDB, Depends(get_scoped_db)]):
    row = await db.fetchrow(
        "SELECT "
        "  (SELECT COUNT(DISTINCT id) FROM users) AS total_users, "
        "  (SELECT COUNT(*) FROM documents WHERE NOT archived) AS total_documents, "
        "  (SELECT COALESCE(SUM(page_count), 0) FROM documents WHERE NOT archived) AS total_pages, "
        "  (SELECT COALESCE(SUM(file_size), 0) FROM documents WHERE NOT archived) AS total_storage_bytes"
    )
    return GlobalStatsResponse(
        total_users=row["total_users"],
        total_documents=row["total_documents"],
        total_pages=row["total_pages"],
        total_storage_bytes=row["total_storage_bytes"],
        global_max_users=settings.GLOBAL_MAX_USERS,
        global_max_pages=settings.GLOBAL_MAX_PAGES,
        global_ocr_enabled=settings.GLOBAL_OCR_ENABLED,
        quota_max_storage_per_user=settings.QUOTA_MAX_STORAGE_BYTES,
    )
