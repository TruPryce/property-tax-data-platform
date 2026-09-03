-- 0008_canonical_release_identity.sql
--
-- Canonical release identity, and its association with the bytes that carry it.
--
-- ReleaseIdentity is jurisdiction, tax year, release kind, and the identifier the
-- source supplied. bronze.release_partition carries three of those four and no
-- release identifier, so it is the artifact-partition fact rather than a canonical
-- release, and is deliberately not read as one.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0008_canonical_release_identity.sql | cut -d' ' -f1)" \
--              -f 0008_canonical_release_identity.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 7) THEN
        RAISE EXCEPTION 'migration 0007 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 8) THEN
        RAISE EXCEPTION 'migration 0008 is already applied';
    END IF;
END $$;

-- Every canonical migration references a relation that may hold rows by the time
-- it is applied, and adding a foreign key takes ShareRowExclusiveLock on the
-- referenced one. Yield rather than queue production traffic behind this.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '300s';

CREATE TABLE canonical.release (
    release_key        bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    jurisdiction_code  text        NOT NULL REFERENCES canonical.jurisdiction (jurisdiction_code),
    tax_year           integer     NOT NULL,
    release_kind       text        NOT NULL,
    release_identifier text        NOT NULL,
    first_recorded_at  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT release_tax_year_plausible
        CHECK (tax_year BETWEEN 1900 AND 2200),
    -- A textual closed set rather than an enum type, for three reasons. The load
    -- below keys into ingestion.run.release_kind, which is text, and a composite
    -- key cannot span two types. 0003 already enumerates its twelve diagnostic
    -- codes this way, so a fifth kind has to be named in a migration someone
    -- reviews. And ALTER TYPE ... ADD VALUE is irreversible, where a CHECK can be
    -- narrowed again and fails loudly against any row that violates it.
    CONSTRAINT release_kind_is_canonical
        CHECK (release_kind IN ('proposed', 'certified', 'supplemental', 'current')),
    CONSTRAINT release_identifier_is_an_identifier
        CHECK (canonical.is_identifier(release_identifier)),

    -- The business identity. The surrogate above is a locator; this is what makes
    -- two counties reusing one source label two releases rather than one.
    CONSTRAINT release_identity
        UNIQUE (jurisdiction_code, tax_year, release_kind, release_identifier),
    -- Composite foreign-key targets.
    CONSTRAINT release_identity_by_county
        UNIQUE (release_key, jurisdiction_code),
    CONSTRAINT release_identity_by_components
        UNIQUE (release_key, jurisdiction_code, tax_year, release_kind, release_identifier)
);

COMMENT ON TABLE canonical.release IS
    'One logical release, identified by its four components. The identifier is opaque and '
    'source-supplied: it is never derived from a filename, an artifact digest, a tax year, '
    'a release kind, row order, or an acquisition time. A run whose components fall '
    'outside this contract simply has no canonical release, and therefore no canonical '
    'records; the evidence stays in bronze and at adapter grain.';
COMMENT ON COLUMN canonical.release.release_key IS
    'A persistence locator for foreign-key mechanics. Not business identity, which is the '
    'four-component unique constraint above.';

CREATE TABLE canonical.artifact_release_binding (
    artifact_sha256   text        NOT NULL REFERENCES bronze.artifact (sha256),
    release_key       bigint      NOT NULL REFERENCES canonical.release (release_key),
    first_recorded_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (artifact_sha256, release_key)
);

COMMENT ON TABLE canonical.artifact_release_binding IS
    'Artifacts and releases related as an association rather than by a field on either, '
    'many-to-many in both directions: one archive carries current values for one year and '
    'certified values for another, and one release may be observed in several artifacts. '
    'Observing a second artifact does not change the release identity. The natural pair is '
    'the primary key and there is no surrogate, because a generated key would be a second '
    'way to name one binding. No jurisdiction agreement is constrained between the two: an '
    'artifact is identified by content alone and the domain binding establishes none.';

CREATE INDEX artifact_release_binding_by_release
    ON canonical.artifact_release_binding (release_key);

GRANT SELECT, INSERT ON
    canonical.release,
    canonical.artifact_release_binding
    TO property_tax_ingestion;

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (8, '0008_canonical_release_identity', :'file_sha256');

COMMIT;
