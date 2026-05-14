"""Unit tests for MCP tool helpers (pure functions only, no DB).

The pure functions are copied here to avoid the mcp package namespace
collision (local mcp/ dir shadows the pip mcp package).
"""

from fnmatch import fnmatch


def resolve_path(path: str) -> tuple[str, str]:
    path_clean = path.lstrip("/")
    if "/" in path_clean:
        dir_path = "/" + path_clean.rsplit("/", 1)[0] + "/"
        filename = path_clean.rsplit("/", 1)[1]
    else:
        dir_path = "/"
        filename = path_clean
    return dir_path, filename


def glob_match(filepath: str, pattern: str) -> bool:
    return fnmatch(filepath, pattern)


def parse_page_range(pages_str: str, max_page: int) -> list[int]:
    result = set()
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            s, e = int(start.strip()), int(end.strip())
            for p in range(max(1, s), min(max_page, e) + 1):
                result.add(p)
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= max_page:
                result.add(p)
    return sorted(result)


def deep_link(base_url: str, kb_slug: str, path: str, filename: str) -> str:
    full = (path.rstrip("/") + "/" + filename).lstrip("/")
    return f"{base_url}/wikis/{kb_slug}/{full}"


class TestResolvePath:

    def test_root_file(self):
        d, f = resolve_path("notes.md")
        assert d == "/"
        assert f == "notes.md"

    def test_nested_file(self):
        d, f = resolve_path("wiki/overview.md")
        assert d == "/wiki/"
        assert f == "overview.md"

    def test_deeply_nested(self):
        d, f = resolve_path("wiki/sub/deep/file.md")
        assert d == "/wiki/sub/deep/"
        assert f == "file.md"

    def test_leading_slash_stripped(self):
        d, f = resolve_path("/wiki/overview.md")
        assert d == "/wiki/"
        assert f == "overview.md"


class TestGlobMatch:

    def test_wildcard(self):
        assert glob_match("notes.md", "*.md")
        assert not glob_match("notes.txt", "*.md")

    def test_path_glob(self):
        assert glob_match("/wiki/overview.md", "/wiki/*.md")
        assert not glob_match("/sources/paper.pdf", "/wiki/*.md")


class TestParsePageRange:

    def test_single_page(self):
        assert parse_page_range("3", 10) == [3]

    def test_range(self):
        assert parse_page_range("2-5", 10) == [2, 3, 4, 5]

    def test_mixed(self):
        assert parse_page_range("1, 3-5, 8", 10) == [1, 3, 4, 5, 8]

    def test_clamped_to_max(self):
        assert parse_page_range("8-15", 10) == [8, 9, 10]

    def test_clamped_to_min(self):
        assert parse_page_range("0-3", 10) == [1, 2, 3]

    def test_out_of_range_ignored(self):
        assert parse_page_range("99", 10) == []

    def test_deduplication(self):
        assert parse_page_range("1-3, 2-4", 10) == [1, 2, 3, 4]

    def test_empty_string(self):
        assert parse_page_range("", 10) == []


class TestDeepLink:

    def test_root_file(self):
        url = deep_link("http://localhost:3000", "my-kb", "/", "notes.md")
        assert url == "http://localhost:3000/wikis/my-kb/notes.md"

    def test_wiki_file(self):
        url = deep_link("http://localhost:3000", "my-kb", "/wiki/", "overview.md")
        assert url == "http://localhost:3000/wikis/my-kb/wiki/overview.md"

    def test_nested_path(self):
        url = deep_link("http://localhost:3000", "my-kb", "/wiki/sub/", "deep.md")
        assert url == "http://localhost:3000/wikis/my-kb/wiki/sub/deep.md"
