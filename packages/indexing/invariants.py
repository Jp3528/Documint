"""PostgreSQL invariants; schema is always qualified, including isolated test schemas."""

from typing import Any

from sqlalchemy import Connection, Table, text


def install_invariant(target: Table, connection: Connection, **kwargs: Any) -> None:
    translated = connection.get_execution_options().get("schema_translate_map") or {}
    schema = (
        translated.get(None) or target.schema or connection.scalar(text("SELECT current_schema()"))
    )
    quoted = connection.dialect.identifier_preparer.quote_schema(str(schema))
    table = connection.dialect.identifier_preparer.quote(target.name)
    if target.name in {"index_chunks", "chunk_embeddings"}:
        connection.exec_driver_sql(f"""CREATE OR REPLACE FUNCTION {quoted}.immutable_index_row()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE revision_id uuid; revision_state text; expected_dimensions integer;
        BEGIN
          IF TG_OP != 'INSERT' THEN
            RAISE EXCEPTION 'index evidence is immutable' USING ERRCODE='23514';
          END IF;
          IF TG_TABLE_NAME = 'index_chunks' THEN revision_id := NEW.index_revision_id;
          ELSE SELECT index_revision_id INTO revision_id FROM {quoted}.index_chunks
            WHERE id=NEW.chunk_id;
          END IF;
          SELECT status, (embedding_profile->>'dimensions')::integer
            INTO revision_state, expected_dimensions FROM {quoted}.index_revisions
            WHERE id=revision_id FOR SHARE;
          IF TG_TABLE_NAME = 'chunk_embeddings' THEN
            IF NEW.dimensions IS DISTINCT FROM expected_dimensions THEN
              RAISE EXCEPTION 'embedding profile dimensions mismatch' USING ERRCODE='23514';
            END IF;
          END IF;
          IF revision_state = 'READY' THEN
            RAISE EXCEPTION 'published index is immutable' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
        connection.exec_driver_sql(
            f"DROP TRIGGER IF EXISTS immutable_index_row ON {quoted}.{table}"
        )
        connection.exec_driver_sql(
            f"CREATE TRIGGER immutable_index_row BEFORE INSERT OR UPDATE OR DELETE "
            f"ON {quoted}.{table} FOR EACH ROW EXECUTE FUNCTION {quoted}.immutable_index_row()"
        )
    elif target.name == "index_revisions":
        connection.exec_driver_sql(f"""CREATE OR REPLACE FUNCTION {quoted}.guard_index_ready()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE chunks bigint; vectors bigint;
        BEGIN
          IF TG_OP = 'UPDATE' AND ROW(NEW.id, NEW.version_id, NEW.extraction_id,
            NEW.generation, NEW.fingerprint, NEW.chunk_config, NEW.embedding_profile,
            NEW.chunk_count, NEW.created_at) IS DISTINCT FROM ROW(OLD.id, OLD.version_id,
            OLD.extraction_id, OLD.generation, OLD.fingerprint, OLD.chunk_config,
            OLD.embedding_profile, OLD.chunk_count, OLD.created_at) THEN
            RAISE EXCEPTION 'index configuration is immutable' USING ERRCODE='23514';
          END IF;
          IF TG_OP = 'UPDATE' AND OLD.status='READY' AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'published revision is immutable' USING ERRCODE='23514';
          END IF;
          IF NEW.status='READY' THEN
            SELECT count(*) INTO chunks FROM {quoted}.index_chunks WHERE index_revision_id=NEW.id;
            SELECT count(*) INTO vectors FROM {quoted}.chunk_embeddings e
              JOIN {quoted}.index_chunks c ON c.id=e.chunk_id
              WHERE c.index_revision_id=NEW.id
                AND e.dimensions=(NEW.embedding_profile->>'dimensions')::integer;
            IF chunks=0 OR chunks!=NEW.chunk_count OR vectors!=chunks
              OR NEW.indexed_count!=vectors THEN
              RAISE EXCEPTION 'index is incomplete' USING ERRCODE='23514';
            END IF;
          END IF;
          RETURN NEW;
        END $$""")
        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS guard_index_ready ON {quoted}.{table}")
        connection.exec_driver_sql(
            f"CREATE TRIGGER guard_index_ready BEFORE INSERT OR UPDATE ON {quoted}.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {quoted}.guard_index_ready()"
        )
    elif target.name == "documents":
        connection.exec_driver_sql(f"""CREATE OR REPLACE FUNCTION {quoted}.guard_active_revision()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.active_index_revision_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM {quoted}.index_revisions r
              JOIN {quoted}.document_versions v ON v.id=r.version_id
            WHERE r.id=NEW.active_index_revision_id AND v.document_id=NEW.id AND r.status='READY'
          ) THEN RAISE EXCEPTION 'active revision is not authorized by index state'
            USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
        connection.exec_driver_sql(
            f"CREATE TRIGGER guard_active_revision BEFORE INSERT OR UPDATE OF "
            f"active_index_revision_id ON {quoted}.{table} FOR EACH ROW "
            f"EXECUTE FUNCTION {quoted}.guard_active_revision()"
        )
