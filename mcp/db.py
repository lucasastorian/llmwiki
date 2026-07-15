import asyncio
from contextlib import asynccontextmanager
import json

import asyncpg

from config import settings

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                _pool = await asyncpg.create_pool(
                    settings.DATABASE_URL, min_size=1, max_size=5, command_timeout=15,
                )
    return _pool


async def _set_rls(conn, user_id: str, claims: dict | None = None):
    if claims:
        jwt_claims = {k: v for k, v in claims.items() if k in ("sub", "aud", "client_id", "scope")}
        jwt_claims.setdefault("sub", user_id)
    else:
        jwt_claims = {"sub": user_id}
    # Pin the role rather than trusting the token claim — these connections are
    # always user-scoped, and auth.role() drives RLS policy evaluation.
    jwt_claims["role"] = "authenticated"
    await conn.execute("SET LOCAL ROLE authenticated")
    await conn.execute("SELECT set_config('request.jwt.claims', $1, true)", json.dumps(jwt_claims))


@asynccontextmanager
async def scoped_connection(user_id: str, claims: dict | None = None):
    """Yield one RLS-scoped connection for a multi-statement operation."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await _set_rls(conn, user_id, claims)
        yield conn


async def scoped_query(user_id: str, sql: str, *args, claims: dict | None = None) -> list[dict]:
    async with scoped_connection(user_id, claims) as conn:
        rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]


async def scoped_queryrow(user_id: str, sql: str, *args, claims: dict | None = None) -> dict | None:
    rows = await scoped_query(user_id, sql, *args, claims=claims)
    return rows[0] if rows else None


async def scoped_execute(user_id: str, sql: str, *args, claims: dict | None = None) -> str:
    async with scoped_connection(user_id, claims) as conn:
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
