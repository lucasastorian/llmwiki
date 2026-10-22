import subprocess

import pytest
import services.pdf_extract as pdf_extract
from services.extracted_assets import build_pdf_image_assets
from services.pdf_extract import _element_to_markdown, _elements_to_pages, extract_pdf


class TestElementToMarkdown:

    def test_heading_h1(self):
        el = {"type": "heading", "heading level": 1, "content": "Title"}
        assert _element_to_markdown(el) == "# Title"

    def test_heading_h2(self):
        el = {"type": "heading", "heading level": 2, "content": "Introduction"}
        assert _element_to_markdown(el) == "## Introduction"

    def test_heading_level_capped_at_6(self):
        el = {"type": "heading", "heading level": 9, "content": "Deep"}
        assert _element_to_markdown(el) == "###### Deep"

    def test_heading_level_zero_floors_to_1(self):
        el = {"type": "heading", "heading level": 0, "content": "Zero"}
        assert _element_to_markdown(el) == "# Zero"

    def test_heading_level_negative_floors_to_1(self):
        el = {"type": "heading", "heading level": -3, "content": "Neg"}
        assert _element_to_markdown(el) == "# Neg"

    def test_heading_defaults_to_h1_when_missing(self):
        el = {"type": "heading", "content": "No Level"}
        assert _element_to_markdown(el) == "# No Level"

    def test_paragraph(self):
        el = {"type": "paragraph", "content": "Some text here."}
        assert _element_to_markdown(el) == "Some text here."

    def test_paragraph_empty(self):
        el = {"type": "paragraph", "content": ""}
        assert _element_to_markdown(el) == ""

    def test_list_with_items(self):
        el = {
            "type": "list",
            "list items": [
                {"content": "First", "kids": []},
                {"content": "Second", "kids": [{"content": "Nested"}]},
            ],
        }
        result = _element_to_markdown(el)
        lines = result.split("\n")
        assert lines[0] == "- First"
        assert lines[1] == "- Second"
        assert lines[2] == "  - Nested"

    def test_list_empty(self):
        el = {"type": "list", "list items": []}
        assert _element_to_markdown(el) == ""

    def test_image_skipped(self):
        el = {"type": "image", "source": "images/fig1.png"}
        assert _element_to_markdown(el) == ""

    def test_image_no_source(self):
        el = {"type": "image"}
        assert _element_to_markdown(el) == ""

    def test_caption(self):
        el = {"type": "caption", "content": "Figure 1: Overview"}
        assert _element_to_markdown(el) == "*Figure 1: Overview*"

    def test_caption_empty(self):
        el = {"type": "caption", "content": ""}
        assert _element_to_markdown(el) == ""

    def test_header_skipped(self):
        assert _element_to_markdown({"type": "header", "kids": []}) == ""

    def test_footer_skipped(self):
        assert _element_to_markdown({"type": "footer", "kids": []}) == ""

    def test_unknown_type_skipped(self):
        assert _element_to_markdown({"type": "annotation", "content": "x"}) == ""


def _cell(text: str) -> dict:
    return {"type": "table cell", "kids": [{"type": "paragraph", "content": text}]}


def _row(*texts: str) -> dict:
    return {"type": "table row", "cells": [_cell(t) for t in texts]}


