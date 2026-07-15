import asyncio
import logging
import re
import time
from base64 import b64decode
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from auth import get_current_user
from config import settings
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.requests import ClientDisconnect

logger = logging.getLogger(__name__)

# Bytes buffered in memory before flushing a PATCH body to the temp file.
FLUSH_SIZE = 1_048_576


def _append_file(path: Path, data: bytes):
    with open(path, "ab") as f:
        f.write(data)


@dataclass
class _StreamResult:
    bytes_written: int
    overflow: bool
    disconnected: bool


async def _drain_to_temp(request: Request, temp_path: Path, remaining: int) -> _StreamResult:
    """Append the PATCH body to temp_path, capped at `remaining` bytes."""
    buf = bytearray()
    bytes_written = 0
    try:
        async for chunk in request.stream():
            if bytes_written + len(buf) + len(chunk) > remaining:
                return _StreamResult(bytes_written, overflow=True, disconnected=False)
            buf.extend(chunk)
            if len(buf) >= FLUSH_SIZE:
                await asyncio.to_thread(_append_file, temp_path, bytes(buf))
                bytes_written += len(buf)
                buf.clear()
    except ClientDisconnect:
        bytes_written += await _flush(temp_path, buf)
        return _StreamResult(bytes_written, overflow=False, disconnected=True)
    bytes_written += await _flush(temp_path, buf)
    return _StreamResult(bytes_written, overflow=False, disconnected=False)


async def _flush(temp_path: Path, buf: bytearray) -> int:
    """Append any buffered bytes to disk; return how many were written."""
    if not buf:
        return 0
    await asyncio.to_thread(_append_file, temp_path, bytes(buf))
    return len(buf)


# Magic-byte signatures we check at finalize time. We don't try to handle
# every file type — just the major ones that downstream code routes by
# extension. Office/OOXML files are ZIP containers, so they share a magic.
_FILE_SIGNATURES: dict[str, tuple[tuple[bytes, ...], ...]] = {
    "pdf":  ((b"%PDF-",),),
    "png":  ((b"\x89PNG\r\n\x1a\n",),),
    "jpg":  ((b"\xff\xd8\xff",),),
    "jpeg": ((b"\xff\xd8\xff",),),
    "webp": ((b"RIFF",),),    # also check "WEBP" further in but RIFF is enough
    "gif":  ((b"GIF87a", b"GIF89a"),),
    # OOXML — pptx/docx/xlsx are ZIP containers (PK\x03\x04). Legacy
    # ppt/doc/xls are CFB (Compound File Binary) starting with D0CF11E0.
    "pptx": ((b"PK\x03\x04",),),
    "docx": ((b"PK\x03\x04",),),
    "xlsx": ((b"PK\x03\x04",),),
    "ppt":  ((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),),
    "doc":  ((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),),
    "xls":  ((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),),
    # CSV and HTML are text — no reliable magic bytes. Skip the strict check
    # for these; the parser layer is more forgiving and they're low-risk.
}


def _validate_file_signature(temp_path: Path, ext: str) -> None:
    """Refuse files whose first bytes don't match their declared extension."""
    signatures = _FILE_SIGNATURES.get(ext)
    if not signatures:
        return
    try:
        with open(temp_path, "rb") as f:
            head = f.read(16)
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Could not read upload: {e}")
    # WebP is a RIFF container; check both the RIFF magic and the WEBP fourcc.
    if ext == "webp":
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return
        raise HTTPException(status_code=400, detail="File content does not match declared type .webp")
    for group in signatures:
        for prefix in group:
            if head.startswith(prefix):
                return
    raise HTTPException(
        status_code=400,
        detail=f"File content does not match declared type .{ext}",
    )

TUS_VERSION = "1.0.0"
MAX_SIZE = 104_857_600  # 100 MB
MAX_HTML_SIZE = 10 * 1024 * 1024
UPLOAD_DIR = Path("/tmp/supavault_tus_uploads")
STALE_SECONDS = 3600

