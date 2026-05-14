from typing import Annotated

from fastapi import APIRouter, Depends

from deps import get_user_service
from services.base import UserService
from services.types import UsageResponse

router = APIRouter(tags=["usage"])


@router.get("/v1/usage", response_model=UsageResponse)
async def get_usage(service: Annotated[UserService, Depends(get_user_service)]):
    return await service.get_usage()
