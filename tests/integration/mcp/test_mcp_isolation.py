"""MCP PostgresVaultFS multi-tenant isolation tests.

Verifies that PostgresVaultFS operations for User A cannot access User B's
data, and vice versa. Tests both read and write isolation at the VaultFS layer.
"""

import os
import json

import asyncpg
import pytest

# MCP path already added by tests/integration/mcp/conftest.py
from vaultfs.postgres import PostgresVaultFS
import db as mcp_db

USER_A_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

KB_A_ID = "11111111-1111-1111-1111-111111111111"
KB_B_ID = "22222222-2222-2222-2222-222222222222"

DOC_A_ID = "aaaa1111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DOC_B_ID = "bbbb1111-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

DOC_A2_ID = "aaaa4444-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DOC_B2_ID = "bbbb4444-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

REF_A_ID = "aaaa3333-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
REF_B_ID = "bbbb3333-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture(scope="session")
async def pg_pool():
    """Shared Postgres pool for MCP isolation tests.

    Reuses the same test DB and schema as the API isolation tests.
    """
    from pathlib import Path
    db_url = os.environ["DATABASE_URL"]
    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=5)

    await pool.execute("DROP SCHEMA IF EXISTS public CASCADE")
    await pool.execute("CREATE SCHEMA public")
    schema_sql = (Path(__file__).parent.parent.parent / "helpers" / "schema.sql").read_text()
    await pool.execute(schema_sql)

    yield pool
    pool.terminate()


@pytest.fixture(autouse=True)
async def seed_and_bind_pool(pg_pool):
    """Seed two tenants and point mcp.db's global pool at the test pool."""
    # Point mcp/db.py's global _pool at our test pool
    mcp_db._pool = pg_pool

    # Clean + seed (mirrors isolation/conftest.py)
    await pg_pool.execute("DELETE FROM document_references")
    await pg_pool.execute("DELETE FROM document_chunks")
    await pg_pool.execute("DELETE FROM document_pages")
    await pg_pool.execute("DELETE FROM documents")
    await pg_pool.execute("DELETE FROM api_keys")
    await pg_pool.execute("DELETE FROM knowledge_bases")
    await pg_pool.execute("DELETE FROM users")

    await pg_pool.execute(
        "INSERT INTO users (id, email, display_name) VALUES ($1, 'alice@test.com', 'Alice')",
        USER_A_ID,
    )
    await pg_pool.execute(
        "INSERT INTO users (id, email, display_name) VALUES ($1, 'bob@test.com', 'Bob')",
        USER_B_ID,
    )
    await pg_pool.execute(
        "INSERT INTO knowledge_bases (id, user_id, name, slug) VALUES ($1, $2, 'Alice KB', 'alice-kb')",
        KB_A_ID, USER_A_ID,
    )
    await pg_pool.execute(
        "INSERT INTO knowledge_bases (id, user_id, name, slug) VALUES ($1, $2, 'Bob KB', 'bob-kb')",
        KB_B_ID, USER_B_ID,
    )
    await pg_pool.execute(
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, "
        "file_type, status, content, version) "
        "VALUES ($1, $2, $3, 'notes.md', 'Notes', '/wiki/', 'md', 'ready', 'Alice secret', 1)",
        DOC_A_ID, KB_A_ID, USER_A_ID,
    )
    await pg_pool.execute(
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, "
        "file_type, status, content, version) "
        "VALUES ($1, $2, $3, 'notes.md', 'Notes', '/wiki/', 'md', 'ready', 'Bob secret', 1)",
        DOC_B_ID, KB_B_ID, USER_B_ID,
    )
    await pg_pool.execute(
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, "
        "file_type, status, content, version) "
        "VALUES ($1, $2, $3, 'source.pdf', 'Source', '/', 'pdf', 'ready', NULL, 1)",
        DOC_A2_ID, KB_A_ID, USER_A_ID,
    )
    await pg_pool.execute(
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, "
        "file_type, status, content, version) "
        "VALUES ($1, $2, $3, 'source.pdf', 'Source', '/', 'pdf', 'ready', NULL, 1)",
        DOC_B2_ID, KB_B_ID, USER_B_ID,
    )
    await pg_pool.execute(
        "INSERT INTO document_references (id, source_document_id, target_document_id, "
        "knowledge_base_id, reference_type) VALUES ($1, $2, $3, $4, 'cites')",
        REF_A_ID, DOC_A_ID, DOC_A2_ID, KB_A_ID,
    )
    await pg_pool.execute(
        "INSERT INTO document_references (id, source_document_id, target_document_id, "
        "knowledge_base_id, reference_type) VALUES ($1, $2, $3, $4, 'cites')",
        REF_B_ID, DOC_B_ID, DOC_B2_ID, KB_B_ID,
    )

    # Document pages for get_pages / get_all_pages tests
    import uuid
    await pg_pool.execute(
        "INSERT INTO document_pages (id, document_id, page, content) VALUES ($1, $2, 1, 'Alice page 1')",
        str(uuid.uuid4()), DOC_A_ID,
    )
    await pg_pool.execute(
        "INSERT INTO document_pages (id, document_id, page, content) VALUES ($1, $2, 1, 'Bob page 1')",
        str(uuid.uuid4()), DOC_B_ID,
    )

    # Document chunks for search_chunks tests (note: PGroonga not available in test, but isolation still testable)
    long_content = "x " * 70
    await pg_pool.execute(
        "INSERT INTO document_chunks (id, document_id, user_id, knowledge_base_id, chunk_index, content, token_count) "
        "VALUES ($1, $2, $3, $4, 0, $5, 35)",
        str(uuid.uuid4()), DOC_A_ID, USER_A_ID, KB_A_ID, long_content,
    )
    await pg_pool.execute(
        "INSERT INTO document_chunks (id, document_id, user_id, knowledge_base_id, chunk_index, content, token_count) "
        "VALUES ($1, $2, $3, $4, 0, $5, 35)",
        str(uuid.uuid4()), DOC_B_ID, USER_B_ID, KB_B_ID, long_content,
    )

    # Set stale_since on Bob's wiki doc for find_stale_pages test
    await pg_pool.execute(
        "UPDATE documents SET stale_since = now() WHERE id = $1", DOC_B_ID,
    )

    yield

    mcp_db._pool = None


