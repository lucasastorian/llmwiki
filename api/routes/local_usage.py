"""Local usage routes — unlimited quotas."""

from fastapi import APIRouter, Depends, Request

from deps import get_user_id

router = APIRouter(tags=["usage"])


@router.get("/v1/usage")
async def get_usage(user_id: str = Depends(get_user_id), request: Request = None):
    from infra.db.sqlite import SQLiteUserRepository
    db = request.app.state.sqlite_db
    repo = SQLiteUserRepository(db)
    usage = await repo.get_usage(user_id)
    limits = await repo.get_limits(user_id)
    return {
        "total_pages": usage.get("total_pages", 0),
        "total_storage_bytes": usage.get("total_storage_bytes", 0),
        "page_limit": limits["page_limit"],
        "storage_limit_bytes": limits["storage_limit_bytes"],
    }
