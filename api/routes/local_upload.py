"""Local multipart upload (no TUS): copies files into the workspace and indexes them."""

import asyncio
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from config import settings
from deps import get_user_id
from domain.file_types import PROCESSING_TYPES, SIMPLE_TEXT_TYPES
from domain.watcher import mark_written
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from infra.threads import executor_future, to_thread_joined, wait_ignoring_cancellation
from services.types import MAX_TEXT_CONTENT_BYTES

router = APIRouter(tags=["upload"])

MAX_LOCAL_UPLOAD_BYTES = 100 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class _StagedUpload:
    path: Path
    size: int
    digest: str


async def _to_thread_cleanup(func, /, *args, **kwargs):
    """Finish filesystem cleanup even if shutdown sends another cancellation."""
    return await wait_ignoring_cancellation(executor_future(func, *args, **kwargs))


async def _to_thread_deferred_cancel(func, /, *args, **kwargs):
    """Finish a critical filesystem mutation and report cancellation afterward."""
    worker = executor_future(func, *args, **kwargs)
    try:
        return await asyncio.shield(worker), None
    except asyncio.CancelledError as cancellation:
        return await wait_ignoring_cancellation(worker), cancellation


async def _await_deferred_cancel(awaitable):
    """As above, for an async critical operation such as SQLite commit."""
    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.shield(task), None
    except asyncio.CancelledError as cancellation:
        return await wait_ignoring_cancellation(task), cancellation


async def _await_cleanup(awaitable):
    return await wait_ignoring_cancellation(asyncio.create_task(awaitable))


def _write_chunk(output, chunk: bytes) -> None:
    output.write(chunk)


def _flush_and_close(output) -> None:
    try:
        output.flush()
        os.fsync(output.fileno())
    finally:
        output.close()


def _replace_path(source: Path, destination: Path) -> None:
    source.replace(destination)


def _publish_and_mark(source: Path, destination: Path, state: dict[str, bool]) -> None:
    _replace_path(source, destination)
    state["published"] = True


def _workspace_root() -> Path:
    return Path(settings.WORKSPACE_PATH).resolve()


def _safe_resolve(relative: str) -> Path:
    ws = _workspace_root()
    resolved = (ws / relative).resolve()
    if not resolved.is_relative_to(ws):
        raise HTTPException(status_code=400, detail="Path escapes workspace")
    return resolved


async def _stream_upload_to_temp(
    file: UploadFile,
    dest: Path,
    *,
    max_bytes: int = MAX_LOCAL_UPLOAD_BYTES,
) -> _StagedUpload:
    """Stream an upload to a same-directory temporary file."""
    await to_thread_joined(dest.parent.mkdir, parents=True, exist_ok=True)
    temp_path = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.upload")
    hasher = hashlib.sha256()
    total = 0
    output_holder: dict[str, object] = {}

    def open_output() -> None:
        output_holder["output"] = temp_path.open("xb")

    completed = False
    try:
        await to_thread_joined(open_output)
        output = output_holder["output"]
        while True:
            chunk = await file.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload exceeds the {max_bytes // (1024 * 1024)} MB limit",
                )
            hasher.update(chunk)
            await to_thread_joined(_write_chunk, output, chunk)

        await to_thread_joined(_flush_and_close, output)
        completed = True
        return _StagedUpload(temp_path, total, hasher.hexdigest())
    finally:
        output = output_holder.get("output")
        if output is not None and not output.closed:
            await _to_thread_cleanup(output.close)
        if not completed:
            await _to_thread_cleanup(temp_path.unlink, missing_ok=True)


