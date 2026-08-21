-- rollback/0005_publication_metadata.sql
--
-- Reverses migrations/0005_publication_metadata.sql.
--
-- Run with:  psql --single-transaction --set ON_ERROR_STOP=on -f rollback/0005_publication_metadata.sql
--
-- CASCADE drops the schema and everything in it, including any data loaded
-- since. That is the honest cost of undoing a schema, and it is stated here
-- rather than discovered.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 5) THEN
        RAISE EXCEPTION 'migration 0005 is not applied';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version > 5) THEN
        RAISE EXCEPTION 'roll back later migrations first: % is still applied',
            (SELECT string_agg(name, ', ' ORDER BY version)
             FROM platform.schema_migration WHERE version > 5);
    END IF;
END $$;

DROP SCHEMA publication CASCADE;

DELETE FROM platform.schema_migration WHERE version = 5;

COMMIT;
