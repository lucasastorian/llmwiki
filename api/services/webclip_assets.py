from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from html_parser import Image
from infra.safe_fetch import fetch_public_image

MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TIMEOUT = 5
IMAGE_CONCURRENCY = 6
IMAGE_TOTAL_BUDGET = 6
MAX_IMAGE_REDIRECTS = 3
MAX_WEBCLIP_IMAGES = 50
MAX_WEBCLIP_ASSET_BYTES = 25 * 1024 * 1024

SAFE_MIME_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/avif": "avif",
}


@dataclass
class WebclipAsset:
    filename: str
    src: str
    data: bytes
    content_type: str
    file_type: str
    original_url: str
    alt: str
    sha256: str
    index: int
    width: int | None = None
    height: int | None = None
    document_id: str | None = None

    @property
    def markdown_src(self) -> str:
        return f"./{self.src}"

    def metadata(self) -> dict:
        return {
            "src": self.markdown_src,
            "path": self.src,
            "filename": self.filename,
            "content_type": self.content_type,
            "file_type": self.file_type,
            "original_url": self.original_url,
            "alt": self.alt,
            "sha256": self.sha256,
            "index": self.index,
            "document_id": self.document_id,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class _ByteReservation:
    capacity: int
    active: bool = True


@dataclass
class _ImageSource:
    index: int
    image: Image
    refs: list[str]


class _AssetByteBudget:
    """Track retained payloads and worst-case bytes for active fetches."""

    def __init__(self, limit: int) -> None:
        self._limit = max(0, limit)
        self._retained = 0
        self._reserved = 0
        self._condition = asyncio.Condition()

    async def reserve(self, requested: int) -> _ByteReservation | None:
        requested = min(max(0, requested), self._limit)
        if requested == 0:
            return None

        async with self._condition:
            while True:
                available = self._limit - self._retained - self._reserved
                if available >= requested:
                    self._reserved += requested
                    return _ByteReservation(requested)

                # In-flight fetches may use less than reserved; let them settle before shrinking this limit.
                if self._reserved:
                    await self._condition.wait()
                    continue

                if available <= 0:
                    return None
                self._reserved += available
                return _ByteReservation(available)

    async def retain(self, reservation: _ByteReservation, size: int) -> bool:
        if size < 0 or size > reservation.capacity:
            await self.release(reservation)
            return False
        async with self._condition:
            if not reservation.active:
                return False
            self._reserved -= reservation.capacity
            self._retained += size
            reservation.active = False
            self._condition.notify_all()
        return True

    async def release(self, reservation: _ByteReservation) -> None:
        async with self._condition:
            if not reservation.active:
                return
            self._reserved -= reservation.capacity
            reservation.active = False
            self._condition.notify_all()


def _bounded_unique_sources(images: list[Image]) -> list[_ImageSource]:
    """Select unique effective sources and collect their reference aliases."""

    selected: list[_ImageSource] = []
    selected_by_url: dict[str, _ImageSource] = {}
    seen_refs: set[str] = set()
    limit = max(0, MAX_WEBCLIP_IMAGES)
    if limit == 0:
        return selected

    for index, image in enumerate(images, start=1):
        if not image.ref or image.ref in seen_refs:
            continue
        seen_refs.add(image.ref)

        source = selected_by_url.get(image.url)
        if source is not None:
            source.refs.append(image.ref)
            continue
        if len(selected) >= limit:
            continue

        source = _ImageSource(index=index, image=image, refs=[image.ref])
        selected.append(source)
        selected_by_url[image.url] = source
    return selected


async def materialize_webclip_assets(
    markdown: str,
    images: list[Image],
    asset_dir_name: str,
) -> tuple[str, list[WebclipAsset]]:
    if not images:
        return markdown, []

    selected_sources = _bounded_unique_sources(images)
    sem = asyncio.Semaphore(IMAGE_CONCURRENCY)
    byte_budget = _AssetByteBudget(MAX_WEBCLIP_ASSET_BYTES)
    assets_by_ref: dict[str, WebclipAsset] = {}

    async def fetch_one(source: _ImageSource) -> None:
        index = source.index
        image = source.image
        async with sem:
            reservation = await byte_budget.reserve(MAX_IMAGE_BYTES)
            if reservation is None:
                return

            try:
                result = await _fetch_image(image.url, reservation.capacity)
                if not result:
                    return

                data, content_type = result
                if len(data) > reservation.capacity:
                    return

                fetched_url = image.url
                ext = SAFE_MIME_EXT.get(content_type) or _guess_extension(fetched_url) or "bin"
                filename = f"image-{index:02d}.{ext}"
                src = f"{asset_dir_name}/{filename}"
                inferred_width, inferred_height = _infer_dimensions_from_url(fetched_url)
                asset = WebclipAsset(
                    filename=filename,
                    src=src,
                    data=data,
                    content_type=content_type,
                    file_type=ext,
                    original_url=fetched_url,
                    alt=image.alt,
                    sha256=hashlib.sha256(data).hexdigest(),
                    index=index,
                    width=image.width or inferred_width,
                    height=image.height or inferred_height,
                )
                if not await byte_budget.retain(reservation, len(data)):
                    return
                for ref in source.refs:
                    assets_by_ref[ref] = asset
            finally:
                await byte_budget.release(reservation)

    # Keep whatever materialized within budget; drop the rest on timeout.
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(
            asyncio.gather(*(fetch_one(source) for source in selected_sources)),
            timeout=IMAGE_TOTAL_BUDGET,
        )

    for image in sorted(images, key=lambda img: len(img.ref or ""), reverse=True):
        token = f"llmwiki-image://{image.ref}"
        asset = assets_by_ref.get(image.ref)
        if asset:
            markdown = markdown.replace(token, asset.markdown_src)
        else:
            markdown = _remove_markdown_image_ref(markdown, token)

    assets = [
        assets_by_ref[source.refs[0]]
        for source in selected_sources
        if source.refs[0] in assets_by_ref
    ]
    return markdown, assets


def _remove_markdown_image_ref(markdown: str, token: str) -> str:
    """Drop each `![alt](token)` the parser emitted, finding its opener by a same-line backward scan from the exact reference."""
    reference = f"]({token})"
    parts: list[str] = []
    cursor = 0
    close = markdown.find(reference)
    while close != -1:
        end = close + len(reference)
        opener = _image_opener(markdown, close)
        if opener is None:
            parts.append(markdown[cursor:close + 2])
        else:
            parts.append(markdown[cursor:opener])
            parts.append(_image_gap(markdown, opener, end))
        cursor = close + 2 if opener is None else end
        close = markdown.find(reference, end)
    parts.append(markdown[cursor:])
    return "".join(parts).replace(token, "")


def _image_opener(markdown: str, close: int) -> int | None:
    """Index of the `![` whose alt ends at `close`; the parser escapes every `[`/`]` inside alt text."""
    line_start = markdown.rfind("\n", 0, close) + 1
    for index in range(close - 1, line_start - 1, -1):
        char = markdown[index]
        if char not in "[]" or _is_escaped(markdown, index, line_start):
            continue
        if char == "]" or index == line_start or markdown[index - 1] != "!":
            return None
        return index - 1
    return None


def _is_escaped(markdown: str, index: int, line_start: int) -> bool:
    backslashes = 0
    while index - backslashes - 1 >= line_start and markdown[index - backslashes - 1] == "\\":
        backslashes += 1
    return backslashes % 2 == 1


def _image_gap(markdown: str, start: int, end: int) -> str:
    """The parser writes images flush against neighbouring text; a space keeps those words apart."""
    before = markdown[start - 1:start]
    after = markdown[end:end + 1]
    return " " if before.strip() and after.strip() else ""


def _is_remote_url(url: str) -> bool:
    return url.startswith(("http://", "https://"))


async def _fetch_image(url: str, max_bytes: int | None = None) -> tuple[bytes, str] | None:
    max_bytes = MAX_IMAGE_BYTES if max_bytes is None else min(max_bytes, MAX_IMAGE_BYTES)
    if max_bytes <= 0:
        return None
    if url.startswith("data:"):
        return _decode_data_image(url, max_bytes)
    if _is_remote_url(url):
        return await _fetch_remote_image(url, max_bytes)
    return None


async def _fetch_remote_image(url: str, max_bytes: int | None = None) -> tuple[bytes, str] | None:
    """Fetch an external image with SSRF guards and size/type validation, or None."""
    max_bytes = MAX_IMAGE_BYTES if max_bytes is None else min(max_bytes, MAX_IMAGE_BYTES)
    return await fetch_public_image(
        url,
        max_bytes=max_bytes,
        timeout=IMAGE_TIMEOUT,
        max_redirects=MAX_IMAGE_REDIRECTS,
    )


def _decode_data_image(url: str, max_bytes: int | None = None) -> tuple[bytes, str] | None:
    max_bytes = MAX_IMAGE_BYTES if max_bytes is None else min(max_bytes, MAX_IMAGE_BYTES)
    if max_bytes <= 0:
        return None
    match = re.match(r"^data:([^;,]+)(;base64)?,(.*)$", url, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    content_type = _clean_content_type(match.group(1))
    if content_type not in SAFE_MIME_EXT:
        return None
    try:
        payload = match.group(3)
        if match.group(2):
            if len(payload) % 4:
                return None
            decoded_size = (len(payload) // 4) * 3 - (len(payload) - len(payload.rstrip("=")))
            if decoded_size > max_bytes:
                return None
            data = base64.b64decode(payload, validate=True)
        else:
            if not payload.isascii() or len(payload) > max_bytes:
                return None
            data = payload.encode("ascii")
    except (binascii.Error, ValueError):
        return None
    if len(data) > max_bytes:
        return None
    if _sniff_image_type(data) != content_type:
        return None
    return data, content_type


def _sniff_image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis"}:
        return "image/avif"
    return None


def _clean_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _guess_content_type(url: str) -> str:
    guessed, _ = mimetypes.guess_type(urlparse(url).path)
    return _clean_content_type(guessed or "")


def _guess_extension(url: str) -> str | None:
    content_type = _guess_content_type(url)
    if content_type in SAFE_MIME_EXT:
        return SAFE_MIME_EXT[content_type]
    suffix = urlparse(url).path.rsplit(".", 1)[-1].lower()
    return suffix if suffix in {"jpg", "jpeg", "png", "gif", "webp", "avif"} else None


def _infer_dimensions_from_url(url: str) -> tuple[int | None, int | None]:
    match = re.search(r"/(\d{2,5})x(\d{2,5})(?:[./?_-]|$)", url)
    if not match:
        return None, None
    width = int(match.group(1))
    height = int(match.group(2))
    return (width or None), (height or None)