class TestTableToMarkdown:

    def test_table_renders_as_markdown_table(self):
        el = {"type": "table", "rows": [_row("Quarter", "Revenue"), _row("Q1", "1,200")]}
        assert _element_to_markdown(el) == (
            "| Quarter | Revenue |\n"
            "| --- | --- |\n"
            "| Q1 | 1,200 |"
        )

    def test_table_with_only_empty_cells_is_skipped(self):
        el = {"type": "table", "rows": [_row("", ""), _row("", "")]}
        assert _element_to_markdown(el) == ""

    def test_table_with_no_rows_is_skipped(self):
        assert _element_to_markdown({"type": "table", "rows": []}) == ""

    def test_ragged_rows_are_padded_to_widest(self):
        el = {"type": "table", "rows": [_row("a"), _row("b", "c")]}
        assert _element_to_markdown(el) == (
            "| a |  |\n"
            "| --- | --- |\n"
            "| b | c |"
        )

    def test_pipes_in_cells_are_escaped(self):
        el = {"type": "table", "rows": [_row("a|b"), _row("c")]}
        assert "a\\|b" in _element_to_markdown(el)

    def test_cell_joins_multiple_nested_blocks(self):
        cell = {
            "type": "table cell",
            "kids": [
                {"type": "paragraph", "content": "Total"},
                {"type": "paragraph", "content": "2021"},
            ],
        }
        el = {"type": "table", "rows": [{"type": "table row", "cells": [cell]}]}
        assert _element_to_markdown(el).splitlines()[0] == "| Total 2021 |"


class TestTextBlockToMarkdown:

    def test_text_block_renders_nested_blocks(self):
        el = {
            "type": "text block",
            "kids": [
                {"type": "heading", "heading level": 2, "content": "Part 1"},
                {"type": "paragraph", "content": "Body text."},
            ],
        }
        assert _element_to_markdown(el) == "## Part 1\n\nBody text."

    def test_nested_text_blocks_are_flattened(self):
        el = {
            "type": "text block",
            "kids": [{
                "type": "text block",
                "kids": [{"type": "paragraph", "content": "Deep"}],
            }],
        }
        assert _element_to_markdown(el) == "Deep"

    def test_empty_text_block(self):
        assert _element_to_markdown({"type": "text block", "kids": []}) == ""

    def test_recursion_is_depth_bounded(self):
        el: dict = {"type": "paragraph", "content": "bottom"}
        for _ in range(pdf_extract.MAX_ELEMENT_DEPTH + 5):
            el = {"type": "text block", "kids": [el]}
        assert _element_to_markdown(el) == ""


class TestTablesAndTextBlocksReachPages:

    def test_table_content_is_stored_on_its_page(self):
        elements = [
            {"type": "table", "page number": 1, "rows": [_row("H"), _row("v")]},
        ]
        pages = _elements_to_pages(elements, total_pages=1)
        assert pages[0][1] == "| H |\n| --- |\n| v |"

    def test_text_block_content_is_stored_on_its_page(self):
        elements = [
            {
                "type": "text block",
                "page number": 1,
                "kids": [{"type": "paragraph", "content": "Recovered"}],
            },
        ]
        pages = _elements_to_pages(elements, total_pages=1)
        assert pages[0][1] == "Recovered"


class TestElementsToPages:

    def test_groups_by_page_number(self):
        elements = [
            {"type": "heading", "heading level": 1, "content": "Title", "page number": 1},
            {"type": "paragraph", "content": "Body.", "page number": 1},
            {"type": "heading", "heading level": 2, "content": "Ch 2", "page number": 2},
        ]
        pages = _elements_to_pages(elements, total_pages=2)
        assert len(pages) == 2
        assert pages[0][0] == 1
        assert pages[0][1] == "# Title\n\nBody."
        assert pages[1][0] == 2
        assert pages[1][1] == "## Ch 2"

    def test_blank_pages_get_empty_string(self):
        elements = [
            {"type": "paragraph", "content": "Page 1", "page number": 1},
            {"type": "paragraph", "content": "Page 3", "page number": 3},
        ]
        pages = _elements_to_pages(elements, total_pages=3)
        assert len(pages) == 3
        assert pages[0][0] == 1
        assert pages[0][1] == "Page 1"
        assert pages[1][0] == 2
        assert pages[1][1] == ""
        assert pages[2][0] == 3
        assert pages[2][1] == "Page 3"

    def test_headers_and_footers_excluded(self):
        elements = [
            {"type": "header", "page number": 1, "kids": []},
            {"type": "paragraph", "content": "Real content", "page number": 1},
            {"type": "footer", "page number": 1, "kids": []},
        ]
        pages = _elements_to_pages(elements, total_pages=1)
        assert len(pages) == 1
        assert pages[0][0] == 1
        assert pages[0][1] == "Real content"

    def test_zero_total_pages(self):
        pages = _elements_to_pages([], total_pages=0)
        assert pages == []

    def test_elements_without_page_number_skipped(self):
        elements = [
            {"type": "paragraph", "content": "No page"},
            {"type": "paragraph", "content": "Has page", "page number": 1},
        ]
        pages = _elements_to_pages(elements, total_pages=1)
        assert len(pages) == 1
        assert pages[0][1] == "Has page"

    def test_page_count_matches_total_pages_not_element_count(self):
        elements = [
            {"type": "paragraph", "content": "Only page 1", "page number": 1},
        ]
        pages = _elements_to_pages(elements, total_pages=5)
        assert len(pages) == 5
        assert pages[0][0] == 1
        assert pages[0][1] == "Only page 1"
        assert all(pages[i][1] == "" for i in range(1, 5))


