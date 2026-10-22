"""SqliteVaultFS fixtures on a temp workspace."""

import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp"))

TEST_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture
async def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "wiki").mkdir()
    (ws / ".llmwiki").mkdir()
    (ws / ".llmwiki" / "cache").mkdir()
    return ws


@pytest.fixture
async def fs(workspace):
    from vaultfs.sqlite import SqliteVaultFS
    await SqliteVaultFS.init(str(workspace))
    instance = SqliteVaultFS(TEST_USER_ID)
    kb_id = await instance.ensure_workspace("test-workspace")
    yield instance, kb_id
    await SqliteVaultFS.close()


@pytest.fixture
async def insert_page(fs):
    async def _insert(doc_id: str, page: int, content: str, elements: dict | None = None):
        from vaultfs.sqlite import SqliteVaultFS
        db = SqliteVaultFS._db_or_raise()
        await db.execute(
            "INSERT INTO document_pages (id, document_id, page, content, elements) "
            "VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), doc_id, page, content, json.dumps(elements) if elements else None),
        )
        await db.commit()
    return _insert


@pytest.fixture
async def insert_chunk(fs):
    async def _insert(doc_id: str, kb_id: str, content: str, page: int = 1, breadcrumb: str = ""):
        from vaultfs.sqlite import SqliteVaultFS
        db = SqliteVaultFS._db_or_raise()
        await db.execute(
            "INSERT INTO document_chunks (id, document_id, "
            "chunk_index, content, page, header_breadcrumb, token_count) "
            "SELECT ?, ?, COALESCE(MAX(chunk_index), -1) + 1, ?, ?, ?, 10 "
            "FROM document_chunks WHERE document_id = ?",
            (str(uuid.uuid4()), doc_id, content, page, breadcrumb, doc_id),
        )
        await db.commit()
    return _insert
