import asyncio
import os
import threading
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

import aiosqlite
from domain.watcher import _get_source_kind, _workspace_relative

SCHEMA_PATH = Path(__file__).parents[2] / "shared" / "sqlite_migrations" / "0001_baseline.sql"


class TestWorkspaceRelative:
    def test_windows_paths_normalize_to_forward_slashes(self):
        relative = _workspace_relative(
            PureWindowsPath(r"C:\ws\wiki\concepts\attention.md"),
            PureWindowsPath(r"C:\ws"),
        )
        assert relative == "wiki/concepts/attention.md"

    def test_posix_paths_unchanged(self):
        relative = _workspace_relative(
            PurePosixPath("/ws/wiki/overview.md"),
            PurePosixPath("/ws"),
        )
        assert relative == "wiki/overview.md"

    def test_windows_wiki_page_classified_as_wiki(self):
        relative = _workspace_relative(
            PureWindowsPath(r"C:\ws\wiki\overview.md"),
            PureWindowsPath(r"C:\ws"),
        )
        assert _get_source_kind(relative) == "wiki"

    def test_source_file_classified_as_source(self):
        assert _get_source_kind("papers/paper.pdf") == "source"


async def test_index_file_reads_snapshot_off_event_loop(tmp_path, monkeypatch):
    import domain.watcher as watcher

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "notes.md"
    source.write_text("Event loops should stay responsive. " * 30, encoding="utf-8")

    db = await aiosqlite.connect(":memory:")
    await db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await db.execute(
        "INSERT INTO workspace (id, name, description, user_id) VALUES (?, 'ws', '', ?)",
        (str(uuid.uuid4()), "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )
    await db.commit()

    main_thread = threading.get_ident()
    snapshot_threads: list[int] = []
    original_snapshot = watcher._read_file_snapshot

    def recording_snapshot(*args, **kwargs):
        snapshot_threads.append(threading.get_ident())
        return original_snapshot(*args, **kwargs)

    monkeypatch.setattr(watcher, "_read_file_snapshot", recording_snapshot)
    await watcher._index_file(db, workspace, source)

    assert snapshot_threads
    assert all(thread_id != main_thread for thread_id in snapshot_threads)

    await db.close()


async def test_large_file_modification_is_not_skipped_when_hash_is_none(
    tmp_path,
    monkeypatch,
):
    import domain.watcher as watcher

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "large.md"
    source.write_text("first payload", encoding="utf-8")

    db = await aiosqlite.connect(":memory:")
    await db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await db.execute(
        "INSERT INTO workspace (id, name, description, user_id) VALUES (?, 'ws', '', ?)",
        (str(uuid.uuid4()), "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )
    await db.commit()

    # Treat the fixture as over the hash limit so snapshots omit content_hash without a 100 MB file.
    monkeypatch.setattr(watcher, "MAX_HASH_SIZE_BYTES", 1)
    await watcher._index_file(db, workspace, source)

    first_stat = source.stat()
    source.write_text("later payload", encoding="utf-8")  # same byte length
    os.utime(
        source,
        ns=(first_stat.st_atime_ns, first_stat.st_mtime_ns + 1_000_000_000),
    )
    await watcher._index_file(db, workspace, source)

    cursor = await db.execute(
        "SELECT content, content_hash, version FROM documents WHERE relative_path = ?",
        ("large.md",),
    )
    content, content_hash, version = await cursor.fetchone()
    assert content == "later payload"
    assert content_hash is None
    assert version == 1

    # Identical size/mtime takes the metadata fallback and skips re-indexing.
    await watcher._index_file(db, workspace, source)
    cursor = await db.execute(
        "SELECT version FROM documents WHERE relative_path = ?",
        ("large.md",),
    )
    assert (await cursor.fetchone())[0] == 1

    await db.close()


async def test_binary_insert_is_committed_before_processor_spawn(tmp_path, monkeypatch):
    import domain.local_processor as processor
    import domain.watcher as watcher

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".llmwiki").mkdir()
    source = workspace / "paper.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    db_path = workspace / ".llmwiki" / "index.db"

    db = await aiosqlite.connect(str(db_path))
    await db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await db.execute(
        "INSERT INTO workspace (id, name, description, user_id) VALUES (?, 'ws', '', ?)",
        (str(uuid.uuid4()), "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )
    await db.commit()

    spawn_called = False
    observed_status: list[str | None] = []
    observer_errors: list[BaseException] = []
    observer_done = asyncio.Event()

    def observe_from_isolated_connection(spawn_workspace: Path, doc_id: str):
        nonlocal spawn_called
        spawn_called = True

        async def observe():
            separate = await aiosqlite.connect(str(db_path))
            try:
                cursor = await separate.execute(
                    "SELECT status FROM documents WHERE id = ?",
                    (doc_id,),
                )
                row = await cursor.fetchone()
                observed_status.append(row[0] if row else None)
            except BaseException as exc:
                observer_errors.append(exc)
            finally:
                await separate.close()
                observer_done.set()

        return observe()

    monkeypatch.setattr(
        processor,
        "process_document_isolated",
        observe_from_isolated_connection,
    )

    class CommitOrderConnection:
        def __init__(self, inner):
            self._inner = inner
            self._inserted_document = False

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def execute(self, query, *args):
            cursor = await self._inner.execute(query, *args)
            if "INSERT INTO documents" in query:
                self._inserted_document = True
            return cursor

        async def commit(self):
            if self._inserted_document:
                assert not spawn_called, "processor spawned before document INSERT commit"
            await self._inner.commit()

    await watcher._index_file(CommitOrderConnection(db), workspace, source)
    await asyncio.wait_for(observer_done.wait(), timeout=2)

    assert spawn_called
    assert observer_errors == []
    assert observed_status == ["pending"]

    await db.close()


async def test_unknown_binary_is_finalized_without_processor(tmp_path, monkeypatch):
    import domain.local_processor as processor
    import domain.watcher as watcher

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "archive.unknown"
    source.write_bytes(b"opaque payload")

    db = await aiosqlite.connect(":memory:")
    await db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await db.execute(
        "INSERT INTO workspace (id, name, description, user_id) VALUES (?, 'ws', '', ?)",
        (str(uuid.uuid4()), "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )
    await db.commit()

    spawned = False

    async def unexpected_spawn(*_args):
        nonlocal spawned
        spawned = True

    monkeypatch.setattr(processor, "process_document_isolated", unexpected_spawn)
    await watcher._index_file(db, workspace, source)
    await asyncio.sleep(0)

    cursor = await db.execute(
        "SELECT status, parser FROM documents WHERE relative_path = ?",
        ("archive.unknown",),
    )
    assert await cursor.fetchone() == ("ready", "native")
    assert not spawned
    await db.close()