@pytest.fixture
def fs_alice():
    return PostgresVaultFS(USER_A_ID)


@pytest.fixture
def fs_bob():
    return PostgresVaultFS(USER_B_ID)


class TestReadIsolation:
    """PostgresVaultFS reads are scoped by user_id (RLS + app-layer WHERE)."""

    async def test_list_kbs_returns_only_own(self, fs_alice):
        kbs = await fs_alice.list_knowledge_bases()
        slugs = [kb["slug"] for kb in kbs]
        assert "alice-kb" in slugs
        assert "bob-kb" not in slugs

    async def test_resolve_kb_other_tenant_returns_none(self, fs_alice):
        result = await fs_alice.resolve_kb("bob-kb")
        assert result is None

    async def test_resolve_kb_own_returns_data(self, fs_alice):
        result = await fs_alice.resolve_kb("alice-kb")
        assert result is not None
        assert result["slug"] == "alice-kb"

    async def test_list_documents_other_kb_returns_empty(self, fs_alice):
        docs = await fs_alice.list_documents(str(KB_B_ID))
        assert docs == []

    async def test_list_documents_own_kb_returns_data(self, fs_alice):
        docs = await fs_alice.list_documents(str(KB_A_ID))
        assert len(docs) == 2

    async def test_get_document_other_tenant_returns_none(self, fs_alice):
        doc = await fs_alice.get_document(str(KB_B_ID), "notes.md", "/wiki/")
        assert doc is None

    async def test_find_document_by_name_other_tenant_returns_none(self, fs_alice):
        doc = await fs_alice.find_document_by_name(str(KB_B_ID), "notes.md")
        assert doc is None


class TestWriteIsolation:
    """PostgresVaultFS writes include WHERE user_id = $N (service-role)."""

    async def test_archive_documents_other_tenant_returns_zero(self, fs_alice, pg_pool):
        count = await fs_alice.archive_documents([str(DOC_B_ID)])
        assert count == 0
        # Verify Bob's doc is not archived
        row = await pg_pool.fetchrow("SELECT archived FROM documents WHERE id = $1", DOC_B_ID)
        assert row["archived"] is False

    async def test_update_document_other_tenant_does_not_modify(self, fs_alice, pg_pool):
        await fs_alice.update_document(str(DOC_B_ID), "pwned by alice")
        row = await pg_pool.fetchrow("SELECT content FROM documents WHERE id = $1", DOC_B_ID)
        assert row["content"] == "Bob secret"


class TestReferenceIsolation:
    """Reference mutations now use scoped_execute (RLS-enforced)."""

    async def test_delete_references_other_tenant_deletes_nothing(self, fs_alice, pg_pool):
        await fs_alice.delete_references(str(DOC_B_ID))
        # Bob's reference should still exist
        row = await pg_pool.fetchrow(
            "SELECT id FROM document_references WHERE id = $1", REF_B_ID,
        )
        assert row is not None

    async def test_upsert_reference_cross_tenant_kb_fails(self, fs_alice, pg_pool):
        """Inserting a reference into Bob's KB should fail silently (exception caught)."""
        await fs_alice.upsert_reference(
            str(DOC_A_ID), str(DOC_A2_ID), str(KB_B_ID), "cites", None,
        )
        # No new reference should exist in Bob's KB from Alice
        rows = await pg_pool.fetch(
            "SELECT id FROM document_references WHERE knowledge_base_id = $1",
            KB_B_ID,
        )
        ids = [str(r["id"]) for r in rows]
        assert ids == [REF_B_ID]  # Only Bob's original reference

    async def test_delete_own_references_works(self, fs_alice, pg_pool):
        await fs_alice.delete_references(str(DOC_A_ID))
        row = await pg_pool.fetchrow(
            "SELECT id FROM document_references WHERE id = $1", REF_A_ID,
        )
        assert row is None


