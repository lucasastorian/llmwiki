"""Request/response models for the API surface."""

import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from domain.quiz_lint import validate_quiz_content
from html_parser.helpers import replace_lone_surrogates
from pydantic import BaseModel, Field, field_validator, model_validator

MAX_TEXT_CONTENT_BYTES = 10 * 1024 * 1024
MAX_WEBCLIP_HTML_CHARS = 4 * 1024 * 1024


def _validate_text_content_size(content: str) -> str:
    if len(content.encode("utf-8")) > MAX_TEXT_CONTENT_BYTES:
        raise ValueError("content must be at most 10 MiB when UTF-8 encoded")
    return content


def _replace_lone_surrogates(value: object) -> object:
    """JS strings may hold unpaired surrogates (e.g. a selection splitting an emoji); keep the text, drop the bad unit."""
    return replace_lone_surrogates(value) if isinstance(value, str) else value


@dataclass
class ChunkRecord:
    """Chunk fields needed for highlight mapping; a None `start_char` (older chunks) means unknown."""
    id: str
    chunk_index: int
    source_content: str
    page: int | None
    start_char: int | None


@dataclass
class DownloadedPdf:
    data: bytes
    filename: str


@dataclass
class ConverterExtraction:
    """Per-page markdown from the converter plus the engine that produced it."""

    pages: list[tuple[int, str]]
    engine: str


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
    content: str = Field(default="", max_length=MAX_TEXT_CONTENT_BYTES)

    _content_size = field_validator("content")(_validate_text_content_size)
    _quiz_blocks = field_validator("content")(validate_quiz_content)


class HighlightAnchor(BaseModel):
    """DOM anchor the extension uses to re-apply a highlight on the live page."""
    xpath: str = Field(max_length=2000)
    endXPath: str | None = Field(default=None, max_length=2000)
    startOffset: int = Field(ge=0)
    endOffset: int = Field(ge=0)
    textContent: str = Field(max_length=10000)
    prefix: str | None = Field(default=None, max_length=200)
    suffix: str | None = Field(default=None, max_length=200)

    _surrogates = field_validator("textContent", "prefix", "suffix", mode="before")(_replace_lone_surrogates)


class TextAnchor(BaseModel):
    """UTF-16 code-unit offsets (JS string indices) into a clip's canonical parse plaintext, computed at save time for the viewer."""
    textStart: int = Field(ge=0)
    textEnd: int = Field(ge=0)
    textContent: str = Field(max_length=10000)
    prefix: str | None = Field(default=None, max_length=200)
    suffix: str | None = Field(default=None, max_length=200)

    _surrogates = field_validator("textContent", "prefix", "suffix", mode="before")(_replace_lone_surrogates)


class PdfRect(BaseModel):
    """One line-rect of a PDF highlight in zoom/rotation-independent user-space points (1/72")."""
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class PdfAnchor(BaseModel):
    """PDF highlight anchor with one rect per visual line of the selection."""
    page: int = Field(ge=1)
    # Offsets into normalized page text; absent on highlights older than offset-aware anchoring.
    textStart: int | None = Field(default=None, ge=0)
    textEnd: int | None = Field(default=None, ge=0)
    textContent: str = Field(max_length=10000)
    prefix: str | None = Field(default=None, max_length=200)
    suffix: str | None = Field(default=None, max_length=200)
    rects: list[PdfRect] = Field(min_length=1, max_length=200)

    _surrogates = field_validator("textContent", "prefix", "suffix", mode="before")(_replace_lone_surrogates)


class HighlightReply(BaseModel):
    """One threaded reply on a highlight's comment, authored by the user or the agent."""
    id: str = Field(max_length=64)
    author: Literal["user", "agent"] = "agent"
    text: str = Field(max_length=4000)
    createdAt: str = Field(max_length=64)

    _surrogates = field_validator("text", mode="before")(_replace_lone_surrogates)


class Highlight(BaseModel):
    id: str = Field(max_length=64)
    type: Literal["text", "pdf"] = "text"
    anchor: HighlightAnchor | None = None
    textAnchor: TextAnchor | None = None
    pdfAnchor: PdfAnchor | None = None
    comment: str | None = Field(default=None, max_length=4000)
    replies: list[HighlightReply] = Field(default_factory=list, max_length=50)
    color: str = Field(default="yellow", max_length=32)
    createdAt: str = Field(max_length=64)

    _surrogates = field_validator("comment", mode="before")(_replace_lone_surrogates)

    @model_validator(mode="after")
    def validate_anchor_shape(self):
        if self.type == "pdf":
            if self.pdfAnchor is None:
                raise ValueError("pdf highlights require pdfAnchor")
            if self.anchor is not None or self.textAnchor is not None:
                raise ValueError("pdf highlights cannot include text anchors")
            if ((self.pdfAnchor.textStart is None) !=
                    (self.pdfAnchor.textEnd is None)):
                raise ValueError("pdf textStart and textEnd must be provided together")
            if (self.pdfAnchor.textStart is not None and
                    self.pdfAnchor.textEnd <= self.pdfAnchor.textStart):
                raise ValueError("pdf textEnd must be greater than textStart")
        else:
            if self.pdfAnchor is not None:
                raise ValueError("text highlights cannot include pdfAnchor")
            if self.anchor is None and self.textAnchor is None:
                raise ValueError("text highlights require anchor or textAnchor")
        return self


class UpsertHighlight(BaseModel):
    """Idempotent upsert: replaces the entry matching `highlight.id`, else appends."""
    highlight: Highlight
    expectedVersion: int | None = None


class CreateFromUrl(BaseModel):
    knowledge_base_id: UUID
    url: str = Field(max_length=2048)
    path: str = Field(default="/", max_length=256)


class CreateWebClip(BaseModel):
    url: str = Field(max_length=2048)
    title: str = Field(max_length=512)
    # Bounds BeautifulSoup parse cost; a typical article is <100 KB.
    html: str = Field(max_length=MAX_WEBCLIP_HTML_CHARS)
    path: str = Field(default="/webclipper/", max_length=256)
    highlights: list[Highlight] | None = Field(default=None, max_length=500)

    _surrogates = field_validator("title", "html", mode="before")(_replace_lone_surrogates)


class UpdateContent(BaseModel):
    content: str = Field(max_length=MAX_TEXT_CONTENT_BYTES)

    _content_size = field_validator("content")(_validate_text_content_size)
    _quiz_blocks = field_validator("content")(validate_quiz_content)


class UpdateMetadata(BaseModel):
    filename: str | None = None
    path: str | None = None
    title: str | None = None
    tags: list[str] | None = None
    date: str | None = None
    metadata: dict | None = None
    # Move target KB.
    knowledge_base_id: str | None = None

    def changed_fields(self) -> dict:
        """Fields the client sent; explicit null clears tags/date and is ignored for the rest."""
        fields = self.model_dump(exclude_unset=True)
        if "tags" in fields and fields["tags"] is None:
            fields["tags"] = []
        return {k: v for k, v in fields.items() if v is not None or k == "date"}


class BulkDelete(BaseModel):
    ids: list[str]


class GradeQuizAnswer(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    rubric: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=4000)


class QuizGradeResponse(BaseModel):
    verdict: Literal["correct", "partial", "incorrect"]
    feedback: str


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
