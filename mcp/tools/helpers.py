"""Pure utility functions shared across tools. No DB, no auth, no state."""

import re
from fnmatch import fnmatch

from config import settings

MAX_LIST = 50
MAX_SEARCH = 20

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_annotation_text(s: str, max_len: int = 600) -> str:
    """Strip control chars, collapse whitespace, cap length so user annotations
    can't break layout or read as instructions to the LLM."""
    if not s:
        return ""
    s = _CONTROL_CHARS_RE.sub("", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\n", " ")
    s = " ".join(s.split())
    if len(s) > max_len:
        s = s[:max_len].rstrip() + "…"
    return s


def highlight_quote_and_page(h: dict) -> tuple[str, int | None]:
    """Return the user-selected quote and optional page for any anchor shape.

    Highlights are one user-facing feature, but different capture surfaces
    store different resolver anchors: PDF viewer (`pdfAnchor`), parsed
    markdown viewer (`textAnchor`), and legacy webclip DOM (`anchor`).
    """
    for key in ("pdfAnchor", "textAnchor", "anchor"):
        anchor = h.get(key) or {}
        if not isinstance(anchor, dict):
            continue
        text = clean_annotation_text(anchor.get("textContent") or "")
        if text:
            page = anchor.get("page") if key == "pdfAnchor" else None
            return text, page
    return "", None


def deep_link(kb_slug: str, path: str, filename: str) -> str:
    full = (path.rstrip("/") + "/" + filename).lstrip("/")
    return f"{settings.APP_URL}/wikis/{kb_slug}/{full}"


def glob_match(filepath: str, pattern: str) -> bool:
    return fnmatch(filepath, pattern)


def resolve_path(path: str) -> tuple[str, str]:
    path_clean = path.lstrip("/")
    if "/" in path_clean:
        dir_path = "/" + path_clean.rsplit("/", 1)[0] + "/"
        filename = path_clean.rsplit("/", 1)[1]
    else:
        dir_path = "/"
        filename = path_clean
    return dir_path, filename


def parse_page_range(pages_str: str, max_page: int) -> list[int]:
    result = set()
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            start, end = start.strip(), end.strip()
            if not start.isdigit() or not end.isdigit():
                continue
            s, e = int(start), int(end)
            for p in range(max(1, s), min(max_page, e) + 1):
                result.add(p)
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= max_page:
                result.add(p)
    return sorted(result)
