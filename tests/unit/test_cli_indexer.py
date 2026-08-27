"""`llmwiki init`/`reindex` must leave the index searchable, not just listed.

The CLI indexer used to insert `documents` rows and stop. MCP `search` matches
on `chunks_fts`, which the schema triggers populate only from `document_chunks`,
so a CLI-built index answered every query with "No matches". The API server's
reconcile pass hid this whenever someone ran `llmwiki serve`; `llmwiki mcp`
never runs reconcile, so an MCP-only machine stayed permanently unsearchable.
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]


def _load_cli():
    """Import the extensionless `llmwiki` CLI script as a module."""
    spec = importlib.util.spec_from_file_location(
        "llmwiki_cli", REPO_ROOT / "llmwiki",
        loader=importlib.machinery.SourceFileLoader("llmwiki_cli", str(REPO_ROOT / "llmwiki")),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_cli()


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "notes.md").write_text(
        "# Trading notes\n\n"
        "A fade-buy is an entry taken materially below the session high.\n\n"
        "## Detail\n\nMore prose so the chunker has something to split.\n",
        encoding="utf-8",
    )
    return tmp_path


def _db(ws: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(ws / ".llmwiki" / "index.db"))


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _fts_hits(conn: sqlite3.Connection, term: str) -> int:
    return conn.execute(
        "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?", (term,)
    ).fetchone()[0]


def test_init_builds_search_chunks(cli, workspace):
    cli.cmd_init(str(workspace))
    conn = _db(workspace)

    assert _count(conn, "documents") > 0
    assert _count(conn, "document_chunks") > 0, "init listed documents but built no chunks"
    assert _count(conn, "chunks_fts") == _count(conn, "document_chunks")
    assert _fts_hits(conn, "fade") > 0, "indexed content is not reachable by search"
    conn.close()


def test_scaffolded_overview_is_marked_chunked(cli, workspace):
    """The scaffold is ~75 chars, under the chunker's MIN_CHUNK_TOKENS floor, so
    it yields no chunks by design. It still must carry the marker, or reconcile
    retries it on every server start forever."""
    cli.cmd_init(str(workspace))
    conn = _db(workspace)

    parser = conn.execute(
        "SELECT parser FROM documents WHERE relative_path = 'wiki/overview.md'"
    ).fetchone()[0]
    assert parser == "text"
    conn.close()


def test_wiki_pages_are_chunked(cli, tmp_path):
    """A real wiki page — not just `source` files — has to reach search."""
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "fade-buys.md").write_text(
        "# Fade-buys\n\n" + "An entry taken below the session high. " * 20,
        encoding="utf-8",
    )
    cli.cmd_init(str(tmp_path))
    conn = _db(tmp_path)

    doc_id = conn.execute(
        "SELECT id FROM documents WHERE relative_path = 'wiki/fade-buys.md'"
    ).fetchone()[0]
    chunks = conn.execute(
        "SELECT count(*) FROM document_chunks WHERE document_id = ?", (doc_id,)
    ).fetchone()[0]
    assert chunks > 0
    assert _fts_hits(conn, "fade") > 0
    conn.close()


def test_text_docs_marked_chunked_so_reconcile_skips_them(cli, workspace):
    """`parser` is the chunked-marker reconcile checks (api/domain/local_processor)."""
    cli.cmd_init(str(workspace))
    conn = _db(workspace)

    parser = conn.execute(
        "SELECT parser FROM documents WHERE relative_path = 'notes.md'"
    ).fetchone()[0]
    assert parser == "text"
    conn.close()


def test_non_text_docs_left_for_reconcile(cli, tmp_path):
    """PDFs need an extraction backend the CLI doesn't run — leave parser NULL."""
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    cli.cmd_init(str(tmp_path))
    conn = _db(tmp_path)

    parser = conn.execute(
        "SELECT parser FROM documents WHERE relative_path = 'paper.pdf'"
    ).fetchone()[0]
    assert parser is None, "PDF marked as chunked would make reconcile skip extraction"
    conn.close()


def test_reindex_repairs_an_unchunked_index(cli, workspace):
    """The upgrade path for indexes built by the pre-fix CLI."""
    cli.cmd_init(str(workspace))
    conn = _db(workspace)

    # Simulate a legacy index: documents listed, chunks never built.
    conn.execute("DELETE FROM document_chunks")
    conn.execute("UPDATE documents SET parser = NULL")
    conn.commit()
    assert _count(conn, "document_chunks") == 0
    assert _fts_hits(conn, "fade") == 0
    conn.close()

    cli.cmd_reindex(str(workspace))

    conn = _db(workspace)
    assert _count(conn, "document_chunks") > 0
    assert _fts_hits(conn, "fade") > 0, "reindex left the index unsearchable"
    conn.close()
