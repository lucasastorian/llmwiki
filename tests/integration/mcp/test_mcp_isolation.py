"""PostgresVaultFS tenant isolation; search_chunks is skipped because the test Postgres lacks PGroonga's `&@~`."""

import json
import os
import uuid

import asyncpg
import db as mcp_db
import pytest
from vaultfs.base import StorageQuotaExceededError
from vaultfs.postgres import PostgresVaultFS

USER_A_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

KB_A_ID = "11111111-1111-1111-1111-111111111111"
KB_B_ID = "22222222-2222-2222-2222-222222222222"

DOC_A_ID = "aaaa1111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DOC_B_ID = "bbbb1111-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

DOC_A2_ID = "aaaa4444-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DOC_B2_ID = "bbbb4444-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

ASSET_A_ID = "aaaa5555-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ASSET_B_ID = "bbbb5555-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

REF_A_ID = "aaaa3333-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
REF_B_ID = "bbbb3333-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture(scope="session")
async def pg_pool():
    """Shared pool on the same test DB and schema as the API isolation tests."""
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
    mcp_db._pool = pg_pool

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
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, "
        "file_type, status, content, version, metadata) "
        "VALUES ($1, $2, $3, 'image-01.png', 'image-01.png', '/webclipper/clip.assets/', "
        "'png', 'ready', NULL, 1, '{\"asset\": true}'::jsonb)",
        ASSET_A_ID, KB_A_ID, USER_A_ID,
    )
    await pg_pool.execute(
        "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, "
        "file_type, status, content, version, metadata) "
        "VALUES ($1, $2, $3, 'image-01.png', 'image-01.png', '/webclipper/clip.assets/', "
        "'png', 'ready', NULL, 1, '{\"asset\": true}'::jsonb)",
        ASSET_B_ID, KB_B_ID, USER_B_ID,
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

    await pg_pool.execute(
        "INSERT INTO document_pages (id, document_id, page, content) VALUES ($1, $2, 1, 'Alice page 1')",
        str(uuid.uuid4()), DOC_A_ID,
    )
    await pg_pool.execute(
        "INSERT INTO document_pages (id, document_id, page, content) VALUES ($1, $2, 1, 'Bob page 1')",
        str(uuid.uuid4()), DOC_B_ID,
    )

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

    async def test_load_asset_bytes_other_tenant_returns_none(self, fs_alice, monkeypatch):
        calls: list[str] = []

        async def fake_load_s3(self, key):
            calls.append(key)
            return b"asset-bytes"

        monkeypatch.setattr(PostgresVaultFS, "_load_s3", fake_load_s3)

        data = await fs_alice.load_asset_bytes(str(ASSET_B_ID))

        assert data is None
        assert calls == []

    async def test_load_asset_bytes_own_tenant_uses_own_s3_prefix(self, fs_alice, monkeypatch):
        calls: list[str] = []

        async def fake_load_s3(self, key):
            calls.append(key)
            return b"asset-bytes"

        monkeypatch.setattr(PostgresVaultFS, "_load_s3", fake_load_s3)

        data = await fs_alice.load_asset_bytes(str(ASSET_A_ID))

        assert data == b"asset-bytes"
        assert calls == [f"{USER_A_ID}/{ASSET_A_ID}/source.png"]


class TestWriteIsolation:
    """PostgresVaultFS writes include WHERE user_id = $N (service-role)."""

    async def test_archive_documents_other_tenant_returns_zero(self, fs_alice, pg_pool):
        count = await fs_alice.archive_documents([str(DOC_B_ID)])
        assert count == 0
        row = await pg_pool.fetchrow("SELECT archived FROM documents WHERE id = $1", DOC_B_ID)
        assert row["archived"] is False

    async def test_archive_mixed_batch_archives_only_own(self, fs_alice, pg_pool):
        count = await fs_alice.archive_documents([str(DOC_A2_ID), str(DOC_B2_ID)])
        assert count == 1
        rows = await pg_pool.fetch(
            "SELECT id, archived FROM documents WHERE id = ANY($1::uuid[])",
            [DOC_A2_ID, DOC_B2_ID],
        )
        archived = {str(r["id"]): r["archived"] for r in rows}
        assert archived[DOC_A2_ID] is True
        assert archived[DOC_B2_ID] is False

    async def test_update_document_other_tenant_does_not_modify(self, fs_alice, pg_pool):
        result = await fs_alice.update_document(str(DOC_B_ID), "pwned by alice")
        assert result is None
        row = await pg_pool.fetchrow("SELECT content FROM documents WHERE id = $1", DOC_B_ID)
        assert row["content"] == "Bob secret"

    async def test_update_knowledge_base_other_tenant_does_not_modify(self, fs_alice, pg_pool):
        result = await fs_alice.update_knowledge_base(str(KB_B_ID), kind="course")
        assert result is None
        row = await pg_pool.fetchrow("SELECT kind FROM knowledge_bases WHERE id = $1", KB_B_ID)
        assert row["kind"] == "wiki"

    async def test_update_knowledge_base_rename_other_tenant_does_not_modify(self, fs_alice, pg_pool):
        result = await fs_alice.update_knowledge_base(str(KB_B_ID), name="Pwned")
        assert result is None
        row = await pg_pool.fetchrow("SELECT name FROM knowledge_bases WHERE id = $1", KB_B_ID)
        assert row["name"] != "Pwned"

    async def test_update_knowledge_base_rename_own_regenerates_slug(self, fs_alice, pg_pool):
        updated = await fs_alice.update_knowledge_base(str(KB_A_ID), name="Deep Learning Notes")
        assert updated["name"] == "Deep Learning Notes"
        assert updated["slug"] == "deep-learning-notes"
        row = await pg_pool.fetchrow("SELECT slug, kind FROM knowledge_bases WHERE id = $1", KB_A_ID)
        assert row["slug"] == "deep-learning-notes"
        assert row["kind"] == "wiki"

    async def test_update_knowledge_base_rename_to_same_slug_keeps_it(self, fs_alice):
        first = await fs_alice.update_knowledge_base(str(KB_A_ID), name="Deep Learning Notes")
        again = await fs_alice.update_knowledge_base(str(KB_A_ID), name="Deep learning notes")
        assert again["slug"] == first["slug"] == "deep-learning-notes"

    async def test_create_document_into_other_tenant_kb_rejected(self, fs_alice, pg_pool):
        """create_document writes into the caller's own KB but refuses a foreign one."""
        own = await fs_alice.create_document(
            str(KB_A_ID), "mine.md", "Mine", "/wiki/", "md", "x", ["t"],
        )
        assert own["filename"] == "mine.md"

        with pytest.raises(PermissionError):
            await fs_alice.create_document(
                str(KB_B_ID), "sneak.md", "Sneak", "/wiki/", "md", "x", ["t"],
            )
        rows = await pg_pool.fetch("SELECT id FROM documents WHERE filename = 'sneak.md'")
        assert rows == []


class TestTextStorageAccounting:
    async def test_create_tracks_utf8_file_size(self, fs_alice, pg_pool):
        doc = await fs_alice.create_document(
            str(KB_A_ID), "unicode.md", "Unicode", "/wiki/", "md", "hé", ["t"],
        )

        assert await pg_pool.fetchval(
            "SELECT file_size FROM documents WHERE id = $1",
            doc["id"],
        ) == len("hé".encode())

    async def test_create_rejects_quota_without_inserting(self, fs_alice, pg_pool):
        await pg_pool.execute(
            "UPDATE users SET storage_limit_bytes = 3 WHERE id = $1",
            USER_A_ID,
        )

        with pytest.raises(StorageQuotaExceededError):
            await fs_alice.create_document(
                str(KB_A_ID), "too-large.md", "Too Large", "/wiki/", "md", "four", ["t"],
            )

        assert await pg_pool.fetchval(
            "SELECT COUNT(*) FROM documents WHERE filename = 'too-large.md'",
        ) == 0

    async def test_update_quota_failure_is_atomic(self, fs_alice, pg_pool):
        await pg_pool.execute(
            "UPDATE documents SET file_size = 1 WHERE id = $1",
            DOC_A_ID,
        )
        await pg_pool.execute(
            "UPDATE users SET storage_limit_bytes = 2 WHERE id = $1",
            USER_A_ID,
        )

        with pytest.raises(StorageQuotaExceededError):
            await fs_alice.update_document(DOC_A_ID, "abc")

        row = await pg_pool.fetchrow(
            "SELECT content, file_size FROM documents WHERE id = $1",
            DOC_A_ID,
        )
        assert dict(row) == {"content": "Alice secret", "file_size": 1}

    async def test_update_clears_the_pages_own_stale_flag(self, fs_alice, pg_pool):
        await pg_pool.execute("UPDATE documents SET stale_since = now() WHERE id = $1", DOC_A_ID)

        await fs_alice.update_document(DOC_A_ID, "refreshed body")

        assert await pg_pool.fetchval("SELECT stale_since FROM documents WHERE id = $1", DOC_A_ID) is None

    async def test_update_merges_frontmatter_metadata_into_app_state(self, fs_alice, pg_pool):
        await pg_pool.execute(
            "UPDATE documents SET metadata = $1::jsonb WHERE id = $2",
            '{"course": {"status": "complete"}, "source_url": "https://example.com", "description": "old"}',
            DOC_A_ID,
        )

        await fs_alice.update_document(DOC_A_ID, "new body", metadata={})

        metadata = json.loads(await pg_pool.fetchval("SELECT metadata FROM documents WHERE id = $1", DOC_A_ID))
        assert metadata == {"course": {"status": "complete"}, "source_url": "https://example.com"}


class TestReplyIsolation:
    """add_highlight_reply is scoped by user_id in both the lock and the write."""

    REPLY = {"id": "r-test", "author": "agent", "text": "reply", "createdAt": "2026-07-09T00:00:00Z"}

    async def _seed_highlight(self, pg_pool, doc_id: str) -> None:
        await pg_pool.execute(
            "UPDATE documents SET highlights = $1::jsonb WHERE id = $2",
            '[{"id": "h1", "type": "text", "comment": "a note", '
            '"textAnchor": {"textStart": 0, "textEnd": 4, "textContent": "text"}}]',
            doc_id,
        )

    async def test_reply_to_other_tenant_highlight_returns_none(self, fs_alice, pg_pool):
        await self._seed_highlight(pg_pool, DOC_B_ID)
        result = await fs_alice.add_highlight_reply(str(DOC_B_ID), "h1", dict(self.REPLY))
        assert result is None
        row = await pg_pool.fetchrow("SELECT highlights, version FROM documents WHERE id = $1", DOC_B_ID)
        assert "r-test" not in (row["highlights"] or "")
        assert row["version"] == 1

    async def test_reply_to_own_highlight_persists_and_bumps_version(self, fs_bob, pg_pool):
        await self._seed_highlight(pg_pool, DOC_B_ID)
        result = await fs_bob.add_highlight_reply(str(DOC_B_ID), "h1", dict(self.REPLY))
        assert result is not None
        assert result["replies"][0]["id"] == "r-test"
        row = await pg_pool.fetchrow("SELECT highlights, version FROM documents WHERE id = $1", DOC_B_ID)
        assert "r-test" in row["highlights"]
        assert row["version"] == 2


class TestReferenceIsolation:
    """Reference mutations are RLS-enforced."""

    async def test_replace_references_is_bulk_and_scoped(self, fs_alice, pg_pool):
        await fs_alice.replace_references(
            str(DOC_A_ID),
            str(KB_A_ID),
            [(str(DOC_A2_ID), "links_to", None)],
        )
        rows = await pg_pool.fetch(
            "SELECT reference_type FROM document_references WHERE source_document_id = $1",
            DOC_A_ID,
        )
        assert [row["reference_type"] for row in rows] == ["links_to"]
        bob = await pg_pool.fetchrow(
            "SELECT id FROM document_references WHERE id = $1", REF_B_ID,
        )
        assert bob is not None

    async def test_replace_references_cannot_clear_other_tenants_edges(self, fs_alice, pg_pool):
        await fs_alice.replace_references(str(DOC_B_ID), str(KB_B_ID), [])

        row = await pg_pool.fetchrow("SELECT id FROM document_references WHERE id = $1", REF_B_ID)
        assert row is not None

    async def test_replace_references_cannot_write_into_other_tenants_kb(self, fs_alice, pg_pool):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await fs_alice.replace_references(
                str(DOC_A_ID), str(KB_B_ID), [(str(DOC_A2_ID), "cites", None)],
            )

        bob_kb = await pg_pool.fetch(
            "SELECT id::text FROM document_references WHERE knowledge_base_id = $1", KB_B_ID,
        )
        assert [r["id"] for r in bob_kb] == [REF_B_ID]
        alice_ref = await pg_pool.fetchrow("SELECT id FROM document_references WHERE id = $1", REF_A_ID)
        assert alice_ref is not None


class TestListDocumentsWithContentIsolation:

    async def test_list_with_content_other_kb_returns_empty(self, fs_alice):
        docs = await fs_alice.list_documents_with_content(str(KB_B_ID))
        assert docs == []

    async def test_list_with_content_own_kb_returns_data(self, fs_alice):
        docs = await fs_alice.list_documents_with_content(str(KB_A_ID))
        assert len(docs) == 2
        contents = [d.get("content") for d in docs if d.get("content")]
        assert "Alice secret" in contents

    async def test_path_filter_and_content_budget_are_applied_in_postgres(self, fs_alice):
        docs = await fs_alice.list_documents_with_content(
            str(KB_A_ID),
            path_glob="/wiki/**",
            content_limit=5,
        )
        assert [doc["filename"] for doc in docs] == ["notes.md"]
        assert docs[0]["content"] == "Alice"
        assert docs[0]["content_truncated"] is True


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

    async def test_get_pages_for_batch_is_bounded_and_scoped(self, fs_alice):
        pages = await fs_alice.get_pages_for_batch(str(DOC_A_ID), 5)
        assert len(pages) == 1
        assert pages[0]["content"] == "Alice"
        assert pages[0]["content_truncated"] is True
        assert await fs_alice.get_pages_for_batch(str(DOC_B_ID), 5) == []


class TestGraphQueryIsolation:

    async def test_get_backlinks_other_tenant_doc_returns_empty(self, fs_alice):
        """DOC_B2 is the target of Bob's citation; Alice sees no backlinks to it."""
        links = await fs_alice.get_backlinks(str(DOC_B2_ID))
        assert links == []

    async def test_get_backlinks_own_doc_returns_data(self, fs_alice):
        """DOC_A2 is the target of Alice's citation (DOC_A cites DOC_A2)."""
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

    async def test_get_reference_edges_returns_only_own_kb(self, fs_alice):
        edges = await fs_alice.get_reference_edges(str(KB_A_ID))
        assert [(edge["source_id"], edge["target_id"]) for edge in edges] == [
            (str(DOC_A_ID), str(DOC_A2_ID))
        ]
        assert await fs_alice.get_reference_edges(str(KB_B_ID)) == []

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
        await fs_alice.propagate_staleness(str(DOC_B2_ID))
        row = await pg_pool.fetchrow(
            "SELECT stale_since FROM documents WHERE id = $1", DOC_A_ID,
        )
        assert row["stale_since"] is None


class TestBidirectional:

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
