from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, TypedDict


class RealPage(TypedDict):
    id: str
    url: str
    sha256: str
    html: str


class PageGolden(TypedDict):
    markdown: str
    plaintext: str
    markdown_sha256: str


class HtmlDocument(NamedTuple):
    """A document to parse; adversarial ones also state what a correct parse must (not) show."""
    html: str
    url: str
    sentinels: tuple[str, ...] = ()
    hidden: tuple[str, ...] = ()
    expects_limit_error: bool = False


@dataclass(frozen=True)
class ParseOutcome:
    """One production parse: its output, or the exception it raised."""
    markdown: str | None = None
    plaintext: str | None = None
    error_type: str | None = None
    error_message: str = ""
    is_limit_error: bool = False


@dataclass(frozen=True)
class IsolatedRun:
    """Two parses of the same input in a resource-limited child, or why the child died."""
    outcomes: list[ParseOutcome]
    failure: str | None = None
