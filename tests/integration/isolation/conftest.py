import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import Request

from scoped_db import ScopedDB
from tests.helpers.jwt import auth_headers, seed_jwks_cache

USER_A_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_A_EMAIL = "alice@test.com"

USER_B_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_B_EMAIL = "bob@test.com"

KB_A_ID = "11111111-1111-1111-1111-111111111111"
KB_B_ID = "22222222-2222-2222-2222-222222222222"

DOC_A_ID = "aaaa1111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DOC_B_ID = "bbbb1111-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

CHUNK_A_ID = "cccc1111-cccc-cccc-cccc-cccccccccccc"
CHUNK_B_ID = "dddd1111-dddd-dddd-dddd-dddddddddddd"

KEY_A_ID = "eeee1111-eeee-eeee-eeee-eeeeeeeeeeee"
KEY_B_ID = "ffff1111-ffff-ffff-ffff-ffffffffffff"

PAGE_A_ID = "aaaa2222-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
PAGE_B_ID = "bbbb2222-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

REF_A_ID = "aaaa3333-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
REF_B_ID = "bbbb3333-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

# Second doc per tenant — needed as reference targets
DOC_A2_ID = "aaaa4444-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DOC_B2_ID = "bbbb4444-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture(autouse=True)
async def seed_two_tenants(pool):
    await pool.execute("DELETE FROM document_references")
    await pool.execute("DELETE FROM document_chunks")
    await pool.execute("DELETE FROM document_pages")
    await pool.execute("DELETE FROM documents")
    await pool.execute("DELETE FROM api_keys")
    await pool.execute("DELETE FROM knowledge_bases")
    await pool.execute("DELETE FROM users")

    await pool.execute(
        "INSERT INTO users (id, email, display_name) VALUES ($1, $2, 'Alice')",
        USER_A_ID, USER_A_EMAIL,
    )
    await pool.execute(
        "INSERT INTO users (id, email, display_name) VALUES ($1, $2, 'Bob')",
        USER_B_ID, USER_B_EMAIL,
    )

    await pool.execute(
        "INSERT INTO knowledge_bases (id, user_id, name, slug) VALUES ($1, $2, 'Alice KB', 'alice-kb')",
        KB_A_ID, USER_A_ID,
    )
    await pool.execute(
        "INSERT INTO knowledge_bases (id, user_id, name, slug) VALUES ($1, $2, 'Bob KB', 'bob-kb')",
        KB_B_ID, USER_B_ID,
    )

    await pool.execute(
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, file_type, status, content, version, page_count, file_size) "
        "VALUES ($1, $2, $3, 'notes.md', 'Notes', '/wiki/', 'md', 'ready', 'Alice secret content', 1, 3, 1024)",
        DOC_A_ID, KB_A_ID, USER_A_ID,
    )
    await pool.execute(
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, file_type, status, content, version, page_count, file_size) "
        "VALUES ($1, $2, $3, 'notes.md', 'Notes', '/wiki/', 'md', 'ready', 'Bob secret content', 1, 10, 5000)",
        DOC_B_ID, KB_B_ID, USER_B_ID,
    )

    long_content = "x " * 70
    await pool.execute(
        "INSERT INTO document_chunks (id, document_id, user_id, knowledge_base_id, chunk_index, content, token_count) "
        "VALUES ($1, $2, $3, $4, 0, $5, 35)",
        CHUNK_A_ID, DOC_A_ID, USER_A_ID, KB_A_ID, long_content,
    )
    await pool.execute(
        "INSERT INTO document_chunks (id, document_id, user_id, knowledge_base_id, chunk_index, content, token_count) "
        "VALUES ($1, $2, $3, $4, 0, $5, 35)",
        CHUNK_B_ID, DOC_B_ID, USER_B_ID, KB_B_ID, long_content,
    )

    await pool.execute(
        "INSERT INTO api_keys (id, user_id, name, key_hash, key_prefix) VALUES ($1, $2, 'Alice Key', 'hash_a', 'sv_alice')",
        KEY_A_ID, USER_A_ID,
    )
    await pool.execute(
        "INSERT INTO api_keys (id, user_id, name, key_hash, key_prefix) VALUES ($1, $2, 'Bob Key', 'hash_b', 'sv_bob__')",
        KEY_B_ID, USER_B_ID,
    )

    # ── Second docs (reference targets) ──
    await pool.execute(
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, file_type, status, content, version) "
        "VALUES ($1, $2, $3, 'source.pdf', 'Source', '/', 'pdf', 'ready', NULL, 1)",
        DOC_A2_ID, KB_A_ID, USER_A_ID,
    )
    await pool.execute(
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, file_type, status, content, version) "
        "VALUES ($1, $2, $3, 'source.pdf', 'Source', '/', 'pdf', 'ready', NULL, 1)",
        DOC_B2_ID, KB_B_ID, USER_B_ID,
    )

    # ── Document pages ──
    await pool.execute(
        "INSERT INTO document_pages (id, document_id, page, content) VALUES ($1, $2, 1, 'Alice page 1 content')",
        PAGE_A_ID, DOC_A_ID,
    )
    await pool.execute(
        "INSERT INTO document_pages (id, document_id, page, content) VALUES ($1, $2, 1, 'Bob page 1 content')",
        PAGE_B_ID, DOC_B_ID,
    )

    # ── Document references ──
    await pool.execute(
        "INSERT INTO document_references (id, source_document_id, target_document_id, knowledge_base_id, reference_type) "
        "VALUES ($1, $2, $3, $4, 'cites')",
        REF_A_ID, DOC_A_ID, DOC_A2_ID, KB_A_ID,
    )
    await pool.execute(
        "INSERT INTO document_references (id, source_document_id, target_document_id, knowledge_base_id, reference_type) "
        "VALUES ($1, $2, $3, $4, 'cites')",
        REF_B_ID, DOC_B_ID, DOC_B2_ID, KB_B_ID,
    )

    yield


