"""Full HTTP stack with RLS disabled, so only application-level user_id filters protect data."""


from tests.helpers.jwt import auth_headers
from tests.integration.isolation.conftest import (
    DOC_A_ID,
    DOC_B_ID,
    KB_A_ID,
    KB_B_ID,
    USER_A_ID,
    USER_B_ID,
)


class TestSanityCheck:
    """Verify that RLS is actually disabled — a raw pool query can see all rows."""

    async def test_pool_sees_both_tenants(self, pool):
        rows = await pool.fetch("SELECT slug FROM knowledge_bases ORDER BY slug")
        slugs = [r["slug"] for r in rows]
        assert "alice-kb" in slugs and "bob-kb" in slugs


class TestReadIsolationWithoutRLS:

    async def test_list_kbs_only_returns_own(self, client_no_rls):
        resp = await client_no_rls.get(
            "/v1/knowledge-bases", headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        slugs = [kb["slug"] for kb in resp.json()]
        assert "alice-kb" in slugs
        assert "bob-kb" not in slugs

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
        resp = await client_no_rls.get("/v1/knowledge-bases", headers=auth_headers(USER_A_ID))
        assert resp.status_code == 200
        assert [kb["slug"] for kb in resp.json()] == ["alice-kb"]

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


class TestEventIsolationWithoutRLS:

    async def test_fixture_contains_both_event_streams(self, pool):
        rows = await pool.fetch(
            "SELECT DISTINCT knowledge_base_id::text, user_id::text "
            "FROM knowledge_base_events"
        )
        ownership = {
            (row["knowledge_base_id"], row["user_id"])
            for row in rows
        }
        assert (KB_A_ID, USER_A_ID) in ownership
        assert (KB_B_ID, USER_B_ID) in ownership

    async def test_own_feed_excludes_other_tenant_events(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/knowledge-bases/{KB_A_ID}/events",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        titles = {event["subject_title"] for event in resp.json()["items"]}
        assert "Alice KB" in titles
        assert "Bob KB" not in titles

    async def test_cross_tenant_feed_returns_404(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/knowledge-bases/{KB_B_ID}/events",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404

    async def test_isolation_is_bidirectional(self, client_no_rls):
        own = await client_no_rls.get(
            f"/v1/knowledge-bases/{KB_B_ID}/events",
            headers=auth_headers(USER_B_ID),
        )
        assert own.status_code == 200
        titles = {event["subject_title"] for event in own.json()["items"]}
        assert "Bob KB" in titles
        assert "Alice KB" not in titles

        forbidden = await client_no_rls.get(
            f"/v1/knowledge-bases/{KB_A_ID}/events",
            headers=auth_headers(USER_B_ID),
        )
        assert forbidden.status_code == 404


class TestWriteIsolationWithoutRLS:

    async def test_create_note_in_other_kb_returns_404(self, client_no_rls):
        resp = await client_no_rls.post(
            f"/v1/knowledge-bases/{KB_B_ID}/documents/note",
            headers=auth_headers(USER_A_ID),
            json={"filename": "injected.md", "content": "pwned"},
        )
        assert resp.status_code == 404

    async def test_create_webclip_in_other_kb_returns_404(self, client_no_rls):
        resp = await client_no_rls.post(
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

    async def test_create_webclip_in_other_kb_does_not_insert(self, client_no_rls, pool):
        before = await pool.fetchval(
            "SELECT COUNT(*) FROM documents WHERE knowledge_base_id = $1",
            KB_B_ID,
        )
        await client_no_rls.post(
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


class TestHighlightIsolationWithoutRLS:
    """Highlight and move endpoints rely on HostedDocumentService's explicit user_id filter alone."""

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

    async def _seed_highlight(self, pool, doc_id, hid):
        import json
        payload = json.dumps([{
            "id": hid,
            "type": "text",
            "anchor": None,
            "textAnchor": {
                "textStart": 0, "textEnd": 5, "textContent": "hello",
                "prefix": None, "suffix": None,
            },
            "comment": None,
            "color": "yellow",
            "createdAt": "2026-05-10T00:00:00Z",
        }])
        await pool.execute(
            "UPDATE documents SET highlights = $1::jsonb WHERE id = $2",
            payload, doc_id,
        )

    async def test_get_highlights_cross_tenant_returns_404(self, client_no_rls):
        resp = await client_no_rls.get(
            f"/v1/documents/{DOC_B_ID}/highlights",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404

    async def test_upsert_highlight_cross_tenant_returns_404(self, client_no_rls):
        resp = await client_no_rls.post(
            f"/v1/documents/{DOC_B_ID}/highlights",
            headers=auth_headers(USER_A_ID),
            json={"highlight": self._new_highlight()},
        )
        assert resp.status_code == 404

    async def test_upsert_highlight_does_not_modify(self, client_no_rls, pool):
        import json
        await client_no_rls.post(
            f"/v1/documents/{DOC_B_ID}/highlights",
            headers=auth_headers(USER_A_ID),
            json={"highlight": self._new_highlight()},
        )
        row = await pool.fetchrow(
            "SELECT highlights FROM documents WHERE id = $1", DOC_B_ID,
        )
        highlights = row["highlights"]
        if isinstance(highlights, str):
            highlights = json.loads(highlights)
        assert highlights == []

    async def test_delete_highlight_cross_tenant_returns_404(self, client_no_rls, pool):
        await self._seed_highlight(pool, DOC_B_ID, "bob-keep")
        resp = await client_no_rls.delete(
            f"/v1/documents/{DOC_B_ID}/highlights/bob-keep",
            headers=auth_headers(USER_A_ID),
        )
        assert resp.status_code == 404

    async def test_delete_highlight_does_not_modify(self, client_no_rls, pool):
        import json
        await self._seed_highlight(pool, DOC_B_ID, "bob-keep")
        await client_no_rls.delete(
            f"/v1/documents/{DOC_B_ID}/highlights/bob-keep",
            headers=auth_headers(USER_A_ID),
        )
        row = await pool.fetchrow(
            "SELECT highlights FROM documents WHERE id = $1", DOC_B_ID,
        )
        highlights = row["highlights"]
        if isinstance(highlights, str):
            highlights = json.loads(highlights)
        assert any(h.get("id") == "bob-keep" for h in highlights)

    async def test_move_bob_doc_as_alice_returns_404(self, client_no_rls):
        resp = await client_no_rls.patch(
            f"/v1/documents/{DOC_B_ID}",
            headers=auth_headers(USER_A_ID),
            json={"knowledge_base_id": KB_A_ID},
        )
        assert resp.status_code == 404

    async def test_move_bob_doc_as_alice_does_not_change_kb(self, client_no_rls, pool):
        await client_no_rls.patch(
            f"/v1/documents/{DOC_B_ID}",
            headers=auth_headers(USER_A_ID),
            json={"knowledge_base_id": KB_A_ID},
        )
        row = await pool.fetchrow(
            "SELECT knowledge_base_id::text FROM documents WHERE id = $1", DOC_B_ID,
        )
        assert row["knowledge_base_id"] == KB_B_ID

    async def test_move_alice_doc_to_bob_kb_returns_404(self, client_no_rls):
        resp = await client_no_rls.patch(
            f"/v1/documents/{DOC_A_ID}",
            headers=auth_headers(USER_A_ID),
            json={"knowledge_base_id": KB_B_ID},
        )
        assert resp.status_code == 404

    async def test_move_alice_doc_to_bob_kb_does_not_change_kb(self, client_no_rls, pool):
        await client_no_rls.patch(
            f"/v1/documents/{DOC_A_ID}",
            headers=auth_headers(USER_A_ID),
            json={"knowledge_base_id": KB_B_ID},
        )
        row = await pool.fetchrow(
            "SELECT knowledge_base_id::text FROM documents WHERE id = $1", DOC_A_ID,
        )
        assert row["knowledge_base_id"] == KB_A_ID


class TestBidirectionalWithoutRLS:

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
