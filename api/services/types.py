"""Request/response models for the API surface."""

import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


@dataclass
class DownloadedPdf:
    data: bytes
    filename: str


class CreateKB(BaseModel):
    name: str
    description: str | None = None
    kind: Literal["wiki", "course"] | None = None


class UpdateKB(BaseModel):
    name: str | None = None
    description: str | None = None
    kind: Literal["wiki", "course"] | None = None


# Mirrors the DB CHECK constraint on knowledge_bases.public_slug.
_PUBLIC_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,78}[a-z0-9]$")


class UpdateSharing(BaseModel):
    visibility: Literal["private", "shared", "public"]
    public_slug: str | None = Field(default=None, max_length=80)

    def validated_slug(self) -> str | None:
        if self.public_slug is None:
            return None
        slug = self.public_slug.strip().lower()
        if not _PUBLIC_SLUG_RE.match(slug):
            return None
        return slug


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


class PdfRect(BaseModel):
    """One line-rect of a PDF highlight, in PDF user-space points (1/72").
    Zoom/rotation independent — viewer converts to viewport coords at render."""
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class PdfAnchor(BaseModel):
    """PDF-relative anchor used when Highlight.type == "pdf".
    Stored once per highlight; one rect per visual line of the selection."""
    page: int = Field(ge=1)
    textContent: str = Field(max_length=10000)
    prefix: str | None = Field(default=None, max_length=200)
    suffix: str | None = Field(default=None, max_length=200)
    rects: list[PdfRect] = Field(min_length=1, max_length=200)


class Highlight(BaseModel):
    id: str = Field(max_length=64)
    type: Literal["text", "pdf"] = "text"
    anchor: HighlightAnchor | None = None
    textAnchor: TextAnchor | None = None
    pdfAnchor: PdfAnchor | None = None
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


class CreateFromUrl(BaseModel):
    knowledge_base_id: UUID
    url: str = Field(max_length=2048)
    path: str = Field(default="/", max_length=256)


class CreateWebClip(BaseModel):
    # 10 MB is generous for HTML; a typical blog article is <100 KB.
    # Bounds the BeautifulSoup parsing surface to keep one upload from
    # DoS-ing the API.
    url: str = Field(max_length=2048)
    title: str = Field(max_length=512)
    html: str = Field(max_length=10 * 1024 * 1024)
    path: str = Field(default="/webclipper/", max_length=256)
    highlights: list[Highlight] | None = Field(default=None, max_length=500)


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
