"""Plain keyword queries with hyphens broke FTS5 MATCH outright.

`search(query="agentic-os dashboard sidebar")` raised `no such column: os`
because the raw query string went into MATCH and FTS5 parsed `agentic-os` as
column-filter syntax. The fix quotes every token (keeping implicit AND and
trailing-`*` prefix queries) unless the caller is already using explicit
phrase syntax. Helper is duplicated in api/infra/db/sqlite.py and
mcp/vaultfs/sqlite.py — this exercises the api copy plus a real FTS5 table.
"""

import sqlite3

import aiosqlite
import pytest
from infra.db.sqlite import _fts5_safe_query


def test_hyphenated_tokens_are_quoted():
    assert _fts5_safe_query("agentic-os dashboard sidebar") == '"agentic-os" "dashboard" "sidebar"'


def test_prefix_star_stays_outside_quotes():
    assert _fts5_safe_query("agent* os") == '"agent"* "os"'


def test_explicit_phrase_syntax_passes_through():
    assert _fts5_safe_query('"exact phrase" extra') == '"exact phrase" extra'


def test_bare_star_and_whitespace_collapse():
    assert _fts5_safe_query("  *   ") == ""


async def test_hyphenated_query_matches_against_real_fts5():
    db = await aiosqlite.connect(":memory:")
    try:
        await db.execute("CREATE VIRTUAL TABLE t USING fts5(content)")
        await db.execute("INSERT INTO t VALUES ('the agentic-os dashboard sidebar')")
        await db.commit()

        # The raw query is the bug: FTS5 reads `agentic-os` as a column filter.
        with pytest.raises(sqlite3.OperationalError):
            await db.execute("SELECT * FROM t WHERE t MATCH ?", ("agentic-os dashboard",))

        cursor = await db.execute(
            "SELECT * FROM t WHERE t MATCH ?", (_fts5_safe_query("agentic-os dashboard"),)
        )
        rows = await cursor.fetchall()
        assert len(rows) == 1
    finally:
        await db.close()
