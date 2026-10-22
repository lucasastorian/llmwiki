import pytest
from config import settings

from tests.helpers.jwt import auth_headers

USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_EMAIL = "alice@test.com"


@pytest.fixture(autouse=True)
async def seed_user(pool):
    await pool.execute("TRUNCATE users CASCADE")
    await pool.execute(
        "INSERT INTO users (id, email, display_name) VALUES ($1, $2, 'Alice')",
        USER_ID, USER_EMAIL,
    )
    yield


class TestCreateKB:

    async def test_creates_kb_with_scaffold_docs(self, client, pool):
        resp = await client.post(
            "/v1/knowledge-bases",
            headers=auth_headers(USER_ID),
            json={"name": "Test KB", "description": "A test"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test KB"
        assert data["slug"] == "test-kb"
        assert data["description"] == "A test"

        kb_id = data["id"]
        docs = await pool.fetch(
            "SELECT filename, path, title, content, tags, date FROM documents "
            "WHERE knowledge_base_id = $1 ORDER BY filename",
            kb_id,
        )
        filenames = [d["filename"] for d in docs]
        assert "log.md" not in filenames
        assert "overview.md" in filenames
        overview = next(d for d in docs if d["filename"] == "overview.md")
        assert overview["content"].startswith("---\n")
        assert overview["tags"] == ["overview", "wiki"]
        assert overview["date"]

    async def test_duplicate_name_is_auto_suffixed(self, client):
        headers = auth_headers(USER_ID)
        resp1 = await client.post("/v1/knowledge-bases", headers=headers, json={"name": "Duplicate"})
        resp2 = await client.post("/v1/knowledge-bases", headers=headers, json={"name": "Duplicate"})

        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp2.json()["name"] == "Duplicate (2)"
        assert resp2.json()["slug"] != resp1.json()["slug"]

    async def test_rename_keeps_slug_when_it_would_not_change(self, client):
        headers = auth_headers(USER_ID)
        kb = (await client.post("/v1/knowledge-bases", headers=headers, json={"name": "My Wiki"})).json()

        resp = await client.patch(f"/v1/knowledge-bases/{kb['id']}", headers=headers, json={"name": "My wiki"})

        assert resp.status_code == 200
        assert resp.json()["slug"] == kb["slug"]

    async def test_rename_to_an_existing_name_is_409(self, client):
        headers = auth_headers(USER_ID)
        await client.post("/v1/knowledge-bases", headers=headers, json={"name": "Taken"})
        other = (await client.post("/v1/knowledge-bases", headers=headers, json={"name": "Other"})).json()

        resp = await client.patch(f"/v1/knowledge-bases/{other['id']}", headers=headers, json={"name": "Taken"})

        assert resp.status_code == 409

    async def test_global_user_cap_enforced(self, client, pool, monkeypatch):
        monkeypatch.setattr(settings, "GLOBAL_MAX_USERS", 1)

        resp = await client.post("/v1/knowledge-bases", headers=auth_headers(USER_ID), json={"name": "Over Cap"})

        assert resp.status_code == 503
        assert await pool.fetchval("SELECT COUNT(*) FROM knowledge_bases WHERE user_id = $1", USER_ID) == 0


class TestListAndGetKB:

    async def test_list_returns_own_kbs(self, client):
        headers = auth_headers(USER_ID)
        await client.post("/v1/knowledge-bases", headers=headers, json={"name": "KB One"})
        await client.post("/v1/knowledge-bases", headers=headers, json={"name": "KB Two"})

        resp = await client.get("/v1/knowledge-bases", headers=headers)
        assert resp.status_code == 200
        names = [kb["name"] for kb in resp.json()]
        assert "KB One" in names
        assert "KB Two" in names

    async def test_list_includes_counts(self, client, pool):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            "/v1/knowledge-bases", headers=headers,
            json={"name": "Counted KB"},
        )
        kb_id = create_resp.json()["id"]

        data = await listed_kb(client, headers, kb_id)
        assert "source_count" in data
        assert "wiki_page_count" in data
        # Activity is database-backed; the only scaffolded page is Overview.
        assert data["wiki_page_count"] == 1

    async def test_lesson_counts_exclude_scaffold_and_track_completion(self, client, pool):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            "/v1/knowledge-bases", headers=headers,
            json={"name": "A Course", "kind": "course"},
        )
        kb_id = create_resp.json()["id"]

        await pool.execute(
            "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, content, metadata) "
            "VALUES ($1, $2, 'lesson-1.md', 'Lesson 1', '/wiki/', 'md', 'ready', 'x', "
            "'{\"course\": {\"status\": \"complete\"}}'::jsonb)",
            kb_id, USER_ID,
        )
        await pool.execute(
            "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, content) "
            "VALUES ($1, $2, 'lesson-2.md', 'Lesson 2', '/wiki/', 'md', 'ready', 'x')",
            kb_id, USER_ID,
        )

        data = await listed_kb(client, headers, kb_id)
        assert data["lesson_count"] == 2
        assert data["lessons_completed"] == 1


class TestUpdateKB:

    async def test_update_name(self, client):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            "/v1/knowledge-bases", headers=headers,
            json={"name": "Original"},
        )
        kb_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/v1/knowledge-bases/{kb_id}", headers=headers,
            json={"name": "Renamed"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"

    async def test_empty_update_rejected(self, client):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            "/v1/knowledge-bases", headers=headers,
            json={"name": "No Update"},
        )
        kb_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/v1/knowledge-bases/{kb_id}", headers=headers,
            json={},
        )
        assert resp.status_code == 400


class TestDeleteKB:

    async def test_delete_removes_kb_and_docs(self, client, pool):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            "/v1/knowledge-bases", headers=headers,
            json={"name": "To Delete"},
        )
        kb_id = create_resp.json()["id"]

        resp = await client.delete(f"/v1/knowledge-bases/{kb_id}", headers=headers)
        assert resp.status_code == 204

        row = await pool.fetchrow("SELECT id FROM knowledge_bases WHERE id = $1", kb_id)
        assert row is None

        docs = await pool.fetch("SELECT id FROM documents WHERE knowledge_base_id = $1", kb_id)
        assert len(docs) == 0

    async def test_delete_nonexistent_returns_404(self, client):
        resp = await client.delete(
            "/v1/knowledge-bases/99999999-9999-9999-9999-999999999999",
            headers=auth_headers(USER_ID),
        )
        assert resp.status_code == 404


async def listed_kb(client, headers: dict, kb_id: str) -> dict:
    resp = await client.get("/v1/knowledge-bases", headers=headers)
    assert resp.status_code == 200
    return next(kb for kb in resp.json() if kb["id"] == kb_id)