ALLOWED_EXTENSIONS = {
    ".pdf": "pdf",
    ".pptx": "pptx", ".ppt": "ppt",
    ".docx": "docx", ".doc": "doc",
    ".png": "png", ".jpg": "jpg", ".jpeg": "jpeg",
    ".webp": "webp", ".gif": "gif",
    ".xlsx": "xlsx", ".xls": "xls", ".csv": "csv",
    ".html": "html", ".htm": "html",
}
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel", "csv": "text/csv",
    "html": "text/html", "htm": "text/html",
}

router = APIRouter(prefix="/v1/uploads", tags=["tus"])


@dataclass
class TusUpload:
    upload_id: str
    user_id: str
    upload_length: int
    upload_offset: int
    filename: str
    knowledge_base_id: str
    temp_path: Path
    path: str = "/"
    last_activity: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)


_uploads: dict[str, TusUpload] = {}


def _check_tus_version(request: Request):
    version = request.headers.get("Tus-Resumable")
    if version != TUS_VERSION:
        raise HTTPException(status_code=412, detail=f"Unsupported Tus-Resumable version (expected {TUS_VERSION})")


def _parse_metadata(header: str) -> dict[str, str]:
    result = {}
    if not header:
        return result
    for pair in header.split(","):
        pair = pair.strip()
        parts = pair.split(" ", 1)
        key = parts[0]
        if len(parts) > 1:
            try:
                value = b64decode(parts[1]).decode("utf-8")
            except Exception:
                raise HTTPException(status_code=400, detail=f"Invalid base64 in Upload-Metadata key '{key}'")
        else:
            value = ""
        result[key] = value
    return result


def _tus_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Tus-Resumable": TUS_VERSION}
    if extra:
        headers.update(extra)
    return headers


def _get_upload(upload_id: str, user_id: str) -> TusUpload:
    upload = _uploads.get(upload_id)
    if not upload or upload.user_id != user_id:
        raise HTTPException(status_code=404, detail="Upload not found")
    return upload


async def _finalize(upload: TusUpload, app_state) -> str:
    document_id = str(uuid4())
    user_id = upload.user_id
    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else "pdf"
    file_type = ALLOWED_EXTENSIONS.get(f".{ext}", ext)
    s3_key = f"{user_id}/{document_id}/source.{ext}"
    title = upload.filename.rsplit(".", 1)[0] if "." in upload.filename else upload.filename
    file_size = upload.upload_length

    # Magic-byte + size checks. On mismatch we discard the temp file and pop
    # the upload entry before raising so a rejected upload doesn't linger.
    try:
        _validate_file_signature(upload.temp_path, ext)
        actual_size = upload.temp_path.stat().st_size
        if actual_size != upload.upload_length:
            raise HTTPException(
                status_code=400,
                detail=f"Upload size mismatch: declared {upload.upload_length}, actual {actual_size}",
            )
    except HTTPException:
        upload.temp_path.unlink(missing_ok=True)
        _uploads.pop(upload.upload_id, None)
        raise

    s3_service = app_state.s3_service
    if not s3_service:
        raise ValueError("File storage not configured")
    await s3_service.upload_file(s3_key, str(upload.temp_path), CONTENT_TYPES.get(ext, "application/octet-stream"))

    pool = app_state.pool
    try:
        conn = await pool.acquire()
        try:
            async with conn.transaction():
                # Re-check quota under the same per-user lock used by text and
                # URL-ingest writes. A note created while this TUS upload was
                # in progress must not let finalization overspend the account.
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1::text))",
                    user_id,
                )
                kb_owner = await conn.fetchval(
                    "SELECT user_id::text FROM knowledge_bases WHERE id = $1::uuid",
                    upload.knowledge_base_id,
                )
                if kb_owner != user_id:
                    raise HTTPException(
                        status_code=403,
                        detail="Knowledge base not found or no longer owned by you",
                    )

                limits = await conn.fetchrow(
                    "SELECT storage_limit_bytes FROM users WHERE id = $1",
                    user_id,
                )
                storage_limit = (
                    limits["storage_limit_bytes"]
                    if limits else settings.QUOTA_MAX_STORAGE_BYTES
                )
                current_bytes = await conn.fetchval(
                    "SELECT COALESCE(SUM(file_size), 0) "
                    "FROM documents WHERE user_id = $1",
                    user_id,
                )
                current_bytes = current_bytes or 0
                if current_bytes + file_size > storage_limit:
                    raise HTTPException(
                        status_code=413,
                        detail="Storage quota changed while the upload was in progress",
                    )

                await conn.execute(
                    "INSERT INTO documents (id, knowledge_base_id, user_id, filename, path, title, "
                    "file_type, file_size, status) "
                    "VALUES ($1::uuid, $2::uuid, $3, $4, $8, $5, $6, $7, 'pending')",
                    document_id,
                    upload.knowledge_base_id,
                    user_id,
                    upload.filename,
                    title,
                    file_type,
                    file_size,
                    upload.path,
                )
        finally:
            await pool.release(conn)
    except Exception:
        try:
            await s3_service.delete_prefix(f"{user_id}/{document_id}/")
        except Exception:
            logger.exception("Failed to clean S3 object after TUS finalization error")
        raise
    finally:
        upload.temp_path.unlink(missing_ok=True)
        _uploads.pop(upload.upload_id, None)

    ocr_service = app_state.ocr_service
    if ocr_service:
        asyncio.create_task(ocr_service.process_document(document_id, user_id))

    logger.info("TUS finalized: doc=%s file=%s", document_id[:8], upload.filename)
    return document_id


