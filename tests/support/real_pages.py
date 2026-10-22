"""Frozen real-site HTML snapshots and their reviewed parser goldens."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from tests.support.types import PageGolden, RealPage

CORPUS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "real_pages"
PAGES_PATH = CORPUS_DIR / "pages.json.gz"
GOLDENS_PATH = CORPUS_DIR / "goldens.json.gz"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_pages() -> list[RealPage]:
    """The snapshots, failing loudly if any HTML no longer matches its recorded hash."""
    pages: list[RealPage] = _read_gzip_json(PAGES_PATH)
    for page in pages:
        if sha256_text(page["html"]) != page["sha256"]:
            raise ValueError(f"real page {page['id']} does not match its recorded sha256")
    return pages


def save_pages(pages: list[RealPage]) -> None:
    _write_gzip_json(PAGES_PATH, pages)


def load_goldens() -> dict[str, PageGolden]:
    return _read_gzip_json(GOLDENS_PATH)


def save_goldens(goldens: dict[str, PageGolden]) -> None:
    _write_gzip_json(GOLDENS_PATH, goldens)


def _read_gzip_json(path: Path) -> Any:
    return json.loads(gzip.decompress(path.read_bytes()))


def _write_gzip_json(path: Path, payload: object) -> None:
    """mtime=0 and sorted keys keep the archive byte-identical for identical content."""
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    path.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
