-- Test schema: mock Supabase auth functions + main migration (no PGroonga)

DROP SCHEMA IF EXISTS auth CASCADE;
CREATE SCHEMA auth;

CREATE TABLE auth.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT,
    raw_user_meta_data JSONB DEFAULT '{}'
);

CREATE OR REPLACE FUNCTION auth.uid() RETURNS UUID
LANGUAGE sql STABLE
AS $$
    SELECT COALESCE(
        nullif(current_setting('request.jwt.claims', true), '')::json->>'sub',
        NULL
    )::uuid
$$;

CREATE OR REPLACE FUNCTION auth.jwt() RETURNS JSON
LANGUAGE sql STABLE
AS $$
    SELECT COALESCE(
        nullif(current_setting('request.jwt.claims', true), ''),
        '{}'
    )::json
$$;

DO $$ BEGIN
    CREATE ROLE authenticated NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TYPE document_status AS ENUM ('pending', 'processing', 'ready', 'failed', 'archived');

CREATE TABLE users (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    onboarded BOOLEAN NOT NULL DEFAULT false,
    page_limit INTEGER NOT NULL DEFAULT 500,
    storage_limit_bytes BIGINT NOT NULL DEFAULT 1073741824,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE TABLE api_keys (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE knowledge_bases (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    UNIQUE(user_id, slug),
    UNIQUE(user_id, name)
);

CREATE TABLE documents (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    title TEXT,
    path TEXT DEFAULT '/' NOT NULL,
    file_type TEXT NOT NULL,
    file_size BIGINT DEFAULT 0 NOT NULL,
    document_number INTEGER,
    status document_status DEFAULT 'pending' NOT NULL,
    page_count INTEGER CHECK (page_count IS NULL OR page_count <= 300),
    content TEXT,
    tags TEXT[] DEFAULT '{}' NOT NULL,
    url TEXT,
    date TEXT,
    metadata JSONB,
    error_message TEXT,
    version INTEGER DEFAULT 0 NOT NULL,
    sort_order INTEGER DEFAULT 0,
    parser TEXT,
    archived BOOLEAN DEFAULT false NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE TABLE document_pages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    content TEXT NOT NULL CHECK (length(content) <= 500000),
    elements JSONB,
    UNIQUE(document_id, page)
);

CREATE TABLE document_chunks (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL CHECK (length(content) <= 10000),
    page INTEGER,
    start_char INTEGER,
    token_count INTEGER NOT NULL,
    header_breadcrumb TEXT,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    UNIQUE(document_id, chunk_index)
);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS stale_since TIMESTAMPTZ;

CREATE TABLE document_references (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    source_document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    reference_type TEXT NOT NULL CHECK (reference_type IN ('cites', 'links_to')),
    page INTEGER,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    UNIQUE(source_document_id, target_document_id, reference_type)
);

CREATE INDEX idx_refs_source ON document_references(source_document_id);
CREATE INDEX idx_refs_target ON document_references(target_document_id);

CREATE POLICY document_references_select ON document_references
    FOR SELECT TO authenticated
    USING (knowledge_base_id IN (
        SELECT id FROM knowledge_bases WHERE user_id = auth.uid()
    ));

CREATE POLICY document_references_write ON document_references
    FOR ALL TO authenticated
    USING (knowledge_base_id IN (
        SELECT id FROM knowledge_bases WHERE user_id = auth.uid()
    ))
    WITH CHECK (knowledge_base_id IN (
        SELECT id FROM knowledge_bases WHERE user_id = auth.uid()
    ));

ALTER TABLE document_references ENABLE ROW LEVEL SECURITY;

CREATE INDEX idx_documents_knowledge_base_id ON documents(knowledge_base_id);
CREATE INDEX idx_documents_user_id ON documents(user_id);
CREATE INDEX idx_documents_tags ON documents USING GIN(tags);
CREATE INDEX idx_documents_kb_path ON documents(knowledge_base_id, path);
CREATE INDEX idx_documents_kb_status ON documents(knowledge_base_id, status) WHERE NOT archived;
CREATE INDEX idx_documents_date ON documents(date) WHERE date IS NOT NULL;
CREATE INDEX idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX idx_chunks_kb ON document_chunks(knowledge_base_id);
CREATE INDEX idx_chunks_doc ON document_chunks(document_id);

-- PGroonga indexes intentionally omitted (requires C extension)

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_bases ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_pages ENABLE ROW LEVEL SECURITY;

CREATE POLICY users_select ON users
    FOR SELECT USING (id = auth.uid());

CREATE POLICY users_update ON users
    FOR UPDATE USING (id = auth.uid());

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

CREATE OR REPLACE FUNCTION generate_slug(name TEXT, p_user_id UUID)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    base_slug TEXT;
    candidate TEXT;
    counter INTEGER := 0;
BEGIN
    base_slug := lower(regexp_replace(trim(name), '[^a-zA-Z0-9]+', '-', 'g'));
    base_slug := trim(both '-' from base_slug);
    IF base_slug = '' THEN
        base_slug := 'untitled';
    END IF;
    candidate := base_slug;
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM knowledge_bases
            WHERE slug = candidate AND user_id = p_user_id
        ) THEN
            RETURN candidate;
        END IF;
        counter := counter + 1;
        candidate := base_slug || '-' || counter;
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.users (id, email, display_name)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data ->> 'display_name', NEW.raw_user_meta_data ->> 'full_name')
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION set_knowledge_base_slug()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.slug IS NULL OR NEW.slug = '' THEN
        NEW.slug := generate_slug(NEW.name, NEW.user_id);
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION handle_new_user();

