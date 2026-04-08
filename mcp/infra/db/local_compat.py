"""Compatibility shim that makes the local SQLite DB look like mcp/db.py.

This module provides the same function signatures as mcp/db.py
(scoped_query, scoped_queryrow, service_queryrow, service_execute)
but backed by SQLite. It's injected as sys.modules['db'] in local mode.

NOTE: The tools pass Postgres-style $1/$2 params. This shim converts
them to ? params for SQLite. This is intentionally limited — it only
handles the parameter placeholder swap, not full SQL translation.
"""

import json
import re
import logging

import aiosqlite

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None


def set_connection(db: aiosqlite.Connection) -> None:
    global _db
    _db = db


def _pg_to_sqlite_params(sql: str) -> str:
    """Convert $1, $2, ... to ? placeholders. Strips ::type casts."""
    sql = re.sub(r"\$\d+::\w+(\[\])?", "?", sql)
    sql = re.sub(r"\$\d+", "?", sql)
    return sql


def _adapt_any_clause(sql: str, args: tuple) -> tuple[str, list]:
    """Expand ANY($N::uuid[]) into IN (?, ?, ...) for SQLite."""
    params = list(args)
    match = re.search(r"= ANY\(\?\)", sql)
    if match and params:
        # Find the parameter that's a list
        for i, p in enumerate(params):
            if isinstance(p, (list, tuple)):
                placeholders = ",".join("?" for _ in p)
                sql = sql[:match.start()] + f"IN ({placeholders})" + sql[match.end():]
                expanded = list(p)
                params = params[:i] + expanded + params[i + 1:]
                break
    return sql, params


def _rows_to_dicts(cursor, rows: list) -> list[dict]:
    if not rows or not cursor.description:
        return []
    cols = [d[0] for d in cursor.description]
    results = []
    for row in rows:
        d = dict(zip(cols, row))
        if "tags" in d and isinstance(d["tags"], str):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
        results.append(d)
    return results


async def get_pool():
    return _db


async def scoped_query(user_id: str, sql: str, *args, claims: dict | None = None) -> list[dict]:
    """Execute a query. In local mode, RLS is not needed (single user)."""
    sql = _pg_to_sqlite_params(sql)
    sql, params = _adapt_any_clause(sql, args)
    # Replace Postgres-specific syntax
    sql = sql.replace("NOT d.archived", "d.status != 'failed'")
    sql = sql.replace("NOT archived", "status != 'failed'")
    sql = sql.replace("now()", "datetime('now')")
    # Remove pgroonga score function if present
    sql = re.sub(r"pgroonga_score\([^)]+\)\s*AS\s*score", "0 AS score", sql)
    # Replace pgroonga search operator with simple LIKE (fallback)
    sql = re.sub(r"(\w+\.content)\s+&@~\s+\?", r"\1 LIKE '%' || ? || '%'", sql)

    try:
        cursor = await _db.execute(sql, params)
        rows = await cursor.fetchall()
        return _rows_to_dicts(cursor, rows)
    except Exception as e:
        logger.error("SQLite query failed: %s\nSQL: %s\nParams: %s", e, sql, params)
        return []


async def scoped_queryrow(user_id: str, sql: str, *args, claims: dict | None = None) -> dict | None:
    rows = await scoped_query(user_id, sql, *args, claims=claims)
    return rows[0] if rows else None


async def scoped_execute(user_id: str, sql: str, *args, claims: dict | None = None) -> str:
    sql = _pg_to_sqlite_params(sql)
    sql, params = _adapt_any_clause(sql, args)
    sql = sql.replace("now()", "datetime('now')")
    try:
        cursor = await _db.execute(sql, params)
        await _db.commit()
        return f"OK {cursor.rowcount}"
    except Exception as e:
        logger.error("SQLite execute failed: %s\nSQL: %s\nParams: %s", e, sql, params)
        return "ERROR"


async def service_queryrow(sql: str, *args) -> dict | None:
    """Service role query — in local mode, same as scoped (no RLS)."""
    sql = _pg_to_sqlite_params(sql)
    sql, params = _adapt_any_clause(sql, args)
    sql = sql.replace("now()", "datetime('now')")
    try:
        cursor = await _db.execute(sql, params)
        rows = await cursor.fetchall()
        if not rows:
            return None
        await _db.commit()
        return _rows_to_dicts(cursor, rows)[0] if rows else None
    except Exception as e:
        logger.error("SQLite service_queryrow failed: %s\nSQL: %s\nParams: %s", e, sql, params)
        return None


async def service_execute(sql: str, *args) -> str:
    """Service role execute — in local mode, same as scoped (no RLS)."""
    sql = _pg_to_sqlite_params(sql)
    sql, params = _adapt_any_clause(sql, args)
    sql = sql.replace("now()", "datetime('now')")
    try:
        cursor = await _db.execute(sql, params)
        await _db.commit()
        return f"OK {cursor.rowcount}"
    except Exception as e:
        logger.error("SQLite service_execute failed: %s\nSQL: %s\nParams: %s", e, sql, params)
        return "ERROR"
