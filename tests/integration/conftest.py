import os
from pathlib import Path

import asyncpg
import httpx
import pytest

from tests.helpers.jwt import seed_jwks_cache

DB_URL = os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
async def pool():
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=20)

    await pool.execute("DROP SCHEMA IF EXISTS public CASCADE")
    await pool.execute("CREATE SCHEMA public")

    schema_sql = (Path(__file__).parent.parent / "helpers" / "schema.sql").read_text()
    await pool.execute(schema_sql)

    yield pool
    pool.terminate()


@pytest.fixture
async def client(pool):
    from main import app

    app.state.pool = pool
    app.state.s3_service = None
    app.state.ocr_service = None

    seed_jwks_cache()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
