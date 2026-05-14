"""Shared types and utilities for service implementations."""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

import yaml
from pydantic import BaseModel, Field

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


class HighlightAnchor(BaseModel):
    """DOM-relative anchor: where the highlight lives on the live page.
    Used by the Chrome extension to re-apply highlights on revisit."""
    xpath: str = Field(max_length=2000)
    endXPath: str | None = Field(default=None, max_length=2000)
    startOffset: int = Field(ge=0)
    endOffset: int = Field(ge=0)
    textContent: str = Field(max_length=10000)
    prefix: str | None = Field(default=None, max_length=200)
    suffix: str | None = Field(default=None, max_length=200)


class TextAnchor(BaseModel):
    """Plaintext-relative anchor: character offsets into the canonical plaintext
    derived from the parsed markdown. Used by the wiki TipTap viewer to render
    highlights as ProseMirror decorations.

    Computed at save time by the html_parser when a web clip is saved with
    highlights — the parser maps each DOM anchor to its plaintext position.
    """
    textStart: int = Field(ge=0)
    textEnd: int = Field(ge=0)
    textContent: str = Field(max_length=10000)
    prefix: str | None = Field(default=None, max_length=200)
    suffix: str | None = Field(default=None, max_length=200)


class Highlight(BaseModel):
    id: str = Field(max_length=64)
    type: Literal["text", "pdf"] = "text"
    anchor: HighlightAnchor | None = None
    textAnchor: TextAnchor | None = None
    comment: str | None = Field(default=None, max_length=4000)
    color: str = Field(default="yellow", max_length=32)
    createdAt: str = Field(max_length=64)


class ReplaceHighlights(BaseModel):
    highlights: list[Highlight] = Field(default_factory=list, max_length=500)
    expectedVersion: int | None = None


class UpsertHighlight(BaseModel):
    """Single-entry idempotent upsert. Server matches by `highlight.id` and
    replaces the matching entry, or appends if absent. Re-posting the same
    payload twice is a no-op semantically (same final state)."""
    highlight: Highlight
    expectedVersion: int | None = None


class DeleteHighlight(BaseModel):
    """Optional body for the DELETE granular endpoint. Empty body is fine."""
    expectedVersion: int | None = None


class CreateWebClip(BaseModel):
    # 10 MB is generous for HTML; a typical blog article is <100 KB.
    # Bounds the BeautifulSoup parsing surface to keep one upload from
    # DoS-ing the API.
    url: str = Field(max_length=2048)
    title: str = Field(max_length=512)
    html: str = Field(max_length=10 * 1024 * 1024)
    highlights: list[Highlight] | None = None


class UpdateContent(BaseModel):
    content: str


class UpdateMetadata(BaseModel):
    filename: str | None = None
    path: str | None = None
    title: str | None = None
    tags: list[str] | None = None
    date: str | None = None
    metadata: dict | None = None
    # knowledge_base_id is the move target. Server validates ownership of the
    # target KB and cascades the kb_id update to chunks/pages.
    knowledge_base_id: str | None = None


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
