"""Local SQLite migration runner; stdlib-only because MCP and the llmwiki CLI load it by file path."""

import re
import sqlite3
from pathlib import Path
from typing import NamedTuple

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "shared" / "sqlite_migrations"
BUSY_TIMEOUT_MS = 60_000

_LEGACY_BACKFILLS = {
    ("document_chunks", "source_content"): "UPDATE document_chunks SET source_content = content",
}

_CONSTANT_DEFAULT = re.compile(r"^('.*'|-?\d+(\.\d+)?|NULL|TRUE|FALSE)$", re.IGNORECASE | re.DOTALL)


class Migration(NamedTuple):
    version: int
    name: str
    sql: str


def apply_migrations(db_path: str) -> None:
    """Bring the index at db_path to the latest schema version."""
    migrations = _load_migrations()
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        for migration in migrations:
            _apply_if_pending(conn, migration)
    finally:
        conn.close()


def _apply_if_pending(conn: sqlite3.Connection, migration: Migration) -> None:
    """Apply one migration, planning under BEGIN IMMEDIATE so racing api/MCP/CLI processes serialize."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if migration.version <= version:
            conn.execute("COMMIT")
            return
        if version == 0 and _is_pre_versioning_db(conn):
            statements = _plan_legacy_reconcile(conn, migration)
        else:
            statements = _split_statements(migration.sql)
        for statement in statements:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {migration.version}")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _is_pre_versioning_db(conn: sqlite3.Connection) -> bool:
    return _has_table(conn, "documents") or _has_table(conn, "workspace")


def _plan_legacy_reconcile(conn: sqlite3.Connection, baseline: Migration) -> list[str]:
    """ALTER missing baseline columns into a pre-versioning DB, dropping triggers first so backfills don't fire."""
    target = sqlite3.connect(":memory:")
    target.executescript(baseline.sql)
    statements = [f"DROP TRIGGER IF EXISTS {name}" for name in _trigger_names(target)]
    for table in _concrete_tables(target):
        if not _has_table(conn, table):
            continue
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for row in target.execute(f"PRAGMA table_info({table})"):
            _cid, name, col_type, notnull, default, _pk = row
            if name in existing:
                continue
            statements.append(f"ALTER TABLE {table} ADD COLUMN {_column_ddl(table, name, col_type, notnull, default)}")
            backfill = _LEGACY_BACKFILLS.get((table, name))
            if backfill is not None:
                statements.append(backfill)
    target.close()
    statements += _split_statements(baseline.sql)
    return statements


def _column_ddl(table: str, name: str, col_type: str, notnull: int, default: str | None) -> str:
    if notnull and default is None:
        raise ValueError(
            f"cannot reconcile {table}.{name}: NOT NULL without a default is not addable via ALTER",
        )
    # table_info strips parens from expression defaults, and ADD COLUMN forbids non-constant ones anyway.
    if default is not None and not _CONSTANT_DEFAULT.match(default.strip()):
        raise ValueError(
            f"cannot reconcile {table}.{name}: non-constant default {default!r} needs an explicit migration",
        )
    ddl = f'"{name}" {col_type}'
    if notnull:
        ddl += " NOT NULL"
    if default is not None:
        ddl += f" DEFAULT {default}"
    return ddl


def _split_statements(sql: str) -> list[str]:
    """Split a migration script on statement boundaries (trigger-body aware)."""
    statements = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    if any(line.strip() and not line.strip().startswith("--") for line in buffer.splitlines()):
        raise ValueError("migration ends with an incomplete SQL statement")
    return statements


def _load_migrations() -> list[Migration]:
    migrations = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = re.match(r"^(\d+)_(.+)\.sql$", path.name)
        if match is None:
            raise ValueError(f"migration filename must be NNNN_name.sql: {path.name}")
        migrations.append(Migration(int(match.group(1)), match.group(2), path.read_text(encoding="utf-8")))
    if not migrations:
        raise FileNotFoundError(f"no migrations found in {MIGRATIONS_DIR}")
    versions = [m.version for m in migrations]
    if len(set(versions)) != len(versions):
        raise ValueError(f"duplicate migration versions in {MIGRATIONS_DIR}")
    return migrations


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,),
    ).fetchone()
    return row is not None


def _trigger_names(target: sqlite3.Connection) -> list[str]:
    return [row[0] for row in target.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")]


def _concrete_tables(target: sqlite3.Connection) -> list[str]:
    """Baseline table names, excluding virtual tables and their shadow tables."""
    rows = target.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'",
    ).fetchall()
    virtual = {name for name, sql in rows if sql is not None and "VIRTUAL TABLE" in sql.upper()}
    return [
        name for name, _sql in rows
        if name not in virtual and not any(name.startswith(v + "_") for v in virtual)
    ]
