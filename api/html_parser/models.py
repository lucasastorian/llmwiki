from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ElementKind = Literal["heading", "paragraph", "table", "list", "blockquote", "code", "form", "text"]


@dataclass
class Element:
    id: str
    content: str
    kind: ElementKind


@dataclass
class Image:
    url: str
    alt: str = ""
    ref: str = ""
    width: int | None = None
    height: int | None = None
    candidate_urls: list[str] = field(default_factory=list)


@dataclass
class EmphasisFrame:
    """An emphasis pair being resolved: its `*` delimiter and the content resolved so far."""
    delimiter: str
    parts: list[str] = field(default_factory=list)
    has_ambiguous: bool = False


@dataclass
class TextAnchor:
    """UTF-16 code-unit offsets into the canonical parse plaintext (JS string indices); mirrors the API-level TextAnchor."""
    text_start: int
    text_end: int
    text_content: str
    prefix: str | None = None
    suffix: str | None = None


@dataclass
class MappedHighlight:
    """A caller-supplied highlight payload plus its parser-computed plaintext anchor."""
    payload: dict[str, Any]
    text_anchor: TextAnchor | None = None


@dataclass
class ParseResult:
    content: str
    images: list[Image] = field(default_factory=list)
    url: str = ""
    plaintext: str = ""
    highlights: list[MappedHighlight] = field(default_factory=list)


@dataclass
class TablePlacement:
    """Grid column of every cell, row by row, and the grid width those columns imply."""
    columns: list[list[int]]
    width: int


@dataclass
class AnchorHaystack:
    """Plaintext in UTF-16 code units, whitespace-collapsed for matching, with an offset map back to the units."""
    units: str
    normalized: str
    index_map: list[int]