CREATE TRIGGER set_knowledge_base_slug
    BEFORE INSERT ON knowledge_bases
    FOR EACH ROW
    EXECUTE FUNCTION set_knowledge_base_slug();

CREATE TRIGGER set_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER set_knowledge_bases_updated_at
    BEFORE UPDATE ON knowledge_bases
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER set_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION set_document_number()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext(NEW.knowledge_base_id::text));
    NEW.document_number := COALESCE(
        (SELECT MAX(document_number) FROM documents WHERE knowledge_base_id = NEW.knowledge_base_id),
        0
    ) + 1;
    RETURN NEW;
END;
$$;

CREATE TRIGGER set_document_number
    BEFORE INSERT ON documents
    FOR EACH ROW
    EXECUTE FUNCTION set_document_number();

CREATE UNIQUE INDEX idx_documents_kb_number ON documents(knowledge_base_id, document_number);

GRANT USAGE ON SCHEMA public TO authenticated;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO authenticated;
-- Supabase grants full CRUD to authenticated by default; mirror those grants
-- so RLS write tests and scoped_execute work correctly.
GRANT INSERT, UPDATE, DELETE ON document_references TO authenticated;
GRANT INSERT, UPDATE, DELETE ON documents TO authenticated;
GRANT INSERT, UPDATE, DELETE ON knowledge_bases TO authenticated;
GRANT UPDATE ON users TO authenticated;

-- Document change notification trigger (mirrors 003_document_notify.sql)
CREATE OR REPLACE FUNCTION notify_document_change() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    PERFORM pg_notify('document_changes', json_build_object(
      'event', TG_OP,
      'id', OLD.id::text,
      'knowledge_base_id', OLD.knowledge_base_id::text,
      'user_id', OLD.user_id::text
    )::text);
    RETURN OLD;
  ELSE
    PERFORM pg_notify('document_changes', json_build_object(
      'event', TG_OP,
      'id', NEW.id::text,
      'knowledge_base_id', NEW.knowledge_base_id::text,
      'user_id', NEW.user_id::text
    )::text);
    RETURN NEW;
  END IF;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER document_change_trigger
  AFTER INSERT OR UPDATE OR DELETE ON documents
  FOR EACH ROW EXECUTE FUNCTION notify_document_change();
