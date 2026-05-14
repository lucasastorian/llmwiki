from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Comment
from bs4.element import NavigableString, Tag

from .models import Element, Image, MappedHighlight, ParseResult, TextAnchor
from .forms import FormExtractor, FormElement

logger = logging.getLogger(__name__)


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
    "video", "audio", "map", "object", "embed",
}

NOISE_TAGS = {"nav", "footer", "aside", "header"}

NOISE_CLASSES = {
    "sidebar", "navigation", "nav", "menu", "footer", "header",
    "advertisement", "ad", "ads", "banner", "cookie", "popup",
    "modal", "overlay", "social", "share", "comment", "comments",
    "related", "recommended", "trending", "popular",
}

NOISE_IDS = {
    "sidebar", "navigation", "nav", "menu", "footer", "header",
    "comments", "ad", "ads", "banner",
}

TRACKED_BLOCKS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "table", "ul", "ol", "blockquote", "pre", "form",
}

_ws = re.compile(r"[ \t]+")
_newlines = re.compile(r"\n{3,}")


class Parser:

    def __init__(self, content: str, url: str = "", content_only: bool = False):
        self.soup = BeautifulSoup(content, "lxml")
        self.url = url
        self.content_only = content_only
        self.images: List[Image] = []
        self.forms = FormExtractor()
        self._segments: List[Tuple[str, Tag]] = []
        self._suppress_tracking: bool = False
        self._block_nodes: Dict[str, List[Tag]] = {}
        self._remove_noise()

    def _resolve_url(self, src: str) -> str:
        if not src:
            return ""
        if src.startswith("//"):
            return "https:" + src
        if src.startswith(("http://", "https://", "data:")):
            return src
        if self.url:
            return urljoin(self.url, src)
        return src

    def _remove_noise(self) -> None:
        for tag_name in REMOVE_TAGS:
            for tag in self.soup.find_all(tag_name):
                tag.decompose()

        for tag in self.soup.find_all(style=re.compile(r'display\s*:\s*none', re.I)):
            tag.decompose()

        for comment in self.soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        if self.content_only:
            to_remove = [
                tag for tag in self.soup.find_all(NOISE_TAGS)
                if tag.parent is not None
            ]
            for tag in to_remove:
                tag.decompose()

    @staticmethod
    def _is_hidden(el: Tag) -> bool:
        if not isinstance(el, Tag):
            return False

        if el.has_attr("hidden"):
            return True

        if el.get("aria-hidden") == "true":
            return True

        style = (el.get("style") or "").lower().replace(" ", "")
        return "display:none" in style or "visibility:hidden" in style

    @staticmethod
    def _is_noise(el: Tag) -> bool:
        if not isinstance(el, Tag):
            return False

        if el.name in NOISE_TAGS:
            return True

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
        if role in {"navigation", "banner", "complementary", "contentinfo"}:
            return True

        return False

    @staticmethod
    def _is_bold(el: Tag) -> bool:
        if not isinstance(el, Tag):
            return False
        if el.name in BOLD_TAGS:
            return True
        style = (el.get("style") or "").lower()
        return "font-weight:700" in style or "font-weight:bold" in style

    @staticmethod
    def _is_italic(el: Tag) -> bool:
        if not isinstance(el, Tag):
            return False
        if el.name in ITALIC_TAGS:
            return True
        style = (el.get("style") or "").lower()
        return "font-style:italic" in style

    @staticmethod
    def _clean_text(text: str) -> str:
        text = text.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
        text = _ws.sub(" ", text)
        return text

    def _get_markdown_wrapper(self, el: Tag) -> str:
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
        return self._clean_text(str(node))

    def _process_heading(self, el: Tag) -> str:
        level = int(el.name[1])
        prefix = "#" * level + " "
        text = self._process_children(el).strip()
        text = text.replace("**", "").replace("*", "")
        if text:
            return f"\n\n{prefix}{text}\n\n"
        return ""

    def _process_link(self, el: Tag) -> str:
        href = el.get("href", "")
        text = self._process_children(el).strip()

        if not text or not href or href.startswith("javascript:"):
            return text

        if href.startswith("#"):
            return text

        href = self._resolve_url(href)
        return f"[{text}]({href})"

    def _process_list(self, el: Tag, ordered: bool = False) -> str:
        items = []
        for i, li in enumerate(el.find_all("li", recursive=False)):
            item_text = self._process_children(li).strip()
            if item_text:
                item_text = re.sub(r'\n\s*\n', '\n', item_text)
                if ordered:
                    items.append(f"{i + 1}. {item_text}")
                else:
                    items.append(f"- {item_text}")

        if items:
            return "\n\n" + "\n".join(items) + "\n\n"
        return ""

    @staticmethod
    def _safe_span(value) -> int:
        try:
            if not value:
                return 1
            return max(1, int(value))
        except (ValueError, TypeError):
            return 1

    _LAYOUT_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "ul", "ol", "blockquote", "pre", "table", "br"}

    def _is_layout_table(self, el: Tag) -> bool:
        """Detect tables used for page layout rather than tabular data."""
        if el.get("role") in ("presentation", "layout"):
            return True
        if el.find("th"):
            return False
        cells = el.find_all(["td", "th"], recursive=True)
        if not cells:
            return False
        for cell in cells:
            if cell.find(self._LAYOUT_BLOCK_TAGS):
                return True
        return False

    def _process_table(self, el: Tag) -> str:
        raw_rows = []
        for tr in el.find_all("tr"):
            cells = []
            for td in tr.find_all(["td", "th"]):
                text = self._process_children(td).strip()
                text = text.replace("|", "\\|").replace("\n", " ")
                text = _ws.sub(" ", text)
                rowspan = self._safe_span(td.get("rowspan"))
                colspan = self._safe_span(td.get("colspan"))
                cells.append((text, rowspan, colspan))
            if cells:
                raw_rows.append(cells)

        if not raw_rows:
            return ""

        max_cols = max(sum(cs for _, _, cs in row) for row in raw_rows)
        num_rows = len(raw_rows)
        grid: List[List[Optional[str]]] = [[None] * max_cols for _ in range(num_rows)]

        for i, row in enumerate(raw_rows):
            col = 0
            for text, rowspan, colspan in row:
                while col < max_cols and grid[i][col] is not None:
                    col += 1
                if col >= max_cols:
                    break
                grid[i][col] = text
                for r in range(rowspan):
                    for c in range(colspan):
                        if r == 0 and c == 0:
                            continue
                        ri, ci = i + r, col + c
                        if ri < num_rows and ci < max_cols:
                            grid[ri][ci] = ""
                col += colspan

        for i in range(num_rows):
            for j in range(max_cols):
                if grid[i][j] is None:
                    grid[i][j] = ""

        grid = [row for row in grid if any(cell.strip() for cell in row)]
        if not grid:
            return ""

        cols_with_content = [
            j for j in range(len(grid[0]))
            if any(grid[i][j].strip() for i in range(len(grid)))
        ]
        if not cols_with_content:
            return ""
        grid = [[row[j] for j in cols_with_content] for row in grid]

        num_cols = len(grid[0])
        lines = []
        for i, row in enumerate(grid):
            lines.append("| " + " | ".join(row) + " |")
            if i == 0:
                lines.append("|" + "|".join(["---"] * num_cols) + "|")

        return "\n\n" + "\n".join(lines) + "\n\n"

    def _process_blockquote(self, el: Tag) -> str:
        text = self._process_children(el).strip()
        if text:
            lines = text.split("\n")
            quoted = "\n".join(f"> {line}" for line in lines)
            return f"\n\n{quoted}\n\n"
        return ""

    def _process_pre(self, el: Tag) -> str:
        text = el.get_text()
        if text.strip():
            return f"\n\n```\n{text}\n```\n\n"
        return ""

    def _process_hr(self) -> str:
        return "\n\n---\n\n"

    def _process_br(self) -> str:
        return "\n"

    def _process_img(self, el: Tag) -> str:
        alt = el.get("alt", "")
        src = el.get("src", "")

        if not src:
            return ""

        abs_url = self._resolve_url(src)
        img = Image(url=abs_url, alt=alt)
        self.images.append(img)

        ref = f"IMG{len(self.images)}"
        if alt:
            return f"[{ref}: {alt}]"
        return f"[{ref}]"

    def _process_children(self, el: Tag) -> str:
        parts = []
        for child in el.children:
            result = self._process_node(child)
            if result:
                parts.append(result)
        return "".join(parts)

    def _process_node(self, node) -> str:
        if isinstance(node, NavigableString):
            return self._process_text(node)

        if not isinstance(node, Tag):
            return ""

        if self._is_hidden(node):
            return ""

        if self.content_only and self._is_noise(node):
            return ""

        tag = node.name

        if tag in TRACKED_BLOCKS:
            was_suppressed = self._suppress_tracking
            self._suppress_tracking = True

            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
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
                inner = self._process_children(node)
                result = self.forms.process_form(node, inner)
            elif tag == "p":
                content = self._process_children(node).strip()
                result = f"\n\n{content}\n\n" if content else ""
            else:
                result = ""

            self._suppress_tracking = was_suppressed

            stripped = result.strip()
            if stripped and not self._suppress_tracking:
                self._segments.append((stripped, node))

            return result

        if tag == "a":
            return self._process_link(node)

        if tag == "li":
            return self._process_children(node)

        if tag == "hr":
            return self._process_hr()

        if tag == "br":
            return self._process_br()

        if tag == "img":
            return self._process_img(node)

        if tag == "input":
            return self.forms.process_input(node)

        if tag == "button":
            return self.forms.process_button(node)

        if tag == "select":
            return self.forms.process_select(node)

        if tag == "textarea":
            return self.forms.process_textarea(node)

        if tag in BLOCK_TAGS:
            seg_before = len(self._segments)
            content = self._process_children(node).strip()
            if content:
                if not self._suppress_tracking and len(self._segments) == seg_before:
                    self._segments.append((content, node))
                return f"\n\n{content}\n\n"
            return ""

        wrapper = self._get_markdown_wrapper(node)
        if wrapper:
            content = self._process_children(node)
            if content.strip():
                return f"{wrapper}{content.strip()}{wrapper}"
            return content

        return self._process_children(node)

    @staticmethod
    def _infer_kind(node: Tag) -> str:
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
    def _generate_id(idx: int, content: str, kind: str) -> str:
        prefix = kind[0] if kind else "x"
        digest = hashlib.sha1(content.encode()).hexdigest()[:8]
        return f"webmd-{prefix}{idx}-{digest}"

    def _build_elements(self, content: str) -> List[Element]:
        elements: List[Element] = []
        current_offset = 0

        for idx, (seg_content, node) in enumerate(self._segments):
            normalized = self._normalize_output(seg_content)
            if not normalized:
                continue

            kind = self._infer_kind(node)
            elem_id = self._generate_id(idx, normalized, kind)

            start = content.find(normalized, current_offset)
            if start != -1:
                end = start + len(normalized)
                current_offset = end
            else:
                start = None
                end = None

            elem = Element(
                id=elem_id,
                content=normalized,
                kind=kind,
                content_start_offset=start,
                content_end_offset=end,
            )
            elements.append(elem)

            self._block_nodes[elem_id] = [node]

        return elements

    def _stamp_dom(self, elements: List[Element]) -> None:
        for elem in elements:
            nodes = self._block_nodes.get(elem.id, [])
            for node in nodes:
                if not node.get("id"):
                    node["id"] = elem.id
                node["data-webmd-block"] = elem.id

    # ── DOM URL rewriting ──────────────────────────────────

    _URL_ATTRS = {
        "a": ["href"],
        "img": ["src"],
        "source": ["src", "srcset"],
        "link": ["href"],
        "form": ["action"],
        "video": ["src", "poster"],
        "audio": ["src"],
    }

    def _rewrite_dom_urls(self) -> None:
        """Resolve all relative URLs in the DOM to absolute using self.url."""
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
                        el[attr] = self._resolve_url(val)

    def _resolve_srcset(self, srcset: str) -> str:
        """Resolve each URL in a srcset attribute."""
        parts = []
        for entry in srcset.split(","):
            entry = entry.strip()
            if not entry:
                continue
            tokens = entry.split(None, 1)
            tokens[0] = self._resolve_url(tokens[0])
            parts.append(" ".join(tokens))
        return ", ".join(parts)

    # ── Image embedding ────────────────────────────────────

    _MAX_IMG_BYTES = 5 * 1024 * 1024    # 5 MB per image
    _MAX_TOTAL_BYTES = 20 * 1024 * 1024  # 20 MB total
    _EMBED_TIMEOUT = 10                   # seconds per image
    _EMBED_CONCURRENCY = 8

    _ALLOWED_SCHEMES = {"http", "https"}

    @staticmethod
    def _is_dangerous_ip(addr: str) -> bool:
        import ipaddress
        try:
            ip = ipaddress.ip_address(addr)
            return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local
        except ValueError:
            return True

    @staticmethod
    def _resolve_safe(url: str) -> tuple[str, str, int, str, str] | None:
        """Resolve URL, validate all IPs are public.
        Returns (safe_ip, host, port, scheme, path_with_query) or None.
        """
        from urllib.parse import urlparse
        import socket
        try:
            parsed = urlparse(url)
            if parsed.scheme not in Parser._ALLOWED_SCHEMES:
                return None
            host = parsed.hostname or ""
            if not host:
                return None
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
                return None
            if Parser._is_dangerous_ip(host):
                return None
            addrs = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
            if not addrs:
                return None
            for _fam, _type, _proto, _canon, sockaddr in addrs:
                if Parser._is_dangerous_ip(sockaddr[0]):
                    return None
            safe_ip = addrs[0][4][0]
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            return safe_ip, host, port, parsed.scheme, path
        except Exception:
            return None

    async def embed_images(self) -> None:
        imgs = [
            img for img in self.soup.find_all("img")
            if img.get("src") and not img["src"].startswith("data:")
        ]
        if not imgs:
            return

        sem = asyncio.Semaphore(self._EMBED_CONCURRENCY)
        total_bytes = 0

        async def _download(img_tag: Tag) -> None:
            nonlocal total_bytes
            src = img_tag["src"]

            resolved = await asyncio.to_thread(Parser._resolve_safe, src)
            if not resolved:
                return
            safe_ip, host, port, scheme, path = resolved

            ip_str = f"[{safe_ip}]" if ":" in safe_ip else safe_ip
            default_port = 443 if scheme == "https" else 80
            port_suffix = f":{port}" if port != default_port else ""
            pinned_url = f"{scheme}://{ip_str}{port_suffix}{path}"

            async with sem:
                try:
                    async with httpx.AsyncClient(
                        follow_redirects=False, verify=False,
                    ) as client:
                        resp = await client.get(
                            pinned_url,
                            headers={"Host": host, "User-Agent": "Mozilla/5.0"},
                            timeout=self._EMBED_TIMEOUT,
                        )
                        resp.raise_for_status()

                    data = resp.content
                    if len(data) > self._MAX_IMG_BYTES:
                        return
                    if total_bytes + len(data) > self._MAX_TOTAL_BYTES:
                        return
                    total_bytes += len(data)

                    ct = resp.headers.get("content-type", "image/png")
                    mime = ct.split(";")[0].strip()
                    if not mime.startswith("image/"):
                        return

                    b64 = base64.b64encode(data).decode("ascii")
                    img_tag["src"] = f"data:{mime};base64,{b64}"

                except Exception:
                    pass

        await asyncio.gather(*[_download(img) for img in imgs])

    def html(self) -> str:
        return str(self.soup)

    def _normalize_output(self, text: str) -> str:
        text = _newlines.sub("\n\n", text)
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(lines)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    # ── Plaintext extraction ───────────────────────────────
    #
    # Produces a canonical plaintext used to locate highlights at save time so
    # each highlight gets a stable plaintext-relative anchor (text_start,
    # text_end). The wiki viewer must implement an EQUIVALENT walker over its
    # ProseMirror doc — `editor.state.doc.textBetween(...)` won't match.
    #
    # Rules (applied identically on server and client):
    #   - blocks (h1-h6, p, blockquote, pre, form, div, section, …): wrapped in
    #     `\n\n` separators; trim inner content
    #   - lists: each item on its own line joined by `\n`, list wrapped in `\n\n`
    #   - tables: each row is cells joined by ` `, rows joined by `\n`
    #   - images: empty string (the ProseMirror Image node is a leaf with no
    #     text content; alt text is metadata, not visible plaintext)
    #   - inline (a, span, b, strong, i, em, u, s, code, …): just children text
    #   - br: `\n`; hr: `\n\n`
    #   - script/style/iframe/video/audio: dropped

    _PLAIN_BLOCK_TAGS = {
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "blockquote", "pre", "form", "fieldset",
        "div", "section", "article", "main",
        "figure", "figcaption", "address",
    }

    def _to_plaintext(self) -> str:
        root = self.soup.body if self.soup.body else self.soup
        raw = self._plaintext_node(root)
        return self._normalize_plaintext(raw)

    def _plaintext_node(self, node) -> str:
        if isinstance(node, NavigableString):
            return self._clean_text(str(node))
        if not isinstance(node, Tag):
            return ""
        if self._is_hidden(node):
            return ""
        if self.content_only and self._is_noise(node):
            return ""

        tag = node.name

        if tag in REMOVE_TAGS:
            return ""

        if tag == "br":
            return "\n"

        if tag == "hr":
            return "\n\n"

        if tag == "img":
            # Images are leaf nodes in ProseMirror; their alt text is not
            # rendered in the visible plaintext flow. Drop here so the client
            # walker (which sees the Image node, not the alt) matches.
            return ""

        if tag in {"a", "span", "b", "strong", "i", "em", "u", "s", "code", "small", "sub", "sup", "mark", "label"}:
            return self._plaintext_children(node)

        if tag in {"input", "button", "select", "textarea"}:
            return ""

        if tag in {"ul", "ol"}:
            items: List[str] = []
            for li in node.find_all("li", recursive=False):
                text = self._plaintext_children(li).strip()
                if text:
                    items.append(text)
            if items:
                return "\n\n" + "\n".join(items) + "\n\n"
            return ""

        if tag == "li":
            return self._plaintext_children(node)

        if tag == "table":
            if self._is_layout_table(node):
                return self._plaintext_children(node)
            rows: List[str] = []
            for tr in node.find_all("tr"):
                cells: List[str] = []
                for cell in tr.find_all(["td", "th"]):
                    txt = self._plaintext_children(cell).strip()
                    if txt:
                        cells.append(txt)
                if cells:
                    rows.append(" ".join(cells))
            if rows:
                return "\n\n" + "\n".join(rows) + "\n\n"
            return ""

        if tag in self._PLAIN_BLOCK_TAGS:
            children = self._plaintext_children(node).strip()
            if children:
                return f"\n\n{children}\n\n"
            return ""

        return self._plaintext_children(node)

    def _plaintext_children(self, node: Tag) -> str:
        return "".join(self._plaintext_node(child) for child in node.children)

    @staticmethod
    def _normalize_plaintext(text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = _ws.sub(" ", text)
        # Collapse 3+ newlines to 2 (paragraph break)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Strip per-line trailing/leading whitespace introduced by collapsing
        text = "\n".join(line.strip() for line in text.split("\n"))
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ── Highlight locator ──────────────────────────────────
    #
    # Given canonical plaintext and a highlight payload (textContent +
    # optional prefix/suffix from the extension's DOM capture), find the best
    # (text_start, text_end) in plaintext.
    #
    # Cross-block highlights are tricky: the extension's `range.toString()`
    # may collapse newlines into spaces, but plaintext keeps `\n\n` between
    # blocks. We work around this by building a normalized search string
    # (whitespace collapsed) plus an index map back to original plaintext
    # offsets. The locator searches in the normalized string; persisted
    # offsets are in the original plaintext.

    _MIN_AUTO_LOCATE_LEN = 4       # below this, require prefix/suffix match
    _MAX_OCCURRENCES = 500          # cap to bound pathological searches

    @staticmethod
    def _normalize_anchor_text(text: str) -> str:
        text = text.replace("​", "").replace("﻿", "").replace("\xa0", " ")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = _ws.sub(" ", text)
        text = " ".join(text.split())
        return text

    @staticmethod
    def _normalize_with_index_map(plaintext: str) -> Tuple[str, List[int]]:
        """Build a whitespace-collapsed version of plaintext alongside a list
        mapping each character in the normalized string back to its original
        position in plaintext. Trailing position appended so callers can map
        an end-exclusive offset.
        """
        out: List[str] = []
        index_map: List[int] = []
        prev_was_ws = True  # treat start as preceded by whitespace (skip leading)
        i = 0
        n = len(plaintext)
        while i < n:
            ch = plaintext[i]
            if ch in (" ", "\t", "\n", "\r"):
                if not prev_was_ws and out:
                    out.append(" ")
                    index_map.append(i)
                prev_was_ws = True
                i += 1
                continue
            if ch == "\xa0":
                # Non-breaking space behaves like a space in normalization
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
        # Append trailing index so an end-exclusive offset has a mapping
        index_map.append(n)
        normalized = "".join(out)
        # Trim trailing space (and its index entry) if present
        if normalized.endswith(" "):
            normalized = normalized[:-1]
            # remove the trailing-space's index entry, keep the trailing-end
            index_map = index_map[:-2] + index_map[-1:]
        return normalized, index_map

    @staticmethod
    def _all_occurrences(haystack: str, needle: str, cap: int) -> List[int]:
        if not needle:
            return []
        occurrences: List[int] = []
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
        prefix: Optional[str], suffix: Optional[str],
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
        cls, plaintext: str, anchor_payload: Dict,
    ) -> Optional[TextAnchor]:
        text_content = anchor_payload.get("textContent") or ""
        prefix = anchor_payload.get("prefix")
        suffix = anchor_payload.get("suffix")

        normalized_needle = cls._normalize_anchor_text(text_content)
        if not normalized_needle:
            return None

        normalized_haystack, index_map = cls._normalize_with_index_map(plaintext)

        occurrences = cls._all_occurrences(
            normalized_haystack, normalized_needle, cap=cls._MAX_OCCURRENCES,
        )
        if not occurrences:
            return None

        if len(occurrences) == 1:
            chosen = occurrences[0]
        else:
            scored = [
                (cls._score_context(
                    normalized_haystack, occ, len(normalized_needle), prefix, suffix,
                ), occ)
                for occ in occurrences
            ]
            best_score, chosen = max(scored, key=lambda t: t[0])

            # For short matches without strong context, leave unlocated rather
            # than guess. False positives on common phrases are worse than
            # falling back to runtime text search at render time.
            if (
                len(normalized_needle) < cls._MIN_AUTO_LOCATE_LEN
                and best_score == 0
            ):
                return None

        # Map back from normalized offsets to original plaintext offsets.
        text_start = index_map[chosen] if chosen < len(index_map) else chosen
        end_norm_idx = chosen + len(normalized_needle)
        text_end = index_map[end_norm_idx] if end_norm_idx < len(index_map) else len(plaintext)

        return TextAnchor(
            text_start=text_start,
            text_end=text_end,
            text_content=plaintext[text_start:text_end],
            prefix=prefix,
            suffix=suffix,
        )

    @classmethod
    def map_highlights(
        cls, plaintext: str, highlights: List[Dict],
    ) -> List[MappedHighlight]:
        """Map each highlight payload to a plaintext-relative anchor.
        Highlights that fail to locate are returned with `text_anchor=None`."""
        results: List[MappedHighlight] = []
        for h in highlights or []:
            if not isinstance(h, dict):
                continue
            anchor_data = h.get("anchor") or {}
            text_anchor = cls._locate_highlight(plaintext, anchor_data) if anchor_data else None
            results.append(MappedHighlight(payload=h, text_anchor=text_anchor))
        return results

    def parse(self, highlights: Optional[List[Dict]] = None) -> ParseResult:
        self.images = []
        self.forms = FormExtractor()
        self._segments = []
        self._block_nodes = {}
        self._suppress_tracking = False
        root = self.soup.body if self.soup.body else self.soup
        raw = self._process_node(root)
        content = self._normalize_output(raw)
        elements = self._build_elements(content)
        self._stamp_dom(elements)
        self._rewrite_dom_urls()

        plaintext = self._to_plaintext()
        mapped = self.map_highlights(plaintext, highlights or [])

        return ParseResult(
            content=content,
            images=self.images,
            form_elements=self.forms.elements,
            url=self.url,
            elements=elements,
            plaintext=plaintext,
            highlights=mapped,
        )

    def markdown(self) -> str:
        return self.parse().content
