"""Durable rolling-window quota for hosted free-form quiz grading."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import asyncpg
from fastapi import HTTPException


@dataclass(frozen=True)
class QuizGradeQuota:
    limit: int = 100
    window: timedelta = timedelta(hours=24)

    async def consume(self, pool: asyncpg.Pool, user_id: str) -> None:
        """Reserve one grading attempt before starting paid inference.

        The advisory transaction lock makes the count-and-insert atomic across
        processes and replicas. The transaction ends before the model request,
        so a slow inference never holds a database connection or user lock.
        """
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))",
                f"quiz-grade:{user_id}",
            )
            cutoff = datetime.now(UTC) - self.window
            await conn.execute(
                "DELETE FROM quiz_grade_attempts "
                "WHERE user_id = $1::uuid AND created_at <= $2",
                user_id,
                cutoff,
            )
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS used, MIN(created_at) AS oldest "
                "FROM quiz_grade_attempts "
                "WHERE user_id = $1::uuid AND created_at > $2",
                user_id,
                cutoff,
            )
            if row["used"] >= self.limit:
                raise self._limit_error(row["oldest"])
            await conn.execute(
                "INSERT INTO quiz_grade_attempts (user_id) VALUES ($1::uuid)",
                user_id,
            )

    def _limit_error(self, oldest: datetime | None) -> HTTPException:
        retry_after = 86_400
        if oldest is not None:
            reset_at = oldest + self.window
            retry_after = max(
                1,
                math.ceil((reset_at - datetime.now(UTC)).total_seconds()),
            )
        return HTTPException(
            status_code=429,
            detail=(
                f"Daily grading limit reached. You can check up to {self.limit} "
                "answers in any 24-hour period."
            ),
            headers={"Retry-After": str(retry_after)},
        )
