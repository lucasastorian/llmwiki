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
CONVERT_TIMEOUT = 120
CONVERTER_SECRET = os.environ.get("CONVERTER_SECRET", "")
S3_HOST_SUFFIX = ".amazonaws.com"


class ExtractRequest(BaseModel):
    source_url: str
    source_ext: str
    request_id: str | None = None


def _validate_s3_url(url: str) -> None:
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.hostname.endswith(S3_HOST_SUFFIX):
        raise HTTPException(400, "URLs must point to S3")


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

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            resp = await client.get(req.source_url)
            resp.raise_for_status()
            await asyncio.to_thread(source_path.write_bytes, resp.content)

        if ext in OFFICE_EXTENSIONS:
            pdf_path = await asyncio.to_thread(_convert_to_pdf, source_path, tmpdir)
        else:
            pdf_path = source_path

        extract_dir = Path(tmpdir) / "extract"
        extract_dir.mkdir()
        pages = await asyncio.to_thread(_extract_pages, str(pdf_path), str(extract_dir))

    page_count = len(pages)
    logger.info("Extracted %s: %d pages (request_id=%s)", ext, page_count, req.request_id or "none")
    response = {"pages": pages, "page_count": page_count}
    if req.request_id:
        response["request_id"] = req.request_id
    return response
