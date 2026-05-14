-- Write policies for document_references — enables graph rebuild through RLS
-- rather than requiring service-role bypass.

CREATE POLICY document_references_write ON document_references
    FOR ALL TO authenticated
    USING (knowledge_base_id IN (
        SELECT id FROM knowledge_bases WHERE user_id = auth.uid()
    ))
    WITH CHECK (knowledge_base_id IN (
        SELECT id FROM knowledge_bases WHERE user_id = auth.uid()
    ));
