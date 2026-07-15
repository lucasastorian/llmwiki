"""Regression tests for set-based hosted persistence helpers."""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


class RecordingConnection:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, *args):
        self.calls.append((sql, args))
        return "INSERT 0 1"


def _load_api_module(name: str, relative_path: str):
    path = Path(__file__).resolve().parents[2] / "api" / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_api_chunk_store_uses_one_set_based_insert():
    chunker = _load_api_module("api_chunker_batch_test", "services/chunker.py")

    conn = RecordingConnection()
    chunks = [
        chunker.Chunk(index=i, content=f"chunk {i}", page=i + 1, start_char=i * 10, token_count=2)
        for i in range(3)
    ]

    await chunker._store_chunks_on_conn(
        conn,
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
        chunks,
    )

    assert len(conn.calls) == 2  # one DELETE + one INSERT, independent of chunk count
    insert_sql, insert_args = conn.calls[1]
    assert "FROM UNNEST" in insert_sql
    assert insert_args[3] == [0, 1, 2]
    assert insert_args[4] == ["chunk 0", "chunk 1", "chunk 2"]


@pytest.mark.asyncio
async def test_ocr_page_store_uses_one_set_based_insert():
    persistence = _load_api_module(
        "api_bulk_persistence_page_test",
        "services/bulk_persistence.py",
    )

    conn = RecordingConnection()
    await persistence.insert_pages(
        conn,
        "11111111-1111-1111-1111-111111111111",
        [
            (1, "page one", {"sheet_name": "One"}),
            (2, "page two", None),
        ],
    )

    assert len(conn.calls) == 1
    sql, args = conn.calls[0]
    assert "FROM UNNEST" in sql
    assert args[1] == [1, 2]
    assert args[2] == ["page one", "page two"]


@pytest.mark.asyncio
async def test_ocr_asset_store_uses_one_set_based_insert():
    persistence = _load_api_module(
        "api_bulk_persistence_asset_test",
        "services/bulk_persistence.py",
    )

    conn = RecordingConnection()
    assets = [
        SimpleNamespace(
            document_id=f"00000000-0000-0000-0000-00000000000{i}",
            filename=f"image-{i}.png",
            path="/assets/",
            file_type="png",
            data=b"png",
            metadata=lambda i=i: {"index": i},
        )
        for i in (1, 2)
    ]

    await persistence.insert_assets(
        conn,
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        assets,
    )

    assert len(conn.calls) == 1
    sql, args = conn.calls[0]
    assert "FROM UNNEST" in sql
    assert args[2] == [asset.document_id for asset in assets]
