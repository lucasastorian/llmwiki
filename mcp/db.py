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


async def _set_rls(conn, user_id: str, claims: dict | None = None):
    if claims:
        jwt_claims = {k: v for k, v in claims.items() if k in ("sub", "aud", "role", "client_id", "scope")}
        jwt_claims.setdefault("sub", user_id)
    else:
        jwt_claims = {"sub": user_id}
    await conn.execute("SET LOCAL ROLE authenticated")
    await conn.execute("SELECT set_config('request.jwt.claims', $1, true)", json.dumps(jwt_claims))


async def scoped_query(user_id: str, sql: str, *args, claims: dict | None = None) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _set_rls(conn, user_id, claims)
            rows = await conn.fetch(sql, *args)
            return [dict(r) for r in rows]


async def scoped_queryrow(user_id: str, sql: str, *args, claims: dict | None = None) -> dict | None:
    rows = await scoped_query(user_id, sql, *args, claims=claims)
    return rows[0] if rows else None


async def scoped_execute(user_id: str, sql: str, *args, claims: dict | None = None) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _set_rls(conn, user_id, claims)
            return await conn.execute(sql, *args)


async def service_queryrow(sql: str, *args) -> dict | None:
    """Execute a query as service role (bypasses RLS). For writes."""
    pool = await get_pool()
    row = await pool.fetchrow(sql, *args)
    return dict(row) if row else None


async def service_execute(sql: str, *args) -> str:
    """Execute a statement as service role (bypasses RLS). For writes."""
    pool = await get_pool()
    return await pool.execute(sql, *args)
