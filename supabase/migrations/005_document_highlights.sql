-- Document highlights & annotations.
-- JSONB array on documents. Each entry: { id, type, anchor, comment, color, createdAt }.
-- The whole array is replaced on PATCH; the column's `version` field provides
-- optimistic concurrency for single-user, multi-tab safety.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS highlights JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Index for the by-source-url lookup the extension makes on every page load.
-- Restricted to non-archived docs so it stays small.
CREATE INDEX IF NOT EXISTS idx_documents_source_url
    ON documents (user_id, (metadata->>'source_url'))
    WHERE metadata ? 'source_url' AND NOT archived;
