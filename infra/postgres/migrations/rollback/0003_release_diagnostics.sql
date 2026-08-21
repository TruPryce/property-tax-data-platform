-- rollback/0003_release_diagnostics.sql
--
-- Reverses migrations/0003_release_diagnostics.sql.
--
-- Run with:  psql --single-transaction --set ON_ERROR_STOP=on -f rollback/0003_release_diagnostics.sql
--
-- CASCADE drops the schema and everything in it, including any data loaded
-- since. That is the honest cost of undoing a schema, and it is stated here
-- rather than discovered.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 3) THEN
        RAISE EXCEPTION 'migration 0003 is not applied';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version > 3) THEN
        RAISE EXCEPTION 'roll back later migrations first: % is still applied',
            (SELECT string_agg(name, ', ' ORDER BY version)
             FROM platform.schema_migration WHERE version > 3);
    END IF;
END $$;

DROP SCHEMA ingestion CASCADE;

DELETE FROM platform.schema_migration WHERE version = 3;

COMMIT;
