"""Local user routes — single user, always onboarded."""

from fastapi import APIRouter, Depends

from deps import get_user_id

router = APIRouter(tags=["me"])


@router.get("/v1/me")
async def get_me(user_id: str = Depends(get_user_id)):
    return {
        "id": user_id,
        "email": "local@localhost",
        "display_name": "Local User",
        "onboarded": True,
    }


@router.post("/v1/onboarding/complete")
async def complete_onboarding(user_id: str = Depends(get_user_id)):
    return {"status": "ok"}
