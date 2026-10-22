"""User A can never reach User B's data via RLS-scoped read routes or user_id-checked write routes."""

import time

import jwt as pyjwt

from tests.helpers import jwt as jwt_helper
from tests.helpers.jwt import auth_headers
from tests.integration.isolation.conftest import (
    DOC_A2_ID,
    DOC_A_ID,
    DOC_B_ID,
    KB_A_ID,
    KB_B_ID,
    USER_A_EMAIL,
    USER_A_ID,
    USER_B_ID,
)


def _claims(sub) -> dict:
    """A fully-valid claim set, so each auth test varies exactly one thing."""
    now = int(time.time())
    return {
        "sub": str(sub),
        "aud": "authenticated",
        "iss": jwt_helper._expected_issuer(),
        "iat": now,
        "exp": now + 3600,
        "role": "authenticated",
    }


class TestReadIsolation:
    """Read routes go through ScopedDB → SET LOCAL ROLE authenticated → RLS."""

    async def test_list_kbs_only_returns_own(self, client):
        resp = await client.get("/v1/knowledge-bases", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 200
        slugs = [kb["slug"] for kb in resp.json()]
        assert "alice-kb" in slugs
        assert "bob-kb" not in slugs

    async def test_list_documents_cross_tenant_returns_empty(self, client):
        resp = await client.get(
            f"/v1/knowledge-bases/{KB_B_ID}/documents",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_documents_hides_asset_documents(self, client, pool):
        await pool.execute(
            "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, content, metadata) "
            "VALUES ('aaaa5555-aaaa-aaaa-aaaa-aaaaaaaaaaaa', $1, $2, 'image-01.png', "
            "'image-01.png', '/webclipper/article.assets/', 'png', 'ready', NULL, "
            "'{\"asset\": true, \"hidden\": true}'::jsonb)",
            KB_A_ID, USER_A_ID,
        )
        resp = await client.get(
            f"/v1/knowledge-bases/{KB_A_ID}/documents",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        filenames = {doc["filename"] for doc in resp.json()}
        assert "notes.md" in filenames
        assert "image-01.png" not in filenames

    async def test_get_document_cross_tenant_returns_404(self, client):
        resp = await client.get(f"/v1/documents/{DOC_B_ID}", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 404

    async def test_get_document_by_url_ignores_asset_documents(self, client, pool):
        source_url = "https://example.com/article"
        await pool.execute(
            "UPDATE documents SET metadata = $1::jsonb WHERE id = $2",
            '{"source_url": "https://example.com/article", "clip_kind": "web"}',
            DOC_A_ID,
        )
        await pool.execute(
            "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, content, metadata, updated_at) "
            "VALUES ('aaaa6666-aaaa-aaaa-aaaa-aaaaaaaaaaaa', $1, $2, 'image-01.png', "
            "'image-01.png', '/webclipper/article.assets/', 'png', 'ready', NULL, "
            "$3::jsonb, now() + interval '1 second')",
            KB_A_ID, USER_A_ID,
            '{"asset": true, "hidden": true, "source_url": "https://example.com/article"}',
        )

        resp = await client.get(
            "/v1/documents/by-url",
            headers=auth_headers(USER_A_ID),
            params={"url": source_url},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == DOC_A_ID

    async def test_get_document_content_cross_tenant_returns_404(self, client):
        resp = await client.get(f"/v1/documents/{DOC_B_ID}/content", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 404

    async def test_get_document_url_cross_tenant_returns_404(self, client):
        resp = await client.get(f"/v1/documents/{DOC_B_ID}/url", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 404

    async def test_own_data_accessible(self, client):
        resp = await client.get("/v1/knowledge-bases", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 200
        assert [kb["slug"] for kb in resp.json()] == ["alice-kb"]

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

    async def test_create_webclip_in_other_kb_returns_404(self, client):
        resp = await client.post(
            f"/v1/knowledge-bases/{KB_B_ID}/documents/web",
            headers=auth_headers(USER_A_ID),
            json={
                "url": "https://example.com/bob",
                "title": "Injected",
                "html": "<article><p>pwned</p></article>",
                "path": "/webclipper/",
            },
        )
        assert resp.status_code == 404

    async def test_create_webclip_in_other_kb_does_not_insert(self, client, pool):
        before = await pool.fetchval(
            "SELECT COUNT(*) FROM documents WHERE knowledge_base_id = $1",
            KB_B_ID,
        )
        await client.post(
            f"/v1/knowledge-bases/{KB_B_ID}/documents/web",
            headers=auth_headers(USER_A_ID),
            json={
                "url": "https://example.com/bob",
                "title": "Injected",
                "html": "<article><p>pwned</p></article>",
                "path": "/webclipper/research/",
            },
        )
        after = await pool.fetchval(
            "SELECT COUNT(*) FROM documents WHERE knowledge_base_id = $1",
            KB_B_ID,
        )
        assert after == before

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

    async def test_convert_kb_kind_cross_tenant_does_not_modify(self, client, pool):
        resp = await client.patch(
            f"/v1/knowledge-bases/{KB_B_ID}",
            headers=auth_headers(USER_A_ID),
            json={"kind": "course"},
        )
        assert resp.status_code == 404
        row = await pool.fetchrow("SELECT kind FROM knowledge_bases WHERE id = $1", KB_B_ID)
        assert row["kind"] == "wiki"

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


class TestHighlightIsolation:
    """Granular highlight CRUD and cross-KB move isolation."""

    async def _seed_highlight(self, pool, doc_id, hid="seed-1"):
        import json
        payload = json.dumps([{
            "id": hid,
            "type": "text",
            "anchor": None,
            "textAnchor": {
                "textStart": 0,
                "textEnd": 5,
                "textContent": "hello",
                "prefix": None,
                "suffix": None,
            },
            "comment": None,
            "color": "yellow",
            "createdAt": "2026-05-10T00:00:00Z",
        }])
        await pool.execute(
            "UPDATE documents SET highlights = $1::jsonb WHERE id = $2",
            payload, doc_id,
        )

    def _new_highlight(self, hid="alice-injected"):
        return {
            "id": hid,
            "type": "text",
            "anchor": None,
            "textAnchor": {
                "textStart": 0,
                "textEnd": 5,
                "textContent": "alice",
                "prefix": None,
                "suffix": None,
            },
            "comment": None,
            "color": "yellow",
            "createdAt": "2026-05-10T00:00:00Z",
        }

    async def test_get_highlights_cross_tenant_returns_404(self, client):
        resp = await client.get(
            f"/v1/documents/{DOC_B_ID}/highlights",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404

    async def test_upsert_highlight_cross_tenant_returns_404(self, client):
        resp = await client.post(
            f"/v1/documents/{DOC_B_ID}/highlights",
            headers=auth_headers(USER_A_ID),
            json={"highlight": self._new_highlight()},
        )
        assert resp.status_code == 404

    async def test_upsert_highlight_cross_tenant_does_not_modify(self, client, pool):
        await client.post(
            f"/v1/documents/{DOC_B_ID}/highlights",
            headers=auth_headers(USER_A_ID),
            json={"highlight": self._new_highlight()},
        )
        row = await pool.fetchrow(
            "SELECT highlights FROM documents WHERE id = $1", DOC_B_ID,
        )
        # Bob's highlights array is empty (default) — must remain so.
        import json
        highlights = row["highlights"]
        if isinstance(highlights, str):
            highlights = json.loads(highlights)
        assert highlights == []

    async def test_delete_highlight_cross_tenant_returns_404(self, client, pool):
        await self._seed_highlight(pool, DOC_B_ID, hid="bob-keep")
        resp = await client.delete(
            f"/v1/documents/{DOC_B_ID}/highlights/bob-keep",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404

    async def test_delete_highlight_cross_tenant_does_not_modify(self, client, pool):
        await self._seed_highlight(pool, DOC_B_ID, hid="bob-keep")
        await client.delete(
            f"/v1/documents/{DOC_B_ID}/highlights/bob-keep",
            headers=auth_headers(USER_A_ID),
        )
        row = await pool.fetchrow(
            "SELECT highlights FROM documents WHERE id = $1", DOC_B_ID,
        )
        import json
        highlights = row["highlights"]
        if isinstance(highlights, str):
            highlights = json.loads(highlights)
        assert any(h.get("id") == "bob-keep" for h in highlights)

    async def test_move_bob_doc_as_alice_returns_404(self, client):
        resp = await client.patch(
            f"/v1/documents/{DOC_B_ID}",
            headers=auth_headers(USER_A_ID),
            json={"knowledge_base_id": KB_A_ID},
        )
        assert resp.status_code == 404

    async def test_move_bob_doc_as_alice_does_not_change_kb(self, client, pool):
        await client.patch(
            f"/v1/documents/{DOC_B_ID}",
            headers=auth_headers(USER_A_ID),
            json={"knowledge_base_id": KB_A_ID},
        )
        row = await pool.fetchrow(
            "SELECT knowledge_base_id::text FROM documents WHERE id = $1", DOC_B_ID,
        )
        assert row["knowledge_base_id"] == KB_B_ID

    async def test_move_alice_doc_to_bob_kb_returns_404(self, client):
        resp = await client.patch(
            f"/v1/documents/{DOC_A_ID}",
            headers=auth_headers(USER_A_ID),
            json={"knowledge_base_id": KB_B_ID},
        )
        assert resp.status_code == 404

    async def test_move_alice_doc_to_bob_kb_does_not_change_kb(self, client, pool):
        await client.patch(
            f"/v1/documents/{DOC_A_ID}",
            headers=auth_headers(USER_A_ID),
            json={"knowledge_base_id": KB_B_ID},
        )
        row = await pool.fetchrow(
            "SELECT knowledge_base_id::text FROM documents WHERE id = $1", DOC_A_ID,
        )
        assert row["knowledge_base_id"] == KB_A_ID


class TestBidirectionalIsolation:

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


class TestUserRouteIsolation:

    async def test_get_me_returns_own_profile(self, client):
        resp = await client.get("/v1/me", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == USER_A_ID
        assert data["email"] == USER_A_EMAIL
        assert data["display_name"] == "Alice"

    async def test_get_me_does_not_leak_other_user(self, client):
        resp = await client.get("/v1/me", headers=auth_headers(USER_A_ID))
        data = resp.json()
        assert data["email"] != "bob@test.com"
        assert data["display_name"] != "Bob"

    async def test_complete_onboarding_only_affects_own_user(self, client, pool):
        await client.post("/v1/onboarding/complete", headers=auth_headers(USER_A_ID))
        alice = await pool.fetchrow("SELECT onboarded FROM users WHERE id = $1", USER_A_ID)
        bob = await pool.fetchrow("SELECT onboarded FROM users WHERE id = $1", USER_B_ID)
        assert alice["onboarded"] is True
        assert bob["onboarded"] is False


class TestUsageIsolation:

    async def test_usage_returns_own_totals_only(self, client):
        resp = await client.get("/v1/usage", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 200
        data = resp.json()
        # Alice has 2 docs: notes.md (3 pages, 1024 bytes) + source.pdf (0 pages, 0 bytes)
        assert data["document_count"] == 2
        assert data["total_pages"] == 3
        assert data["total_storage_bytes"] == 1024

    async def test_usage_does_not_include_other_tenant(self, client):
        resp = await client.get("/v1/usage", headers=auth_headers(USER_A_ID))
        data = resp.json()
        # Bob has 10 pages, 5000 bytes — should not appear in Alice's usage
        assert data["total_pages"] != 13  # 3 + 10
        assert data["total_storage_bytes"] != 6024  # 1024 + 5000


class TestGraphIsolation:
    """Knowledge graph routes use ScopedDB (RLS-enforced)."""

    async def test_get_graph_returns_own_nodes(self, client):
        resp = await client.get(
            f"/v1/knowledge-bases/{KB_A_ID}/graph",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert str(DOC_A_ID) in node_ids
        assert str(DOC_A2_ID) in node_ids
        assert str(DOC_B_ID) not in node_ids

    async def test_get_graph_cross_tenant_returns_empty(self, client):
        resp = await client.get(
            f"/v1/knowledge-bases/{KB_B_ID}/graph",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["edges"] == []

    async def test_rebuild_graph_cross_tenant_does_not_delete_refs(self, client, pool):
        before = await pool.fetchval(
            "SELECT COUNT(*) FROM document_references WHERE knowledge_base_id = $1", KB_B_ID,
        )
        await client.post(
            f"/v1/knowledge-bases/{KB_B_ID}/graph/rebuild",
            headers=auth_headers(USER_A_ID),
        )
        after = await pool.fetchval(
            "SELECT COUNT(*) FROM document_references WHERE knowledge_base_id = $1", KB_B_ID,
        )
        assert after == before


class TestTUSUploadIsolation:
    """TUS upload routes enforce KB ownership on create and user_id on HEAD/PATCH."""

    def _tus_headers(self, user_id, extra=None):
        headers = {
            **auth_headers(user_id),
            "Tus-Resumable": "1.0.0",
        }
        if extra:
            headers.update(extra)
        return headers

    def _metadata(self, filename, kb_id):
        import base64
        fn = base64.b64encode(filename.encode()).decode()
        kb = base64.b64encode(kb_id.encode()).decode()
        return f"filename {fn},knowledge_base_id {kb}"

    async def test_create_upload_in_other_tenant_kb_returns_403(self, client):
        resp = await client.post(
            "/v1/uploads",
            headers=self._tus_headers(USER_A_ID, {
                "Upload-Length": "1024",
                "Upload-Metadata": self._metadata("test.pdf", str(KB_B_ID)),
            }),
        )
        assert resp.status_code == 403

    async def test_create_upload_in_own_kb_returns_201(self, client):
        resp = await client.post(
            "/v1/uploads",
            headers=self._tus_headers(USER_A_ID, {
                "Upload-Length": "1024",
                "Upload-Metadata": self._metadata("test.pdf", str(KB_A_ID)),
            }),
        )
        assert resp.status_code == 201
        assert "Location" in resp.headers

    async def test_head_other_users_upload_returns_404(self, client):
        resp = await client.post(
            "/v1/uploads",
            headers=self._tus_headers(USER_A_ID, {
                "Upload-Length": "1024",
                "Upload-Metadata": self._metadata("test.pdf", str(KB_A_ID)),
            }),
        )
        assert resp.status_code == 201
        location = resp.headers["Location"]

        resp = await client.head(location, headers=self._tus_headers(USER_B_ID))
        assert resp.status_code == 404

    async def test_patch_other_users_upload_returns_404(self, client):
        resp = await client.post(
            "/v1/uploads",
            headers=self._tus_headers(USER_A_ID, {
                "Upload-Length": "1024",
                "Upload-Metadata": self._metadata("test.pdf", str(KB_A_ID)),
            }),
        )
        assert resp.status_code == 201
        location = resp.headers["Location"]

        resp = await client.patch(
            location,
            headers=self._tus_headers(USER_B_ID, {
                "Upload-Offset": "0",
                "Content-Type": "application/offset+octet-stream",
            }),
            content=b"pwned",
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

    @staticmethod
    async def _assert_rejected(client, token: str) -> None:
        resp = await client.get(
            "/v1/knowledge-bases",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    async def test_expired_token_returns_401(self, client):
        claims = _claims(USER_A_ID)
        claims["exp"] = int(time.time()) - 100
        token = pyjwt.encode(
            claims, jwt_helper._private_key, algorithm="ES256",
            headers={"kid": jwt_helper.TEST_KID},
        )
        await self._assert_rejected(client, token)

    async def test_wrong_issuer_returns_401(self, client):
        claims = _claims(USER_A_ID)
        claims["iss"] = "https://attacker.example.com/auth/v1"
        token = pyjwt.encode(
            claims, jwt_helper._private_key, algorithm="ES256",
            headers={"kid": jwt_helper.TEST_KID},
        )
        await self._assert_rejected(client, token)

    async def test_alg_none_token_returns_401(self, client):
        token = pyjwt.encode(
            _claims(USER_A_ID), "", algorithm="none",
            headers={"kid": jwt_helper.TEST_KID},
        )
        await self._assert_rejected(client, token)

    async def test_hs256_algorithm_confusion_returns_401(self, client):
        """Hand-forge an HS256 JWS keyed with the EC public key (PyJWT refuses); ES256 pinning must reject it."""
        import base64
        import hashlib
        import hmac
        import json

        def b64(raw: bytes) -> bytes:
            return base64.urlsafe_b64encode(raw).rstrip(b"=")

        header = {"alg": "HS256", "typ": "JWT", "kid": jwt_helper.TEST_KID}
        signing_input = (
            b64(json.dumps(header).encode()) + b"." + b64(json.dumps(_claims(USER_A_ID)).encode())
        )
        sig = hmac.new(jwt_helper._public_jwk, signing_input, hashlib.sha256).digest()
        token = (signing_input + b"." + b64(sig)).decode()
        await self._assert_rejected(client, token)

    async def test_unknown_kid_returns_401(self, client):
        """An unknown kid forces a JWKS refetch; with no resolvable key, fail closed."""
        token = pyjwt.encode(
            _claims(USER_A_ID), jwt_helper._private_key, algorithm="ES256",
            headers={"kid": "unknown-kid-999"},
        )
        await self._assert_rejected(client, token)