class TestListDocumentsWithContentIsolation:

    async def test_list_with_content_other_kb_returns_empty(self, fs_alice):
        docs = await fs_alice.list_documents_with_content(str(KB_B_ID))
        assert docs == []

    async def test_list_with_content_own_kb_returns_data(self, fs_alice):
        docs = await fs_alice.list_documents_with_content(str(KB_A_ID))
        assert len(docs) == 2
        contents = [d.get("content") for d in docs if d.get("content")]
        assert "Alice secret" in contents


class TestPageIsolation:
    """get_pages / get_all_pages use RLS on document_pages."""

    async def test_get_pages_other_tenant_doc_returns_empty(self, fs_alice):
        pages = await fs_alice.get_pages(str(DOC_B_ID), [1])
        assert pages == []

    async def test_get_pages_own_doc_returns_data(self, fs_alice):
        pages = await fs_alice.get_pages(str(DOC_A_ID), [1])
        assert len(pages) == 1
        assert pages[0]["content"] == "Alice page 1"

    async def test_get_all_pages_other_tenant_doc_returns_empty(self, fs_alice):
        pages = await fs_alice.get_all_pages(str(DOC_B_ID))
        assert pages == []

    async def test_get_all_pages_own_doc_returns_data(self, fs_alice):
        pages = await fs_alice.get_all_pages(str(DOC_A_ID))
        assert len(pages) == 1


class TestGraphQueryIsolation:
    """Backlinks, forward references, uncited sources, stale pages."""

    async def test_get_backlinks_other_tenant_doc_returns_empty(self, fs_alice):
        # DOC_B2_ID is the target of Bob's reference — Alice shouldn't see it
        links = await fs_alice.get_backlinks(str(DOC_B2_ID))
        assert links == []

    async def test_get_backlinks_own_doc_returns_data(self, fs_alice):
        # DOC_A2_ID is the target of Alice's reference (DOC_A -> DOC_A2)
        links = await fs_alice.get_backlinks(str(DOC_A2_ID))
        assert len(links) == 1
        assert links[0]["filename"] == "notes.md"

    async def test_get_forward_references_other_tenant_doc_returns_empty(self, fs_alice):
        refs = await fs_alice.get_forward_references(str(DOC_B_ID))
        assert refs == []

    async def test_get_forward_references_own_doc_returns_data(self, fs_alice):
        refs = await fs_alice.get_forward_references(str(DOC_A_ID))
        assert len(refs) == 1
        assert refs[0]["filename"] == "source.pdf"

    async def test_find_uncited_sources_other_kb_returns_empty(self, fs_alice):
        sources = await fs_alice.find_uncited_sources(str(KB_B_ID))
        assert sources == []

    async def test_find_stale_pages_other_kb_returns_empty(self, fs_alice):
        stale = await fs_alice.find_stale_pages(str(KB_B_ID))
        assert stale == []

    async def test_find_stale_pages_own_kb_excludes_other_tenant(self, fs_alice):
        """Alice's KB has no stale pages (only Bob's doc is stale)."""
        stale = await fs_alice.find_stale_pages(str(KB_A_ID))
        assert stale == []


class TestPropagateStalenesIsolation:
    """propagate_staleness uses service_execute with WHERE user_id."""

    async def test_propagate_staleness_does_not_affect_other_tenant(self, fs_alice, pg_pool):
        """Alice propagating staleness for Bob's doc should not mark Alice's docs stale."""
        await fs_alice.propagate_staleness(str(DOC_B2_ID))
        row = await pg_pool.fetchrow(
            "SELECT stale_since FROM documents WHERE id = $1", DOC_A_ID,
        )
        assert row["stale_since"] is None


class TestBidirectional:
    """Verify isolation works from Bob's perspective too."""

    async def test_bob_cannot_see_alice_kb(self, fs_bob):
        result = await fs_bob.resolve_kb("alice-kb")
        assert result is None

    async def test_bob_cannot_list_alice_docs(self, fs_bob):
        docs = await fs_bob.list_documents(str(KB_A_ID))
        assert docs == []

    async def test_bob_cannot_archive_alice_doc(self, fs_bob, pg_pool):
        count = await fs_bob.archive_documents([str(DOC_A_ID)])
        assert count == 0
        row = await pg_pool.fetchrow("SELECT archived FROM documents WHERE id = $1", DOC_A_ID)
        assert row["archived"] is False

    async def test_bob_cannot_read_alice_pages(self, fs_bob):
        pages = await fs_bob.get_pages(str(DOC_A_ID), [1])
        assert pages == []

    async def test_bob_cannot_get_alice_backlinks(self, fs_bob):
        links = await fs_bob.get_backlinks(str(DOC_A2_ID))
        assert links == []
