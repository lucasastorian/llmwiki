import json

import asyncpg

from config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.DATABASE_URL, min_size=1, max_size=5, command_timeout=15,
        )
    return _pool


async def _set_rls(conn, user_id: str):
    claims = json.dumps({"sub": user_id})
    await conn.execute("SET LOCAL ROLE authenticated")
    await conn.execute("SELECT set_config('request.jwt.claims', $1, true)", claims)


async def scoped_query(user_id: str, sql: str, *args) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _set_rls(conn, user_id)
            rows = await conn.fetch(sql, *args)
            return [dict(r) for r in rows]


async def scoped_queryrow(user_id: str, sql: str, *args) -> dict | None:
    rows = await scoped_query(user_id, sql, *args)
    return rows[0] if rows else None


async def scoped_execute(user_id: str, sql: str, *args) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _set_rls(conn, user_id)
            return await conn.execute(sql, *args)
