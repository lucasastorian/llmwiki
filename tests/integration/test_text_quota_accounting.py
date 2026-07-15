"""Hosted text notes participate in storage accounting and quota locking."""

import asyncio
from types import SimpleNamespace

import pytest

from tests.helpers.jwt import auth_headers

USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
KB_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
async def seed_user_and_kb(pool):
    await pool.execute("TRUNCATE users CASCADE")
    await pool.execute(
        "INSERT INTO users (id, email, storage_limit_bytes) "
        "VALUES ($1, 'quota@test.com', 1000000)",
        USER_ID,
    )
    await pool.execute(
        "INSERT INTO knowledge_bases (id, user_id, name, slug) "
        "VALUES ($1, $2, 'Quota KB', 'quota-kb')",
        KB_ID,
        USER_ID,
    )


async def _create_note(client, filename: str, content: str):
    return await client.post(
        f"/v1/knowledge-bases/{KB_ID}/documents/note",
        headers=auth_headers(USER_ID),
        json={"filename": filename, "content": content},
    )


async def test_create_and_update_track_utf8_file_size(client, pool):
    created = await _create_note(client, "unicode.md", "hé")
    assert created.status_code == 201
    doc_id = created.json()["id"]
    assert await pool.fetchval(
        "SELECT file_size FROM documents WHERE id = $1",
        doc_id,
    ) == len("hé".encode("utf-8"))

    updated = await client.put(
        f"/v1/documents/{doc_id}/content",
        headers=auth_headers(USER_ID),
        json={"content": "éé"},
    )
    assert updated.status_code == 200
    assert await pool.fetchval(
        "SELECT file_size FROM documents WHERE id = $1",
        doc_id,
    ) == len("éé".encode("utf-8"))


async def test_create_rejects_storage_quota_without_inserting(client, pool):
    await pool.execute(
        "UPDATE users SET storage_limit_bytes = 2 WHERE id = $1",
        USER_ID,
    )

    response = await _create_note(client, "too-large.md", "abc")

    assert response.status_code == 413
    assert await pool.fetchval(
        "SELECT COUNT(*) FROM documents WHERE user_id = $1",
        USER_ID,
    ) == 0


async def test_update_quota_failure_is_atomic(client, pool):
    created = await _create_note(client, "stable.md", "a")
    doc_id = created.json()["id"]
    await pool.execute(
        "UPDATE users SET storage_limit_bytes = 2 WHERE id = $1",
        USER_ID,
    )

    response = await client.put(
        f"/v1/documents/{doc_id}/content",
        headers=auth_headers(USER_ID),
        json={"content": "abc"},
    )

    assert response.status_code == 413
    row = await pool.fetchrow(
        "SELECT content, file_size FROM documents WHERE id = $1",
        doc_id,
    )
    assert dict(row) == {"content": "a", "file_size": 1}


async def test_concurrent_creates_cannot_both_spend_same_quota(client, pool):
    await pool.execute(
        "UPDATE users SET storage_limit_bytes = 5 WHERE id = $1",
        USER_ID,
    )

    responses = await asyncio.gather(
        _create_note(client, "one.md", "four"),
        _create_note(client, "two.md", "four"),
    )

    assert sorted(response.status_code for response in responses) == [201, 413]
    assert await pool.fetchval(
        "SELECT COALESCE(SUM(file_size), 0) FROM documents WHERE user_id = $1",
        USER_ID,
    ) == 4


async def test_tus_finalize_reserves_quota_in_real_transaction(pool, tmp_path):
    from infra import tus

    class RecordingS3:
        def __init__(self):
            self.uploads = []

        async def upload_file(self, key, file_path, content_type):
            self.uploads.append((key, file_path, content_type))

        async def delete_prefix(self, prefix):
            raise AssertionError(f"unexpected cleanup: {prefix}")

    temp_path = tmp_path / "source.pdf"
    temp_path.write_bytes(b"%PDF-1.4")
    upload = tus.TusUpload(
        upload_id="real-quota-transaction",
        user_id=USER_ID,
        upload_length=8,
        upload_offset=8,
        filename="source.pdf",
        knowledge_base_id=KB_ID,
        temp_path=temp_path,
    )
    tus._uploads[upload.upload_id] = upload
    s3 = RecordingS3()

    doc_id = await tus._finalize(
        upload,
        SimpleNamespace(s3_service=s3, pool=pool, ocr_service=None),
    )

    row = await pool.fetchrow(
        "SELECT user_id::text, knowledge_base_id::text, file_size, status::text "
        "FROM documents WHERE id = $1",
        doc_id,
    )
    assert dict(row) == {
        "user_id": USER_ID,
        "knowledge_base_id": KB_ID,
        "file_size": 8,
        "status": "pending",
    }
    assert len(s3.uploads) == 1
    assert not temp_path.exists()
