"""Integration tests for note (document) CRUD lifecycle."""

import pytest

from tests.helpers.jwt import auth_headers

USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_EMAIL = "alice@test.com"
KB_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
async def seed_user_and_kb(pool):
    await pool.execute("TRUNCATE users CASCADE")
    await pool.execute(
        "INSERT INTO users (id, email, display_name) VALUES ($1, $2, 'Alice')",
        USER_ID, USER_EMAIL,
    )
    await pool.execute(
        "INSERT INTO knowledge_bases (id, user_id, name, slug) VALUES ($1, $2, 'Test KB', 'test-kb')",
        KB_ID, USER_ID,
    )
    yield


class TestCreateNote:

    async def test_creates_note_with_content(self, client):
        resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=auth_headers(USER_ID),
            json={"filename": "research.md", "content": "Some research notes here."},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["filename"] == "research.md"
        assert data["file_type"] == "md"
        assert data["status"] == "ready"

    async def test_title_derived_from_filename(self, client):
        resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=auth_headers(USER_ID),
            json={"filename": "operating-leverage.md", "content": "x " * 70},
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "Operating Leverage"

    async def test_title_from_frontmatter(self, client):
        content = "---\ntitle: Custom Title\n---\nBody text here. " + "x " * 60
        resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=auth_headers(USER_ID),
            json={"filename": "ignored-name.md", "content": content},
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "Custom Title"

    async def test_tags_from_frontmatter(self, client):
        content = "---\ntags:\n  - research\n  - draft\n---\nBody. " + "x " * 60
        resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=auth_headers(USER_ID),
            json={"filename": "tagged.md", "content": content},
        )
        assert resp.status_code == 201
        assert "research" in resp.json()["tags"]
        assert "draft" in resp.json()["tags"]

    async def test_creates_chunks(self, client, pool):
        content = "A substantial paragraph of text. " * 20
        resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=auth_headers(USER_ID),
            json={"filename": "chunked.md", "content": content},
        )
        doc_id = resp.json()["id"]
        chunks = await pool.fetch(
            "SELECT * FROM document_chunks WHERE document_id = $1 ORDER BY chunk_index",
            doc_id,
        )
        assert len(chunks) >= 1
        assert str(chunks[0]["user_id"]) == USER_ID
        assert str(chunks[0]["knowledge_base_id"]) == KB_ID

    async def test_empty_content_creates_no_chunks(self, client, pool):
        resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=auth_headers(USER_ID),
            json={"filename": "empty.md", "content": ""},
        )
        doc_id = resp.json()["id"]
        chunks = await pool.fetch(
            "SELECT * FROM document_chunks WHERE document_id = $1", doc_id,
        )
        assert len(chunks) == 0

    async def test_document_number_auto_increments(self, client):
        headers = auth_headers(USER_ID)
        r1 = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers, json={"filename": "first.md", "content": "x " * 70},
        )
        r2 = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers, json={"filename": "second.md", "content": "x " * 70},
        )
        assert r2.json()["document_number"] > r1.json()["document_number"]


class TestUpdateContent:

    async def test_update_bumps_version(self, client):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "versioned.md", "content": "v1 content. " + "x " * 60},
        )
        doc_id = create_resp.json()["id"]

        update_resp = await client.put(
            f"/v1/documents/{doc_id}/content",
            headers=headers,
            json={"content": "v2 content. " + "x " * 60},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["version"] == 1

    async def test_update_rebuilds_chunks(self, client, pool):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "rebuild.md", "content": "Original content. " * 20},
        )
        doc_id = create_resp.json()["id"]

        old_chunks = await pool.fetch(
            "SELECT content FROM document_chunks WHERE document_id = $1", doc_id,
        )

        await client.put(
            f"/v1/documents/{doc_id}/content",
            headers=headers,
            json={"content": "Completely new content. " * 20},
        )

        new_chunks = await pool.fetch(
            "SELECT content FROM document_chunks WHERE document_id = $1", doc_id,
        )
        assert len(new_chunks) >= 1
        assert new_chunks[0]["content"] != old_chunks[0]["content"]

    async def test_clearing_content_removes_chunks(self, client, pool):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "to-clear.md", "content": "Has content. " * 20},
        )
        doc_id = create_resp.json()["id"]

        await client.put(
            f"/v1/documents/{doc_id}/content",
            headers=headers,
            json={"content": ""},
        )

        chunks = await pool.fetch(
            "SELECT * FROM document_chunks WHERE document_id = $1", doc_id,
        )
        assert len(chunks) == 0


class TestUpdateMetadata:

    async def test_patch_title_and_tags(self, client):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "meta.md", "content": "x " * 70},
        )
        doc_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/v1/documents/{doc_id}",
            headers=headers,
            json={"title": "New Title", "tags": ["important", "v2"]},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"
        assert resp.json()["tags"] == ["important", "v2"]

    async def test_empty_patch_rejected(self, client):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "nopatch.md", "content": "x " * 70},
        )
        doc_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/v1/documents/{doc_id}",
            headers=headers,
            json={},
        )
        assert resp.status_code == 400


class TestDeleteDocument:

    async def test_delete_archives_document(self, client, pool):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "to-archive.md", "content": "x " * 70},
        )
        doc_id = create_resp.json()["id"]

        resp = await client.delete(f"/v1/documents/{doc_id}", headers=headers)
        assert resp.status_code == 204

        row = await pool.fetchrow("SELECT archived FROM documents WHERE id = $1", doc_id)
        assert row["archived"] is True

    async def test_archived_doc_not_in_list(self, client):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "hidden.md", "content": "x " * 70},
        )
        doc_id = create_resp.json()["id"]

        await client.delete(f"/v1/documents/{doc_id}", headers=headers)

        list_resp = await client.get(
            f"/v1/knowledge-bases/{KB_ID}/documents", headers=headers,
        )
        doc_ids = [d["id"] for d in list_resp.json()]
        assert doc_id not in doc_ids

    async def test_bulk_delete_archives_multiple(self, client, pool):
        headers = auth_headers(USER_ID)
        ids = []
        for i in range(3):
            r = await client.post(
                f"/v1/knowledge-bases/{KB_ID}/documents/note",
                headers=headers,
                json={"filename": f"bulk-{i}.md", "content": "x " * 70},
            )
            ids.append(r.json()["id"])

        resp = await client.post(
            "/v1/documents/bulk-delete",
            headers=headers,
            json={"ids": ids},
        )
        assert resp.status_code == 204

        for doc_id in ids:
            row = await pool.fetchrow("SELECT archived FROM documents WHERE id = $1", doc_id)
            assert row["archived"] is True
