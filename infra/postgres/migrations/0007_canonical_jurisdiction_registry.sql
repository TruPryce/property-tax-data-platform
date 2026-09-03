-- 0007_canonical_jurisdiction_registry.sql
--
-- The county registry, persisted.
--
-- The promoted jurisdiction contract has two rules and the state-and-county
-- grammar is only the first: a slug the version-controlled registry does not
-- describe cannot become a Jurisdiction. `tx-madeup` matches the grammar, so a
-- schema that constrained only the grammar would persist a county the domain
-- cannot represent.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0007_canonical_jurisdiction_registry.sql | cut -d' ' -f1)" \
--              -f 0007_canonical_jurisdiction_registry.sql

\if :{?file_sha256}
\else
\echo 'ERROR: pass -v file_sha256="$(sha256sum <this file> | cut -d\' \' -f1)"'
\echo '       The ledger records what was applied, and a version number cannot'
\echo '       tell you whether the file behind it was edited afterwards.'
-- Not \quit: psql treats that as normal termination and exits 0, so a script
-- reading the status would call this a success. An error exits 3 under
-- ON_ERROR_STOP, which is what the operator's `&&` is testing.
DO $missing$ BEGIN
    RAISE EXCEPTION 'file_sha256 was not supplied';
END $missing$;
\endif

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 6) THEN
        RAISE EXCEPTION 'migration 0006 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 7) THEN
        RAISE EXCEPTION 'migration 0007 is already applied';
    END IF;
END $$;

-- Every canonical migration references a relation that may hold rows by the time
-- it is applied, and adding a foreign key takes ShareRowExclusiveLock on the
-- referenced one. Yield rather than queue production traffic behind this.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '300s';

CREATE TABLE canonical.jurisdiction (
    jurisdiction_code text PRIMARY KEY,
    county_fips       text NOT NULL,

    CONSTRAINT jurisdiction_code_is_state_and_county
        CHECK (jurisdiction_code ~ '^[a-z]{2}-[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT jurisdiction_fips_is_five_digits
        CHECK (county_fips ~ '^[0-9]{5}$')
);

COMMENT ON TABLE canonical.jurisdiction IS
    'The version-controlled county registry, keyed by the jurisdiction identity. Every '
    'canonical relation naming a county references this, so a well-formed but '
    'unregistered slug is unrepresentable rather than merely wrong. Seeded here rather '
    'than left to a loader, as 0005 seeds its three products: it is reference data, not '
    'something an operator supplies.';
COMMENT ON COLUMN canonical.jurisdiction.county_fips IS
    'Validated registry metadata, and it lives here and nowhere else. It is keyed by the '
    'identity rather than part of it, so no record relation carries a FIPS column and no '
    'second, independent county identity exists. The domain excludes it from equality for '
    'the same reason.';

-- The natural key is the identity. No surrogate: a generated key here would be a
-- second way to name one county, which is exactly what the promoted contract
-- refuses when it says no database identifier participates in jurisdiction identity.
INSERT INTO canonical.jurisdiction (jurisdiction_code, county_fips) VALUES
    ('tx-dallas', '48113'),
    ('tx-collin', '48085'),
    ('tx-tarrant', '48439'),
    ('tx-denton', '48121'),
    ('tx-rockwall', '48397'),
    ('tx-ellis', '48139');

-- ---------------------------------------------------------------------------
-- Privileges
--
-- Reference data the loader reads and does not write, exactly as quality.rule is.
-- The REVOKE is not redundant: 0006 set ALTER DEFAULT PRIVILEGES granting SELECT
-- and INSERT on every table this role creates in the schema, so a relation created
-- by property_tax_migrator inherits INSERT before this line runs.  Revoking it
-- explicitly is what makes the registry read-only in the cluster where the
-- migrator owns the object, and harmless in one where it does not.
-- ---------------------------------------------------------------------------

GRANT SELECT ON canonical.jurisdiction TO property_tax_ingestion;
REVOKE INSERT ON canonical.jurisdiction FROM property_tax_ingestion;

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (7, '0007_canonical_jurisdiction_registry', :'file_sha256');

COMMIT;
