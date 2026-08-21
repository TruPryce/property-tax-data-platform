-- rollback/0001_release_manifests.sql
--
-- Reverses migrations/0001_release_manifests.sql, which means removing the
-- ledger itself. After this the database has no record of ever having been
-- migrated, because that record lived in what is being dropped.
--
-- Run with:  psql --single-transaction --set ON_ERROR_STOP=on -f rollback/0001_release_manifests.sql

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 1) THEN
        RAISE EXCEPTION 'migration 0001 is not applied';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version > 1) THEN
        RAISE EXCEPTION 'roll back later migrations first: % is still applied',
            (SELECT string_agg(name, ', ' ORDER BY version)
             FROM platform.schema_migration WHERE version > 1);
    END IF;
END $$;

DROP SCHEMA bronze CASCADE;
DROP SCHEMA platform CASCADE;

COMMIT;