def test_build_pdf_image_assets_uses_hidden_relative_asset_paths():
    pages = [
        (1, "Page one", [{"id": "img_1_0.png", "bytes": b"png", "format": "png"}]),
        (2, "Page two", [{"id": "img_2_0.jpeg", "bytes": b"jpg", "format": "jpeg"}]),
    ]

    assets, page_elements = build_pdf_image_assets(
        "doc-a",
        "Quarterly Report.pdf",
        "/sources/",
        pages,
    )

    assert [asset.filename for asset in assets] == [
        "page-001-image-01.png",
        "page-002-image-01.jpg",
    ]
    assert assets[0].path == "/sources/quarterly-report.assets/"
    assert assets[0].src == "quarterly-report.assets/page-001-image-01.png"
    assert assets[0].metadata()["hidden"] is True
    assert assets[0].metadata()["kind"] == "pdf_image"
    assert page_elements[1]["images"][0]["src"] == "./quarterly-report.assets/page-001-image-01.png"


def test_extractor_timeout_kills_process_group(monkeypatch, tmp_path):
    killed: list[tuple[int, int]] = []

    class StalledProcess:
        pid = 4312
        returncode = None

        def communicate(self, timeout):
            raise subprocess.TimeoutExpired("extract", timeout)

        def poll(self):
            return self.returncode

        def wait(self):
            self.returncode = -9
            return self.returncode

    process = StalledProcess()
    monkeypatch.setattr(pdf_extract.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(pdf_extract.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        pdf_extract.os,
        "killpg",
        lambda process_group, sig: killed.append((process_group, sig)),
    )
    monkeypatch.setattr(pdf_extract, "EXTRACT_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(TimeoutError, match="timed out"):
        pdf_extract._run_extractor(str(tmp_path / "source.pdf"), str(tmp_path))

    assert killed == [(process.pid, pdf_extract.signal.SIGKILL)]
    assert process.returncode == -9


def test_extract_pdf_rejects_oversized_json_before_loading(monkeypatch, tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4")

    def write_large_output(_source: str, output_dir: str) -> None:
        (pdf_extract.Path(output_dir) / "result.json").write_bytes(b"x" * 32)

    monkeypatch.setattr(pdf_extract, "_run_extractor", write_large_output)
    monkeypatch.setattr(pdf_extract, "MAX_EXTRACT_JSON_BYTES", 16)

    with pytest.raises(RuntimeError, match="output exceeds"):
        extract_pdf(str(source))


def test_elements_to_pages_rejects_unbounded_element_count(monkeypatch):
    monkeypatch.setattr(pdf_extract, "MAX_EXTRACT_ELEMENTS", 2)
    elements = [
        {"type": "paragraph", "page number": 1, "content": str(index)}
        for index in range(3)
    ]

    with pytest.raises(RuntimeError, match="too many elements"):
        _elements_to_pages(elements, total_pages=1)
