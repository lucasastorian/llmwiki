"""Unit tests for the PDF extraction module (opendataloader-pdf integration)."""

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

    def test_image_with_source(self):
        el = {"type": "image", "source": "images/fig1.png"}
        assert _element_to_markdown(el) == "![image](images/fig1.png)"

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


class TestElementsToPages:

    def test_groups_by_page_number(self):
        elements = [
            {"type": "heading", "heading level": 1, "content": "Title", "page number": 1},
            {"type": "paragraph", "content": "Body.", "page number": 1},
            {"type": "heading", "heading level": 2, "content": "Ch 2", "page number": 2},
        ]
        pages = _elements_to_pages(elements, total_pages=2)
        assert len(pages) == 2
        assert pages[0] == (1, "# Title\n\nBody.")
        assert pages[1] == (2, "## Ch 2")

    def test_blank_pages_get_empty_string(self):
        elements = [
            {"type": "paragraph", "content": "Page 1", "page number": 1},
            {"type": "paragraph", "content": "Page 3", "page number": 3},
        ]
        pages = _elements_to_pages(elements, total_pages=3)
        assert len(pages) == 3
        assert pages[0] == (1, "Page 1")
        assert pages[1] == (2, "")
        assert pages[2] == (3, "Page 3")

    def test_headers_and_footers_excluded(self):
        elements = [
            {"type": "header", "page number": 1, "kids": []},
            {"type": "paragraph", "content": "Real content", "page number": 1},
            {"type": "footer", "page number": 1, "kids": []},
        ]
        pages = _elements_to_pages(elements, total_pages=1)
        assert pages == [(1, "Real content")]

    def test_zero_total_pages(self):
        pages = _elements_to_pages([], total_pages=0)
        assert pages == []

    def test_elements_without_page_number_skipped(self):
        elements = [
            {"type": "paragraph", "content": "No page"},
            {"type": "paragraph", "content": "Has page", "page number": 1},
        ]
        pages = _elements_to_pages(elements, total_pages=1)
        assert pages == [(1, "Has page")]

    def test_page_count_matches_total_pages_not_element_count(self):
        elements = [
            {"type": "paragraph", "content": "Only page 1", "page number": 1},
        ]
        pages = _elements_to_pages(elements, total_pages=5)
        assert len(pages) == 5
        assert pages[0][1] == "Only page 1"
        assert all(pages[i][1] == "" for i in range(1, 5))
