"""Markdown escaping, inline-style and UTF-16 offset helpers for the HTML parser."""
from __future__ import annotations

import re
import unicodedata

# JS `\s` / String.prototype.trim(); the viewer's locator and markdown-it's trims use exactly this set.
JS_WHITESPACE = "\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"

# markdown-it's isWhiteSpace, which decides whether an emphasis delimiter run can open or close.
_MARKDOWN_IT_WHITESPACE = frozenset("\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000")
_ASCII_PUNCTUATION = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

# `<`, `&` and `~` are escaped unconditionally: what follows them may sit in the next text node.
_INLINE_SPECIAL_RE = re.compile(r"[\\`*\[\]<&~]|(?<![^\W_])_|_(?![^\W_])")
_LINE_START_MARKER_RE = re.compile(r"^( *)([#>+\-=|])")
_LINE_START_ORDINAL_RE = re.compile(r"^( *\d{1,9})([.)])")
_PENDING_ORDINAL_RE = re.compile(r" *\d{1,9}")
_BACKTICK_RUN_RE = re.compile(r"`+")
_IMPORTANT_RE = re.compile(r"\s*!\s*important\s*$", re.I)
# Strings, comments and bracket blocks may hold `;` that does not end a declaration.
_STYLE_TOKEN_RE = re.compile(
    r'"(?:[^"\\]|\\.)*"?|\'(?:[^\'\\]|\\.)*\'?|/\*.*?(?:\*/|\Z)|[()\[\]{};]|[^"\'/()\[\]{};]+|/',
    re.S,
)
_STYLE_OPENERS = frozenset("([{")
_STYLE_CLOSERS = frozenset(")]}")
_ASTRAL_RE = re.compile("[\U00010000-\U0010ffff]")
_LONE_SURROGATE_RE = re.compile("[\ud800-\udfff]")


def escape_markdown_text(text: str, is_line_start: bool) -> str:
    """Backslash-escape text so markdown-it renders it literally instead of as formatting."""
    escaped = _INLINE_SPECIAL_RE.sub(r"\\\g<0>", text)
    if not is_line_start:
        return escaped
    escaped = _LINE_START_MARKER_RE.sub(r"\1\\\2", escaped, count=1)
    return _LINE_START_ORDINAL_RE.sub(r"\1\\\2", escaped, count=1)


def escape_line_continuation(text: str, line_start: str) -> str:
    """Escape text that continues a line holding only `line_start`, digits that may still form an ordered-list marker."""
    escaped = _INLINE_SPECIAL_RE.sub(r"\\\g<0>", text)
    match = _LINE_START_ORDINAL_RE.match(line_start + text)
    if not match:
        return escaped
    split = match.end(1) - len(line_start)
    return f"{escaped[:split]}\\{escaped[split:]}"


def is_pending_ordinal(line_start: str) -> bool:
    """Whether a line holding only this text could still turn into an ordered-list marker."""
    return _PENDING_ORDINAL_RE.fullmatch(line_start) is not None


def parse_inline_style(style: str) -> dict[str, str]:
    """Inline `style` values by lower-cased property under CSS precedence: `!important` first, then last wins."""
    declarations: dict[str, str] = {}
    important: set[str] = set()
    for declaration in _split_style_declarations(style):
        name, has_colon, value = declaration.partition(":")
        name = name.strip().lower()
        if not has_colon or not name or name.startswith("--"):
            continue
        is_important = _IMPORTANT_RE.search(value) is not None
        if name in important and not is_important:
            continue
        if is_important:
            important.add(name)
        declarations[name] = _IMPORTANT_RE.sub("", value).strip().lower()
    return declarations


def _split_style_declarations(style: str) -> list[str]:
    """Split on top-level `;` only, dropping comments, the way a CSS declaration list is tokenized."""
    declarations: list[str] = []
    current: list[str] = []
    depth = 0
    for token in _STYLE_TOKEN_RE.findall(style):
        if token.startswith("/*"):
            current.append(" ")
            continue
        if token in _STYLE_OPENERS:
            depth += 1
        elif token in _STYLE_CLOSERS:
            depth = max(0, depth - 1)
        elif token == ";" and depth == 0:
            declarations.append("".join(current))
            current = []
            continue
        current.append(token)
    declarations.append("".join(current))
    return declarations


def inline_code(code: str) -> str:
    """Wrap code in a backtick fence longer than any backtick run it contains."""
    fence = "`" * (_longest_backtick_run(code) + 1)
    pad = " " if code.startswith("`") or code.endswith("`") else ""
    return f"{fence}{pad}{code}{pad}{fence}"


def code_fence(code: str) -> str:
    """Opening/closing fence that no line of `code` can close early."""
    return "`" * max(3, _longest_backtick_run(code) + 1)


def can_open_emphasis(before: str, first: str) -> bool:
    """CommonMark left-flanking test for a `*` run between `before` and the emphasised text's first char."""
    if _is_markdown_whitespace(first):
        return False
    return not _is_markdown_punctuation(first) or _is_markdown_whitespace(before) or _is_markdown_punctuation(before)


def can_close_emphasis(last: str, after: str) -> bool:
    """CommonMark right-flanking test for a `*` run between the emphasised text's last char and `after`."""
    if _is_markdown_whitespace(last):
        return False
    return not _is_markdown_punctuation(last) or _is_markdown_whitespace(after) or _is_markdown_punctuation(after)


def is_ambiguous_delimiter(before: str, after: str) -> bool:
    """A `*` run between these chars can both open and close, so markdown-it may pair it unexpectedly."""
    return can_open_emphasis(before, after) and can_close_emphasis(before, after)


def replace_lone_surrogates(text: str) -> str:
    """Swap unpaired UTF-16 surrogates (valid in JS strings, unencodable as UTF-8) for U+FFFD, keeping UTF-16 length."""
    return _LONE_SURROGATE_RE.sub("\ufffd", text)


def to_utf16_units(text: str) -> str:
    """Split astral characters into surrogate pairs so str indices count UTF-16 code units like JS."""
    return _ASTRAL_RE.sub(_surrogate_pair, text)


def from_utf16_units(units: str) -> str:
    """Rejoin surrogate pairs produced by `to_utf16_units`."""
    return units.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def _surrogate_pair(match: re.Match[str]) -> str:
    offset = ord(match.group()) - 0x10000
    return chr(0xD800 + (offset >> 10)) + chr(0xDC00 + (offset & 0x3FF))


def _longest_backtick_run(code: str) -> int:
    return max((len(run) for run in _BACKTICK_RUN_RE.findall(code)), default=0)


def _is_markdown_whitespace(char: str) -> bool:
    return char in _MARKDOWN_IT_WHITESPACE


def _is_markdown_punctuation(char: str) -> bool:
    """markdown-it's punctuation test: ASCII punctuation or any Unicode P*/S* character (so emoji count)."""
    return char in _ASCII_PUNCTUATION or unicodedata.category(char)[0] in "PS"
