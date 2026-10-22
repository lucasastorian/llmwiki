"""Per-page markdown extraction via opendataloader-pdf."""

import sys
from collections import defaultdict

from converter import process_group
from converter.bounds import bounded_utf8_size, ensure_bounded_json, read_bounded_json
from converter.config import OPENDATALOADER_ENGINE, ConverterConfig
from converter.markdown_renderer import MarkdownRenderer

# A child process group, not an in-process call, so a timeout can kill the JVM instead of orphaning it.
_WORKER_SCRIPT = (
    "import sys, opendataloader_pdf\n"
    "opendataloader_pdf.convert(input_path=sys.argv[1], output_dir=sys.argv[2], format='json', quiet=True)\n"
)


class OpendataloaderEngine:
    name = OPENDATALOADER_ENGINE

    def __init__(self, config: ConverterConfig, renderer: MarkdownRenderer) -> None:
        self._config = config
        self._renderer = renderer

    def extract_pages(self, pdf_path: str, output_dir: str) -> list[dict]:
        process_group.run_in_process_group(
            [sys.executable, "-c", _WORKER_SCRIPT, pdf_path, output_dir],
            timeout=self._config.extract_timeout_seconds,
            what=self.name,
        )
        data = read_bounded_json(output_dir, self.name, self._config.max_extraction_json_bytes)
        pages = self._assemble_pages(data)
        ensure_bounded_json(pages, self._config.max_extraction_response_bytes, "extraction response")
        return pages

    def _assemble_pages(self, data: dict) -> list[dict]:
        total_pages = self._clamped_page_count(data)
        elements = data.get("kids", [])
        if not isinstance(elements, list):
            raise RuntimeError("opendataloader kids must be a list")
        if len(elements) > self._config.max_extraction_elements:
            raise RuntimeError("opendataloader produced too many elements")

        page_parts: dict[int, list[str]] = defaultdict(list)
        total_text_bytes = 0
        for el in elements:
            if not isinstance(el, dict):
                raise RuntimeError("opendataloader elements must be objects")
            page_num = el.get("page number")
            if el.get("type") in ("header", "footer"):
                continue
            if type(page_num) is not int or not 1 <= page_num <= total_pages:
                continue
            md = self._renderer.render(el)
            if not md:
                continue
            separator_bytes = 2 if page_parts[page_num] else 0
            remaining = self._config.max_extracted_text_bytes - total_text_bytes - separator_bytes
            md_bytes = bounded_utf8_size(md, remaining, "total extracted text")
            total_text_bytes += separator_bytes + md_bytes
            page_parts[page_num].append(md)

        return [
            {"page": page_num, "content": "\n\n".join(page_parts[page_num])}
            for page_num in range(1, total_pages + 1)
        ]

    def _clamped_page_count(self, data: dict) -> int:
        """`number of pages` comes from the untrusted PDF; a crafted count must not drive an unbounded loop."""
        total_pages = data.get("number of pages", 0)
        if type(total_pages) is not int or total_pages < 0:
            total_pages = 0
        return min(total_pages, self._config.max_pages)