# ── Tier 1 fixture: RLS-enforced DB session (no application-level user_id) ──

def _quote_literal(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


@pytest.fixture
def rls_session(pool):
    """Return an async context manager that yields a raw asyncpg connection
    with RLS active for a given user_id.  No application-level WHERE user_id
    clauses — only RLS protects the query."""

    @asynccontextmanager
    async def _session(user_id: str):
        conn = await pool.acquire()
        tr = conn.transaction()
        await tr.start()
        try:
            claims = json.dumps({"sub": user_id})
            await conn.execute("SET LOCAL ROLE authenticated")
            await conn.execute(
                f"SET LOCAL request.jwt.claims = {_quote_literal(claims)}"
            )
            yield conn
            await tr.commit()
        except Exception:
            await tr.rollback()
            raise
        finally:
            await pool.release(conn)

    return _session


# ── Tier 2 fixture: HTTP client with RLS disabled (application layer only) ──

@pytest.fixture
async def client_no_rls(pool):
    """HTTP client where get_scoped_db skips RLS setup (no SET LOCAL ROLE,
    no JWT claims).  Only the application-level WHERE user_id clauses
    protect data access."""
    import deps
    from main import app
    from services.hosted import HostedServiceFactory

    async def _unscoped_db(request: Request):
        from auth import get_current_user
        user_id = await get_current_user(request)
        _pool = request.app.state.pool
        conn = await _pool.acquire()
        tr = conn.transaction()
        await tr.start()
        try:
            # Intentionally NO role switch or JWT claims — RLS is inactive
            yield ScopedDB(_pool, conn, user_id)
            await tr.commit()
        except Exception:
            await tr.rollback()
            raise
        finally:
            await _pool.release(conn)

    app.state.pool = pool
    app.state.s3_service = None
    app.state.ocr_service = None
    app.state.auth_provider = None
    app.state.factory = HostedServiceFactory(pool)
    seed_jwks_cache()

    app.dependency_overrides[deps.get_scoped_db] = _unscoped_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(deps.get_scoped_db, None)
