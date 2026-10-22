"""Local-mode filesystem watcher; file identity is by path, so a rename is delete + create."""

import asyncio
import contextlib
import hashlib
import logging
import time
import uuid
from pathlib import Path, PurePath

import aiosqlite
from domain.file_types import PROCESSING_TYPES, SIMPLE_TEXT_TYPES

logger = logging.getLogger(__name__)

IGNORE_DIRS = frozenset({
    ".llmwiki", ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".idea", ".vscode", ".DS_Store",
})

COOLDOWN_SECONDS = 2.0
MAX_HASH_SIZE_BYTES = 100_000_000

_ignore_patterns: list[str] | None = None


def _load_ignore_patterns(workspace: Path) -> list[str]:
    """Load ignore patterns from .llmwikiignore, falling back to .gitignore."""
    global _ignore_patterns
    if _ignore_patterns is not None:
        return _ignore_patterns

    patterns = []
    for ignore_file in (".llmwikiignore", ".gitignore"):
        p = workspace / ignore_file
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
            break
    _ignore_patterns = patterns
    return patterns


def _matches_ignore_pattern(relative: str, patterns: list[str]) -> bool:
    """Simple gitignore-style matching (directory and glob patterns)."""
    from fnmatch import fnmatch
    for pattern in patterns:
        pattern = pattern.rstrip("/")
        if fnmatch(relative, pattern):
            return True
        if fnmatch(relative, f"**/{pattern}"):
            return True
        for part in relative.split("/"):
            if fnmatch(part, pattern):
                return True
    return False

# App-initiated writes, skipped by the watcher to avoid re-indexing loops.
_recently_written: dict[str, float] = {}


def mark_written(path: str) -> None:
    """Mark a path as recently written by the app. Watcher will skip it."""
    _recently_written[str(Path(path).resolve())] = time.monotonic()


def _is_recently_written(path: str) -> bool:
    resolved = str(Path(path).resolve())
    ts = _recently_written.get(resolved)
    if ts and (time.monotonic() - ts) < COOLDOWN_SECONDS:
        return True
    _recently_written.pop(resolved, None)
    return False


def _should_ignore(
    path: Path,
    workspace: Path,
    patterns: list[str] | None = None,
) -> bool:
    """Check if a path should be ignored based on directory rules + ignore files."""
    try:
        relative = path.relative_to(workspace)
    except ValueError:
        return True

    relative_str = relative.as_posix()
    parts = relative.parts

    for part in parts:
        if part in IGNORE_DIRS or part.startswith("."):
            return True

    if patterns is None:
        patterns = _load_ignore_patterns(workspace)
    return bool(patterns and _matches_ignore_pattern(relative_str, patterns))


def _workspace_relative(file_path: PurePath, workspace: PurePath) -> str:
    """Workspace-relative path with forward slashes on every platform."""
    return file_path.relative_to(workspace).as_posix()


def _get_source_kind(relative_path: str) -> str:
    if relative_path.startswith("wiki/"):
        return "wiki"
    return "source"


def _read_file_snapshot(file_path: Path, include_content: bool):
    """Read filesystem metadata/content/hash without blocking the event loop."""
    stat = file_path.stat()

    content = None
    if include_content:
        with contextlib.suppress(OSError):
            content = file_path.read_text(encoding="utf-8", errors="replace")

    content_hash = None
    if stat.st_size < MAX_HASH_SIZE_BYTES:
        with contextlib.suppress(OSError):
            digest = hashlib.sha256()
            with file_path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            content_hash = digest.hexdigest()

    return stat, content, content_hash


