"""Supavault Converter — FastAPI app wiring."""

import hmac
import logging

from fastapi import FastAPI, Header, HTTPException

from converter.config import ConverterConfig
from converter.extraction_service import ExtractionService
from converter.models import ExtractRequest

logging.basicConfig(level=logging.INFO)
# httpx logs full request URLs at INFO, and ours are presigned S3 capabilities.
logging.getLogger("httpx").setLevel(logging.WARNING)

config = ConverterConfig.from_env()
service = ExtractionService(config)
app = FastAPI(title="Supavault Converter")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/extract")
async def extract(req: ExtractRequest, authorization: str = Header(default="")) -> dict:
    """Extract per-page markdown from a PDF or Office file (Office converts via LibreOffice first)."""
    _require_bearer(authorization)
    return await service.extract(req)


def _require_bearer(authorization: str) -> None:
    if not hmac.compare_digest(authorization, f"Bearer {config.secret}"):
        raise HTTPException(401, "Unauthorized")
