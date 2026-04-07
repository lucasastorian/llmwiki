"""Unit tests for route helpers and utilities."""

from routes.documents import parse_frontmatter
from routes.knowledge_bases import _slugify


class TestFrontmatterParsing:

    def test_valid_frontmatter(self):
        content = "---\ntitle: My Doc\ntags:\n  - research\n---\nBody text here."
        meta, body = parse_frontmatter(content)
        assert meta["title"] == "My Doc"
        assert meta["tags"] == ["research"]
        assert body == "Body text here."

    def test_no_frontmatter(self):
        content = "Just plain text."
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_invalid_yaml_returns_empty(self):
        content = "---\n: invalid: yaml: [[\n---\nBody."
        meta, body = parse_frontmatter(content)
        assert meta == {}

    def test_non_dict_yaml_returns_empty(self):
        content = "---\n- just a list\n---\nBody."
        meta, body = parse_frontmatter(content)
        assert meta == {}
        assert body == content


class TestSlugify:

    def test_basic(self):
        assert _slugify("My Knowledge Base") == "my-knowledge-base"

    def test_special_characters_stripped(self):
        assert _slugify("Hello, World! (2024)") == "hello-world-2024"

    def test_empty_returns_kb(self):
        assert _slugify("!!!") == "kb"

    def test_whitespace_trimmed(self):
        assert _slugify("  spaces  ") == "spaces"

    def test_consecutive_separators_collapsed(self):
        assert _slugify("a---b   c") == "a-b-c"
