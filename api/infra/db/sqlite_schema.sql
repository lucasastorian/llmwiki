-- LLM Wiki local index schema (SQLite + FTS5)
-- This is derived state — deletable and rebuildable from the workspace filesystem.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS workspace (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    user_id TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id)
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    title TEXT,
    path TEXT DEFAULT '/' NOT NULL,
    relative_path TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('wiki', 'source', 'asset')),
    file_type TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    document_number INTEGER,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
    page_count INTEGER,
    content TEXT,
    tags TEXT DEFAULT '[]',
    date TEXT,
    metadata TEXT,
    error_message TEXT,
    version INTEGER DEFAULT 0,
    parser TEXT,
    content_hash TEXT,
    mtime_ns INTEGER,
    last_indexed_at TEXT,
    stale_since TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(relative_path)
);

CREATE TABLE IF NOT EXISTS document_pages (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    content TEXT NOT NULL,
    elements TEXT,
    UNIQUE(document_id, page)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    page INTEGER,
    start_char INTEGER,
    token_count INTEGER NOT NULL,
    header_breadcrumb TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS document_references (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    source_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    reference_type TEXT NOT NULL CHECK (reference_type IN ('cites', 'links_to')),
    page INTEGER,
    UNIQUE(source_document_id, target_document_id, reference_type)
);

-- FTS5 full-text search (replaces pgroonga)
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content='document_chunks',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

-- Keep FTS in sync with document_chunks
CREATE TRIGGER IF NOT EXISTS chunks_fts_insert AFTER INSERT ON document_chunks BEGIN
    INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON document_chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_update AFTER UPDATE ON document_chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
    INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE INDEX IF NOT EXISTS idx_documents_relative_path ON documents(relative_path);
CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path);
CREATE INDEX IF NOT EXISTS idx_documents_source_kind ON documents(source_kind);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_refs_source ON document_references(source_document_id);
CREATE INDEX IF NOT EXISTS idx_refs_target ON document_references(target_document_id);
