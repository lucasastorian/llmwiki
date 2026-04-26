"""Tier 2: Application-layer-only isolation tests.

These tests run through the full HTTP/FastAPI stack but with RLS DISABLED
(no SET LOCAL ROLE, no JWT claims on the connection). Only the application-
level WHERE user_id clauses protect data access.

If isolation holds here, the application layer works independently of RLS.
"""

import pytest

from tests.helpers.jwt import auth_headers
from tests.integration.isolation.conftest import (
    USER_A_ID, USER_B_ID,
    KB_A_ID, KB_B_ID,
    DOC_A_ID, DOC_A2_ID, DOC_B_ID,
    KEY_A_ID, KEY_B_ID,
    REF_B_ID,
)


class TestSanityCheck:
    """Verify that RLS is actually disabled — a raw pool query can see all rows."""

    async def test_pool_sees_both_tenants(self, pool):
        rows = await pool.fetch("SELECT slug FROM knowledge_bases ORDER BY slug")
        slugs = [r["slug"] for r in rows]
        assert "alice-kb" in slugs and "bob-kb" in slugs


class TestReadIsolationWithoutRLS:
    """Read routes should block cross-tenant access via WHERE user_id alone."""

    async def test_list_kbs_only_returns_own(self, client_no_rls):
        resp = await client_no_rls.get(
            "/v1/knowledge-bases", headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        slugs = [kb["slug"] for kb in resp.json()]
        assert "alice-kb" in slugs
        assert "bob-kb" not in slugs

    async def test_get_kb_cross_tenant_returns_404(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/knowledge-bases/{KB_B_ID}", headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404

    async def test_list_documents_cross_tenant_returns_empty(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/knowledge-bases/{KB_B_ID}/documents",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_document_cross_tenant_returns_404(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/documents/{DOC_B_ID}", headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404

    async def test_get_document_content_cross_tenant_returns_404(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/documents/{DOC_B_ID}/content", headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404

    async def test_get_document_url_cross_tenant_returns_404(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/documents/{DOC_B_ID}/url", headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404

    async def test_own_data_accessible(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/knowledge-bases/{KB_A_ID}", headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        assert resp.json()["slug"] == "alice-kb"

        resp = await client_no_rls.get(
            f"/v1/documents/{DOC_A_ID}", headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        assert resp.json()["filename"] == "notes.md"

        resp = await client_no_rls.get(
            f"/v1/documents/{DOC_A_ID}/content", headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "Alice secret content"


class TestWriteIsolationWithoutRLS:
    """Write routes should block cross-tenant access via WHERE user_id alone."""

    async def test_create_note_in_other_kb_returns_404(self, client_no_rls):
        resp = await client_no_rls.post(
            f"/v1/knowledge-bases/{KB_B_ID}/documents/note",
            headers=auth_headers(USER_A_ID),
            json={"filename": "injected.md", "content": "pwned"},
        )
        assert resp.status_code == 404

    async def test_update_content_cross_tenant_returns_404(self, client_no_rls):
        resp = await client_no_rls.put(
            f"/v1/documents/{DOC_B_ID}/content",
            headers=auth_headers(USER_A_ID),
            json={"content": "overwritten by alice"},
        )
        assert resp.status_code == 404

    async def test_update_content_does_not_modify(self, client_no_rls, pool):
        await client_no_rls.put(
            f"/v1/documents/{DOC_B_ID}/content",
            headers=auth_headers(USER_A_ID),
            json={"content": "overwritten by alice"},
        )
        row = await pool.fetchrow("SELECT content FROM documents WHERE id = $1", DOC_B_ID)
        assert row["content"] == "Bob secret content"

    async def test_update_metadata_cross_tenant_returns_404(self, client_no_rls):
        resp = await client_no_rls.patch(
            f"/v1/documents/{DOC_B_ID}",
            headers=auth_headers(USER_A_ID),
            json={"title": "Hacked"},
        )
        assert resp.status_code == 404

    async def test_delete_document_cross_tenant_returns_404(self, client_no_rls):
        resp = await client_no_rls.delete(
            f"/v1/documents/{DOC_B_ID}", headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404

    async def test_delete_document_does_not_archive(self, client_no_rls, pool):
        await client_no_rls.delete(
            f"/v1/documents/{DOC_B_ID}", headers=auth_headers(USER_A_ID),
        )
        row = await pool.fetchrow("SELECT archived FROM documents WHERE id = $1", DOC_B_ID)
        assert row["archived"] is False

    async def test_bulk_delete_does_not_archive(self, client_no_rls, pool):
        await client_no_rls.post(
            "/v1/documents/bulk-delete",
            headers=auth_headers(USER_A_ID),
            json={"ids": [str(DOC_B_ID)]},
        )
        row = await pool.fetchrow("SELECT archived FROM documents WHERE id = $1", DOC_B_ID)
        assert row["archived"] is False

    async def test_update_kb_cross_tenant_returns_404(self, client_no_rls):
        resp = await client_no_rls.patch(
            f"/v1/knowledge-bases/{KB_B_ID}",
            headers=auth_headers(USER_A_ID),
            json={"name": "Hijacked"},
        )
        assert resp.status_code == 404

    async def test_delete_kb_cross_tenant_returns_404(self, client_no_rls):
        resp = await client_no_rls.delete(
            f"/v1/knowledge-bases/{KB_B_ID}", headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404


class TestBidirectionalWithoutRLS:

    async def test_bob_cannot_access_alice_kb(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/knowledge-bases/{KB_A_ID}", headers=auth_headers(USER_B_ID),
        )
        assert resp.status_code == 404

    async def test_bob_cannot_access_alice_document(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/documents/{DOC_A_ID}", headers=auth_headers(USER_B_ID),
        )
        assert resp.status_code == 404

    async def test_bob_cannot_modify_alice_document(self, client_no_rls):
        resp = await client_no_rls.put(
            f"/v1/documents/{DOC_A_ID}/content",
            headers=auth_headers(USER_B_ID),
            json={"content": "overwritten by bob"},
        )
        assert resp.status_code == 404


class TestAPIKeyIsolationWithoutRLS:
    """API key list uses ScopedDB — tests app-layer WHERE with RLS disabled."""

    async def test_list_api_keys_only_returns_own(self, client_no_rls):
        resp = await client_no_rls.get("/v1/api-keys", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 200
        names = [k["name"] for k in resp.json()]
        assert "Alice Key" in names
        assert "Bob Key" not in names

    async def test_revoke_api_key_cross_tenant_returns_404(self, client_no_rls):
        resp = await client_no_rls.delete(
            f"/v1/api-keys/{KEY_B_ID}",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404


class TestGraphIsolationWithoutRLS:
    """Graph routes use ScopedDB — tests app-layer WHERE with RLS disabled."""

    async def test_get_graph_returns_own_nodes(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/knowledge-bases/{KB_A_ID}/graph",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        node_ids = {n["id"] for n in resp.json()["nodes"]}
        assert str(DOC_A_ID) in node_ids
        assert str(DOC_B_ID) not in node_ids

    async def test_get_graph_cross_tenant_returns_empty(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/knowledge-bases/{KB_B_ID}/graph",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []

    async def test_rebuild_graph_cross_tenant_does_not_delete_refs(self, client_no_rls, pool):
        """Alice rebuilding Bob's KB should not delete Bob's references."""
        before = await pool.fetchval(
            "SELECT COUNT(*) FROM document_references WHERE knowledge_base_id = $1", KB_B_ID,
        )
        assert before > 0
        await client_no_rls.post(
            f"/v1/knowledge-bases/{KB_B_ID}/graph/rebuild",
            headers=auth_headers(USER_A_ID),
        )
        after = await pool.fetchval(
            "SELECT COUNT(*) FROM document_references WHERE knowledge_base_id = $1", KB_B_ID,
        )
        assert after == before
