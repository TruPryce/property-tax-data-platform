-- 0013_canonical_values.sql
--
-- Account-level appraisal values, the taxing units a county names, and the
-- taxable values that exist only for one of them.
--
-- The canonical vocabulary is market, appraised, and assessed. Taxable is not a
-- member of it: a taxable value is qualified by a taxing unit, and one that is
-- not has no shape to live in.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0013_canonical_values.sql | cut -d' ' -f1)" \
--              -f 0013_canonical_values.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 12) THEN
        RAISE EXCEPTION 'migration 0012 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 13) THEN
        RAISE EXCEPTION 'migration 0013 is already applied';
    END IF;
END $$;

-- Every canonical migration references a relation that may hold rows by the time
-- it is applied, and adding a foreign key takes ShareRowExclusiveLock on the
-- referenced one. Yield rather than queue production traffic behind this.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '300s';

CREATE TABLE canonical.appraisal_value_observation (
    value_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_key   bigint NOT NULL,
    release_key    bigint NOT NULL,
    load_key       bigint NOT NULL,
    provenance_key bigint NOT NULL,
    kind   text    NOT NULL,
    amount numeric NOT NULL,

    -- Three members and no fourth. No taxable, and no land, improvement,
    -- agricultural, timber, productivity, or cap kind: mapping a source-native
    -- value into a canonical kind needs an accepted contract establishing
    -- equivalence, and widening this set would be how a resemblance becomes one.
    CONSTRAINT appraisal_value_kind_is_canonical
        CHECK (kind IN ('market', 'appraised', 'assessed')),
    CONSTRAINT appraisal_value_amount_is_finite
        CHECK (canonical.is_finite(amount)),

    -- The parent must be a snapshot of this record's own release. It need not be
    -- of the same load or artifact: the promoted capability permits two snapshots
    -- at one grain with different artifact lineage, and a same-release enrichment
    -- from a second artifact would otherwise be unrepresentable.
    CONSTRAINT appraisal_value_observation_parent_is_of_its_release
        FOREIGN KEY (snapshot_key, release_key)
        REFERENCES canonical.account_snapshot (snapshot_key, release_key),
    -- This record's own release and load are its provenance's, so neither can be
    -- moved independently of the lineage it claims.
    CONSTRAINT appraisal_value_observation_lineage_is_its_provenance
        FOREIGN KEY (provenance_key, release_key, load_key)
        REFERENCES canonical.provenance (provenance_key, release_key, load_key)
);

COMMENT ON TABLE canonical.appraisal_value_observation IS
    'One canonical market, appraised, or assessed value. Nothing limits a snapshot to one '
    'value of a kind: no accepted contract establishes that, so no constraint says it. '
    'A source-native total whose meaning is unresolved has no destination here and stays '
    'at adapter grain with its lineage.';
COMMENT ON COLUMN canonical.appraisal_value_observation.amount IS
    'Unconstrained numeric: no accepted contract fixes a precision or scale, and NUMERIC(p,s) '
    'would silently round a county value to fit. Negative is permitted because some rolls '
    'carry adjustments, and zero is a figure counties publish rather than an absent value.';

CREATE INDEX appraisal_value_observation_by_snapshot
    ON canonical.appraisal_value_observation (snapshot_key, release_key);

CREATE TABLE canonical.taxing_unit_observation (
    taxing_unit_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_key   bigint NOT NULL,
    release_key    bigint NOT NULL,
    load_key       bigint NOT NULL,
    provenance_key bigint NOT NULL,
    unit_code text NOT NULL,
    unit_name text,

    CONSTRAINT taxing_unit_code_is_an_identifier
        CHECK (canonical.is_identifier(unit_code)),
    CONSTRAINT taxing_unit_name_is_a_label
        CHECK (canonical.is_bounded_text(unit_name, 256) IS NOT FALSE),

    CONSTRAINT taxing_unit_carries_its_snapshot UNIQUE (taxing_unit_key, snapshot_key),

    -- The parent must be a snapshot of this record's own release. It need not be
    -- of the same load or artifact: the promoted capability permits two snapshots
    -- at one grain with different artifact lineage, and a same-release enrichment
    -- from a second artifact would otherwise be unrepresentable.
    CONSTRAINT taxing_unit_observation_parent_is_of_its_release
        FOREIGN KEY (snapshot_key, release_key)
        REFERENCES canonical.account_snapshot (snapshot_key, release_key),
    -- This record's own release and load are its provenance's, so neither can be
    -- moved independently of the lineage it claims.
    CONSTRAINT taxing_unit_observation_lineage_is_its_provenance
        FOREIGN KEY (provenance_key, release_key, load_key)
        REFERENCES canonical.provenance (provenance_key, release_key, load_key)
);

