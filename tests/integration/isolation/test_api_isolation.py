"""API tenant isolation tests.

Every test here proves that User A cannot access User B's data,
and vice versa. Both read routes (RLS-enforced via ScopedDB) and
write routes (service-role with explicit user_id checks) are covered.
"""

import pytest

from tests.helpers.jwt import auth_headers
from tests.integration.isolation.conftest import (
    USER_A_ID, USER_B_ID,
    KB_A_ID, KB_B_ID,
    DOC_A_ID, DOC_B_ID,
)


class TestReadIsolation:
    """Read routes go through ScopedDB → SET LOCAL ROLE authenticated → RLS."""

    async def test_list_kbs_only_returns_own(self, client):
        resp = await client.get("/v1/knowledge-bases", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 200
        slugs = [kb["slug"] for kb in resp.json()]
        assert "alice-kb" in slugs
        assert "bob-kb" not in slugs

    async def test_get_kb_cross_tenant_returns_404(self, client):
        resp = await client.get(f"/v1/knowledge-bases/{KB_B_ID}", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 404

    async def test_list_documents_cross_tenant_returns_empty(self, client):
        resp = await client.get(
            f"/v1/knowledge-bases/{KB_B_ID}/documents",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_document_cross_tenant_returns_404(self, client):
        resp = await client.get(f"/v1/documents/{DOC_B_ID}", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 404

    async def test_get_document_content_cross_tenant_returns_404(self, client):
        resp = await client.get(f"/v1/documents/{DOC_B_ID}/content", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 404

    async def test_get_document_url_cross_tenant_returns_404(self, client):
        resp = await client.get(f"/v1/documents/{DOC_B_ID}/url", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 404

    async def test_own_data_accessible(self, client):
        resp = await client.get(f"/v1/knowledge-bases/{KB_A_ID}", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 200
        assert resp.json()["slug"] == "alice-kb"

        resp = await client.get(f"/v1/documents/{DOC_A_ID}", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 200
        assert resp.json()["filename"] == "notes.md"

        resp = await client.get(f"/v1/documents/{DOC_A_ID}/content", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 200
        assert resp.json()["content"] == "Alice secret content"


class TestWriteIsolation:
    """Write routes use pool directly with WHERE user_id = $N checks."""

    async def test_create_note_in_other_kb_returns_404(self, client):
        resp = await client.post(
            f"/v1/knowledge-bases/{KB_B_ID}/documents/note",
            headers=auth_headers(USER_A_ID),
            json={"filename": "injected.md", "content": "pwned"},
        )
        assert resp.status_code == 404

    async def test_update_content_cross_tenant_returns_404(self, client):
        resp = await client.put(
            f"/v1/documents/{DOC_B_ID}/content",
            headers=auth_headers(USER_A_ID),
            json={"content": "overwritten by alice"},
        )
        assert resp.status_code == 404

    async def test_update_content_cross_tenant_does_not_modify(self, client, pool):
        await client.put(
            f"/v1/documents/{DOC_B_ID}/content",
            headers=auth_headers(USER_A_ID),
            json={"content": "overwritten by alice"},
        )
        row = await pool.fetchrow("SELECT content FROM documents WHERE id = $1", DOC_B_ID)
        assert row["content"] == "Bob secret content"

    async def test_update_metadata_cross_tenant_returns_404(self, client):
        resp = await client.patch(
            f"/v1/documents/{DOC_B_ID}",
            headers=auth_headers(USER_A_ID),
            json={"title": "Hacked"},
        )
        assert resp.status_code == 404

    async def test_delete_document_cross_tenant_returns_404(self, client):
        resp = await client.delete(
            f"/v1/documents/{DOC_B_ID}",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404

    async def test_delete_document_cross_tenant_does_not_archive(self, client, pool):
        await client.delete(f"/v1/documents/{DOC_B_ID}", headers=auth_headers(USER_A_ID))
        row = await pool.fetchrow("SELECT archived FROM documents WHERE id = $1", DOC_B_ID)
        assert row["archived"] is False

    async def test_bulk_delete_cross_tenant_does_not_archive(self, client, pool):
        await client.post(
            "/v1/documents/bulk-delete",
            headers=auth_headers(USER_A_ID),
            json={"ids": [str(DOC_B_ID)]},
        )
        row = await pool.fetchrow("SELECT archived FROM documents WHERE id = $1", DOC_B_ID)
        assert row["archived"] is False

    async def test_update_kb_cross_tenant_returns_404(self, client):
        resp = await client.patch(
            f"/v1/knowledge-bases/{KB_B_ID}",
            headers=auth_headers(USER_A_ID),
            json={"name": "Hijacked"},
        )
        assert resp.status_code == 404

    async def test_delete_kb_cross_tenant_returns_404(self, client):
        resp = await client.delete(
            f"/v1/knowledge-bases/{KB_B_ID}",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404

    async def test_delete_kb_cross_tenant_does_not_delete(self, client, pool):
        await client.delete(f"/v1/knowledge-bases/{KB_B_ID}", headers=auth_headers(USER_A_ID))
        row = await pool.fetchrow("SELECT id FROM knowledge_bases WHERE id = $1", KB_B_ID)
        assert row is not None


class TestBidirectionalIsolation:
    """Verify isolation works in both directions."""

    async def test_bob_cannot_access_alice_kb(self, client):
        resp = await client.get(f"/v1/knowledge-bases/{KB_A_ID}", headers=auth_headers(USER_B_ID))
        assert resp.status_code == 404

    async def test_bob_cannot_access_alice_document(self, client):
        resp = await client.get(f"/v1/documents/{DOC_A_ID}", headers=auth_headers(USER_B_ID))
        assert resp.status_code == 404

    async def test_bob_cannot_create_note_in_alice_kb(self, client):
        resp = await client.post(
            f"/v1/knowledge-bases/{KB_A_ID}/documents/note",
            headers=auth_headers(USER_B_ID),
            json={"filename": "injected.md", "content": "pwned"},
        )
        assert resp.status_code == 404

    async def test_bob_cannot_modify_alice_document(self, client):
        resp = await client.put(
            f"/v1/documents/{DOC_A_ID}/content",
            headers=auth_headers(USER_B_ID),
            json={"content": "overwritten by bob"},
        )
        assert resp.status_code == 404

    async def test_bob_cannot_delete_alice_kb(self, client):
        resp = await client.delete(
            f"/v1/knowledge-bases/{KB_A_ID}",
            headers=auth_headers(USER_B_ID),
        )
        assert resp.status_code == 404


class TestAuthBoundary:
    """Requests without valid auth are rejected before any data access."""

    async def test_no_auth_header_returns_401(self, client):
        resp = await client.get("/v1/knowledge-bases")
        assert resp.status_code == 401

    async def test_bad_token_returns_401(self, client):
        resp = await client.get(
            "/v1/knowledge-bases",
            headers={"Authorization": "Bearer garbage-token"},
        )
        assert resp.status_code == 401

    async def test_wrong_audience_returns_401(self, client):
        from tests.helpers.jwt import make_token
        token = make_token(USER_A_ID, aud="wrong-audience")
        resp = await client.get(
            "/v1/knowledge-bases",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
