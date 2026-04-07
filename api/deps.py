import json
from typing import Annotated, AsyncGenerator

import asyncpg
from fastapi import Depends, Request

from auth import get_current_user
from scoped_db import ScopedDB


def _quote_literal(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


async def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


async def get_user_id(request: Request) -> str:
    """Authenticate and return user_id. No RLS — for routes that use pool directly."""
    return await get_current_user(request)


async def get_scoped_db(
    request: Request,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> AsyncGenerator[ScopedDB, None]:
    """Read-only scoped DB with RLS enforced. For SELECT routes only."""
    user_id = await get_current_user(request)
    conn = await pool.acquire()
    tr = conn.transaction()
    await tr.start()
    try:
        claims = json.dumps({"sub": user_id})
        await conn.execute("SET LOCAL ROLE authenticated")
        await conn.execute(f"SET LOCAL request.jwt.claims = {_quote_literal(claims)}")
        yield ScopedDB(pool, conn, user_id)
        await tr.commit()
    except Exception:
        await tr.rollback()
        raise
    finally:
        await pool.release(conn)
