-- Lock down RLS: authenticated role gets SELECT-only.
-- All writes go through the API (service role / pool connection).

BEGIN;

-- Drop old FOR ALL policies
DROP POLICY IF EXISTS api_keys_all ON api_keys;
DROP POLICY IF EXISTS knowledge_bases_all ON knowledge_bases;
DROP POLICY IF EXISTS documents_all ON documents;
DROP POLICY IF EXISTS document_pages_all ON document_pages;
DROP POLICY IF EXISTS document_chunks_all ON document_chunks;

-- Create SELECT-only policies for authenticated role
CREATE POLICY api_keys_select ON api_keys
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY knowledge_bases_select ON knowledge_bases
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY documents_select ON documents
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY document_pages_select ON document_pages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM documents
            WHERE documents.id = document_pages.document_id
              AND documents.user_id = auth.uid()
        )
    );

CREATE POLICY document_chunks_select ON document_chunks
    FOR SELECT USING (user_id = auth.uid());

-- Sanity CHECK constraints
ALTER TABLE documents ADD CONSTRAINT chk_documents_page_count
    CHECK (page_count IS NULL OR page_count <= 1000);

ALTER TABLE document_pages ADD CONSTRAINT chk_pages_content_length
    CHECK (length(content) <= 500000);

ALTER TABLE document_chunks ADD CONSTRAINT chk_chunks_content_length
    CHECK (length(content) <= 10000);

COMMIT;
