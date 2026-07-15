from typing import Annotated

import httpx
from config import settings
from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException, Request
from infra.rate_limit import limiter
from services.quiz_grader import QuizGrader
from services.quiz_quota import QuizGradeQuota
from services.types import GradeQuizAnswer, QuizGradeResponse

router = APIRouter(tags=["quiz"])
quiz_quota = QuizGradeQuota(limit=settings.QUIZ_GRADE_DAILY_LIMIT)


@router.post("/v1/quiz/grade", response_model=QuizGradeResponse)
@limiter.limit("20/minute")
async def grade_quiz_answer(
    request: Request,
    body: GradeQuizAnswer,
    user_id: Annotated[str, Depends(get_user_id)],
):
    if not settings.CLOUDFLARE_ACCOUNT_ID or not settings.CLOUDFLARE_AUTH_TOKEN:
        raise HTTPException(status_code=501, detail="Quiz grading is not configured")
    await quiz_quota.consume(request.app.state.pool, user_id)
    async with httpx.AsyncClient() as client:
        return await QuizGrader(client).grade(
            body.prompt,
            body.rubric,
            body.answer,
            user_id=user_id,
        )
