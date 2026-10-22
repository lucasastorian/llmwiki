"""Canonical highlight plaintext with lazily emitted separators; mirrors web/src/lib/highlights/canonicalPlaintext.ts."""
from __future__ import annotations

from .helpers import JS_WHITESPACE

BLOCK_SEPARATOR = "\n\n"
LIST_SEPARATOR = "\n"
CELL_SEPARATOR = " "

_SEPARATOR_RANK = {"": 0, CELL_SEPARATOR: 1, LIST_SEPARATOR: 2, BLOCK_SEPARATOR: 3}
_TRAILING_WHITESPACE = " \t\n\r\f"


class PlaintextBuilder:
    """Collapses inline whitespace like ProseMirror and joins blocks with the strongest separator requested between them."""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._separator = ""
        self._has_pending_space = False
        self._has_pending_hard_break = False
        self._line_has_text = False
        self._has_trimmable_end = False

    def text(self, value: str) -> None:
        """Append HTML-collapsed inline text (whitespace runs already reduced to one space)."""
        if value.startswith(" ") and self._line_has_text:
            self._has_pending_space = True
        core = value.strip(" ") if self._line_has_text else value.lstrip(JS_WHITESPACE).rstrip(" ")
        if not core:
            return
        self._flush_pending()
        self._parts.append(core)
        self._line_has_text = True
        self._has_trimmable_end = True
        self._has_pending_space = value.endswith(" ")

    def verbatim(self, value: str) -> None:
        """Append preformatted text untouched."""
        self._flush_pending()
        self._parts.append(value)
        self._line_has_text = True
        self._has_trimmable_end = False

    def hard_break(self) -> None:
        """Queue a line break; dropped at line starts and when a block boundary follows."""
        if not self._line_has_text:
            return
        self._trim_line_end()
        self._has_pending_hard_break = True
        self._has_pending_space = False
        self._line_has_text = False

    def block(self, separator: str) -> None:
        """Mark a block boundary; the separator is only emitted if more text follows."""
        self._trim_line_end()
        if _SEPARATOR_RANK[separator] > _SEPARATOR_RANK[self._separator]:
            self._separator = separator
        self._has_pending_space = False
        self._has_pending_hard_break = False
        self._line_has_text = False

    def result(self) -> str:
        self._trim_line_end()
        return "".join(self._parts).rstrip(_TRAILING_WHITESPACE)

    def _flush_pending(self) -> None:
        if self._separator:
            if self._parts:
                self._parts.append(self._separator)
        elif self._has_pending_hard_break:
            self._parts.append("\n")
        elif self._has_pending_space:
            self._parts.append(" ")
        self._separator = ""
        self._has_pending_hard_break = False
        self._has_pending_space = False

    def _trim_line_end(self) -> None:
        """markdown-it trims Unicode whitespace off block ends, and the Markdown writer off hard-break edges."""
        if not self._has_trimmable_end:
            return
        self._has_trimmable_end = False
        while self._parts:
            trimmed = self._parts[-1].rstrip(JS_WHITESPACE)
            if trimmed:
                self._parts[-1] = trimmed
                return
            self._parts.pop()
