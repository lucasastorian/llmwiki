"""PDF extraction via opendataloader-pdf.

Shared module used by both the hosted OCR service and the local processor.
No server-specific dependencies (no asyncpg, S3, httpx).
"""

import json
import tempfile
from collections import defaultdict
from pathlib import Path

import opendataloader_pdf


def _element_to_markdown(el: dict) -> str:
    """Convert a single JSON element to markdown."""
    t = el.get("type", "")
    content = el.get("content", "")

    if t == "heading":
        level = max(1, min(el.get("heading level", 1), 6))
        prefix = "#" * level
        return f"{prefix} {content}"

    if t == "paragraph":
        return content

    if t == "list":
        lines = []
        for item in el.get("list items", []):
            lines.append(f"- {item.get('content', '')}")
            for child in item.get("kids", []):
                lines.append(f"  - {child.get('content', '')}")
        return "\n".join(lines)

    if t == "image":
        src = el.get("source", "")
        return f"![image]({src})" if src else ""

    if t == "caption":
        return f"*{content}*" if content else ""

    # Skip headers, footers, and unknown types
    return ""


def _elements_to_pages(elements: list[dict], total_pages: int) -> list[tuple[int, str]]:
    """Group JSON elements by page number and reconstruct markdown per page.

    Returns a list of (page_num, markdown) for every page up to total_pages,
    using empty string for pages with no extractable content.
    """
    page_elements: dict[int, list[dict]] = defaultdict(list)

    for el in elements:
        page_num = el.get("page number")
        if page_num is None or el.get("type") in ("header", "footer"):
            continue
        page_elements[page_num].append(el)

    pages = []
    for page_num in range(1, total_pages + 1):
        parts = []
        for el in page_elements.get(page_num, []):
            md = _element_to_markdown(el)
            if md:
                parts.append(md)
        pages.append((page_num, "\n\n".join(parts)))

    return pages


def extract_pdf(pdf_path: str) -> list[tuple[int, str]]:
    """Run opendataloader-pdf and return per-page markdown from structured JSON output.

    Raises RuntimeError if extraction fails (Java missing, corrupt PDF, etc.).
    """
    try:
        with tempfile.TemporaryDirectory() as extract_dir:
            opendataloader_pdf.convert(
                input_path=pdf_path,
                output_dir=extract_dir,
                format="json",
                quiet=True,
            )

            json_files = list(Path(extract_dir).glob("*.json"))
            if not json_files:
                raise RuntimeError("opendataloader-pdf produced no output")

            with open(json_files[0], encoding="utf-8") as f:
                data = json.load(f)

        total_pages = data.get("number of pages", 0)
        elements = data.get("kids", [])
        return _elements_to_pages(elements, total_pages)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"PDF extraction failed: {e}") from e