COMMENT ON TABLE canonical.taxing_unit_observation IS
    'A school district, city, county tax unit, or similar, as the county named it. Not the '
    'appraisal jurisdiction, which identifies the district publishing a roll, and not '
    'substitutable for it. There is no canonical cross-county taxing-unit registry and no '
    'vocabulary on either column: no accepted contract establishes one.';

CREATE INDEX taxing_unit_observation_by_snapshot
    ON canonical.taxing_unit_observation (snapshot_key, release_key);

CREATE TABLE canonical.taxable_value_observation (
    taxable_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_key   bigint NOT NULL,
    release_key    bigint NOT NULL,
    load_key       bigint NOT NULL,
    provenance_key bigint NOT NULL,
    taxing_unit_key bigint  NOT NULL,
    amount          numeric NOT NULL,
    basis           text    NOT NULL,

    CONSTRAINT taxable_value_amount_is_finite
        CHECK (canonical.is_finite(amount)),
    CONSTRAINT taxable_value_basis_is_a_label
        CHECK (canonical.is_bounded_text(basis, 256)),

    -- NOT NULL, and of this snapshot. A property-wide taxable value is not
    -- rejected by a check; it has no representable form, which is the difference
    -- between a rule and a shape.
    CONSTRAINT taxable_value_names_a_taxing_unit_of_its_snapshot
        FOREIGN KEY (taxing_unit_key, snapshot_key)
        REFERENCES canonical.taxing_unit_observation (taxing_unit_key, snapshot_key),

    -- The parent must be a snapshot of this record's own release. It need not be
    -- of the same load or artifact: the promoted capability permits two snapshots
    -- at one grain with different artifact lineage, and a same-release enrichment
    -- from a second artifact would otherwise be unrepresentable.
    CONSTRAINT taxable_value_observation_parent_is_of_its_release
        FOREIGN KEY (snapshot_key, release_key)
        REFERENCES canonical.account_snapshot (snapshot_key, release_key),
    -- This record's own release and load are its provenance's, so neither can be
    -- moved independently of the lineage it claims.
    CONSTRAINT taxable_value_observation_lineage_is_its_provenance
        FOREIGN KEY (provenance_key, release_key, load_key)
        REFERENCES canonical.provenance (provenance_key, release_key, load_key)
);

COMMENT ON TABLE canonical.taxable_value_observation IS
    'A taxable value, qualified by the taxing unit it applies to. Several units on one '
    'account are several rows, each keeping its own unit and its source-native basis, and '
    'none is selected to stand for the account. There is no default taxing unit.';
COMMENT ON COLUMN canonical.taxable_value_observation.basis IS
    'The county''s own word for what this figure is measured against, preserved verbatim. '
    'Carrying a label is not canonicalizing it, and no vocabulary constrains this column.';

CREATE INDEX taxable_value_observation_by_snapshot
    ON canonical.taxable_value_observation (snapshot_key, release_key);

COMMENT ON COLUMN canonical.appraisal_value_observation.value_key IS
    'A persistence locator for foreign-key mechanics, not business identity.';

COMMENT ON COLUMN canonical.taxing_unit_observation.taxing_unit_key IS
    'A persistence locator for foreign-key mechanics, not business identity.';

COMMENT ON COLUMN canonical.taxable_value_observation.taxable_key IS
    'A persistence locator for foreign-key mechanics, not business identity.';

GRANT SELECT, INSERT ON
    canonical.appraisal_value_observation,
    canonical.taxing_unit_observation,
    canonical.taxable_value_observation
    TO property_tax_ingestion;

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (13, '0013_canonical_values', :'file_sha256');

COMMIT;
