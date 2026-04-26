from typing import Annotated

from fastapi import APIRouter, Depends

from deps import get_user_service
from services.base import UserService
from services.types import MeResponse

router = APIRouter(tags=["me"])


@router.get("/v1/me", response_model=MeResponse)
async def get_me(service: Annotated[UserService, Depends(get_user_service)]):
    return await service.get_profile()


@router.post("/v1/onboarding/complete", status_code=204)
async def complete_onboarding(service: Annotated[UserService, Depends(get_user_service)]):
    await service.complete_onboarding()
