from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Element:
    id: str
    content: str
    kind: str  # "heading", "paragraph", "table", "list", "blockquote", "code", "form", "text"
    content_start_offset: Optional[int] = None
    content_end_offset: Optional[int] = None


@dataclass
class Image:
    url: str
    alt: str = ""


@dataclass
class TextAnchor:
    """Plaintext-relative anchor: character offsets into the canonical
    plaintext produced during parsing. Mirrors the API-level TextAnchor type.
    """
    text_start: int
    text_end: int
    text_content: str
    prefix: Optional[str] = None
    suffix: Optional[str] = None


@dataclass
class MappedHighlight:
    """A highlight enriched with a plaintext-relative position.

    Carries the caller-supplied highlight payload alongside the `text_anchor`
    computed by the parser. Returned in ParseResult.highlights when the caller
    passes highlights to Parser.parse(...).
    """
    payload: Dict[str, Any]
    text_anchor: Optional[TextAnchor] = None


@dataclass
class ParseResult:
    content: str
    images: List[Image] = field(default_factory=list)
    form_elements: list = field(default_factory=list)
    url: str = ""
    elements: List[Element] = field(default_factory=list)
    plaintext: str = ""
    highlights: List[MappedHighlight] = field(default_factory=list)
