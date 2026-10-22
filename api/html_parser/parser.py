from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from collections.abc import Iterator
from html import unescape
from itertools import groupby
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from bs4.element import NavigableString, PageElement, PreformattedString, Tag
from infra import safe_fetch

from .dom import remove_elements
from .forms import FormExtractor
from .helpers import (
    JS_WHITESPACE,
    can_close_emphasis,
    can_open_emphasis,
    code_fence,
    escape_line_continuation,
    escape_markdown_text,
    from_utf16_units,
    inline_code,
    is_ambiguous_delimiter,
    is_pending_ordinal,
    parse_inline_style,
    replace_lone_surrogates,
    to_utf16_units,
)
from .models import (
    AnchorHaystack,
    Element,
    ElementKind,
    EmphasisFrame,
    Image,
    MappedHighlight,
    ParseResult,
    TablePlacement,
    TextAnchor,
)
from .parse_limit_exceeded_error import ParseLimitExceededError
from .plaintext_builder import BLOCK_SEPARATOR, CELL_SEPARATOR, LIST_SEPARATOR, PlaintextBuilder
from .table_layout import place_cells

MAX_TABLE_SPAN = 1000
MAX_TABLE_CELLS = 100_000
# Deeper subtrees are flattened to text blocks so both recursive walkers stay well inside Python's recursion limit.
MAX_RENDER_DEPTH = 128
# Quotes and lists re-prefix every line of their content per level, so their nesting is capped far lower.
MAX_BLOCK_NESTING = 32
# Cumulative cap on rendered characters (text, destinations, indents, resolved URLs), so amplification cannot run away.
MAX_OUTPUT_CHARS = 20_000_000
MIN_CONTENT_ONLY_PLAINTEXT = 200


BLOCK_TAGS = {
    "div", "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "article", "section", "header", "footer", "main", "aside", "nav",
    "table", "br", "hr", "ul", "ol", "li", "blockquote", "pre", "figure",
    "figcaption", "form", "fieldset", "address"
}

BOLD_TAGS = {"b", "strong"}
ITALIC_TAGS = {"i", "em"}

REMOVE_TAGS = {
    "script", "style", "noscript", "svg", "iframe", "canvas",
    "video", "audio", "map", "object", "embed", "template",
}

SANITIZE_DROP_TAGS = REMOVE_TAGS | {
    "base", "link", "meta",
}

SANITIZE_GLOBAL_ATTRS = {
    "id", "class", "title", "role", "aria-label", "aria-hidden",
    "data-webmd-block",
}

SANITIZE_ATTRS_BY_TAG = {
    "a": {"href", "target", "rel"},
    "blockquote": {"cite"},
    "button": {"disabled", "type"},
    "col": {"span"},
    "colgroup": {"span"},
    "form": {"method"},
    "img": {"src", "srcset", "alt", "width", "height", "loading"},
    "input": {"type", "name", "value", "placeholder", "checked", "disabled"},
    "label": {"for"},
    "ol": {"start", "type"},
    "option": {"value", "selected", "disabled"},
    "select": {"name", "disabled", "multiple"},
    "td": {"colspan", "rowspan"},
    "textarea": {"name", "placeholder", "disabled"},
    "th": {"colspan", "rowspan", "scope"},
    "ul": {"type"},
}

LINK_SCHEMES = {"http", "https", "mailto"}

SANITIZE_URL_ATTRS = {"href", "src", "cite"}
SANITIZE_ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "tel"}
SANITIZE_ALLOWED_DATA_IMAGE_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
}

NOISE_TAGS = {"nav", "footer", "aside"}

NOISE_CLASSES = {
    "sidebar", "navigation", "nav", "menu", "footer", "header",
    "advertisement", "ad", "ads", "cookie", "popup",
    "modal", "overlay", "social", "share", "comment", "comments",
    "related", "recommended", "trending", "popular",
    "navbar", "mobile-nav", "dropdown-menu", "mega-menu", "w-nav",
}

NOISE_IDS = {
    "sidebar", "navigation", "nav", "menu", "footer", "header",
    "comments", "ad", "ads",
}

TRACKED_BLOCKS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "table", "ul", "ol", "blockquote", "pre", "form",
}

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
FORM_FIELD_TAGS = {"input", "button", "select", "textarea"}
CELL_FLATTENED_TAGS = (TRACKED_BLOCKS | BLOCK_TAGS | {"tr", "td", "th"}) - {"br", "pre"}
FLATTEN_BOUNDARY_TAGS = TRACKED_BLOCKS | BLOCK_TAGS | {"li", "tr", "td", "th"}
# Walkers only read these through their row/item children, so a flattened one must stop being one.
STRUCTURAL_CONTAINER_TAGS = {"ul", "ol", "table", "thead", "tbody", "tfoot", "tr"}
PREFIXING_CONTAINER_TAGS = {"blockquote", "ul", "ol"}
TABLE_CELL_TAGS = {"td", "th"}
TABLE_PART_TAGS = {"thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup", "col"}
NOISE_HEADER_HEADINGS = {"h1", "h2"}

# In-band markers resolved by _normalize_output; _clean_text scrubs them from source text.
HARD_BREAK = "\x00"
INDENT = "\x02"
CODE_MARK = "\x03"
IMAGE_EDGE = "\x05"
EMPHASIS_OPEN = "\x06"
EMPHASIS_CLOSE = "\x07"
INLINE_CODE_MARK = "\x08"

_ws = re.compile(r"[ \t]+")
_html_ws = re.compile(r"[ \t\n\r\f]+")
_control_chars = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f]")
_inline_ws_chars = JS_WHITESPACE.replace("\n", "")
# The lookbehinds pin each match to the start of its run; without them every position of a long run is retried.
_hard_break_run = re.compile(
    f"(?<![{_inline_ws_chars}{HARD_BREAK}])[{_inline_ws_chars}{HARD_BREAK}]*{HARD_BREAK}[{_inline_ws_chars}{HARD_BREAK}]*"
)
_edge_hard_break = re.compile(f"{HARD_BREAK}(?=\n|$)|(?<=\n){HARD_BREAK}|^{HARD_BREAK}")
_image_edge = re.compile(f"(?<![{_inline_ws_chars}])[{_inline_ws_chars}]*{IMAGE_EDGE}[{_inline_ws_chars}]*")
_line_prefix = re.compile(f"[{INDENT}> \t]*")
_blank_runs = re.compile(r"\n{3,}")
_code_placeholder = re.compile(f"{CODE_MARK}(\\d+){CODE_MARK}")
_inline_code_run = re.compile(f"(?:{INLINE_CODE_MARK}\\d+{INLINE_CODE_MARK})+")
_emphasis_marker = re.compile(f"[{EMPHASIS_OPEN}{EMPHASIS_CLOSE}]")
_heading_closing_hashes = re.compile(r"(\s)(#+)$")
# Viewer headings stop at h3, so deeper ATX headings render as paragraphs.
_non_paragraph_start = re.compile(f"(?:{EMPHASIS_OPEN}\\*{{1,3}})*(?:#{{1,3}} |{CODE_MARK}|[-+*] |\\d+[.)] |\\||>|---(?:\n|$)|!\\[|\\[!\\[)")
_unsafe_link_destination = re.compile(r"[\s()<>]")
_url_noise = re.compile(r"[\x00-\x20\x7f]")
_url_scheme = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*):")
# markdown-it decodes these entity forms inside link destinations.
_destination_entity = re.compile(r"&(?=[A-Za-z#][A-Za-z0-9]{1,31};)")
_js_ws_run = re.compile(f"[{JS_WHITESPACE}]+")
_xml_declaration = re.compile(r"^\s*<\?xml[^>]*>")


