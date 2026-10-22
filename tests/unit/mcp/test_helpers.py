"""Unit tests for MCP tool helpers and reference parsing. Pure functions, no DB."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp"))


class TestDeepLink:

    def test_builds_url_with_path(self):
        from tools.helpers import deep_link
        url = deep_link("my-kb", "/wiki/concepts/", "scaling.md")
        assert url.endswith("/wikis/my-kb/wiki/concepts/scaling.md")

    def test_root_path(self):
        from tools.helpers import deep_link
        url = deep_link("kb", "/", "notes.md")
        assert url.endswith("/wikis/kb/notes.md")


class TestGlobMatch:

    def test_star_matches_extension(self):
        from tools.helpers import glob_match
        assert glob_match("/wiki/page.md", "/wiki/*.md")

    def test_double_star_matches_nested(self):
        from tools.helpers import glob_match
        assert glob_match("/wiki/concepts/scaling.md", "/wiki/**")

    def test_no_match(self):
        from tools.helpers import glob_match
        assert not glob_match("/notes.md", "/wiki/*")


class TestResolvePath:

    def test_root_file(self):
        from tools.helpers import resolve_path
        assert resolve_path("notes.md") == ("/", "notes.md")

    def test_nested_file(self):
        from tools.helpers import resolve_path
        assert resolve_path("wiki/concepts/scaling.md") == ("/wiki/concepts/", "scaling.md")

    def test_leading_slash(self):
        from tools.helpers import resolve_path
        assert resolve_path("/wiki/page.md") == ("/wiki/", "page.md")


class TestParsePageRange:

    def test_single_page(self):
        from tools.helpers import parse_page_range
        assert parse_page_range("3", 10) == [3]

    def test_range(self):
        from tools.helpers import parse_page_range
        assert parse_page_range("2-5", 10) == [2, 3, 4, 5]

    def test_clamps_to_max(self):
        from tools.helpers import parse_page_range
        assert parse_page_range("1-100", 5) == [1, 2, 3, 4, 5]

    def test_deduplicates_and_sorts(self):
        from tools.helpers import parse_page_range
        assert parse_page_range("3,1,3,2", 10) == [1, 2, 3]

    def test_ignores_invalid(self):
        from tools.helpers import parse_page_range
        assert parse_page_range("abc,2,xyz", 10) == [2]

    def test_malformed_range_does_not_crash(self):
        from tools.helpers import parse_page_range
        # An LLM emitting "5-" (page 5 onward) or "-5" (up to 5) must not raise.
        assert parse_page_range("1-", 10) == []
        assert parse_page_range("-5", 10) == []
        assert parse_page_range("1-x", 10) == []
        assert parse_page_range("2-4,9-", 10) == [2, 3, 4]

    def test_mixed(self):
        from tools.helpers import parse_page_range
        assert parse_page_range("1-3,7,5-6", 10) == [1, 2, 3, 5, 6, 7]


class TestCitationParsing:

    def test_filename_and_page(self):
        from tools.references import _parse_citation_filename
        assert _parse_citation_filename("paper.pdf, p.3") == ("paper.pdf", 3)

    def test_filename_only(self):
        from tools.references import _parse_citation_filename
        assert _parse_citation_filename("paper.pdf") == ("paper.pdf", None)

    def test_strips_markdown_link(self):
        from tools.references import _parse_citation_filename
        name, _ = _parse_citation_filename("[Paper Title](http://example.com)")
        assert name == "Paper Title"

    def test_markdown_link_keeps_page_suffix(self):
        from tools.references import _parse_citation_filename
        name, page = _parse_citation_filename("[paper.pdf](http://example.com), p.7")
        assert name == "paper.pdf"
        assert page == 7

    def test_strips_trailing_dash_text(self):
        from tools.references import _parse_citation_filename
        name, page = _parse_citation_filename("paper.pdf, p.5 — section on scaling")
        assert name == "paper.pdf"
        assert page == 5

    def test_preserves_hyphenated_version_suffix(self):
        from tools.references import _parse_citation_filename
        name, page = _parse_citation_filename("2501.12948v2-2.pdf, p.5")
        assert name == "2501.12948v2-2.pdf"
        assert page == 5

    def test_strips_em_dash(self):
        from tools.references import _parse_citation_filename
        name, _ = _parse_citation_filename("paper.pdf — some note")
        assert name == "paper.pdf"

    def test_strips_bold_markers(self):
        from tools.references import _parse_citation_filename
        name, _ = _parse_citation_filename("**paper.pdf**")
        assert name == "paper.pdf"


class TestWikiLinkParsing:

    def test_absolute_wiki_path(self):
        from tools.references import _parse_wiki_links
        links = _parse_wiki_links("[Page](/wiki/concepts/scaling.md)", "")
        assert "concepts/scaling.md" in links

    def test_relative_path(self):
        from tools.references import _parse_wiki_links
        links = _parse_wiki_links("[Page](./scaling.md)", "concepts/")
        assert "concepts/scaling.md" in links

    def test_parent_path(self):
        from tools.references import _parse_wiki_links
        links = _parse_wiki_links("[Page](../overview.md)", "concepts/deep/")
        assert "concepts/overview.md" in links

    def test_bare_filename(self):
        from tools.references import _parse_wiki_links
        links = _parse_wiki_links("[Page](scaling.md)", "concepts/")
        assert "concepts/scaling.md" in links

    def test_ignores_external_links(self):
        from tools.references import _parse_wiki_links
        links = _parse_wiki_links("[Google](https://google.com)", "")
        assert links == []

    def test_ignores_anchors(self):
        from tools.references import _parse_wiki_links
        links = _parse_wiki_links("[Section](#methods)", "")
        assert links == []

    def test_ignores_images(self):
        from tools.references import _parse_wiki_links
        links = _parse_wiki_links("![Diagram](diagram.png)", "")
        assert links == []

    def test_ignores_mailto(self):
        from tools.references import _parse_wiki_links
        links = _parse_wiki_links("[Email](mailto:test@test.com)", "")
        assert links == []

    def test_ignores_data_uri(self):
        from tools.references import _parse_wiki_links
        links = _parse_wiki_links("[Img](data:image/png;base64,abc)", "")
        assert links == []


@pytest.mark.asyncio
async def test_read_webclip_returns_asset_images_when_requested():
    from tools.read import ReadHandler

    class FakeFS:
        async def get_document(self, kb_id, filename, dir_path):
            return {
                "id": "doc-1",
                "filename": filename,
                "title": "Clip",
                "path": dir_path,
                "content": "Body ![Hero](./clip.assets/image-01.webp)",
                "tags": [],
                "version": 1,
                "file_type": "md",
                "metadata": {
                    "assets": [
                        {
                            "document_id": "asset-1",
                            "filename": "image-01.webp",
                            "content_type": "image/webp",
                            "file_type": "webp",
                            "alt": "Hero",
                        }
                    ]
                },
            }

        async def find_document_by_name(self, kb_id, name):
            return None

        async def get_document_metadata(self, kb_id, filename, dir_path):
            return await self.get_document(kb_id, filename, dir_path)

        async def find_document_metadata_by_name(self, kb_id, name):
            return None

        async def load_asset_bytes(self, asset_doc_id):
            assert asset_doc_id == "asset-1"
            return b"webp-bytes"

        async def get_backlinks(self, doc_id):
            return []

    handler = ReadHandler(FakeFS(), {"id": "kb-1", "slug": "kb"})

    result = await handler.read("clip.md", pages="", sections=None, include_images=True)

    assert isinstance(result, list)
    assert result[0].type == "text"
    assert result[1].type == "text"
    assert "Hero" in result[1].text
    assert result[2].type == "image"
    assert result[2].mimeType == "image/webp"
