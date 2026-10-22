"""Global and per-user page-quota enforcement."""

import asyncpg
from config import settings


class PageQuota:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def check_global_limits(self) -> None:
        if not settings.GLOBAL_OCR_ENABLED:
            raise ValueError("OCR processing is temporarily disabled by the administrator.")

        total_pages = await self._count_platform_pages()
        if total_pages >= settings.GLOBAL_MAX_PAGES:
            raise ValueError(
                f"Platform page limit reached ({settings.GLOBAL_MAX_PAGES:,} pages). "
                "Please contact the administrator."
            )

    async def check_user_page_limit(
        self, user_id: str, new_pages: int, conn: asyncpg.Connection | None = None,
    ) -> None:
        """Quota check — uses an advisory lock when given a transaction connection so concurrent jobs serialize."""
        executor = conn or self._pool
        if conn is not None:
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1::text))", user_id,
            )
        row = await self._fetch_usage(executor, user_id)
        if not row:
            return
        limit = row["page_limit"]
        used = row["used"] or 0
        if used + new_pages > limit:
            raise ValueError(
                f"Page limit reached: this document adds {new_pages} pages, "
                f"you have {used}/{limit}. Delete documents or upgrade your plan."
            )

    async def _count_platform_pages(self) -> int:
        return await self._pool.fetchval(
            "SELECT COALESCE(SUM(page_count), 0) FROM documents WHERE NOT archived"
        )

    @staticmethod
    async def _fetch_usage(executor: asyncpg.Pool | asyncpg.Connection, user_id: str) -> asyncpg.Record | None:
        return await executor.fetchrow(
            "SELECT u.page_limit, "
            "COALESCE((SELECT SUM(page_count) FROM documents WHERE user_id = $1 AND NOT archived), 0)::bigint AS used "
            "FROM users u WHERE u.id = $1",
            user_id,
        )
