"""Local usage routes — matches the hosted response shape."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from deps import get_user_id

router = APIRouter(tags=["usage"])


class UsageResponse(BaseModel):
    total_pages: int
    total_storage_bytes: int
    document_count: int
    max_pages: int
    max_storage_bytes: int


@router.get("/v1/usage", response_model=UsageResponse)
async def get_usage(user_id: str = Depends(get_user_id), request: Request = None):
    from infra.db.sqlite import SQLiteUserRepository
    db = request.app.state.sqlite_db
    repo = SQLiteUserRepository(db)
    usage = await repo.get_usage(user_id)
    limits = await repo.get_limits(user_id)

    # Count documents
    cursor = await db.execute(
        "SELECT count(*) FROM documents WHERE status != 'failed'",
    )
    row = await cursor.fetchone()
    doc_count = row[0] if row else 0

    return UsageResponse(
        total_pages=usage.get("total_pages", 0),
        total_storage_bytes=usage.get("total_storage_bytes", 0),
        document_count=doc_count,
        max_pages=limits["page_limit"],
        max_storage_bytes=limits["storage_limit_bytes"],
    )
