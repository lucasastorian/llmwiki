import json
import os
import asyncio
import logging
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import httpx
import opendataloader_pdf
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Supavault Converter")

OFFICE_EXTENSIONS = {"pptx", "ppt", "docx", "doc"}
PDF_EXTENSIONS = {"pdf"}
SUPPORTED_EXTENSIONS = OFFICE_EXTENSIONS | PDF_EXTENSIONS
CONVERT_TIMEOUT = 120  # LibreOffice subprocess timeout (seconds)
EXTRACT_TIMEOUT = 180  # opendataloader extraction timeout (seconds)
MAX_SOURCE_BYTES = 200 * 1024 * 1024  # 200 MB — hard cap on downloaded file size

CONVERTER_SECRET = os.environ.get("CONVERTER_SECRET", "")
# Bucket name from env — used to lock the S3 URL allowlist to OUR bucket
# rather than any `*.amazonaws.com` URL (which would let any S3-hosted file
# be processed by this service).
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Refuse to start in "public mode". Setting CONVERTER_SECRET is mandatory.
if not CONVERTER_SECRET:
    raise RuntimeError(
        "CONVERTER_SECRET environment variable is required. "
        "Generate a random string and set it on both the API and converter services."
    )


class ExtractRequest(BaseModel):
    source_url: str
    source_ext: str
    request_id: str | None = None


def _validate_s3_url(url: str) -> None:
    parsed = urlparse(url)
    if not parsed.hostname:
        raise HTTPException(400, "URL has no hostname")
    if not S3_BUCKET:
        # Fall back to broad check if bucket isn't configured. Less safe but
        # the service still works for self-hosters.
        if not parsed.hostname.endswith(".amazonaws.com"):
            raise HTTPException(400, "URLs must point to S3")
        return
    # Strict: only allow URLs pointing at our specific bucket. Accept both
    # virtual-host style (`{bucket}.s3.{region}.amazonaws.com`) and path
    # style (`s3.{region}.amazonaws.com/{bucket}/...`).
    expected_vhost = f"{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com"
    expected_vhost_global = f"{S3_BUCKET}.s3.amazonaws.com"
    vhost_ok = parsed.hostname in (expected_vhost, expected_vhost_global)
    path_ok = (
        parsed.hostname in (f"s3.{S3_REGION}.amazonaws.com", "s3.amazonaws.com")
        and parsed.path.lstrip("/").startswith(f"{S3_BUCKET}/")
    )
    if not (vhost_ok or path_ok):
        raise HTTPException(400, "URL does not point to the configured S3 bucket")


def _element_to_markdown(el: dict) -> str:
    """Convert a single JSON element to markdown."""
    t = el.get("type", "")
    content = el.get("content", "")

    if t == "heading":
        level = max(1, min(el.get("heading level", 1), 6))
        prefix = "#" * level
        return f"{prefix} {content}"

    if t == "paragraph":
        return content

    if t == "list":
        lines = []
        for item in el.get("list items", []):
            lines.append(f"- {item.get('content', '')}")
            for child in item.get("kids", []):
                lines.append(f"  - {child.get('content', '')}")
        return "\n".join(lines)

    if t == "image":
        src = el.get("source", "")
        return f"![image]({src})" if src else ""

    if t == "caption":
        return f"*{content}*" if content else ""

    return ""


def _extract_pages(pdf_path: str, output_dir: str) -> list[dict]:
    """Run opendataloader-pdf with JSON output and return per-page markdown."""
    opendataloader_pdf.convert(
        input_path=pdf_path,
        output_dir=output_dir,
        format="json",
        quiet=True,
    )

    json_files = list(Path(output_dir).glob("*.json"))
    if not json_files:
        raise RuntimeError("opendataloader-pdf produced no output")

    with open(json_files[0], encoding="utf-8") as f:
        data = json.load(f)

    total_pages = data.get("number of pages", 0)
    elements = data.get("kids", [])
    page_elements: dict[int, list[dict]] = defaultdict(list)

    for el in elements:
        page_num = el.get("page number")
        if page_num is None or el.get("type") in ("header", "footer"):
            continue
        page_elements[page_num].append(el)

    pages = []
    for page_num in range(1, total_pages + 1):
        parts = []
        for el in page_elements.get(page_num, []):
            md = _element_to_markdown(el)
            if md:
                parts.append(md)
        pages.append({"page": page_num, "content": "\n\n".join(parts)})

    return pages


def _convert_to_pdf(source_path: Path, tmpdir: str) -> Path:
    """Convert Office file to PDF via LibreOffice."""
    result = subprocess.run(
        [
            "libreoffice", "--headless", "--norestore",
            "--convert-to", "pdf", "--outdir", tmpdir,
            str(source_path),
        ],
        capture_output=True,
        timeout=CONVERT_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice failed: {result.stderr.decode()[:500]}")

    pdf_path = Path(tmpdir) / f"{source_path.stem}.pdf"
    if not pdf_path.exists():
        raise RuntimeError("LibreOffice did not produce a PDF")

    return pdf_path


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/extract")
async def extract(
    req: ExtractRequest,
    authorization: str = Header(default=""),
):
    """Extract markdown pages from PDF or Office files.

    For Office files, converts to PDF first via LibreOffice.
    Returns per-page markdown content.
    """
    if CONVERTER_SECRET:
        expected = f"Bearer {CONVERTER_SECRET}"
        if authorization != expected:
            raise HTTPException(401, "Unauthorized")

    ext = req.source_ext.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported extension: {ext}")

    _validate_s3_url(req.source_url)

    with tempfile.TemporaryDirectory(dir="/tmp/conversions") as tmpdir:
        source_path = Path(tmpdir) / f"source.{ext}"

        # Stream the download and abort if the file exceeds MAX_SOURCE_BYTES.
        # Don't buffer the whole response into memory.
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            async with client.stream("GET", req.source_url) as resp:
                resp.raise_for_status()
                total = 0
                with open(source_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(64 * 1024):
                        total += len(chunk)
                        if total > MAX_SOURCE_BYTES:
                            raise HTTPException(
                                413,
                                f"Source file exceeds {MAX_SOURCE_BYTES} bytes",
                            )
                        f.write(chunk)

        if ext in OFFICE_EXTENSIONS:
            pdf_path = await asyncio.to_thread(_convert_to_pdf, source_path, tmpdir)
        else:
            pdf_path = source_path

        extract_dir = Path(tmpdir) / "extract"
        extract_dir.mkdir()
        # Wall-clock bound on opendataloader. It runs in a thread so this
        # won't kill the underlying Java process if it deadlocks, but it
        # prevents the request from hanging the API indefinitely.
        try:
            pages = await asyncio.wait_for(
                asyncio.to_thread(_extract_pages, str(pdf_path), str(extract_dir)),
                timeout=EXTRACT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                504,
                f"PDF extraction exceeded {EXTRACT_TIMEOUT}s timeout",
            )

    page_count = len(pages)
    logger.info("Extracted %s: %d pages (request_id=%s)", ext, page_count, req.request_id or "none")
    response = {"pages": pages, "page_count": page_count}
    if req.request_id:
        response["request_id"] = req.request_id
    return response
