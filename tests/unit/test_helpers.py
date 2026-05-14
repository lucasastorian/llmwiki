"""Unit tests for route helpers and utilities."""

from services.types import parse_frontmatter
from services.hosted import _slugify


class TestFrontmatterParsing:

    def test_valid_frontmatter(self):
        content = "---\ntitle: My Doc\ntags:\n  - research\n---\nBody text here."
        meta = parse_frontmatter(content)
        assert meta["title"] == "My Doc"
        assert meta["tags"] == ["research"]

    def test_no_frontmatter(self):
        content = "Just plain text."
        meta = parse_frontmatter(content)
        assert meta == {}

    def test_invalid_yaml_returns_empty(self):
        content = "---\n: invalid: yaml: [[\n---\nBody."
        meta = parse_frontmatter(content)
        assert meta == {}

    def test_non_dict_yaml_returns_empty(self):
        content = "---\n- just a list\n---\nBody."
        meta = parse_frontmatter(content)
        assert meta == {}


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
