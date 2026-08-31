-- 0015_canonical_land_and_improvements.sql
--
-- Land and improvement children, at their own grain and with no invented key.
--
-- Two relations rather than one shared shape with mostly-absent fields: they are
-- different things that happen to share four attributes.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0015_canonical_land_and_improvements.sql | cut -d' ' -f1)" \
--              -f 0015_canonical_land_and_improvements.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 14) THEN
        RAISE EXCEPTION 'migration 0014 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 15) THEN
        RAISE EXCEPTION 'migration 0015 is already applied';
    END IF;
END $$;

-- Every canonical migration references a relation that may hold rows by the time
-- it is applied, and adding a foreign key takes ShareRowExclusiveLock on the
-- referenced one. Yield rather than queue production traffic behind this.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '300s';

CREATE TABLE canonical.land_observation (
    land_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_key   bigint NOT NULL,
    release_key    bigint NOT NULL,
    load_key       bigint NOT NULL,
    provenance_key bigint NOT NULL,
    source_discriminator text,
    classification       text,
    area                 numeric,
    area_unit            text,

    CONSTRAINT land_observation_discriminator_is_an_identifier
        CHECK (source_discriminator IS NULL OR canonical.is_identifier(source_discriminator)),
    CONSTRAINT land_observation_classification_is_a_label
        CHECK (canonical.is_bounded_text(classification, 256) IS NOT FALSE),
    CONSTRAINT land_observation_area_unit_is_a_label
        CHECK (canonical.is_bounded_text(area_unit, 256) IS NOT FALSE),
    -- A magnitude, not an amount: a monetary figure may legitimately be negative
    -- and a measured extent may not. Zero is accepted.
    CONSTRAINT land_observation_area_is_a_magnitude
        CHECK (area IS NULL OR (canonical.is_finite(area) AND area >= 0)),
    CONSTRAINT land_observation_area_and_unit_arrive_together
        CHECK ((area IS NULL) = (area_unit IS NULL)),

    -- The parent must be a snapshot of this record's own release. It need not be
    -- of the same load or artifact: the promoted capability permits two snapshots
    -- at one grain with different artifact lineage, and a same-release enrichment
    -- from a second artifact would otherwise be unrepresentable.
    CONSTRAINT land_observation_parent_is_of_its_release
        FOREIGN KEY (snapshot_key, release_key)
        REFERENCES canonical.account_snapshot (snapshot_key, release_key),
    -- This record's own release and load are its provenance's, so neither can be
    -- moved independently of the lineage it claims.
    CONSTRAINT land_observation_lineage_is_its_provenance
        FOREIGN KEY (provenance_key, release_key, load_key)
        REFERENCES canonical.provenance (provenance_key, release_key, load_key)
);

COMMENT ON TABLE canonical.land_observation IS
    'One land record at child grain. No natural key is invented: a sequence number, row '
    'number, or physical ordering is not a stable business identity unless an accepted '
    'county contract establishes one, and where a source child key is unresolved the '
    'discriminator is absent rather than fabricated. Nothing limits how many a snapshot '
    'may carry.';

CREATE INDEX land_observation_by_snapshot
    ON canonical.land_observation (snapshot_key, release_key);

CREATE TABLE canonical.improvement_observation (
    improvement_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_key   bigint NOT NULL,
    release_key    bigint NOT NULL,
    load_key       bigint NOT NULL,
    provenance_key bigint NOT NULL,
    source_discriminator text,
    classification       text,
    area                 numeric,
    area_unit            text,
    year_built           integer,
    CONSTRAINT improvement_observation_discriminator_is_an_identifier
        CHECK (source_discriminator IS NULL OR canonical.is_identifier(source_discriminator)),
    CONSTRAINT improvement_observation_classification_is_a_label
        CHECK (canonical.is_bounded_text(classification, 256) IS NOT FALSE),
    CONSTRAINT improvement_observation_area_unit_is_a_label
        CHECK (canonical.is_bounded_text(area_unit, 256) IS NOT FALSE),
    -- A magnitude, not an amount: a monetary figure may legitimately be negative
    -- and a measured extent may not. Zero is accepted.
    CONSTRAINT improvement_observation_area_is_a_magnitude
        CHECK (area IS NULL OR (canonical.is_finite(area) AND area >= 0)),
    CONSTRAINT improvement_observation_area_and_unit_arrive_together
        CHECK ((area IS NULL) = (area_unit IS NULL)),
    -- The year rule, 1600 through 2200. Deliberately a different bound from a
    -- release tax year, which is 1900 through 2200: they are different values.
    CONSTRAINT improvement_observation_year_built_is_a_year
        CHECK (year_built IS NULL OR year_built BETWEEN 1600 AND 2200),
    -- The parent must be a snapshot of this record's own release. It need not be
    -- of the same load or artifact: the promoted capability permits two snapshots
    -- at one grain with different artifact lineage, and a same-release enrichment
    -- from a second artifact would otherwise be unrepresentable.
    CONSTRAINT improvement_observation_parent_is_of_its_release
        FOREIGN KEY (snapshot_key, release_key)
        REFERENCES canonical.account_snapshot (snapshot_key, release_key),
    -- This record's own release and load are its provenance's, so neither can be
    -- moved independently of the lineage it claims.
    CONSTRAINT improvement_observation_lineage_is_its_provenance
        FOREIGN KEY (provenance_key, release_key, load_key)
        REFERENCES canonical.provenance (provenance_key, release_key, load_key)
);

COMMENT ON TABLE canonical.improvement_observation IS
    'One improvement record at child grain, kept separate from land rather than merged into '
    'the account snapshot. Several improvements on one account are several rows, each with '
    'its own lineage.';

CREATE INDEX improvement_observation_by_snapshot
    ON canonical.improvement_observation (snapshot_key, release_key);

COMMENT ON COLUMN canonical.land_observation.land_key IS
    'A persistence locator for foreign-key mechanics, not business identity. No natural '
    'land key is invented, so a sequence or row number is not smuggled in here either.';

COMMENT ON COLUMN canonical.improvement_observation.improvement_key IS
    'A persistence locator for foreign-key mechanics, not business identity. A building '
    'number is not a business identity unless a county contract establishes one, and none '
    'does.';

GRANT SELECT, INSERT ON
    canonical.land_observation,
    canonical.improvement_observation
    TO property_tax_ingestion;

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (15, '0015_canonical_land_and_improvements', :'file_sha256');

COMMIT;
