from __future__ import annotations

import asyncio
import base64
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from html_parser import Image
from infra.safe_fetch import build_pinned_request, parse_public_fetch_url, redirect_location, resolve_public_ip

MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TIMEOUT = 5
IMAGE_CONCURRENCY = 6
IMAGE_TOTAL_BUDGET = 6
MAX_IMAGE_REDIRECTS = 3
MAX_REMOTE_IMAGES = 50

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


async def materialize_webclip_assets(
    markdown: str,
    images: list[Image],
    asset_dir_name: str,
) -> tuple[str, list[WebclipAsset]]:
    if not images:
        return markdown, []

    sem = asyncio.Semaphore(IMAGE_CONCURRENCY)
    assets_by_ref: dict[str, WebclipAsset] = {}
    remote_allowed = {
        image.ref
        for image in [i for i in images if i.ref and _is_remote_url(i.url)][:MAX_REMOTE_IMAGES]
    }

    async def fetch_one(index: int, image: Image) -> None:
        if not image.ref:
            return
        if _is_remote_url(image.url) and image.ref not in remote_allowed:
            return

        fetched: tuple[bytes, str, str] | None = None
        async with sem:
            result = await _fetch_image(image.url)
        if result:
            fetched = (result[0], result[1], image.url)
        if not fetched:
            return

        data, content_type, fetched_url = fetched
        ext = SAFE_MIME_EXT.get(content_type) or _guess_extension(fetched_url) or "bin"
        filename = f"image-{index:02d}.{ext}"
        src = f"{asset_dir_name}/{filename}"
        inferred_width, inferred_height = _infer_dimensions_from_url(fetched_url)
        assets_by_ref[image.ref] = WebclipAsset(
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

    try:
        await asyncio.wait_for(
            asyncio.gather(*(fetch_one(i, image) for i, image in enumerate(images, start=1))),
            timeout=IMAGE_TOTAL_BUDGET,
        )
    except TimeoutError:
        pass  # keep whatever materialized within budget; drop the rest

    for image in sorted(images, key=lambda img: len(img.ref or ""), reverse=True):
        token = f"llmwiki-image://{image.ref}"
        asset = assets_by_ref.get(image.ref)
        if asset:
            markdown = markdown.replace(token, asset.markdown_src)
        else:
            markdown = _remove_markdown_image_ref(markdown, token)

    assets = [assets_by_ref[image.ref] for image in images if image.ref in assets_by_ref]
    return markdown, assets


def _remove_markdown_image_ref(markdown: str, token: str) -> str:
    escaped_token = re.escape(token)
    image_pattern = re.compile(rf"!\[(?:\\.|[^\]])*\]\({escaped_token}\)")
    markdown, count = image_pattern.subn("", markdown)
    return markdown if count else markdown.replace(token, "")


def _is_remote_url(url: str) -> bool:
    return url.startswith(("http://", "https://"))


async def _fetch_image(url: str) -> tuple[bytes, str] | None:
    if url.startswith("data:"):
        return _decode_data_image(url)
    if _is_remote_url(url):
        return await _fetch_remote_image(url)
    return None


async def _fetch_remote_image(url: str) -> tuple[bytes, str] | None:
    """Fetch an external image with SSRF guards and size/type validation, or None."""
    current = url
    async with httpx.AsyncClient(timeout=IMAGE_TIMEOUT, follow_redirects=False, trust_env=False) as client:
        for _ in range(MAX_IMAGE_REDIRECTS + 1):
            parsed = parse_public_fetch_url(current)
            if not parsed:
                return None
            ip = resolve_public_ip(parsed.hostname)
            if not ip:
                return None
            request = build_pinned_request(client, parsed, ip, {"Accept": "image/*"})
            try:
                resp = await client.send(request, stream=True)
            except (httpx.HTTPError, ValueError):
                return None
            try:
                redirect = redirect_location(resp, current)
                if redirect:
                    current = redirect
                    continue
                return await _read_image_response(resp)
            finally:
                await resp.aclose()
    return None


async def _read_image_response(resp: httpx.Response) -> tuple[bytes, str] | None:
    if resp.status_code != 200:
        return None

    content_length = resp.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_IMAGE_BYTES:
        return None

    chunks = bytearray()
    async for chunk in resp.aiter_bytes():
        chunks.extend(chunk)
        if len(chunks) > MAX_IMAGE_BYTES:
            return None
    data = bytes(chunks)

    sniffed = _sniff_image_type(data)
    content_type = _clean_content_type(resp.headers.get("content-type", ""))
    if content_type not in SAFE_MIME_EXT:
        content_type = sniffed or ""
    if content_type not in SAFE_MIME_EXT or sniffed != content_type:
        return None
    return data, content_type


def _decode_data_image(url: str) -> tuple[bytes, str] | None:
    match = re.match(r"^data:([^;,]+)(;base64)?,(.*)$", url, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    content_type = _clean_content_type(match.group(1))
    if content_type not in SAFE_MIME_EXT:
        return None
    try:
        payload = match.group(3)
        data = base64.b64decode(payload, validate=True) if match.group(2) else payload.encode("utf-8")
    except Exception:
        return None
    if len(data) > MAX_IMAGE_BYTES:
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