async def cleanup_stale_uploads():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        stale = [
            uid for uid, u in _uploads.items()
            if not u.lock.locked() and now - u.last_activity > STALE_SECONDS
        ]
        for uid in stale:
            upload = _uploads.pop(uid, None)
            if upload:
                upload.temp_path.unlink(missing_ok=True)
                logger.info("Cleaned stale TUS upload: %s", uid)


async def _get_user_id(request: Request) -> str:
    return await get_current_user(request)


@router.options("")
async def tus_options():
    return Response(
        status_code=204,
        headers=_tus_headers({
            "Tus-Version": TUS_VERSION,
            "Tus-Max-Size": str(MAX_SIZE),
            "Tus-Extension": "creation",
        }),
    )


@router.post("", status_code=201)
async def tus_create(request: Request):
    user_id = await _get_user_id(request)
    _check_tus_version(request)

    upload_length_str = request.headers.get("Upload-Length")
    if not upload_length_str:
        raise HTTPException(status_code=400, detail="Missing Upload-Length header")
    try:
        upload_length = int(upload_length_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Upload-Length")
    if upload_length < 1:
        raise HTTPException(status_code=400, detail="Upload-Length must be positive")
    if upload_length > MAX_SIZE:
        raise HTTPException(status_code=413, detail=f"Upload-Length exceeds maximum of {MAX_SIZE} bytes")

    meta_header = request.headers.get("Upload-Metadata", "")
    metadata = _parse_metadata(meta_header)

    filename = metadata.get("filename", "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename in Upload-Metadata")

    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS.keys())}",
        )
    if ext in {".html", ".htm"} and upload_length > MAX_HTML_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"HTML uploads exceed the {MAX_HTML_SIZE // (1024 * 1024)} MiB limit",
        )

    kb_id = metadata.get("knowledge_base_id", "").strip()
    if not kb_id:
        raise HTTPException(status_code=400, detail="Missing knowledge_base_id in Upload-Metadata")

    pool = request.app.state.pool

    try:
        import uuid as _uuid
        _uuid.UUID(kb_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid knowledge_base_id format")

    kb_owner = await pool.fetchval(
        "SELECT user_id::text FROM knowledge_bases WHERE id = $1::uuid",
        kb_id,
    )
    if kb_owner != user_id:
        raise HTTPException(status_code=403, detail="Knowledge base not found or not owned by you")
    user_limits = await pool.fetchrow(
        "SELECT storage_limit_bytes FROM users WHERE id = $1",
        user_id,
    )
    storage_limit = user_limits["storage_limit_bytes"] if user_limits else settings.QUOTA_MAX_STORAGE_BYTES

    current_bytes = await pool.fetchval(
        "SELECT COALESCE(SUM(file_size), 0) FROM documents WHERE user_id = $1",
        user_id,
    )
    in_progress_bytes = sum(u.upload_length for u in _uploads.values() if u.user_id == user_id)
    if current_bytes + in_progress_bytes + upload_length > storage_limit:
        used_mb = current_bytes / (1024 * 1024)
        max_mb = storage_limit / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"Storage quota exceeded. Using {used_mb:.0f} MB of {max_mb:.0f} MB.",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    upload_id = str(uuid4())
    temp_path = UPLOAD_DIR / upload_id
    temp_path.touch()

    # Sanitize path: must start with /, no traversal, no double slashes
    raw_path = metadata.get("path", "/").strip() or "/"
    upload_path = "/" + raw_path.replace("\\", "/").strip("/") + "/"
    upload_path = re.sub(r"/\.\.(/|$)", "/", upload_path)  # strip traversal
    upload_path = re.sub(r"/+", "/", upload_path)  # collapse double slashes
    if upload_path == "//":
        upload_path = "/"

    upload = TusUpload(
        upload_id=upload_id,
        user_id=user_id,
        upload_length=upload_length,
        upload_offset=0,
        filename=filename,
        knowledge_base_id=kb_id,
        temp_path=temp_path,
        path=upload_path,
    )
    _uploads[upload_id] = upload

    location = f"/v1/uploads/{upload_id}"
    return Response(status_code=201, headers=_tus_headers({"Location": location}))


@router.head("/{upload_id}")
async def tus_head(upload_id: str, request: Request):
    user_id = await _get_user_id(request)
    upload = _get_upload(upload_id, user_id)
    return Response(
        status_code=200,
        headers=_tus_headers({
            "Upload-Offset": str(upload.upload_offset),
            "Upload-Length": str(upload.upload_length),
            "Cache-Control": "no-store",
        }),
    )


@router.patch("/{upload_id}", status_code=204)
async def tus_patch(upload_id: str, request: Request):
    user_id = await _get_user_id(request)
    _check_tus_version(request)

    content_type = request.headers.get("Content-Type", "")
    if content_type != "application/offset+octet-stream":
        raise HTTPException(status_code=415, detail="Content-Type must be application/offset+octet-stream")

    upload = _get_upload(upload_id, user_id)

    offset_str = request.headers.get("Upload-Offset")
    if offset_str is None:
        raise HTTPException(status_code=400, detail="Missing Upload-Offset header")
    try:
        client_offset = int(offset_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Upload-Offset")

    # TUS offsets are compare-and-append state. Serialize the whole operation,
    # including finalization, so concurrent PATCH requests cannot both pass the
    # same offset check and append the declared length twice.
    async with upload.lock:
        # Another PATCH may have finalized and removed this upload while this
        # request waited for the per-upload lock.
        if _uploads.get(upload_id) is not upload:
            raise HTTPException(status_code=404, detail="Upload not found")

        if client_offset != upload.upload_offset:
            raise HTTPException(status_code=409, detail="Offset mismatch")

        upload.last_activity = time.time()

        # Hard ceiling on how many bytes this PATCH can write — never let the
        # client exceed Upload-Length, regardless of streamed body size.
        remaining = upload.upload_length - upload.upload_offset
        result = await _drain_to_temp(request, upload.temp_path, remaining)
        upload.upload_offset += result.bytes_written
        upload.last_activity = time.time()

        if result.overflow:
            raise HTTPException(status_code=413, detail="Body exceeds declared Upload-Length")

        if result.disconnected:
            # Client hung up mid-PATCH. Bytes received so far are persisted and the
            # offset advanced, so the client resumes from HEAD + the next PATCH.
            return Response(
                status_code=204,
                headers=_tus_headers({"Upload-Offset": str(upload.upload_offset)}),
            )

        if upload.upload_offset > upload.upload_length:
            upload.temp_path.unlink(missing_ok=True)
            _uploads.pop(upload_id, None)
            raise HTTPException(status_code=400, detail="Upload exceeded declared length")

        headers = _tus_headers({"Upload-Offset": str(upload.upload_offset)})

        if upload.upload_offset == upload.upload_length:
            try:
                document_id = await _finalize(upload, request.app.state)
                headers["X-Document-Id"] = document_id
            except HTTPException:
                raise
            except Exception:
                logger.exception("TUS finalization failed for upload %s", upload_id)
                raise HTTPException(status_code=500, detail="Finalization failed")

        return Response(status_code=204, headers=headers)
