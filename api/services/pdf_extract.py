"""PDF extraction via opendataloader-pdf, kept free of server dependencies (asyncpg, S3, httpx)."""

import base64
import json
import os
import signal
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

EXTRACT_TIMEOUT_SECONDS = 180
MAX_EXTRACT_JSON_BYTES = 64 * 1024 * 1024
MAX_EXTRACT_PAGES = 10_000
MAX_EXTRACT_ELEMENTS = 100_000
# Text blocks and table cells nest arbitrarily deep in the extractor output.
MAX_ELEMENT_DEPTH = 16

_EXTRACT_SCRIPT = (
    "import sys, opendataloader_pdf\n"
    "opendataloader_pdf.convert("
    "input_path=sys.argv[1], output_dir=sys.argv[2], format='json', "
    "image_output='embedded', quiet=True)\n"
)


def _inline_text(el: dict, depth: int = 0) -> str:
    """Flatten an element and its descendants into single-line text."""
    if depth > MAX_ELEMENT_DEPTH:
        return ""
    parts = []
    content = el.get("content")
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    for kid in el.get("kids", []):
        if not isinstance(kid, dict):
            continue
        nested = _inline_text(kid, depth + 1)
        if nested:
            parts.append(nested)
    return " ".join(parts)


def _escape_cell(text: str) -> str:
    """Make text safe to place inside a markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _table_to_markdown(el: dict) -> str:
    """Render a table element as a markdown table, treating row one as the header."""
    grid = []
    for row in el.get("rows", []):
        if not isinstance(row, dict):
            continue
        cells = [
            _escape_cell(_inline_text(cell))
            for cell in row.get("cells", [])
            if isinstance(cell, dict)
        ]
        if cells:
            grid.append(cells)

    if not any(any(cell for cell in row) for row in grid):
        return ""

    width = max(len(row) for row in grid)
    padded = [row + [""] * (width - len(row)) for row in grid]
    header, body = padded[0], padded[1:]

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _text_block_to_markdown(el: dict, depth: int) -> str:
    """Render a text block container by rendering each nested block."""
    if depth > MAX_ELEMENT_DEPTH:
        return ""
    parts = []
    for kid in el.get("kids", []):
        if not isinstance(kid, dict):
            continue
        md = _element_to_markdown(kid, depth + 1)
        if md:
            parts.append(md)
    return "\n\n".join(parts)


def _element_to_markdown(el: dict, depth: int = 0) -> str:
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

    if t == "table":
        return _table_to_markdown(el)

    if t == "text block":
        return _text_block_to_markdown(el, depth)

    if t == "image":
        # Images are stored separately, never inlined as data URIs.
        return ""

    if t == "caption":
        return f"*{content}*" if content else ""

    # Skip headers, footers, and unknown types
    return ""


def _parse_data_uri(data_uri: str) -> tuple[bytes, str] | None:
    """Parse a data URI into (bytes, format). Returns None on failure."""
    if not data_uri.startswith("data:"):
        return None
    try:
        header, b64 = data_uri.split(",", 1)
        fmt = "png"
        if "jpeg" in header or "jpg" in header:
            fmt = "jpeg"
        return base64.b64decode(b64), fmt
    except ValueError:
        return None


def _elements_to_pages(
    elements: list[dict], total_pages: int,
) -> list[tuple[int, str, list[dict]]]:
    """Rebuild (page_num, markdown, images) for every page up to total_pages."""
    if not isinstance(total_pages, int) or total_pages < 0:
        total_pages = 0
    total_pages = min(total_pages, MAX_EXTRACT_PAGES)
    if len(elements) > MAX_EXTRACT_ELEMENTS:
        raise RuntimeError(
            f"PDF extraction produced too many elements ({len(elements):,})"
        )

    page_elements: dict[int, list[dict]] = defaultdict(list)

    for el in elements:
        page_num = el.get("page number")
        if page_num is None or el.get("type") in ("header", "footer"):
            continue
        page_elements[page_num].append(el)

    pages = []
    img_counter = 0
    for page_num in range(1, total_pages + 1):
        parts = []
        images = []
        for el in page_elements.get(page_num, []):
            if el.get("type") == "image":
                src = el.get("source", "")
                parsed = _parse_data_uri(src) if src else None
                if parsed:
                    img_bytes, fmt = parsed
                    img_id = f"img_{page_num}_{img_counter}.{fmt}"
                    img_counter += 1
                    images.append({"id": img_id, "bytes": img_bytes, "format": fmt})
                continue
            md = _element_to_markdown(el)
            if md:
                parts.append(md)
        pages.append((page_num, "\n\n".join(parts), images))

    return pages


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Terminate the extractor and the JVM/processes it spawned."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:  # pragma: no cover - exercised on Windows installations
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if proc.poll() is None:
                proc.kill()
    except ProcessLookupError:
        pass
    finally:
        proc.wait()


def _run_extractor(pdf_path: str, output_dir: str) -> None:
    """Run opendataloader in a bounded child process group."""
    popen_options: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
    }
    if os.name == "posix":
        popen_options["start_new_session"] = True
    elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):  # pragma: no cover - Windows
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        [sys.executable, "-c", _EXTRACT_SCRIPT, pdf_path, output_dir],
        **popen_options,
    )
    try:
        _, stderr = proc.communicate(timeout=EXTRACT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        _kill_process_tree(proc)
        raise TimeoutError(
            f"PDF extraction timed out after {EXTRACT_TIMEOUT_SECONDS} seconds"
        ) from error

    if proc.returncode != 0:
        detail = (stderr or b"").decode(errors="replace")[:500]
        raise RuntimeError(f"opendataloader-pdf failed: {detail}")


def extract_pdf(pdf_path: str) -> list[tuple[int, str, list[dict]]]:
    """Return per-page (page_num, markdown, images); raises RuntimeError if extraction fails."""
    try:
        with tempfile.TemporaryDirectory() as extract_dir:
            _run_extractor(pdf_path, extract_dir)

            json_files = list(Path(extract_dir).glob("*.json"))
            if not json_files:
                raise RuntimeError("opendataloader-pdf produced no output")

            json_path = json_files[0]
            json_size = json_path.stat().st_size
            if json_size > MAX_EXTRACT_JSON_BYTES:
                raise RuntimeError(
                    "PDF extraction output exceeds the "
                    f"{MAX_EXTRACT_JSON_BYTES // (1024 * 1024)} MiB limit"
                )

            with json_path.open(encoding="utf-8") as f:
                data = json.load(f)

        if not isinstance(data, dict):
            raise RuntimeError("opendataloader-pdf returned invalid JSON")
        total_pages = data.get("number of pages", 0)
        elements = data.get("kids", [])
        if not isinstance(elements, list) or not all(isinstance(el, dict) for el in elements):
            raise RuntimeError("opendataloader-pdf returned invalid elements")
        return _elements_to_pages(elements, total_pages)
    except (RuntimeError, TimeoutError):
        raise
    except Exception as e:
        raise RuntimeError(f"PDF extraction failed: {e}") from e
