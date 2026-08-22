-- 0002_silver_source_records.sql
--
-- Silver source records: county rows at adapter grain, vendor-neutral, with their origin
-- attached and nothing inferred.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0002_silver_source_records.sql | cut -d' ' -f1)" \
--              -f 0002_silver_source_records.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 1) THEN
        RAISE EXCEPTION 'migration 0001 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 2) THEN
        RAISE EXCEPTION 'migration 0002 is already applied';
    END IF;
END $$;

CREATE SCHEMA silver;

COMMENT ON SCHEMA silver IS
    'Normalized county data at source grain. Normalized means vendor-neutral shape, '
    'not corrected values: what a county said is preserved exactly as it said it.';

-- ---------------------------------------------------------------------------
-- One county row, with where it came from
-- ---------------------------------------------------------------------------

CREATE TABLE silver.source_record (
    record_id                 bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    jurisdiction_code         text        NOT NULL,
    appraisal_year            integer     NOT NULL,
    source_account_id         text,
    source_family             text,
    source_status             text,
    parcel_reference          text,

    -- Provenance is inlined rather than referenced, because a source-native
    -- record whose origin is unknown is not evidence of anything, and a
    -- nullable foreign key would make "unknown" representable.
    release_identifier        text        NOT NULL,
    source_member_name        text        NOT NULL,
    source_row_number         integer     NOT NULL,
    parser_contract_version   integer     NOT NULL,
    layout_fingerprint        text        NOT NULL,
    provenance_table_name     text,
    provenance_source_family  text,
    provenance_source_year    integer,
    provenance_source_status  text,
    observed_fields           text[],
    normalized_fields         text[],

    -- No standalone reference: 0003 binds this together with run_id,
    -- jurisdiction_code, and release_identifier to one run, so the four cannot
    -- describe different releases.
    manifest_id               bigint      NOT NULL,
    loaded_at                 timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT record_jurisdiction_is_state_and_county
        CHECK (jurisdiction_code ~ '^[a-z]{2}-[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT record_appraisal_year_positive
        CHECK (appraisal_year >= 1),
    CONSTRAINT record_source_row_number_one_based
        CHECK (source_row_number >= 1),
    CONSTRAINT record_parser_contract_version_positive
        CHECK (parser_contract_version >= 1),
    CONSTRAINT record_provenance_source_year_positive
        CHECK (provenance_source_year IS NULL OR provenance_source_year >= 1),
    CONSTRAINT record_release_identifier_not_blank
        CHECK (platform.is_named(release_identifier)),
    CONSTRAINT record_source_member_name_not_blank
        CHECK (platform.is_named(source_member_name)),
    CONSTRAINT record_layout_fingerprint_not_blank
        CHECK (platform.is_named(layout_fingerprint)),
    CONSTRAINT record_optional_text_not_blank CHECK (
        (source_account_id        IS NULL OR platform.is_named(source_account_id))        AND
        (source_family            IS NULL OR platform.is_named(source_family))            AND
        (source_status            IS NULL OR platform.is_named(source_status))            AND
        (parcel_reference         IS NULL OR platform.is_named(parcel_reference))         AND
        (provenance_table_name    IS NULL OR platform.is_named(provenance_table_name))    AND
        (provenance_source_family IS NULL OR platform.is_named(provenance_source_family)) AND
        (provenance_source_status IS NULL OR platform.is_named(provenance_source_status))
    )
);

COMMENT ON TABLE silver.source_record IS
    'One county row as the county published it. Accounts are not deduplicated and '
    'identifiers are not treated as equivalent across counties: one artifact row '
    'carrying current and certified observations becomes one record per observation.';
COMMENT ON COLUMN silver.source_record.source_account_id IS
    'Nullable on purpose. Collin publishes no single account identifier, and inventing '
    'one would make an absent fact look like a present one; its identifiers live in '
    'silver.source_native_identifier under their exact source names.';
COMMENT ON COLUMN silver.source_record.observed_fields IS
    'NULL means the county records no field vector. An empty array means it recorded '
    'an empty one. Those are different facts and the column keeps them apart.';

-- Idempotent retry. NULLS NOT DISTINCT because an absent source_family is a
-- value here, not an unknown: two loads of the same row must collide rather
-- than quietly become two records.
--
-- jurisdiction_code leads the key because release_identifier is caller-supplied
-- and local to a county, not a global name. Dallas and Collin can each publish
-- "certified-2025" containing a "property.txt" with a row 100, and those are two
-- different facts. Without the county in the key the second county to load
-- collides with the first and its rows are silently rejected as retries.
CREATE UNIQUE INDEX source_record_logical_identity
    ON silver.source_record (
        jurisdiction_code,
        release_identifier,
        source_member_name,
        source_row_number,
        appraisal_year,
        source_family,
        source_status
    )
    NULLS NOT DISTINCT;

CREATE INDEX source_record_by_account
    ON silver.source_record (jurisdiction_code, source_account_id, appraisal_year)
    WHERE source_account_id IS NOT NULL;
CREATE INDEX source_record_by_release
    ON silver.source_record (release_identifier);

-- ---------------------------------------------------------------------------
-- Identifiers under their exact source names
-- ---------------------------------------------------------------------------

CREATE TABLE silver.source_native_identifier (
    record_id         bigint NOT NULL
                             REFERENCES silver.source_record (record_id) ON DELETE CASCADE,
    identifier_name   text   NOT NULL,
    identifier_value  text   NOT NULL,

    PRIMARY KEY (record_id, identifier_name),
    CONSTRAINT native_identifier_name_not_blank  CHECK (platform.is_named(identifier_name)),
    CONSTRAINT native_identifier_value_not_blank CHECK (platform.is_named(identifier_value))
);

COMMENT ON TABLE silver.source_native_identifier IS
    'Identifiers keyed by the name the county used, not by a name this platform chose. '
    'Collin''s prop_id and geo_id stay separate and stay themselves.';

-- ---------------------------------------------------------------------------
-- Values, exactly as observed
-- ---------------------------------------------------------------------------

CREATE TABLE silver.source_native_value (
    record_id         bigint  NOT NULL
                              REFERENCES silver.source_record (record_id) ON DELETE CASCADE,
    source_field      text    NOT NULL,
    classification    text    NOT NULL DEFAULT 'source-native',
    lexical_text      text,
    text_value        text,
    integer_value     bigint,
    numeric_value     numeric,
    numeric_precision integer,
    numeric_scale     integer,

    PRIMARY KEY (record_id, source_field),
    CONSTRAINT native_value_source_field_not_blank
        CHECK (platform.is_named(source_field)),
    CONSTRAINT native_value_classification_is_source_native
        CHECK (classification = 'source-native'),
    CONSTRAINT native_value_has_exactly_one_representation CHECK (
        (text_value    IS NOT NULL)::integer +
        (integer_value IS NOT NULL)::integer +
        (numeric_value IS NOT NULL)::integer = 1
    ),
    CONSTRAINT native_value_precision_and_scale_together
        CHECK ((numeric_precision IS NULL) = (numeric_scale IS NULL)),
    CONSTRAINT native_value_precision_and_scale_describe_a_number
        CHECK (numeric_precision IS NULL OR numeric_value IS NOT NULL),
    CONSTRAINT native_value_precision_positive
        CHECK (numeric_precision IS NULL OR numeric_precision >= 1),
    CONSTRAINT native_value_scale_not_negative
        CHECK (numeric_scale IS NULL OR numeric_scale >= 0)
);

COMMENT ON TABLE silver.source_native_value IS
    'One value exactly as a county observed it. Three typed columns with exactly one '
    'populated, because a value that is text in the source and a number here has '
    'already been interpreted.';
COMMENT ON COLUMN silver.source_native_value.lexical_text IS
    'The characters the source actually carried, kept beside the typed value. An '
    'observed empty string is a fact about the source and is deliberately allowed.';
COMMENT ON COLUMN silver.source_native_value.classification IS
    'Fixed at source-native. The column exists so a later classification cannot be '
    'added by widening a value; it would have to add a constraint someone must read.';

-- ---------------------------------------------------------------------------
-- What may be published, which is nothing until someone approves it
-- ---------------------------------------------------------------------------

CREATE TABLE silver.field_publication_policy (
    jurisdiction_code   text        NOT NULL,
    source_field        text        NOT NULL,
    sensitivity         text        NOT NULL,
    publication_allowed boolean     NOT NULL DEFAULT false,
    approved_by         text,
    approved_at         timestamptz,
    review_reference    text,

    PRIMARY KEY (jurisdiction_code, source_field),
    CONSTRAINT policy_sensitivity_is_known
        CHECK (sensitivity IN ('sensitive', 'ordinary')),
    CONSTRAINT policy_permission_carries_its_approval CHECK (
        NOT publication_allowed
        OR (
            approved_at IS NOT NULL
            -- btrim of the ASCII control range as well as spaces: '' and '\t'
            -- are not a named approver, and neither is a tab someone pasted.
            AND platform.is_named(coalesce(approved_by, ''))
            AND platform.is_named(coalesce(review_reference, ''))
        )
    )
);

COMMENT ON TABLE silver.field_publication_policy IS
    'Default-deny. A field is publishable only with a named approver, an approval '
    'time, and a review reference, so permission cannot be granted by a migration '
    'or a default. Owner names, mailing addresses, and publisher confidentiality '
    'markers are sensitive until a reviewed county policy says otherwise, and the '
    'absence of a protected-owner flag is not evidence that a row is safe.';

-- ---------------------------------------------------------------------------
-- Privileges
--
-- Granted here rather than later, because the bootstrap leaves both roles able
-- only to connect and an object with no grant is invisible to the role that
-- needs it.  The ALTER DEFAULT PRIVILEGES lines are what make a table added by
-- a later migration reachable without anyone remembering to come back.
--
-- No sequence grants: every generated key is GENERATED ALWAYS AS IDENTITY, whose
-- implicit sequence is covered by INSERT on the table.
-- ---------------------------------------------------------------------------

GRANT USAGE ON SCHEMA silver TO property_tax_ingestion;

GRANT SELECT, INSERT, UPDATE ON
    silver.source_record,
    silver.source_native_identifier,
    silver.source_native_value
    TO property_tax_ingestion;

GRANT SELECT ON silver.field_publication_policy TO property_tax_ingestion;

ALTER DEFAULT PRIVILEGES FOR ROLE property_tax_migrator IN SCHEMA silver
    GRANT SELECT, INSERT, UPDATE ON TABLES TO property_tax_ingestion;

-- property_tax_api is granted nothing in silver, deliberately.
--
-- field_publication_policy is metadata: no view, no row policy, and no privilege
-- applies it, so SELECT on source_native_value would return every retained value
-- including those whose policy says publication_allowed = false. Dallas retains
-- every unknown extra column by accepted contract (issue #78), so an OWNER_NAME
-- or address-shaped column in a real release would land there.
--
-- The API reads approved Gold products through bounded projections that do not
-- exist yet. Until they do, connect-only is the honest privilege.

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (2, '0002_silver_source_records', :'file_sha256');

COMMIT;
