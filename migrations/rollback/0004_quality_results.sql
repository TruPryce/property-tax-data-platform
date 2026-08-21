-- rollback/0004_quality_results.sql
--
-- Reverses migrations/0004_quality_results.sql.
--
-- Run with:  psql --single-transaction --set ON_ERROR_STOP=on -f rollback/0004_quality_results.sql
--
-- CASCADE drops the schema and everything in it, including any data loaded
-- since. That is the honest cost of undoing a schema, and it is stated here
-- rather than discovered.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 4) THEN
        RAISE EXCEPTION 'migration 0004 is not applied';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version > 4) THEN
        RAISE EXCEPTION 'roll back later migrations first: % is still applied',
            (SELECT string_agg(name, ', ' ORDER BY version)
             FROM platform.schema_migration WHERE version > 4);
    END IF;
END $$;

DROP SCHEMA quality CASCADE;

DELETE FROM platform.schema_migration WHERE version = 4;

COMMIT;
