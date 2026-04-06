import os
import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Supavault Converter")

ALLOWED_EXTENSIONS = {"pptx", "ppt", "docx", "doc"}
CONVERT_TIMEOUT = 120
CONVERTER_SECRET = os.environ.get("CONVERTER_SECRET", "")
S3_HOST_SUFFIX = ".amazonaws.com"


class ConvertRequest(BaseModel):
    source_url: str
    result_url: str
    source_ext: str


def _validate_s3_url(url: str) -> None:
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.hostname.endswith(S3_HOST_SUFFIX):
        raise HTTPException(400, "URLs must point to S3")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/convert")
async def convert(
    req: ConvertRequest,
    authorization: str = Header(default=""),
):
    if CONVERTER_SECRET:
        expected = f"Bearer {CONVERTER_SECRET}"
        if authorization != expected:
            raise HTTPException(401, "Unauthorized")

    if req.source_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported extension: {req.source_ext}")

    _validate_s3_url(req.source_url)
    _validate_s3_url(req.result_url)

    with tempfile.TemporaryDirectory(dir="/tmp/conversions") as tmpdir:
        source_path = Path(tmpdir) / f"source.{req.source_ext}"

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            resp = await client.get(req.source_url)
            resp.raise_for_status()
            await asyncio.to_thread(source_path.write_bytes, resp.content)

        result = await asyncio.to_thread(
            subprocess.run,
            [
                "libreoffice", "--headless", "--norestore",
                "--convert-to", "pdf", "--outdir", tmpdir,
                str(source_path),
            ],
            capture_output=True,
            timeout=CONVERT_TIMEOUT,
        )
        if result.returncode != 0:
            logger.error("LibreOffice failed: %s", result.stderr.decode()[:500])
            raise HTTPException(500, "Conversion failed")

        pdf_path = Path(tmpdir) / "source.pdf"
        if not pdf_path.exists():
            raise HTTPException(500, "LibreOffice did not produce a PDF")

        pdf_bytes = await asyncio.to_thread(pdf_path.read_bytes)

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            resp = await client.put(
                req.result_url,
                content=pdf_bytes,
                headers={"Content-Type": "application/pdf"},
            )
            resp.raise_for_status()

    logger.info("Converted %s → PDF (%d bytes)", req.source_ext, len(pdf_bytes))
    return {"status": "ok", "size": len(pdf_bytes)}
