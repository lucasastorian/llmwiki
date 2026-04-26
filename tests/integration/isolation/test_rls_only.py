"""Tier 1: RLS-only isolation tests.

Every query here deliberately OMITS application-level user_id WHERE clauses.
If isolation holds, only Postgres Row-Level Security blocked cross-tenant access.
This proves RLS works independently of the application layer.
"""

import pytest

from tests.integration.isolation.conftest import (
    USER_A_ID, USER_B_ID,
    KB_A_ID, KB_B_ID,
    DOC_A_ID, DOC_B_ID,
    KEY_A_ID, KEY_B_ID,
)


class TestRLSBlocksKnowledgeBases:

    async def test_list_kbs_only_returns_own(self, rls_session):
        async with rls_session(USER_A_ID) as conn:
            rows = await conn.fetch("SELECT slug FROM knowledge_bases ORDER BY slug")
        slugs = [r["slug"] for r in rows]
        assert "alice-kb" in slugs
        assert "bob-kb" not in slugs

    async def test_get_other_kb_returns_nothing(self, rls_session):
        async with rls_session(USER_A_ID) as conn:
            row = await conn.fetchrow(
                "SELECT id FROM knowledge_bases WHERE id = $1", KB_B_ID,
            )
        assert row is None

    async def test_own_kb_visible(self, rls_session):
        async with rls_session(USER_A_ID) as conn:
            row = await conn.fetchrow(
                "SELECT slug FROM knowledge_bases WHERE id = $1", KB_A_ID,
            )
        assert row is not None
        assert row["slug"] == "alice-kb"


class TestRLSBlocksDocuments:

    async def test_list_documents_only_returns_own(self, rls_session):
        async with rls_session(USER_A_ID) as conn:
            rows = await conn.fetch("SELECT id, content FROM documents")
        ids = [str(r["id"]) for r in rows]
        assert DOC_A_ID in ids
        assert DOC_B_ID not in ids

    async def test_get_other_document_returns_nothing(self, rls_session):
        async with rls_session(USER_A_ID) as conn:
            row = await conn.fetchrow(
                "SELECT id, content FROM documents WHERE id = $1", DOC_B_ID,
            )
        assert row is None

    async def test_own_document_content_readable(self, rls_session):
        async with rls_session(USER_A_ID) as conn:
            row = await conn.fetchrow(
                "SELECT content FROM documents WHERE id = $1", DOC_A_ID,
            )
        assert row is not None
        assert row["content"] == "Alice secret content"

    async def test_cross_tenant_content_not_leaked(self, rls_session):
        """Even a broad SELECT cannot leak Bob's content to Alice."""
        async with rls_session(USER_A_ID) as conn:
            rows = await conn.fetch("SELECT content FROM documents")
        contents = [r["content"] for r in rows]
        assert "Bob secret content" not in contents


class TestRLSBlocksDocumentChunks:

    async def test_chunks_only_returns_own(self, rls_session):
        from tests.integration.isolation.conftest import CHUNK_A_ID, CHUNK_B_ID
        async with rls_session(USER_A_ID) as conn:
            rows = await conn.fetch("SELECT id FROM document_chunks")
        ids = [str(r["id"]) for r in rows]
        assert CHUNK_A_ID in ids
        assert CHUNK_B_ID not in ids

    async def test_other_chunk_not_visible(self, rls_session):
        from tests.integration.isolation.conftest import CHUNK_B_ID
        async with rls_session(USER_A_ID) as conn:
            row = await conn.fetchrow(
                "SELECT id FROM document_chunks WHERE id = $1", CHUNK_B_ID,
            )
        assert row is None


class TestRLSBlocksAPIKeys:

    async def test_list_api_keys_only_returns_own(self, rls_session):
        async with rls_session(USER_A_ID) as conn:
            rows = await conn.fetch("SELECT id, name FROM api_keys")
        names = [r["name"] for r in rows]
        assert "Alice Key" in names
        assert "Bob Key" not in names

    async def test_other_api_key_not_visible(self, rls_session):
        async with rls_session(USER_A_ID) as conn:
            row = await conn.fetchrow(
                "SELECT id FROM api_keys WHERE id = $1", KEY_B_ID,
            )
        assert row is None


class TestRLSBidirectional:
    """Same checks from Bob's perspective."""

    async def test_bob_cannot_see_alice_kb(self, rls_session):
        async with rls_session(USER_B_ID) as conn:
            row = await conn.fetchrow(
                "SELECT id FROM knowledge_bases WHERE id = $1", KB_A_ID,
            )
        assert row is None

    async def test_bob_cannot_see_alice_document(self, rls_session):
        async with rls_session(USER_B_ID) as conn:
            row = await conn.fetchrow(
                "SELECT id FROM documents WHERE id = $1", DOC_A_ID,
            )
        assert row is None

    async def test_bob_sees_own_data(self, rls_session):
        async with rls_session(USER_B_ID) as conn:
            kb = await conn.fetchrow(
                "SELECT slug FROM knowledge_bases WHERE id = $1", KB_B_ID,
            )
            doc = await conn.fetchrow(
                "SELECT content FROM documents WHERE id = $1", DOC_B_ID,
            )
        assert kb["slug"] == "bob-kb"
        assert doc["content"] == "Bob secret content"
