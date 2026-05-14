"""Unit tests for granular highlight upsert/delete on the SQLite repository.

Covers:
- upsert appends when id is new
- upsert replaces when id exists (idempotent)
- delete removes by id and bumps version
- delete on absent id is a no-op (does NOT bump version)
- expectedVersion mismatch returns {"conflict": True}
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

from infra.db.sqlite import SQLiteDocumentRepository, create_pool


def _hl(idx: str, text: str) -> dict:
    return {
        "id": idx,
        "type": "text",
        "anchor": None,
        "textAnchor": {
            "textStart": 0,
            "textEnd": len(text),
            "textContent": text,
            "prefix": None,
            "suffix": None,
        },
        "comment": None,
        "color": "yellow",
        "createdAt": "2026-05-10T00:00:00Z",
    }


@pytest.fixture
async def repo():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = await create_pool(path)
    repo = SQLiteDocumentRepository(db)
    user_id = "u1"
    # Workspace + doc fixture
    await db.execute(
        "INSERT INTO workspace (id, name, user_id) VALUES ('w1', 'Test', ?)",
        (user_id,),
    )
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, path, relative_path, "
        "source_kind, file_type, status, content, version, highlights) "
        "VALUES ('d1', ?, 'a.html', '/webclipper/', 'webclipper/a.html', "
        "'source', 'html', 'ready', 'hello world', 0, '[]')",
        (user_id,),
    )
    await db.commit()
    try:
        yield repo
    finally:
        await db.close()
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.mark.asyncio
async def test_upsert_appends_when_new(repo: SQLiteDocumentRepository):
    h = _hl("a", "hello")
    res = await repo.upsert_highlight("d1", "u1", h)
    assert res is not None
    assert res["version"] == 1
    assert len(res["highlights"]) == 1
    assert res["highlights"][0]["id"] == "a"


@pytest.mark.asyncio
async def test_upsert_replaces_when_id_exists(repo: SQLiteDocumentRepository):
    await repo.upsert_highlight("d1", "u1", _hl("a", "hello"))
    h2 = _hl("a", "world")
    h2["color"] = "blue"
    res = await repo.upsert_highlight("d1", "u1", h2)
    assert res is not None
    # Two upserts → version 2
    assert res["version"] == 2
    assert len(res["highlights"]) == 1
    assert res["highlights"][0]["color"] == "blue"


@pytest.mark.asyncio
async def test_upsert_with_correct_version(repo: SQLiteDocumentRepository):
    res = await repo.upsert_highlight("d1", "u1", _hl("a", "hello"), expected_version=0)
    assert res is not None
    assert res["version"] == 1


@pytest.mark.asyncio
async def test_upsert_with_stale_version_returns_conflict(repo: SQLiteDocumentRepository):
    await repo.upsert_highlight("d1", "u1", _hl("a", "hello"))
    res = await repo.upsert_highlight("d1", "u1", _hl("b", "world"), expected_version=0)
    assert res == {"conflict": True}


@pytest.mark.asyncio
async def test_delete_removes_by_id(repo: SQLiteDocumentRepository):
    await repo.upsert_highlight("d1", "u1", _hl("a", "hello"))
    await repo.upsert_highlight("d1", "u1", _hl("b", "world"))
    res = await repo.delete_highlight("d1", "u1", "a")
    assert res is not None
    assert res["version"] == 3
    ids = [h["id"] for h in res["highlights"]]
    assert ids == ["b"]


@pytest.mark.asyncio
async def test_delete_absent_id_is_noop_keeps_version(repo: SQLiteDocumentRepository):
    await repo.upsert_highlight("d1", "u1", _hl("a", "hello"))
    res = await repo.delete_highlight("d1", "u1", "does-not-exist")
    assert res is not None
    assert res["version"] == 1  # unchanged
    assert len(res["highlights"]) == 1


@pytest.mark.asyncio
async def test_delete_idempotent_double_delete(repo: SQLiteDocumentRepository):
    await repo.upsert_highlight("d1", "u1", _hl("a", "hello"))
    res1 = await repo.delete_highlight("d1", "u1", "a")
    res2 = await repo.delete_highlight("d1", "u1", "a")
    # First delete bumps version; second is a no-op (id no longer present).
    assert res1["version"] == 2
    assert res2["version"] == 2
    assert res2["highlights"] == []


@pytest.mark.asyncio
async def test_delete_with_stale_version_returns_conflict(repo: SQLiteDocumentRepository):
    await repo.upsert_highlight("d1", "u1", _hl("a", "hello"))
    res = await repo.delete_highlight("d1", "u1", "a", expected_version=0)
    assert res == {"conflict": True}


@pytest.mark.asyncio
async def test_upsert_returns_none_for_missing_doc(repo: SQLiteDocumentRepository):
    res = await repo.upsert_highlight("does-not-exist", "u1", _hl("a", "hello"))
    assert res is None


@pytest.mark.asyncio
async def test_delete_returns_none_for_missing_doc(repo: SQLiteDocumentRepository):
    res = await repo.delete_highlight("does-not-exist", "u1", "a")
    assert res is None


@pytest.mark.asyncio
async def test_upsert_rejects_highlight_without_id(repo: SQLiteDocumentRepository):
    bad = _hl("a", "hello")
    bad.pop("id")
    res = await repo.upsert_highlight("d1", "u1", bad)
    assert res is None


@pytest.mark.asyncio
async def test_upsert_rejects_when_at_500_cap(repo: SQLiteDocumentRepository):
    # Pre-load 500 highlights via direct SQL to avoid 500 API calls in test.
    payload = json.dumps([_hl(f"h{i}", f"text{i}") for i in range(500)])
    await repo._db.execute(
        "UPDATE documents SET highlights = ? WHERE id = ?", (payload, "d1"),
    )
    await repo._db.commit()

    res = await repo.upsert_highlight("d1", "u1", _hl("new", "overflow"))
    assert res == {"limit_exceeded": True}


@pytest.mark.asyncio
async def test_upsert_replace_at_cap_still_works(repo: SQLiteDocumentRepository):
    # Replacing an existing id when at cap should NOT trigger the limit.
    payload = json.dumps([_hl(f"h{i}", f"text{i}") for i in range(500)])
    await repo._db.execute(
        "UPDATE documents SET highlights = ? WHERE id = ?", (payload, "d1"),
    )
    await repo._db.commit()

    res = await repo.upsert_highlight("d1", "u1", _hl("h0", "replaced"))
    assert res is not None
    assert "limit_exceeded" not in res
    assert len(res["highlights"]) == 500