class Parser:

    def __init__(self, content: str, url: str = "", content_only: bool = False):
        self._content = self._repair_markup(content)
        self.soup = BeautifulSoup(self._content, "lxml")
        self.url = url
        self.content_only = content_only
        self.images: list[Image] = []
        self.forms = FormExtractor()
        self._segments: list[tuple[str, Tag]] = []
        self._suppress_tracking: bool = False
        self._block_nodes: dict[str, list[Tag]] = {}
        self._parsed: bool = False
        self._is_line_start: bool = True
        self._line_start_digits: str = ""
        self._is_in_heading: bool = False
        self._is_in_table_cell: bool = False
        self._code_blocks: list[str] = []
        self._inline_codes: list[str] = []
        self._rendered_form_ids: set[int] = set()
        self._hoisted_list_item_ids: set[int] = set()
        self._atx_heading_ids: set[int] = set()
        self._is_in_link: bool = False
        self._list_depth: int = 0
        self._lists_started_by_depth: dict[int, int] = {}
        self._styles: dict[int, dict[str, str]] = {}
        self._table_placements: dict[int, TablePlacement] = {}
        self._output_chars: int = 0
        self._prepare_dom()

    @staticmethod
    def _repair_markup(content: str) -> str:
        """Drop a leading XML declaration (which trips bs4's XML sniffing) and unencodable lone surrogates."""
        return replace_lone_surrogates(_xml_declaration.sub("", content, count=1))

    def _prepare_dom(self) -> None:
        """Filter, bound and index the tree once, so both walkers read the same final DOM."""
        self._remove_unrendered()
        self._flatten_deep_subtrees()
        self._place_table_cells()
        self._index_elements()

    def _remove_unrendered(self) -> None:
        """Physically drop what no reader sees (non-content, hidden, content-only noise), so no handler can leak it."""
        remove_elements([node for node in self.soup.descendants if self._is_unrendered(node)])
        if self.content_only:
            self._remove_noise()

    def _remove_noise(self) -> None:
        """Judged on the visible tree only, so a heading hidden inside a site header does not make it an article header."""
        heading_holder_ids = self._heading_holder_ids()
        remove_elements([
            node for node in self.soup.descendants if isinstance(node, Tag) and self._is_noise(node, heading_holder_ids)
        ])

    def _heading_holder_ids(self) -> set[int]:
        """Ids of elements with an h1/h2 descendant, found in one bottom-up sweep instead of a find() per element."""
        holder_ids: set[int] = set()
        tags = [node for node in self.soup.descendants if isinstance(node, Tag)]
        for tag in reversed(tags):
            if tag.name in NOISE_HEADER_HEADINGS or id(tag) in holder_ids:
                holder_ids.add(id(tag.parent))
        return holder_ids

    def _is_unrendered(self, node: PageElement) -> bool:
        if isinstance(node, PreformattedString):
            return True
        if not isinstance(node, Tag):
            return False
        if node.name in REMOVE_TAGS:
            return True
        declarations = parse_inline_style(str(node["style"])) if node.has_attr("style") else {}
        return self._is_hidden(node, declarations)

    def _flatten_deep_subtrees(self) -> None:
        for subtree in self._subtrees_too_deep():
            self._flatten_subtree(subtree)

    def _subtrees_too_deep(self) -> list[Tag]:
        """Outermost subtrees past the render depth or the quote/list nesting cap; a table cut mid-structure goes whole."""
        subtrees: dict[int, Tag] = {}
        stack: list[tuple[Tag, int, int]] = [(self.soup, 0, 0)]
        while stack:
            tag, depth, nesting = stack.pop()
            for child in tag.children:
                if not isinstance(child, Tag):
                    continue
                child_nesting = nesting + (child.name in PREFIXING_CONTAINER_TAGS)
                if depth + 1 >= MAX_RENDER_DEPTH or child_nesting > MAX_BLOCK_NESTING:
                    subtree = self._flattening_root(child)
                    subtrees[id(subtree)] = subtree
                else:
                    stack.append((child, depth + 1, child_nesting))
        return list(subtrees.values())

    @staticmethod
    def _flattening_root(cutoff: Tag) -> Tag:
        """The owning table when the cut lands on its rows or cells, since walkers only read a table through them."""
        root = cutoff
        while root.name in TABLE_PART_TAGS and isinstance(root.parent, Tag):
            root = root.parent
        return root if root.name == "table" else cutoff

    def _flatten_subtree(self, subtree: Tag) -> None:
        """Replace a too-deep subtree's content with one flat block per text run, keeping images."""
        blocks = self._flattened_blocks(subtree)
        remove_elements(list(subtree.contents))
        if subtree.name in STRUCTURAL_CONTAINER_TAGS:
            subtree.name = "div"
        for block in blocks:
            container = self.soup.new_tag("div")
            for is_text, parts in groupby(block, key=lambda part: isinstance(part, str)):
                if is_text:
                    container.append(self.soup.new_string("".join(parts)))
                else:
                    container.extend(parts)
            subtree.append(container)

    def _flattened_blocks(self, subtree: Tag) -> list[list[str | Tag]]:
        """Text runs and image copies of a subtree, split wherever a block starts or ends."""
        blocks: list[list[str | Tag]] = [[]]
        stack: list[tuple[PageElement, bool]] = [(child, False) for child in reversed(subtree.contents)]
        while stack:
            node, is_block_end = stack.pop()
            if is_block_end:
                blocks.append([])
            elif isinstance(node, NavigableString):
                blocks[-1].append(str(node))
            elif isinstance(node, Tag):
                self._push_flattened_tag(node, blocks, stack)
        return [block for block in blocks if any(not isinstance(part, str) or part.strip() for part in block)]

    def _push_flattened_tag(
        self, node: Tag, blocks: list[list[str | Tag]], stack: list[tuple[PageElement, bool]],
    ) -> None:
        if node.name == "img":
            blocks[-1].append(self.soup.new_tag("img", attrs=dict(node.attrs)))
            return
        if node.name in FLATTEN_BOUNDARY_TAGS:
            blocks.append([])
            stack.append((node, True))
        stack.extend((child, False) for child in reversed(node.contents))

    def _place_table_cells(self) -> None:
        """Lay out every table once; one whose spanned grid would exceed the cell budget becomes a block per cell."""
        tables = [node for node in self.soup.descendants if isinstance(node, Tag) and node.name == "table"]
        for table in tables:
            rows = self._table_rows(table)
            placement = place_cells([[self._cell_spans(cell) for cell in row] for row in rows], MAX_TABLE_CELLS)
            if placement:
                self._table_placements[id(table)] = placement
            else:
                self._convert_to_blocks([table, *(cell for row in rows for cell in row)])

    @staticmethod
    def _convert_to_blocks(tags: list[Tag]) -> None:
        for tag in tags:
            tag.name = "div"

    def _index_elements(self) -> None:
        """Scrub control chars from attributes and parse inline styles."""
        for tag in self.soup.descendants:
            if not isinstance(tag, Tag):
                continue
            self._scrub_attributes(tag)
            declarations = parse_inline_style(str(tag["style"])) if tag.has_attr("style") else {}
            if declarations:
                self._styles[id(tag)] = declarations

    @staticmethod
    def _scrub_attributes(tag: Tag) -> None:
        """Attribute values feed URLs, alt text and labels; the in-band markers must never come from them."""
        for name, value in tag.attrs.items():
            if isinstance(value, str):
                if _control_chars.search(value):
                    tag.attrs[name] = _control_chars.sub("", value)
            elif any(_control_chars.search(item) for item in value):
                tag.attrs[name] = [_control_chars.sub("", item) for item in value]

    def _resolve_url(self, src: str) -> str:
        """`src` made absolute against the page URL, or "" when it does not parse as a URL."""
        if not src:
            return ""
        try:
            resolved = self._join_url(src)
            urlsplit(resolved)
        except ValueError:
            return ""
        return resolved

    def _join_url(self, src: str) -> str:
        if src.startswith("//"):
            return "https:" + src
        if src.startswith(("http://", "https://", "data:")):
            return src
        if self.url:
            return urljoin(self.url, src)
        return src

    @staticmethod
    def _is_hidden(el: Tag, declarations: dict[str, str]) -> bool:
        if el.has_attr("hidden") and not Parser._is_react_streamed_segment(el):
            return True

        if el.get("aria-hidden") == "true":
            return True

        return declarations.get("display") == "none" or declarations.get("visibility") == "hidden"

    @staticmethod
    def _is_react_streamed_segment(el: Tag) -> bool:
        """React streaming SSR parks finished content in `<div hidden id="S:n">` until a script swaps it in."""
        return el.name == "div" and str(el.get("id", "")).startswith("S:")

    @staticmethod
    def _is_noise(el: Tag, heading_holder_ids: set[int]) -> bool:
        if el.name in NOISE_TAGS:
            return True

        if el.name == "header":
            return Parser._is_noise_header(el, heading_holder_ids)

        el_id = (el.get("id") or "").lower()
        if el_id in NOISE_IDS:
            return True

        classes = el.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        for cls in classes:
            if cls.lower() in NOISE_CLASSES:
                return True

        role = (el.get("role") or "").lower()
        return role in {"navigation", "banner", "complementary", "contentinfo"}

    @staticmethod
    def _is_noise_header(el: Tag, heading_holder_ids: set[int]) -> bool:
        """Drop site-chrome headers but keep headline headers (article headers hold the headline and byline)."""
        role = (el.get("role") or "").lower()
        if role in {"banner", "navigation"}:
            return True

        classes = el.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        class_set = {cls.lower() for cls in classes}
        el_id = (el.get("id") or "").lower()

        chrome_tokens = {
            "header", "site-header", "masthead", "topbar", "navbar",
            "navigation", "nav", "menu",
        }
        if el_id in chrome_tokens or class_set.intersection(chrome_tokens):
            return True

        return id(el) not in heading_holder_ids

    def _is_bold(self, el: Tag) -> bool:
        is_styled_bold = self._is_bold_weight(self._styles.get(id(el), {}).get("font-weight", ""))
        return el.name in BOLD_TAGS if is_styled_bold is None else is_styled_bold

    def _is_italic(self, el: Tag) -> bool:
        is_styled_italic = self._is_italic_style(self._styles.get(id(el), {}).get("font-style", ""))
        return el.name in ITALIC_TAGS if is_styled_italic is None else is_styled_italic

    @staticmethod
    def _is_bold_weight(weight: str) -> bool | None:
        """Whether a `font-weight` value bolds, or None when absent or not statically known (`inherit`, `var()`)."""
        if weight in {"bold", "bolder"}:
            return True
        if weight in {"normal", "lighter"}:
            return False
        try:
            return float(weight) >= 600
        except ValueError:
            return None

    @staticmethod
    def _is_italic_style(style: str) -> bool | None:
        """Whether a `font-style` value italicises, or None when absent or not statically known."""
        if style == "italic" or style.startswith("oblique"):
            return True
        if style == "normal":
            return False
        return None

    @staticmethod
    def _clean_text(text: str) -> str:
        """Collapse HTML whitespace the way a browser renders inline text."""
        text = text.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
        text = _control_chars.sub("", text)
        return _html_ws.sub(" ", text)

    def _get_markdown_wrapper(self, el: Tag) -> str:
        if self._is_in_heading:
            return ""
        bold = self._is_bold(el)
        italic = self._is_italic(el)
        if bold and italic:
            return "***"
        if bold:
            return "**"
        if italic:
            return "*"
        return ""

    def _process_text(self, node: NavigableString) -> str:
        text = self._clean_text(str(node))
        if not text.strip():
            if self._line_start_digits:
                self._end_line_start()
            return text
        escaped = self._escape_text(text)
        self._advance_line_start(text)
        return escaped

    def _escape_text(self, text: str) -> str:
        if self._line_start_digits:
            return escape_line_continuation(text, self._line_start_digits)
        return escape_markdown_text(text, self._is_line_start)

    def _advance_line_start(self, text: str) -> None:
        """Text split across nodes can still assemble an ordered-list marker, so a digits-only line start stays open."""
        if self._is_line_start and is_pending_ordinal(self._line_start_digits + text):
            self._line_start_digits += text
            return
        self._end_line_start()

    def _start_line(self) -> None:
        self._is_line_start = True
        self._line_start_digits = ""

    def _end_line_start(self) -> None:
        self._is_line_start = False
        self._line_start_digits = ""

    def _process_heading(self, el: Tag) -> str:
        level = int(el.name[1])
        prefix = "#" * level + " "
        was_in_heading = self._is_in_heading
        self._is_in_heading = True
        text = _image_edge.sub("", self._process_children(el)).strip()
        self._is_in_heading = was_in_heading
        if "\n" in text or _non_paragraph_start.match(text):
            return f"\n\n{text}\n\n"
        text = _heading_closing_hashes.sub(r"\1\\\2", text.replace(HARD_BREAK, " ").strip())
        if not text:
            return BLOCK_SEPARATOR
        self._atx_heading_ids.add(id(el))
        return f"\n\n{prefix}{text}\n\n"

    def _process_link(self, el: Tag) -> str:
        href = el.get("href", "")
        was_in_link = self._is_in_link
        self._is_in_link = True
        content = self._process_children(el)
        self._is_in_link = was_in_link
        lead, text, trail = self._split_inline_edges(content)

        # Markdown links cannot nest; the outermost one keeps the href.
        if was_in_link or not text or "\n" in text or not href or href.startswith("#"):
            return content
        destination = self._resolve_url(href)
        if not destination or not self._has_link_scheme(destination):
            return content

        return f"{lead}[{text}]({self._link_destination(destination)}){trail}"

    @staticmethod
    def _has_link_scheme(href: str) -> bool:
        """Relative or http(s)/mailto once entity-decoded; browsers ignore whitespace and control chars in a scheme."""
        scheme = _url_scheme.match(_url_noise.sub("", unescape(href)))
        return scheme is None or scheme.group(1).lower() in LINK_SCHEMES

    @staticmethod
    def _link_destination(href: str) -> str:
        href = _destination_entity.sub("&amp;", href)
        if not _unsafe_link_destination.search(href):
            return href
        return "<" + href.replace("\n", "").replace("<", "%3C").replace(">", "%3E") + ">"

    @staticmethod
    def _split_inline_edges(content: str) -> tuple[str, str, str]:
        """Split off edge whitespace, hard breaks and image edges, which must sit outside emphasis/link delimiters."""
        edge_chars = f"{_inline_ws_chars}{HARD_BREAK}{IMAGE_EDGE}"
        core = content.strip(edge_chars)
        if not core:
            return content, "", ""
        lead = content[:len(content) - len(content.lstrip(edge_chars))]
        trail = content[len(content.rstrip(edge_chars)):]
        return lead, core, trail

    def _process_list(self, el: Tag, ordered: bool = False) -> str:
        is_alternate = self._next_list_is_alternate()
        self._list_depth += 1
        items = []
        for i, li in enumerate(el.find_all("li", recursive=False)):
            self._start_line()
            item_text = self._normalize_nested_block(self._process_children(li))
            if item_text:
                if _non_paragraph_start.match(item_text):
                    self._hoisted_list_item_ids.add(id(li))
                marker = self._list_marker(i + 1 if ordered else None, is_alternate)
                items.append(marker + self._indent_continuation(item_text, INDENT * len(marker)))
        self._list_depth -= 1
        self._start_line()

        return "\n\n" + "\n".join(items) + "\n\n"

    def _next_list_is_alternate(self) -> bool:
        """Alternate markers per nesting depth: Markdown merges same-marker lists separated only by blank lines."""
        count = self._lists_started_by_depth.get(self._list_depth, 0)
        self._lists_started_by_depth[self._list_depth] = count + 1
        return count % 2 == 1

    @staticmethod
    def _list_marker(number: int | None, is_alternate: bool) -> str:
        if number is None:
            return "* " if is_alternate else "- "
        return f"{number}) " if is_alternate else f"{number}. "

    @staticmethod
    def _indent_continuation(text: str, prefix: str) -> str:
        first, *rest = text.split("\n")
        return "\n".join([first, *(prefix + line if line else line for line in rest)])

    @staticmethod
    def _safe_span(value: str | None) -> int:
        try:
            if not value:
                return 1
            return min(max(1, int(value)), MAX_TABLE_SPAN)
        except (ValueError, TypeError):
            return 1

    _LAYOUT_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "ul", "ol", "blockquote", "pre", "table", "br"}

    def _is_layout_table(self, el: Tag) -> bool:
        """Detect tables used for page layout rather than tabular data."""
        if el.get("role") in ("presentation", "layout"):
            return True
        cells = [cell for row in self._table_rows(el) for cell in row]
        if not cells or any(cell.name == "th" for cell in cells):
            return False
        return any(self._has_layout_block(cell) for cell in cells)

    @classmethod
    def _has_layout_block(cls, cell: Tag) -> bool:
        """Scanned by hand: bs4's find() builds a matcher per call, which dominated wide-table parses."""
        return any(isinstance(node, Tag) and node.name in cls._LAYOUT_BLOCK_TAGS for node in cell.descendants)

    @staticmethod
    def _table_rows(table: Tag) -> list[list[Tag]]:
        """Rows this table owns, not those of tables nested in it, each with its direct td/th cells."""
        rows: list[list[Tag]] = []
        stack: list[PageElement] = list(reversed(table.contents))
        while stack:
            node = stack.pop()
            if not isinstance(node, Tag) or node.name == "table":
                continue
            if node.name == "tr":
                rows.append([
                    cell for cell in node.children
                    if isinstance(cell, Tag) and cell.name in TABLE_CELL_TAGS
                ])
                continue
            stack.extend(reversed(node.contents))
        return rows

    def _process_table(self, el: Tag) -> str:
        texts = [[self._process_cell(cell) for cell in row] for row in self._table_rows(el)]
        return self._table_markdown(self._spanned_grid(texts, self._table_placements[id(el)]))

    def _cell_spans(self, cell: Tag) -> tuple[int, int]:
        return self._safe_span(cell.get("rowspan")), self._safe_span(cell.get("colspan"))

    @staticmethod
    def _spanned_grid(texts: list[list[str]], placement: TablePlacement) -> list[list[str]]:
        """Cells at their spanned columns, minus rows and columns with no content."""
        grid = [[""] * placement.width for _ in texts]
        for row, (row_texts, row_columns) in enumerate(zip(texts, placement.columns, strict=True)):
            for text, column in zip(row_texts, row_columns, strict=True):
                grid[row][column] = text
        grid = [row for row in grid if any(cell.strip() for cell in row)]
        filled_columns = [j for j in range(placement.width) if any(row[j].strip() for row in grid)]
        return [[row[j] for j in filled_columns] for row in grid]

    @staticmethod
    def _table_markdown(grid: list[list[str]]) -> str:
        if not grid:
            return BLOCK_SEPARATOR
        width = len(grid[0])
        lines = ["| " + " | ".join(grid[0]) + " |", "|" + "|".join(["---"] * width) + "|"]
        lines.extend("| " + " | ".join(row) + " |" for row in grid[1:])
        return "\n\n" + "\n".join(lines) + "\n\n"

    def _process_cell(self, td: Tag) -> str:
        was_in_cell = self._is_in_table_cell
        self._is_in_table_cell = True
        text = self._process_children(td)
        self._is_in_table_cell = was_in_cell
        text = self._expand_inline_code(text).replace(HARD_BREAK, " ").replace("|", "\\|").replace("\n", " ")
        return _ws.sub(" ", text).strip()

    def _process_blockquote(self, el: Tag) -> str:
        text = self._normalize_nested_block(self._process_children(el))
        if not text:
            return BLOCK_SEPARATOR
        quoted = "\n".join(f">{INDENT}{line}" if line else ">" for line in text.split("\n"))
        return f"\n\n{quoted}\n\n"

    def _process_pre(self, el: Tag) -> str:
        code = self._pre_code(el)
        if not code.strip():
            return BLOCK_SEPARATOR
        if self._is_in_table_cell:
            return f" {self._inline_code_placeholder(self._clean_text(code).strip())} "
        self._charge_output(len(code))
        self._code_blocks.append(code)
        return f"\n\n{CODE_MARK}{len(self._code_blocks) - 1}{CODE_MARK}\n\n"

    @staticmethod
    def _pre_code(el: Tag) -> str:
        """Preformatted text verbatim, minus control characters and leading/trailing blank lines."""
        parts: list[str] = []
        for descendant in el.descendants:
            if isinstance(descendant, NavigableString):
                parts.append(str(descendant))
            elif isinstance(descendant, Tag) and descendant.name == "br":
                parts.append("\n")
        code = "".join(parts).replace("\r\n", "\n").replace("\r", "\n")
        return _control_chars.sub("", code).strip("\n")

    def _process_inline_code(self, el: Tag) -> str:
        lead, code, trail = self._split_inline_edges(self._clean_text(el.get_text()))
        if not code:
            return lead
        self._end_line_start()
        return f"{lead}{self._inline_code_placeholder(code)}{trail}"

    def _inline_code_placeholder(self, code: str) -> str:
        self._charge_output(len(code))
        self._inline_codes.append(code)
        return f"{INLINE_CODE_MARK}{len(self._inline_codes) - 1}{INLINE_CODE_MARK}"

    def _expand_inline_code(self, text: str) -> str:
        """Adjacent code spans merge into one, since their backtick fences would otherwise fuse."""
        return _inline_code_run.sub(self._merged_inline_code, text)

    def _merged_inline_code(self, match: re.Match[str]) -> str:
        indexes = match.group().strip(INLINE_CODE_MARK).split(INLINE_CODE_MARK * 2)
        code = "".join(self._inline_codes[int(index)] for index in indexes)
        rendered = inline_code(code)
        self._charge_output(len(rendered) - len(code))
        return rendered

    def _process_hr(self) -> str:
        return "\n\n---\n\n"

    def _process_br(self) -> str:
        return HARD_BREAK

    def _process_img(self, el: Tag) -> str:
        alt = el.get("alt", "")
        src_url = self._resolve_url(el.get("src", ""))
        candidates = self._parse_srcset(el.get("srcset"))

        if not src_url and not candidates:
            return ""

        abs_url = src_url or candidates[0][0]
        self._charge_output(len(src_url))
        candidate_urls = self._candidate_image_urls(abs_url, candidates)
        inferred_width, inferred_height = self._infer_dimensions_from_url(candidate_urls[0])
        ref = f"IMG{len(self.images) + 1}"
        img = Image(
            url=abs_url,
            alt=alt,
            ref=ref,
            width=self._parse_dimension(el.get("width")) or inferred_width,
            height=self._parse_dimension(el.get("height")) or inferred_height,
            candidate_urls=candidate_urls,
        )
        self.images.append(img)
        self._end_line_start()

        return f"{IMAGE_EDGE}![{self._escape_md_link_text(self._clean_text(alt))}](llmwiki-image://{ref}){IMAGE_EDGE}"

    def _parse_srcset(self, value: object) -> list[tuple[str, int | None]]:
        """Resolved candidates, charged one by one so a long base URL cannot balloon them before the budget sees it."""
        candidates: list[tuple[str, int | None]] = []
        for url, width in self._srcset_candidates(value):
            self._charge_output(len(url))
            candidates.append((url, width))
        return candidates

    def _srcset_candidates(self, value: object) -> Iterator[tuple[str, int | None]]:
        if not value:
            return
        for raw in str(value).split(","):
            parts = raw.strip().split()
            if not parts:
                continue
            url = self._resolve_url(parts[0])
            if not url:
                continue
            width: int | None = None
            if len(parts) > 1 and parts[1].endswith("w"):
                width = self._parse_dimension(parts[1][:-1])
            yield url, width

    @staticmethod
    def _candidate_image_urls(src: str, srcset: list[tuple[str, int | None]]) -> list[str]:
        ordered_srcset = [
            url for url, _width in sorted(
                srcset,
                key=lambda item: item[1] or 0,
                reverse=True,
            )
        ]
        # Some publishers (e.g. Bloomberg) put a sentinel URL in src and the real image in srcset.
        return list(dict.fromkeys(url for url in [*ordered_srcset, src] if url))

    @staticmethod
    def _infer_dimensions_from_url(url: str) -> tuple[int | None, int | None]:
        match = re.search(r"/(\d{2,5})x(\d{2,5})(?:[./?_-]|$)", url)
        if not match:
            return None, None
        width = int(match.group(1))
        height = int(match.group(2))
        return (width or None), (height or None)

    @staticmethod
    def _parse_dimension(value: object) -> int | None:
        if value is None:
            return None
        match = re.match(r"^\s*(\d{1,5})", str(value))
        if not match:
            return None
        parsed = int(match.group(1))
        return parsed if parsed > 0 else None

    @staticmethod
    def _escape_md_link_text(value: str) -> str:
        return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")

    def _process_children(self, el: Tag) -> str:
        parts = []
        for child in el.children:
            result = self._process_node(child)
            if result:
                parts.append(result)
        return "".join(parts)

    def _process_node(self, node: PageElement) -> str:
        """Render a node, charging the budget for whatever its rendering adds beyond what its descendants charged."""
        charged_before = self._output_chars
        result = self._render_node(node)
        self._charge_output(len(result) - (self._output_chars - charged_before))
        return result

    def _charge_output(self, chars: int) -> None:
        if chars <= 0:
            return
        self._output_chars += chars
        if self._output_chars > MAX_OUTPUT_CHARS:
            raise self._limit_error()

    @staticmethod
    def _limit_error() -> ParseLimitExceededError:
        return ParseLimitExceededError(
            f"Page is too large to convert: rendering it would exceed {MAX_OUTPUT_CHARS:,} characters.",
        )

    def _render_node(self, node: PageElement) -> str:
        if isinstance(node, NavigableString):
            return self._process_text(node)

        if not isinstance(node, Tag):
            return ""

        is_block = node.name in TRACKED_BLOCKS or node.name in BLOCK_TAGS
        if is_block:
            self._start_line()
        result = self._process_tag(node)
        if is_block:
            self._start_line()
        return result

    def _process_tag(self, node: Tag) -> str:
        tag = node.name

        if self._is_in_table_cell and tag in CELL_FLATTENED_TAGS:
            return f" {self._process_children(node)} "

        if tag in TRACKED_BLOCKS:
            return self._process_tracked_block(node)

        if tag == "a":
            return self._process_link(node)

        if tag == "code":
            return self._process_inline_code(node)

        if tag == "li":
            return self._process_children(node)

        if tag == "hr":
            return self._process_hr()

        if tag == "br":
            return self._process_br()

        if tag == "img":
            return self._process_img(node)

        if tag in FORM_FIELD_TAGS:
            return self._process_form_field(node)

        if tag in BLOCK_TAGS:
            seg_before = len(self._segments)
            content = self._process_children(node).strip()
            if not content:
                return BLOCK_SEPARATOR
            if not self._suppress_tracking and len(self._segments) == seg_before:
                self._segments.append((content, node))
            return f"\n\n{content}\n\n"

        wrapper = self._get_markdown_wrapper(node)
        if wrapper:
            content = self._process_children(node)
            lead, core, trail = self._split_inline_edges(content)
            if core and "\n" not in core:
                return f"{lead}{EMPHASIS_OPEN}{wrapper}{core}{wrapper}{EMPHASIS_CLOSE}{trail}"
            return content

        return self._process_children(node)

    def _process_tracked_block(self, node: Tag) -> str:
        tag = node.name
        was_suppressed = self._suppress_tracking
        self._suppress_tracking = True

        if tag in HEADING_TAGS:
            result = self._process_heading(node)
        elif tag == "ul":
            result = self._process_list(node, ordered=False)
        elif tag == "ol":
            result = self._process_list(node, ordered=True)
        elif tag == "table":
            if self._is_layout_table(node):
                self._suppress_tracking = was_suppressed
                return self._process_children(node)
            result = self._process_table(node)
        elif tag == "blockquote":
            result = self._process_blockquote(node)
        elif tag == "pre":
            result = self._process_pre(node)
        elif tag == "form":
            result = self._process_form(node)
        elif tag == "p":
            content = self._process_children(node).strip()
            result = f"\n\n{content}\n\n" if content else BLOCK_SEPARATOR
        else:
            result = ""

        self._suppress_tracking = was_suppressed

        stripped = result.strip()
        if stripped and not self._suppress_tracking:
            self._segments.append((stripped, node))

        return result

    def _process_form(self, node: Tag) -> str:
        inner = self._process_children(node).strip()
        if not inner:
            return BLOCK_SEPARATOR
        self._rendered_form_ids.add(id(node))
        header = escape_markdown_text(self._clean_text(self.forms.form_header(node)).strip(), is_line_start=True)
        return f"\n\n{header}\n\n{inner}\n\n"

    def _process_form_field(self, node: Tag) -> str:
        label = self._form_field_label(node, self.forms)
        if not label:
            return ""
        self._end_line_start()
        return escape_markdown_text(label, is_line_start=False)

    @classmethod
    def _form_field_label(cls, node: Tag, forms: FormExtractor) -> str:
        if node.name == "input":
            label = forms.process_input(node)
        elif node.name == "button":
            label = forms.process_button(node)
        elif node.name == "select":
            label = forms.process_select(node)
        else:
            label = forms.process_textarea(node)
        return cls._clean_text(label).strip()

    @staticmethod
    def _infer_kind(node: Tag) -> ElementKind:
        tag = node.name
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            return "heading"
        if tag == "p":
            return "paragraph"
        if tag == "table":
            return "table"
        if tag in {"ul", "ol"}:
            return "list"
        if tag == "blockquote":
            return "blockquote"
        if tag == "pre":
            return "code"
        if tag == "form":
            return "form"
        return "text"

    @staticmethod
    def _generate_id(idx: int, content: str, kind: ElementKind) -> str:
        prefix = kind[0] if kind else "x"
        digest = hashlib.sha1(content.encode()).hexdigest()[:8]
        return f"webmd-{prefix}{idx}-{digest}"

    def _build_elements(self) -> list[Element]:
        elements: list[Element] = []

        for idx, (seg_content, node) in enumerate(self._segments):
            normalized = self._normalize_output(seg_content)
            if not normalized:
                continue

            kind = self._infer_kind(node)
            elem_id = self._generate_id(idx, normalized, kind)
            elements.append(Element(id=elem_id, content=normalized, kind=kind))

            self._block_nodes[elem_id] = [node]

        return elements

    def _stamp_dom(self, elements: list[Element]) -> None:
        for elem in elements:
            nodes = self._block_nodes.get(elem.id, [])
            for node in nodes:
                if not node.get("id"):
                    node["id"] = elem.id
                node["data-webmd-block"] = elem.id

    _URL_ATTRS = {
        "a": ["href"],
        "img": ["src", "srcset"],
        "source": ["src", "srcset"],
        "link": ["href"],
        "form": ["action"],
        "video": ["src", "poster"],
        "audio": ["src"],
    }

    def _rewrite_dom_urls(self) -> None:
        """Resolve all relative URLs in the DOM to absolute using self.url; unparseable ones are left as written."""
        if not self.url:
            return
        for tag_name, attrs in self._URL_ATTRS.items():
            for el in self.soup.find_all(tag_name):
                for attr in attrs:
                    val = el.get(attr)
                    if not val:
                        continue
                    if val.startswith("#"):
                        continue
                    if attr == "srcset":
                        el[attr] = self._resolve_srcset(val)
                    else:
                        el[attr] = self._resolve_url(val) or val
                        self._charge_output(len(el[attr]))

    def _resolve_srcset(self, srcset: str) -> str:
        parts = []
        for entry in srcset.split(","):
            entry = entry.strip()
            if not entry:
                continue
            tokens = entry.split(None, 1)
            tokens[0] = self._resolve_url(tokens[0]) or tokens[0]
            self._charge_output(len(tokens[0]))
            parts.append(" ".join(tokens))
        return ", ".join(parts)

    _MAX_IMG_BYTES = 5 * 1024 * 1024
    _MAX_TOTAL_BYTES = 20 * 1024 * 1024
    _EMBED_TIMEOUT_SECONDS = 10
    _EMBED_CONCURRENCY = 8
    _MAX_EMBED_IMAGES = 32

    async def embed_images(self) -> None:
        imgs = [
            img for img in self.soup.find_all("img")
            if img.get("src") and not img["src"].startswith("data:")
        ][:self._MAX_EMBED_IMAGES]
        if not imgs:
            return

        sem = asyncio.Semaphore(self._EMBED_CONCURRENCY)
        total_bytes = 0

        async def _download(img_tag: Tag) -> None:
            nonlocal total_bytes
            src = img_tag["src"]

            async with sem:
                if total_bytes >= self._MAX_TOTAL_BYTES:
                    return
                try:
                    fetched = await safe_fetch.fetch_public_image(
                        src,
                        max_bytes=self._MAX_IMG_BYTES,
                        timeout=self._EMBED_TIMEOUT_SECONDS,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    if not fetched:
                        return
                    data, mime = fetched
                    if total_bytes + len(data) > self._MAX_TOTAL_BYTES:
                        return
                    total_bytes += len(data)

                    b64 = base64.b64encode(data).decode("ascii")
                    img_tag["src"] = f"data:{mime};base64,{b64}"

                except Exception:  # noqa: BLE001
                    pass

        await asyncio.gather(*[_download(img) for img in imgs])

    @staticmethod
    def _is_safe_url(value: str, *, allow_data_image: bool = False) -> bool:
        value = value.strip()
        if not value:
            return False
        if re.search(r"[\x00-\x1f\x7f]", value):
            return False
        lowered = value.lower()
        if lowered.startswith(("#", "/", "./", "../")):
            return True
        if lowered.startswith("//"):
            return True
        if ":" not in lowered.split("/", 1)[0]:
            return True
        scheme = lowered.split(":", 1)[0]
        if scheme in SANITIZE_ALLOWED_URL_SCHEMES:
            return True
        if allow_data_image and lowered.startswith("data:"):
            header = lowered[5:].split(",", 1)[0].split(";", 1)[0].strip()
            return header in SANITIZE_ALLOWED_DATA_IMAGE_TYPES
        return False

    @classmethod
    def _sanitize_srcset(cls, value: str) -> str | None:
        if "data:" in value.lower():
            return None

        entries: list[str] = []
        for raw_entry in value.split(","):
            entry = raw_entry.strip()
            if not entry:
                continue
            tokens = entry.split()
            if not tokens:
                continue
            if cls._is_safe_url(tokens[0], allow_data_image=False):
                entries.append(" ".join(tokens))
        return ", ".join(entries) if entries else None

    def _sanitize_dom(self) -> None:
        remove_elements(self.soup.find_all(SANITIZE_DROP_TAGS))

        for tag in self.soup.find_all(True):
            allowed_attrs = SANITIZE_GLOBAL_ATTRS | SANITIZE_ATTRS_BY_TAG.get(tag.name, set())
            for attr in list(tag.attrs.keys()):
                attr_l = attr.lower()
                value = tag.get(attr)

                if attr_l.startswith("on") or attr_l == "style" or attr_l == "srcdoc":
                    del tag.attrs[attr]
                    continue

                if attr_l not in allowed_attrs:
                    del tag.attrs[attr]
                    continue

                if attr_l in SANITIZE_URL_ATTRS:
                    raw = " ".join(value) if isinstance(value, list) else str(value)
                    allow_data = tag.name == "img" and attr_l == "src"
                    if not self._is_safe_url(raw, allow_data_image=allow_data):
                        del tag.attrs[attr]
                    continue

                if tag.name == "img" and attr_l == "srcset":
                    raw = " ".join(value) if isinstance(value, list) else str(value)
                    clean = self._sanitize_srcset(raw)
                    if clean:
                        tag.attrs[attr] = clean
                    else:
                        del tag.attrs[attr]
                    continue

                if attr_l == "target" and str(value).lower() != "_blank":
                    del tag.attrs[attr]
                    continue

                if tag.name == "a" and attr_l == "rel":
                    tag.attrs[attr] = "noopener noreferrer"

            if tag.name == "a" and tag.get("target") == "_blank":
                tag["rel"] = "noopener noreferrer"

    def html(self, sanitize: bool = False) -> str:
        if sanitize:
            self._sanitize_dom()
        return str(self.soup)

    def _normalize_output(self, text: str) -> str:
        text = self._normalize_block(text).replace(INDENT, " ")
        text = self._resolve_emphasis(self._expand_inline_code(text))
        return "\n".join(self._expand_code_block(line) for line in text.split("\n"))

    @classmethod
    def _resolve_emphasis(cls, text: str) -> str:
        """Resolve emphasis markers in one pass, innermost pairs first, keeping delimiters only where markdown-it pairs them as written."""
        frames = [EmphasisFrame(delimiter="")]
        cursor = 0
        for marker in _emphasis_marker.finditer(text):
            if marker.start() > cursor:
                frames[-1].parts.append(text[cursor:marker.start()])
            cursor = marker.end()
            if marker.group() == EMPHASIS_OPEN:
                window = text[cursor:cursor + 3]
                run = len(window) - len(window.lstrip("*"))
                frames.append(EmphasisFrame(delimiter="*" * run))
                cursor += run
            elif len(frames) > 1:
                cls._close_emphasis(frames, text[cursor] if cursor < len(text) else " ")
        if cursor < len(text):
            frames[-1].parts.append(text[cursor:])
        while len(frames) > 1:
            unclosed = frames.pop()
            frames[-1].parts.append("".join(unclosed.parts))
        return "".join(frames[0].parts)

    @classmethod
    def _close_emphasis(cls, frames: list[EmphasisFrame], after: str) -> None:
        frame = frames.pop()
        parent = frames[-1]
        content = "".join(frame.parts)[:-len(frame.delimiter)]
        before = parent.parts[-1][-1] if parent.parts else (parent.delimiter[-1:] or " ")
        # A delimiter run that can both open and close may pair with an outer run instead of its own.
        if frame.has_ambiguous or not cls._is_emphasis_parseable(content, before, after):
            if content:
                parent.parts.append(content)
            parent.has_ambiguous = parent.has_ambiguous or frame.has_ambiguous
            return
        parent.parts.append(f"{frame.delimiter}{content}{frame.delimiter}")
        if is_ambiguous_delimiter(before, content[0]) or is_ambiguous_delimiter(content[-1], after):
            parent.has_ambiguous = True

    @staticmethod
    def _is_emphasis_parseable(visible: str, before: str, after: str) -> bool:
        """Whether markdown-it opens and closes emphasis here: no fused neighbour runs, no leading image, flanking met."""
        if not visible or visible.startswith("!["):
            return False
        if before in f"*{EMPHASIS_CLOSE}" or after in f"*{EMPHASIS_OPEN}":
            return False
        return can_open_emphasis(before, visible[0]) and can_close_emphasis(visible[-1], after)

    def _normalize_nested_block(self, text: str) -> str:
        """Charged as work: each enclosing quote or list re-normalizes and re-prefixes the same text."""
        self._charge_output(len(text))
        return self._normalize_block(text)

    @classmethod
    def _normalize_block(cls, text: str) -> str:
        """Resolve hard breaks and image edges, drop stray whitespace outside structural prefixes, collapse blank runs."""
        text = _hard_break_run.sub(HARD_BREAK, text)
        text = _edge_hard_break.sub("", text).replace(HARD_BREAK, "\\\n")
        text = _image_edge.sub("", text)
        text = "\n".join(cls._normalize_line(line) for line in text.split("\n"))
        return _blank_runs.sub("\n\n", text).strip("\n")

    @staticmethod
    def _normalize_line(line: str) -> str:
        """Strip line-edge whitespace outside the structural prefix, Unicode too since markdown-it only trims ASCII."""
        prefix = _line_prefix.match(line).group()
        structure = prefix.replace(" ", "").replace("\t", "")
        content = line[len(prefix):].strip(JS_WHITESPACE)
        return structure + content if content else structure.rstrip(INDENT)

    def _expand_code_block(self, line: str) -> str:
        """Replace a code placeholder with a fenced block, repeating the line's container prefix on every code line."""
        match = _code_placeholder.search(line)
        if not match:
            return line
        code = self._code_blocks[int(match.group(1))]
        first_prefix = line[:match.start()]
        prefix = re.sub(r"[^> ]", " ", first_prefix)
        fence = code_fence(code)
        self._charge_output(len(prefix) * code.count("\n") + 2 * len(fence))
        body = [prefix + code_line if code_line else prefix.rstrip() for code_line in code.split("\n")]
        return "\n".join([first_prefix + fence, *body, prefix + fence])

    def _to_plaintext(self) -> str:
        """Canonical highlight-anchor plaintext: what canonicalPlaintext.ts reads off the viewer's render of the Markdown."""
        builder = PlaintextBuilder()
        root = self.soup.body if self.soup.body else self.soup
        self._plaintext_node(root, builder, BLOCK_SEPARATOR, is_in_heading=False)
        return builder.result()

    def _plaintext_node(self, node: PageElement, builder: PlaintextBuilder, separator: str, is_in_heading: bool) -> None:
        if isinstance(node, NavigableString):
            builder.text(self._clean_text(str(node)))
            return
        if not isinstance(node, Tag):
            return
        self._plaintext_tag(node, builder, separator, is_in_heading)

    def _plaintext_tag(self, node: Tag, builder: PlaintextBuilder, separator: str, is_in_heading: bool) -> None:
        tag = node.name
        if separator == CELL_SEPARATOR and tag in CELL_FLATTENED_TAGS:
            self._plaintext_block(node, builder, separator, is_in_heading)
        elif tag == "br":
            self._plaintext_br(builder, separator, is_in_heading)
        elif tag == "hr":
            builder.block(separator)
        elif tag == "img":
            if self._has_image_source(node):
                builder.block(separator)
        elif tag == "code":
            builder.text(self._clean_text(node.get_text()))
        elif tag == "pre":
            self._plaintext_pre(node, builder, separator)
        elif tag in FORM_FIELD_TAGS:
            builder.text(self._form_field_label(node, FormExtractor()))
        elif tag == "form":
            self._plaintext_form(node, builder, separator, is_in_heading)
        elif tag in {"ul", "ol"}:
            self._plaintext_list(node, builder, separator, is_in_heading)
        elif tag == "table":
            self._plaintext_table(node, builder, separator, is_in_heading)
        elif tag in HEADING_TAGS:
            self._plaintext_block(node, builder, separator, is_in_heading=id(node) in self._atx_heading_ids)
        elif tag != "li" and (tag in BLOCK_TAGS or tag in TRACKED_BLOCKS):
            self._plaintext_block(node, builder, separator, is_in_heading)
        else:
            self._plaintext_children(node, builder, separator, is_in_heading)

    def _plaintext_children(self, node: Tag, builder: PlaintextBuilder, separator: str, is_in_heading: bool) -> None:
        for child in node.children:
            self._plaintext_node(child, builder, separator, is_in_heading)

    def _plaintext_block(self, node: Tag, builder: PlaintextBuilder, separator: str, is_in_heading: bool) -> None:
        builder.block(separator)
        self._plaintext_children(node, builder, separator, is_in_heading)
        builder.block(separator)

    @staticmethod
    def _plaintext_br(builder: PlaintextBuilder, separator: str, is_in_heading: bool) -> None:
        """ATX headings and table cells cannot hold a hard break, so the Markdown writer turns those into spaces."""
        if is_in_heading or separator == CELL_SEPARATOR:
            builder.text(" ")
            return
        builder.hard_break()

    def _has_image_source(self, node: Tag) -> bool:
        return bool(self._resolve_url(node.get("src", "")) or next(self._srcset_candidates(node.get("srcset")), None))

    def _plaintext_pre(self, node: Tag, builder: PlaintextBuilder, separator: str) -> None:
        code = self._pre_code(node)
        if not code.strip():
            return
        if separator == CELL_SEPARATOR:
            builder.text(self._clean_text(code))
            return
        builder.block(separator)
        builder.verbatim(code)
        builder.block(separator)

    def _plaintext_form(self, node: Tag, builder: PlaintextBuilder, separator: str, is_in_heading: bool) -> None:
        builder.block(separator)
        if id(node) in self._rendered_form_ids:
            builder.text(self._clean_text(FormExtractor.form_header(node)))
            builder.block(separator)
        self._plaintext_children(node, builder, separator, is_in_heading)
        builder.block(separator)

    def _plaintext_list(self, node: Tag, builder: PlaintextBuilder, separator: str, is_in_heading: bool) -> None:
        """An item not opening with a paragraph is hoisted out of the list by ProseMirror, splitting it there."""
        builder.block(separator)
        follows_hoisted = False
        for li in node.find_all("li", recursive=False):
            is_hoisted = id(li) in self._hoisted_list_item_ids
            item_separator = separator if is_hoisted or follows_hoisted else LIST_SEPARATOR
            builder.block(item_separator)
            self._plaintext_children(li, builder, separator if is_hoisted else LIST_SEPARATOR, is_in_heading)
            follows_hoisted = is_hoisted
        builder.block(separator)

    def _plaintext_table(self, node: Tag, builder: PlaintextBuilder, separator: str, is_in_heading: bool) -> None:
        if self._is_layout_table(node):
            self._plaintext_children(node, builder, separator, is_in_heading)
            return
        builder.block(separator)
        for row in self._table_rows(node):
            builder.block(LIST_SEPARATOR)
            for cell in row:
                builder.block(CELL_SEPARATOR)
                self._plaintext_children(cell, builder, CELL_SEPARATOR, is_in_heading)
        builder.block(separator)

    _MIN_AUTO_LOCATE_LEN = 4       # below this, require prefix/suffix match
    _MAX_OCCURRENCES = 500

    @staticmethod
    def _normalize_anchor_text(text: str) -> str:
        text = text.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
        return _js_ws_run.sub(" ", text).strip(JS_WHITESPACE)

    @staticmethod
    def _normalize_with_index_map(plaintext: str) -> tuple[str, list[int]]:
        """Collapse whitespace (selections flatten block breaks) with an offset map back, plus an end sentinel."""
        out: list[str] = []
        index_map: list[int] = []
        prev_was_ws = True  # skips leading whitespace
        i = 0
        n = len(plaintext)
        while i < n:
            ch = plaintext[i]
            if ch in ("\u200b", "\ufeff"):
                i += 1
                continue
            if ch in JS_WHITESPACE:
                if not prev_was_ws and out:
                    out.append(" ")
                    index_map.append(i)
                prev_was_ws = True
                i += 1
                continue
            out.append(ch)
            index_map.append(i)
            prev_was_ws = False
            i += 1
        index_map.append(n)
        normalized = "".join(out)
        if normalized.endswith(" "):
            normalized = normalized[:-1]
            # drop the space's entry, keep the end sentinel
            index_map = index_map[:-2] + index_map[-1:]
        return normalized, index_map

    @staticmethod
    def _all_occurrences(haystack: str, needle: str, cap: int) -> list[int]:
        if not needle:
            return []
        occurrences: list[int] = []
        start = 0
        while len(occurrences) < cap:
            idx = haystack.find(needle, start)
            if idx == -1:
                break
            occurrences.append(idx)
            start = idx + 1
        return occurrences

    @classmethod
    def _score_context(
        cls, normalized_plaintext: str, idx: int, length: int,
        prefix: str | None, suffix: str | None,
    ) -> int:
        score = 0
        if prefix:
            normalized_prefix = cls._normalize_anchor_text(prefix)
            if normalized_prefix:
                window = max(len(normalized_prefix), 32)
                before = normalized_plaintext[max(0, idx - window):idx]
                if before.endswith(normalized_prefix):
                    score += 4
                elif normalized_prefix in before:
                    score += 1
        if suffix:
            normalized_suffix = cls._normalize_anchor_text(suffix)
            if normalized_suffix:
                window = max(len(normalized_suffix), 32)
                after = normalized_plaintext[idx + length:idx + length + window]
                if after.startswith(normalized_suffix):
                    score += 4
                elif normalized_suffix in after:
                    score += 1
        return score

    @classmethod
    def _locate_highlight(
        cls, plaintext: str, anchor_payload: dict,
    ) -> TextAnchor | None:
        return cls._locate_in_haystack(cls._anchor_haystack(plaintext), anchor_payload)

    @classmethod
    def _anchor_haystack(cls, plaintext: str) -> AnchorHaystack:
        units = to_utf16_units(plaintext)
        normalized, index_map = cls._normalize_with_index_map(units)
        return AnchorHaystack(units=units, normalized=normalized, index_map=index_map)

    @classmethod
    def _locate_in_haystack(
        cls, haystack: AnchorHaystack, anchor_payload: dict,
    ) -> TextAnchor | None:
        """Locate in UTF-16 code units, the unit the browser's offsets and windows use."""
        prefix = anchor_payload.get("prefix")
        suffix = anchor_payload.get("suffix")
        units = haystack.units
        normalized_haystack = haystack.normalized
        index_map = haystack.index_map

        normalized_needle = cls._normalize_anchor_text(to_utf16_units(anchor_payload.get("textContent") or ""))
        if not normalized_needle:
            return None

        occurrences = cls._all_occurrences(
            normalized_haystack, normalized_needle, cap=cls._MAX_OCCURRENCES,
        )
        if not occurrences:
            return None

        if len(occurrences) == 1:
            chosen = occurrences[0]
        else:
            unit_prefix = to_utf16_units(prefix) if prefix else prefix
            unit_suffix = to_utf16_units(suffix) if suffix else suffix
            scored = [
                (cls._score_context(
                    normalized_haystack, occ, len(normalized_needle), unit_prefix, unit_suffix,
                ), occ)
                for occ in occurrences
            ]
            best_score, chosen = max(scored, key=lambda t: t[0])

            # A wrong guess on a short phrase is worse than the viewer's runtime text-search fallback.
            if (
                len(normalized_needle) < cls._MIN_AUTO_LOCATE_LEN
                and best_score == 0
            ):
                return None

        text_start = index_map[chosen] if chosen < len(index_map) else chosen
        end_norm_idx = chosen + len(normalized_needle)
        text_end = index_map[end_norm_idx] if end_norm_idx < len(index_map) else len(units)

        return TextAnchor(
            text_start=text_start,
            text_end=text_end,
            text_content=from_utf16_units(units[text_start:text_end]),
            prefix=prefix,
            suffix=suffix,
        )

    @classmethod
    def map_highlights(
        cls, plaintext: str, highlights: list[dict],
    ) -> list[MappedHighlight]:
        """Map each highlight payload to a plaintext anchor, or `text_anchor=None` when unlocatable."""
        if not highlights:
            return []
        haystack = cls._anchor_haystack(plaintext)
        results: list[MappedHighlight] = []
        for h in highlights:
            if not isinstance(h, dict):
                continue
            anchor_data = h.get("anchor") or {}
            text_anchor = cls._locate_in_haystack(haystack, anchor_data) if anchor_data else None
            results.append(MappedHighlight(payload=h, text_anchor=text_anchor))
        return results

    def parse(self, highlights: list[dict] | None = None) -> ParseResult:
        if self._parsed:
            raise RuntimeError("Parser instances are single-use; create a new Parser to parse again.")
        self._parsed = True
        root = self.soup.body if self.soup.body else self.soup
        raw = self._process_node(root)
        # Plaintext must see the same raw URLs (e.g. form actions) the Markdown was built from.
        plaintext = self._to_plaintext()
        if self.content_only and len(plaintext) < MIN_CONTENT_ONLY_PLAINTEXT:
            return self._parse_whole_page(highlights or [])

        content = self._normalize_output(raw)
        if len(content) > MAX_OUTPUT_CHARS:
            raise self._limit_error()
        elements = self._build_elements()
        self._stamp_dom(elements)
        self._rewrite_dom_urls()

        return ParseResult(
            content=content,
            images=self.images,
            url=self.url,
            plaintext=plaintext,
            highlights=self.map_highlights(plaintext, highlights or []),
        )

    def _parse_whole_page(self, highlights: list[dict]) -> ParseResult:
        """A thin content-only result usually means the noise filter ate the article, so the whole page wins."""
        whole_page = Parser(self._content, url=self.url)
        result = whole_page.parse(highlights)
        self.soup = whole_page.soup
        self.images = whole_page.images
        return result

    def markdown(self) -> str:
        return self.parse().content