@router.post("/v1/upload", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    path: str = Form(default="/"),
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    """Upload a file directly into the workspace and index it."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")

    filename = file.filename
    relative = (path.rstrip("/") + "/" + filename).lstrip("/")
    dest = _safe_resolve(relative)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    max_bytes = MAX_TEXT_CONTENT_BYTES if ext in SIMPLE_TEXT_TYPES else MAX_LOCAL_UPLOAD_BYTES
    staged = await _stream_upload_to_temp(file, dest, max_bytes=max_bytes)
    try:
        # Chunk off the event loop before publishing; chunks commit in the document row's transaction.
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        title = stem.replace("-", " ").replace("_", " ").strip().title()
        dir_path = (
            "/" + "/".join(relative.split("/")[:-1]) + "/"
            if "/" in relative
            else "/"
        )
        source_kind = "wiki" if relative.startswith("wiki/") else "source"
        text_content = None
        text_chunks = None
        needs_processing = ext in PROCESSING_TYPES
        if ext in SIMPLE_TEXT_TYPES:
            text_content = await to_thread_joined(
                staged.path.read_text,
                encoding="utf-8",
                errors="replace",
            )
            from services.chunker import chunk_text

            text_chunks = await to_thread_joined(chunk_text, text_content)
        mtime_ns = (await to_thread_joined(staged.path.stat)).st_mtime_ns

        from infra.db.sqlite import SQLiteDocumentRepository, serialized_write

        db = request.app.state.sqlite_db
        doc_repo = SQLiteDocumentRepository(db)
        doc_id = str(uuid.uuid4())
        publish_state = {"published": False}
        commit_state = {"committed": False}
        deferred_cancellation: asyncio.CancelledError | None = None

        try:
            async with serialized_write():
                existing = await db.execute(
                    "SELECT id FROM documents WHERE relative_path = ?",
                    (relative,),
                )
                if await existing.fetchone() or await to_thread_joined(dest.exists):
                    raise HTTPException(
                        status_code=409,
                        detail=f"'{relative}' already exists",
                    )

                cursor = await db.execute(
                    "SELECT COALESCE(MAX(document_number), 0) + 1 FROM documents"
                )
                row = await cursor.fetchone()
                doc_number = row[0]
                await db.execute(
                    "INSERT INTO documents (id, user_id, filename, title, path, "
                    "relative_path, source_kind, file_type, file_size, status, content, "
                    "tags, version, content_hash, mtime_ns, last_indexed_at, "
                    "document_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', "
                    "0, ?, ?, datetime('now'), ?)",
                    (
                        doc_id,
                        user_id,
                        filename,
                        title,
                        dir_path,
                        relative,
                        source_kind,
                        ext or "bin",
                        staged.size,
                        "pending" if needs_processing else "ready",
                        text_content,
                        staged.digest,
                        int(mtime_ns),
                        doc_number,
                    ),
                )
                if text_chunks:
                    await db.executemany(
                        "INSERT INTO document_chunks "
                        "(id, document_id, chunk_index, content, source_content, page, "
                        "start_char, token_count, header_breadcrumb) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            (
                                str(uuid.uuid4()),
                                doc_id,
                                chunk.index,
                                chunk.content,
                                chunk.content,
                                chunk.page,
                                chunk.start_char,
                                chunk.token_count,
                                chunk.header_breadcrumb,
                            )
                            for chunk in text_chunks
                        ],
                    )

                mark_written(str(dest))
                _, publish_cancellation = await _to_thread_deferred_cancel(
                    _publish_and_mark,
                    staged.path,
                    dest,
                    publish_state,
                )

                async def commit_and_mark() -> None:
                    await db.commit()
                    commit_state["committed"] = True

                _, commit_cancellation = await _await_deferred_cancel(commit_and_mark())
                deferred_cancellation = publish_cancellation or commit_cancellation
        except BaseException:
            if not commit_state["committed"]:
                await _await_cleanup(db.rollback())
                if publish_state["published"]:
                    await _to_thread_cleanup(dest.unlink, missing_ok=True)
            raise

        if needs_processing:
            from domain.local_processor import process_document_isolated

            asyncio.create_task(process_document_isolated(_workspace_root(), doc_id))

        if deferred_cancellation is not None:
            raise deferred_cancellation

        return await doc_repo.get(doc_id)
    finally:
        await _to_thread_cleanup(staged.path.unlink, missing_ok=True)
