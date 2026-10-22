import asyncpg


class ScopedDB:
    __slots__ = ("_conn", "_user_id")

    def __init__(self, conn: asyncpg.Connection, user_id: str):
        assert user_id
        self._conn = conn
        self._user_id = user_id

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def conn(self) -> asyncpg.Connection:
        return self._conn

    async def fetchrow(self, sql: str, *args) -> dict | None:
        row = await self._conn.fetchrow(sql, *args)
        return dict(row) if row else None

    async def fetch(self, sql: str, *args) -> list[dict]:
        return [dict(r) for r in await self._conn.fetch(sql, *args)]

    async def fetchval(self, sql: str, *args):
        return await self._conn.fetchval(sql, *args)

    async def execute(self, sql: str, *args) -> str:
        return await self._conn.execute(sql, *args)
