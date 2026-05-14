-- Notify on document changes so the API can push WebSocket events.
-- Replaces direct Supabase Realtime dependency.

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
