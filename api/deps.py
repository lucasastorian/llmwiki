import asyncio
import inspect
import json
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from scoped_db import ScopedDB

DB_ACQUIRE_TIMEOUT_SECONDS = 10.0


async def _acquire_connection(pool):
    """Acquire without allowing a saturated pool to hang a request forever."""
    try:
        parameters = inspect.signature(pool.acquire).parameters.values()
        supports_timeout = any(
            parameter.name == "timeout"
            or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
    except (TypeError, ValueError):
        supports_timeout = False

    if supports_timeout:
        return await pool.acquire(timeout=DB_ACQUIRE_TIMEOUT_SECONDS)
    return await asyncio.wait_for(
        pool.acquire(),
        timeout=DB_ACQUIRE_TIMEOUT_SECONDS,
    )


async def get_pool(request: Request):
    return request.app.state.pool


async def get_user_id(request: Request) -> str:
    """Authenticate via the startup-chosen provider (local mode), else Supabase JWKS."""
    auth_provider = request.app.state.auth_provider
    if auth_provider:
        return await auth_provider.get_current_user(request)
    from auth import get_current_user
    return await get_current_user(request)


async def get_user_service(request: Request):
    user_id = await get_user_id(request)
    return request.app.state.factory.user_service(user_id)


async def get_kb_service(request: Request):
    user_id = await get_user_id(request)
    return request.app.state.factory.kb_service(user_id)


async def get_document_service(request: Request):
    user_id = await get_user_id(request)
    return request.app.state.factory.document_service(user_id)


async def get_scoped_db(
    request: Request,
    pool: Annotated = Depends(get_pool),
) -> AsyncGenerator[ScopedDB, None]:
    """RLS-enforced Postgres connection for hosted-only routes."""
    from auth import get_current_user
    user_id = await get_current_user(request)
    conn = await _acquire_connection(pool)
    try:
        # RLS setup sits inside the transaction so any failure or cancel rolls back before release.
        async with conn.transaction():
            claims = json.dumps({"sub": user_id})
            await conn.execute("SET LOCAL ROLE authenticated")
            await conn.execute("SELECT set_config('request.jwt.claims', $1, true)", claims)
            yield ScopedDB(conn, user_id)
    finally:
        await asyncio.shield(pool.release(conn))
