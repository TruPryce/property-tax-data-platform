-- 0016_canonical_geometry.sql
--
-- Geometry, carried opaquely, with no geospatial dependency of any kind.
--
-- No PostGIS, no spatial type, no spatial index. Nothing here parses, validates,
-- reprojects, or interprets a payload, and nothing infers a coordinate reference:
-- geometry whose coordinate system is unknown cannot be placed, so the reference
-- is required.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0016_canonical_geometry.sql | cut -d' ' -f1)" \
--              -f 0016_canonical_geometry.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 15) THEN
        RAISE EXCEPTION 'migration 0015 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 16) THEN
        RAISE EXCEPTION 'migration 0016 is already applied';
    END IF;
END $$;

-- Every canonical migration references a relation that may hold rows by the time
-- it is applied, and adding a foreign key takes ShareRowExclusiveLock on the
-- referenced one. Yield rather than queue production traffic behind this.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '300s';

CREATE TABLE canonical.geometry_observation (
    geometry_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_key   bigint NOT NULL,
    release_key    bigint NOT NULL,
    load_key       bigint NOT NULL,
    provenance_key bigint NOT NULL,
    encoding      text  NOT NULL,
    payload_bytes bytea,
    payload_text  text,
    crs           text  NOT NULL,

    CONSTRAINT geometry_encoding_is_known
        CHECK (encoding IN ('wkb', 'wkt')),

    -- Two columns, one domain field. SQL has no union type, and a single bytea
    -- holding UTF-8 encoded WKT would make the encoding a claim about bytes
    -- rather than a typed fact. These two checks together make exactly one
    -- column populated and make it the one the encoding names.
    CONSTRAINT geometry_wkb_carries_bytes
        CHECK ((encoding = 'wkb') = (payload_bytes IS NOT NULL)),
    CONSTRAINT geometry_wkt_carries_text
        CHECK ((encoding = 'wkt') = (payload_text IS NOT NULL)),

    -- 8 MiB, non-empty. The text case is measured as UTF-8 bytes rather than
    -- characters, stated explicitly rather than relying on the server encoding
    -- being UTF-8, because that is the rule the promoted capability fixes.
    CONSTRAINT geometry_bytes_payload_is_bounded
        CHECK (payload_bytes IS NULL OR octet_length(payload_bytes) BETWEEN 1 AND 8388608),
    CONSTRAINT geometry_text_payload_is_bounded
        CHECK (payload_text IS NULL
               OR octet_length(convert_to(payload_text, 'UTF8')) BETWEEN 1 AND 8388608),

    CONSTRAINT geometry_crs_is_bounded
        CHECK (canonical.is_bounded_text(crs, 64)),

    -- The parent must be a snapshot of this record's own release. It need not be
    -- of the same load or artifact: the promoted capability permits two snapshots
    -- at one grain with different artifact lineage, and a same-release enrichment
    -- from a second artifact would otherwise be unrepresentable.
    CONSTRAINT geometry_observation_parent_is_of_its_release
        FOREIGN KEY (snapshot_key, release_key)
        REFERENCES canonical.account_snapshot (snapshot_key, release_key),
    -- This record's own release and load are its provenance's, so neither can be
    -- moved independently of the lineage it claims.
    CONSTRAINT geometry_observation_lineage_is_its_provenance
        FOREIGN KEY (provenance_key, release_key, load_key)
        REFERENCES canonical.provenance (provenance_key, release_key, load_key)
);

COMMENT ON TABLE canonical.geometry_observation IS
    'Geometry as an enrichment, carried opaquely. payload_bytes and payload_text are one '
    'logical payload: the two mutual-exclusion checks above make exactly one populated and '
    'make it the one the encoding names, so a reader takes whichever the encoding says. '
    'A snapshot may carry several geometries -- no constraint mentions snapshot_key alone -- '
    'because no accepted contract establishes that a county publishes only one. Geometry '
    'present for an account is not evidence that a complete appraisal record exists for it.';
COMMENT ON COLUMN canonical.geometry_observation.crs IS
    'The coordinate reference as the source stated it. Required, and never inferred: a '
    'default here would place geometry somewhere nobody chose.';

CREATE INDEX geometry_observation_by_snapshot
    ON canonical.geometry_observation (snapshot_key, release_key);

COMMENT ON COLUMN canonical.geometry_observation.geometry_key IS
    'A persistence locator for foreign-key mechanics, not business identity.';

GRANT SELECT, INSERT ON canonical.geometry_observation TO property_tax_ingestion;

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (16, '0016_canonical_geometry', :'file_sha256');

COMMIT;
