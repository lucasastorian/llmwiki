"""Shared types and utilities for service implementations."""

import re
from datetime import datetime
from uuid import UUID

import yaml
from pydantic import BaseModel

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.+?\n)---[ \t]*\n", re.DOTALL)


def parse_frontmatter(content: str) -> dict:
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}
    try:
        meta = yaml.safe_load(m.group(1))
    except Exception:
        return {}
    return meta if isinstance(meta, dict) else {}


def title_from_filename(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return stem.replace("-", " ").replace("_", " ").strip().title()


def extract_tags(meta: dict) -> list[str]:
    tags = meta.get("tags", [])
    if isinstance(tags, list):
        return [str(t) for t in tags if t is not None]
    return []


# ── Request/response models ──

class CreateKB(BaseModel):
    name: str
    description: str | None = None


class UpdateKB(BaseModel):
    name: str | None = None
    description: str | None = None


class CreateNote(BaseModel):
    filename: str
    path: str = "/"
    content: str = ""


class UpdateContent(BaseModel):
    content: str


class UpdateMetadata(BaseModel):
    filename: str | None = None
    path: str | None = None
    title: str | None = None
    tags: list[str] | None = None
    date: str | None = None
    metadata: dict | None = None


class BulkDelete(BaseModel):
    ids: list[str]


class MeResponse(BaseModel):
    id: str
    email: str
    display_name: str | None
    onboarded: bool


class UsageResponse(BaseModel):
    total_pages: int
    total_storage_bytes: int
    document_count: int
    max_pages: int
    max_storage_bytes: int