async def _index_file(db: aiosqlite.Connection, workspace: Path, file_path: Path) -> None:
    relative = _workspace_relative(file_path, workspace)
    filename = file_path.name
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    parts = relative.split("/")
    if len(parts) > 1:
        dir_path = "/" + "/".join(parts[:-1]) + "/"
    else:
        dir_path = "/"

    source_kind = _get_source_kind(relative)

    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    title = stem.replace("-", " ").replace("_", " ").strip().title()

    stat, content, content_hash = await asyncio.to_thread(
        _read_file_snapshot,
        file_path,
        ext in SIMPLE_TEXT_TYPES,
    )

    cursor = await db.execute(
        "SELECT id, content_hash, file_size, mtime_ns FROM documents WHERE relative_path = ?",
        (relative,),
    )
    existing = await cursor.fetchone()

    if existing:
        doc_id, old_hash, old_size, old_mtime_ns = existing
        hash_matches = content_hash is not None and old_hash == content_hash
        metadata_matches = (
            content_hash is None
            and old_size == stat.st_size
            and old_mtime_ns == int(stat.st_mtime_ns)
        )
        if hash_matches or metadata_matches:
            return
        await db.execute(
            "UPDATE documents SET content = ?, file_size = ?, content_hash = ?, "
            "mtime_ns = ?, last_indexed_at = datetime('now'), "
            "updated_at = datetime('now'), version = version + 1 "
            "WHERE id = ?",
            (content, stat.st_size, content_hash, int(stat.st_mtime_ns), doc_id),
        )
        await db.commit()
        logger.info("Re-indexed (modified): %s", relative)
        if ext in PROCESSING_TYPES:
            await db.execute(
                "UPDATE documents SET status = 'pending', parser = NULL, error_message = NULL, "
                "updated_at = datetime('now') WHERE id = ?",
                (doc_id,),
            )
            await db.commit()
            from domain.local_processor import process_document_isolated
            asyncio.create_task(process_document_isolated(workspace, doc_id))
        elif content is not None:
            from domain.local_processor import chunk_text_document
            await chunk_text_document(db, doc_id, content)
        else:
            # No extractor can make unknown binaries searchable; finalize without a background job.
            await db.execute(
                "UPDATE documents SET status = 'ready', parser = 'native', "
                "error_message = NULL, updated_at = datetime('now') WHERE id = ?",
                (doc_id,),
            )
            await db.commit()
        return

    doc_id = str(uuid.uuid4())
    cursor = await db.execute(
        "SELECT COALESCE(MAX(document_number), 0) + 1 FROM documents",
    )
    row = await cursor.fetchone()
    doc_number = row[0]

    needs_processing = ext in PROCESSING_TYPES
    status = "pending" if needs_processing else "ready"
    parser = "native" if content is None and not needs_processing else None
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, "
        "source_kind, file_type, file_size, status, content, tags, version, "
        "content_hash, mtime_ns, last_indexed_at, document_number, parser) "
        "VALUES (?, (SELECT user_id FROM workspace LIMIT 1), ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, '[]', 0, ?, ?, datetime('now'), ?, ?)",
        (doc_id, filename, title, dir_path, relative, source_kind,
         ext or "bin", stat.st_size, status, content, content_hash,
         int(stat.st_mtime_ns), doc_number, parser),
    )
    logger.info("Indexed (new): %s", relative)
    # Commit before spawning: the processor's own connection must see the row to claim it.
    await db.commit()
    if status == "pending":
        from domain.local_processor import process_document_isolated
        asyncio.create_task(process_document_isolated(workspace, doc_id))

    if status == "ready" and content is not None:
        from domain.local_processor import chunk_text_document
        await chunk_text_document(db, doc_id, content)


async def _remove_file(db: aiosqlite.Connection, workspace: Path, file_path: Path) -> None:
    try:
        relative = _workspace_relative(file_path, workspace)
    except ValueError:
        return

    cursor = await db.execute(
        "DELETE FROM documents WHERE relative_path = ?", (relative,),
    )
    if cursor.rowcount > 0:
        await db.commit()
        logger.info("Removed from index: %s", relative)


async def watch_workspace(db: aiosqlite.Connection, workspace: Path) -> None:
    """Sync workspace file changes into the SQLite index until cancelled."""
    from watchfiles import Change, awatch

    logger.info("File watcher started: %s", workspace)
    ignore_patterns = await asyncio.to_thread(_load_ignore_patterns, workspace)

    async for changes in awatch(
        str(workspace),
        watch_filter=lambda change, path: not _should_ignore(
            Path(path), workspace, ignore_patterns,
        ),
        debounce=500,
        step=200,
    ):
        for change_type, path_str in changes:
            path = Path(path_str)

            if _should_ignore(path, workspace, ignore_patterns):
                continue

            if _is_recently_written(path_str):
                continue

            try:
                if change_type == Change.added or change_type == Change.modified:
                    if await asyncio.to_thread(path.is_file):
                        await _index_file(db, workspace, path)
                elif change_type == Change.deleted:
                    await _remove_file(db, workspace, path)
            except Exception as e:  # noqa: BLE001 -- watcher must survive per-file failures
                logger.warning("Watcher error for %s: %s", path_str, e)

        now = time.monotonic()
        expired = [k for k, v in _recently_written.items() if now - v > COOLDOWN_SECONDS * 2]
        for k in expired:
            _recently_written.pop(k, None)
