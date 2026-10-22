import asyncio
import json
import uuid

import pytest

from tests.helpers.jwt import auth_headers


class _RecordingS3:
    def __init__(self):
        self.deleted: list[str] = []

    async def delete_prefix(self, prefix: str) -> None:
        self.deleted.append(prefix)

USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_EMAIL = "alice@test.com"
KB_ID = "11111111-1111-1111-1111-111111111111"
INVALID_QUIZ = """```quiz
Q: What does koji contribute?
- [x] Enzymes
- [ ] Alcohol
E: Koji supplies enzymes.
```
"""


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

    async def test_invalid_quiz_is_rejected_without_persistence(self, client, pool):
        resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=auth_headers(USER_ID),
            json={"filename": "invalid-quiz.md", "content": INVALID_QUIZ},
        )

        assert resp.status_code == 422
        assert "required `questions:`" in resp.text
        count = await pool.fetchval(
            "SELECT COUNT(*) FROM documents WHERE knowledge_base_id = $1 AND filename = $2",
            KB_ID,
            "invalid-quiz.md",
        )
        assert count == 0

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

    async def test_invalid_quiz_preserves_content_and_version(self, client):
        headers = auth_headers(USER_ID)
        original = "Original content. " + "x " * 60
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "valid-before-update.md", "content": original},
        )
        doc_id = create_resp.json()["id"]

        update_resp = await client.put(
            f"/v1/documents/{doc_id}/content",
            headers=headers,
            json={"content": INVALID_QUIZ},
        )

        assert update_resp.status_code == 422
        assert "required `questions:`" in update_resp.text
        stored = await client.get(f"/v1/documents/{doc_id}/content", headers=headers)
        assert stored.json()["content"] == original
        assert stored.json()["version"] == 0

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

    async def test_append_keeps_unchanged_chunks(self, client, pool):
        headers = auth_headers(USER_ID)
        body = "\n\n".join(f"## Section {i}\n\n" + f"Paragraph {i} sentence. " * 120 for i in range(4))
        doc_id = (await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "long.md", "content": body},
        )).json()["id"]
        before = await chunk_ids(pool, doc_id)

        await client.put(f"/v1/documents/{doc_id}/content", headers=headers, json={"content": body})
        assert await chunk_ids(pool, doc_id) == before

        await client.put(
            f"/v1/documents/{doc_id}/content", headers=headers, json={"content": body + "\n\nAppended tail."},
        )
        after = await chunk_ids(pool, doc_id)
        assert len(before) >= 3
        assert after[:len(before) - 1] == before[:-1]
        tail = await pool.fetchval(
            "SELECT source_content FROM document_chunks WHERE document_id = $1 ORDER BY chunk_index DESC LIMIT 1",
            doc_id,
        )
        assert "Appended tail." in tail

    async def test_content_edit_keeps_highlight_comments_searchable(self, client, pool):
        headers = auth_headers(USER_ID)
        body = "The mitochondria is the powerhouse of the cell. " * 10
        doc_id = (await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "bio.md", "content": body},
        )).json()["id"]
        await pool.execute(
            "UPDATE documents SET highlights = $1::jsonb WHERE id = $2",
            '[{"id": "h1", "type": "text", "comment": "ask about ATP", '
            '"textAnchor": {"textContent": "powerhouse of the cell"}}]',
            doc_id,
        )

        await client.put(f"/v1/documents/{doc_id}/content", headers=headers, json={"content": body + "\n\nMore."})

        annotations = await pool.fetch(
            "SELECT annotations_text FROM document_chunks WHERE document_id = $1 AND has_highlight", doc_id,
        )
        assert any("ask about ATP" in (r["annotations_text"] or "") for r in annotations)

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

    async def test_metadata_round_trips_as_object(self, client):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "progress.md", "content": "x " * 70},
        )
        doc_id = create_resp.json()["id"]

        course = {"status": "complete", "completed_at": "2026-07-07T00:00:00Z"}
        patch_resp = await client.patch(
            f"/v1/documents/{doc_id}",
            headers=headers,
            json={"metadata": {"course": course}},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["metadata"] == {"course": course}

        list_resp = await client.get(
            f"/v1/knowledge-bases/{KB_ID}/documents", headers=headers,
        )
        listed = next(d for d in list_resp.json() if d["id"] == doc_id)
        assert listed["metadata"] == {"course": course}

        get_resp = await client.get(f"/v1/documents/{doc_id}", headers=headers)
        assert get_resp.json()["metadata"] == {"course": course}

    async def test_metadata_patch_merges_top_level_keys(self, client):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "merge.md", "content": "x " * 70},
        )
        doc_id = create_resp.json()["id"]

        await client.patch(
            f"/v1/documents/{doc_id}",
            headers=headers,
            json={"metadata": {"source_url": "https://example.com"}},
        )
        resp = await client.patch(
            f"/v1/documents/{doc_id}",
            headers=headers,
            json={"metadata": {"course": {"status": "complete"}}},
        )
        assert resp.json()["metadata"] == {
            "source_url": "https://example.com",
            "course": {"status": "complete"},
        }

    async def test_patch_can_clear_tags_date_and_properties(self, client):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "clear.md", "content": "x " * 70},
        )
        doc_id = create_resp.json()["id"]
        await client.patch(
            f"/v1/documents/{doc_id}",
            headers=headers,
            json={"tags": ["a"], "date": "2026-10-01", "metadata": {"properties": {"k": "v"}, "course": {"s": 1}}},
        )

        resp = await client.patch(
            f"/v1/documents/{doc_id}",
            headers=headers,
            json={"title": None, "tags": None, "date": None, "metadata": {"properties": {}}},
        )

        body = resp.json()
        assert resp.status_code == 200
        assert body["tags"] == []
        assert body["date"] is None
        assert body["metadata"] == {"properties": {}, "course": {"s": 1}}
        assert body["title"] == "Clear"

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

    async def test_move_to_another_kb_renumbers_and_applies_other_fields(self, client, pool):
        headers = auth_headers(USER_ID)
        target_kb_id = "22222222-2222-2222-2222-222222222222"
        await pool.execute(
            "INSERT INTO knowledge_bases (id, user_id, name, slug) VALUES ($1, $2, 'Target', 'target')",
            target_kb_id, USER_ID,
        )
        resident = (await client.post(
            f"/v1/knowledge-bases/{target_kb_id}/documents/note",
            headers=headers, json={"filename": "resident.md", "content": "x " * 70},
        )).json()
        mover = (await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers, json={"filename": "mover.md", "content": "y " * 70},
        )).json()

        resp = await client.patch(
            f"/v1/documents/{mover['id']}",
            headers=headers,
            json={"knowledge_base_id": target_kb_id, "title": "Moved", "tags": ["moved"]},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["knowledge_base_id"] == target_kb_id
        assert body["title"] == "Moved"
        assert body["tags"] == ["moved"]
        assert body["document_number"] == resident["document_number"] + 1
        chunk_kbs = await pool.fetch(
            "SELECT DISTINCT knowledge_base_id::text AS kb FROM document_chunks WHERE document_id = $1",
            mover["id"],
        )
        assert [r["kb"] for r in chunk_kbs] == [target_kb_id]


class TestDeleteDocument:

    async def test_delete_wiki_page_archives(self, client, pool):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "to-archive.md", "path": "/wiki/", "content": "x " * 70},
        )
        doc_id = create_resp.json()["id"]

        resp = await client.delete(f"/v1/documents/{doc_id}", headers=headers)
        assert resp.status_code == 204

        row = await pool.fetchrow("SELECT archived FROM documents WHERE id = $1", doc_id)
        assert row is not None
        assert row["archived"] is True

    async def test_delete_source_doc_hard_deletes(self, client, pool):
        headers = auth_headers(USER_ID)
        create_resp = await client.post(
            f"/v1/knowledge-bases/{KB_ID}/documents/note",
            headers=headers,
            json={"filename": "to-delete.md", "path": "/", "content": "x " * 70},
        )
        doc_id = create_resp.json()["id"]

        resp = await client.delete(f"/v1/documents/{doc_id}", headers=headers)
        assert resp.status_code == 204

        row = await pool.fetchrow("SELECT id FROM documents WHERE id = $1", doc_id)
        assert row is None

    async def test_deleted_doc_not_in_list(self, client):
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

    async def test_bulk_delete_wiki_archives(self, client, pool):
        headers = auth_headers(USER_ID)
        ids = []
        for i in range(3):
            r = await client.post(
                f"/v1/knowledge-bases/{KB_ID}/documents/note",
                headers=headers,
                json={"filename": f"bulk-wiki-{i}.md", "path": "/wiki/", "content": "x " * 70},
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
            assert row is not None
            assert row["archived"] is True

    async def test_bulk_delete_source_hard_deletes(self, client, pool):
        headers = auth_headers(USER_ID)
        ids = []
        for i in range(3):
            r = await client.post(
                f"/v1/knowledge-bases/{KB_ID}/documents/note",
                headers=headers,
                json={"filename": f"bulk-src-{i}.md", "path": "/", "content": "x " * 70},
            )
            ids.append(r.json()["id"])

        resp = await client.post(
            "/v1/documents/bulk-delete",
            headers=headers,
            json={"ids": ids},
        )
        assert resp.status_code == 204

        for doc_id in ids:
            row = await pool.fetchrow("SELECT id FROM documents WHERE id = $1", doc_id)
            assert row is None


class TestDeleteS3Purge:

    async def _insert_doc(self, pool, doc_id, path, filename, metadata=None):
        await pool.execute(
            "INSERT INTO documents (id, knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, content, tags, version, metadata) "
            "VALUES ($1, $2, $3, $4, $5, $6, 'md', 'ready', 'body', $7, 0, $8::jsonb)",
            doc_id, KB_ID, USER_ID, filename, filename, path, [],
            json.dumps(metadata) if metadata else None,
        )

    async def test_delete_purges_doc_and_child_asset_s3(self, pool):
        from services.hosted import HostedDocumentService

        parent_id = str(uuid.uuid4())
        asset_id = str(uuid.uuid4())
        await self._insert_doc(pool, parent_id, "/webclipper/", "page.md")
        await self._insert_doc(
            pool, asset_id, "/webclipper/page.assets/", "image-01.png",
            metadata={"asset": True, "parent_document_id": parent_id},
        )

        s3 = _RecordingS3()
        service = HostedDocumentService(pool, USER_ID, s3)
        assert await service.delete(parent_id) is True

        assert f"{USER_ID}/{parent_id}/" in s3.deleted
        assert f"{USER_ID}/{asset_id}/" in s3.deleted
        row = await pool.fetchrow(
            "SELECT id FROM documents WHERE id = ANY($1::uuid[])", [parent_id, asset_id],
        )
        assert row is None

    async def test_kb_delete_purges_document_s3(self, pool):
        from services.hosted import HostedKBService

        doc_id = str(uuid.uuid4())
        await self._insert_doc(pool, doc_id, "/webclipper/", "page.md")

        s3 = _RecordingS3()
        assert await HostedKBService(pool, USER_ID, s3).delete(KB_ID) is True

        assert f"{USER_ID}/{doc_id}/" in s3.deleted


class TestWebClipReclip:

    async def test_reclip_same_url_replaces_assets_without_500(self, client, pool):
        png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        body = {
            "url": "https://example.com/reclip",
            "title": "Reclip",
            "html": f'<article><p>Body text here, long enough to chunk.</p>'
                    f'<img src="data:image/png;base64,{png}"></article>',
            "path": "/webclipper/",
        }
        headers = auth_headers(USER_ID)

        r1 = await client.post(f"/v1/knowledge-bases/{KB_ID}/documents/web", headers=headers, json=body)
        assert r1.status_code == 201
        await pool.execute(
            "UPDATE documents SET metadata = metadata || '{\"course\": {\"status\": \"complete\"}}'::jsonb WHERE id = $1",
            r1.json()["id"],
        )

        # Re-clipping the same URL must update, not 500 on the asset unique index.
        r2 = await client.post(f"/v1/knowledge-bases/{KB_ID}/documents/web", headers=headers, json=body)
        assert r2.status_code == 201
        assert r2.json()["id"] == r1.json()["id"]
        metadata = json.loads(await pool.fetchval("SELECT metadata FROM documents WHERE id = $1", r1.json()["id"]))
        assert metadata["course"] == {"status": "complete"}
        assert metadata["source_url"] == "https://example.com/reclip"

        asset_count = await pool.fetchval(
            "SELECT COUNT(*) FROM documents WHERE knowledge_base_id = $1 "
            "AND COALESCE(metadata->>'asset', 'false') = 'true'",
            KB_ID,
        )
        assert asset_count == 1


async def chunk_ids(pool, doc_id: str) -> list[str]:
    rows = await pool.fetch(
        "SELECT id::text FROM document_chunks WHERE document_id = $1 ORDER BY chunk_index", doc_id,
    )
    return [r["id"] for r in rows]


class TestGraphRebuild:

    async def test_rebuild_records_citations_and_links(self, pool):
        from services.graph import rebuild_hosted

        source_id = await insert_doc(pool, "paper.pdf", "/", "pdf", "Extracted")
        topic_id = await insert_doc(pool, "topic.md", "/wiki/", "md", "Topic page.")
        overview_id = await insert_doc(
            pool, "overview.md", "/wiki/", "md",
            "See [Topic](topic.md).\n\nClaim.[^1]\n\n[^1]: paper.pdf, p.3",
        )

        async with pool.acquire() as conn:
            result = await rebuild_hosted(conn, KB_ID, USER_ID)

        rows = await pool.fetch(
            "SELECT source_document_id, target_document_id, reference_type, page FROM document_references "
            "ORDER BY reference_type",
        )
        assert result == {"citations": 1, "links": 1}
        assert [(r["source_document_id"], r["target_document_id"], r["reference_type"], r["page"]) for r in rows] == [
            (overview_id, source_id, "cites", 3),
            (overview_id, topic_id, "links_to", None),
        ]


async def insert_doc(pool, filename: str, path: str, file_type: str, content: str) -> uuid.UUID:
    return await pool.fetchval(
        "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, file_type, status, content) "
        "VALUES ($1, $2, $3, $3, $4, $5, 'ready', $6) RETURNING id",
        KB_ID, USER_ID, filename, path, file_type, content,
    )


class TestChunkStore:

    async def test_annotated_chunk_is_rewritten_even_when_unchanged(self, pool):
        from services.chunker import chunk_text, store_chunks

        doc_id = str(await insert_doc(pool, "note.md", "/wiki/", "md", "x"))
        chunks = chunk_text("Unchanged text that stays the same. " * 10)
        await store_chunks(pool, doc_id, USER_ID, KB_ID, chunks)
        await pool.execute(
            "UPDATE document_chunks SET has_highlight = true, annotations_text = 'old comment', "
            "content = content || ' old comment' WHERE document_id = $1",
            doc_id,
        )

        await store_chunks(pool, doc_id, USER_ID, KB_ID, chunks)

        row = await pool.fetchrow(
            "SELECT has_highlight, annotations_text, content, source_content FROM document_chunks "
            "WHERE document_id = $1",
            doc_id,
        )
        assert (row["has_highlight"], row["annotations_text"]) == (False, None)
        assert row["content"] == row["source_content"]

    async def test_pool_writes_wait_for_the_document_lock(self, pool):
        from services.chunker import chunk_text, store_chunks

        doc_id = str(await insert_doc(pool, "note.md", "/wiki/", "md", "x"))
        async with pool.acquire() as holder, holder.transaction():
            await holder.execute("SELECT 1 FROM documents WHERE id = $1 FOR NO KEY UPDATE", doc_id)
            write = asyncio.create_task(store_chunks(pool, doc_id, USER_ID, KB_ID, chunk_text("New text. " * 10)))
            await asyncio.sleep(0.3)
            assert not write.done()
        await asyncio.wait_for(write, timeout=5)
        assert await pool.fetchval("SELECT COUNT(*) FROM document_chunks WHERE document_id = $1", doc_id) == 1

