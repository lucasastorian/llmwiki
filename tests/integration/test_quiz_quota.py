"""Hosted free-form quiz grading has a durable rolling per-user quota."""

import asyncio
import json
from datetime import timedelta

import asyncpg
import pytest
from fastapi import HTTPException
from services.quiz_quota import QuizGradeQuota

USER_ID = "99999999-9999-9999-9999-999999999999"


@pytest.fixture(autouse=True)
async def quota_user(pool):
    await pool.execute(
        "INSERT INTO users (id, email) VALUES ($1, 'quiz-quota@test.com') "
        "ON CONFLICT (id) DO NOTHING",
        USER_ID,
    )
    await pool.execute("DELETE FROM quiz_grade_attempts WHERE user_id = $1", USER_ID)
    yield
    await pool.execute("DELETE FROM users WHERE id = $1", USER_ID)


async def test_quota_allows_up_to_limit_and_returns_retry_after(pool):
    quota = QuizGradeQuota(limit=2)

    await quota.consume(pool, USER_ID)
    await quota.consume(pool, USER_ID)

    with pytest.raises(HTTPException) as exc:
        await quota.consume(pool, USER_ID)

    assert exc.value.status_code == 429
    assert "2 answers" in exc.value.detail
    assert 1 <= int(exc.value.headers["Retry-After"]) <= 86_400
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM quiz_grade_attempts WHERE user_id = $1",
        USER_ID,
    ) == 2


async def test_quota_discards_attempts_outside_rolling_window(pool):
    await pool.execute(
        "INSERT INTO quiz_grade_attempts (user_id, created_at) "
        "VALUES ($1, now() - interval '25 hours')",
        USER_ID,
    )

    await QuizGradeQuota(limit=1).consume(pool, USER_ID)

    assert await pool.fetchval(
        "SELECT COUNT(*) FROM quiz_grade_attempts WHERE user_id = $1",
        USER_ID,
    ) == 1


async def test_quota_serializes_concurrent_attempts(pool):
    quota = QuizGradeQuota(limit=1, window=timedelta(hours=24))

    results = await asyncio.gather(
        quota.consume(pool, USER_ID),
        quota.consume(pool, USER_ID),
        return_exceptions=True,
    )

    assert sum(result is None for result in results) == 1
    errors = [result for result in results if isinstance(result, HTTPException)]
    assert len(errors) == 1
    assert errors[0].status_code == 429
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM quiz_grade_attempts WHERE user_id = $1",
        USER_ID,
    ) == 1


async def test_quota_ledger_is_hidden_from_authenticated_sessions(pool):
    await QuizGradeQuota(limit=1).consume(pool, USER_ID)

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL ROLE authenticated")
        await conn.execute(
            "SELECT set_config('request.jwt.claims', $1, true)",
            json.dumps({"sub": USER_ID}),
        )
        assert await conn.fetchval("SELECT COUNT(*) FROM quiz_grade_attempts") == 0
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO quiz_grade_attempts (user_id) VALUES ($1)",
                    USER_ID,
                )
