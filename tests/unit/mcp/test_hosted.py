import os
import sys

# hosted builds FastMCP at import, which needs URL-valid SUPABASE_URL/MCP_URL; tests/conftest.py sets them empty.
os.environ["SUPABASE_URL"] = "https://example.supabase.co"
os.environ.setdefault("MCP_URL", "http://example.com")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp"))


class TestBuildAllowedHosts:

    def test_includes_bare_host_and_port_wildcard(self):
        """In-container Host headers carry the port, which would 421 without the `host:*` wildcard."""
        from hosted import _build_allowed_hosts

        allowed = _build_allowed_hosts("http://llmwiki-mcp:8080")

        assert "llmwiki-mcp" in allowed
        assert "llmwiki-mcp:*" in allowed

    def test_handles_https_url(self):
        from hosted import _build_allowed_hosts

        allowed = _build_allowed_hosts("https://wiki.example.com")

        assert allowed == ["wiki.example.com", "wiki.example.com:*"]

    def test_falls_back_to_localhost_for_invalid_url(self):
        """``urlparse(...).hostname`` is None for inputs without a scheme."""
        from hosted import _build_allowed_hosts

        allowed = _build_allowed_hosts("not-a-url")

        assert allowed == ["localhost", "localhost:*"]
