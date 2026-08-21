-- 0002_silver_canonical.sql
--
-- Silver: county rows at source grain, vendor-neutral, with their origin
-- attached and nothing inferred.
--
-- Run with:  psql --single-transaction --set ON_ERROR_STOP=on -f 0002_silver_canonical.sql

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

    manifest_id               bigint      REFERENCES bronze.release_manifest (manifest_id),
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
        CHECK (btrim(release_identifier) <> ''),
    CONSTRAINT record_source_member_name_not_blank
        CHECK (btrim(source_member_name) <> ''),
    CONSTRAINT record_layout_fingerprint_not_blank
        CHECK (btrim(layout_fingerprint) <> ''),
    CONSTRAINT record_optional_text_not_blank CHECK (
        (source_account_id        IS NULL OR btrim(source_account_id)        <> '') AND
        (source_family            IS NULL OR btrim(source_family)            <> '') AND
        (source_status            IS NULL OR btrim(source_status)            <> '') AND
        (parcel_reference         IS NULL OR btrim(parcel_reference)         <> '') AND
        (provenance_table_name    IS NULL OR btrim(provenance_table_name)    <> '') AND
        (provenance_source_family IS NULL OR btrim(provenance_source_family) <> '') AND
        (provenance_source_status IS NULL OR btrim(provenance_source_status) <> '')
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
CREATE UNIQUE INDEX source_record_logical_identity
    ON silver.source_record (
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
    CONSTRAINT native_identifier_name_not_blank  CHECK (btrim(identifier_name) <> ''),
    CONSTRAINT native_identifier_value_not_blank CHECK (btrim(identifier_value) <> '')
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
        CHECK (btrim(source_field) <> ''),
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
        OR (approved_by IS NOT NULL AND approved_at IS NOT NULL AND review_reference IS NOT NULL)
    )
);

COMMENT ON TABLE silver.field_publication_policy IS
    'Default-deny. A field is publishable only with a named approver, an approval '
    'time, and a review reference, so permission cannot be granted by a migration '
    'or a default. Owner names, mailing addresses, and publisher confidentiality '
    'markers are sensitive until a reviewed county policy says otherwise, and the '
    'absence of a protected-owner flag is not evidence that a row is safe.';

INSERT INTO platform.schema_migration (version, name)
VALUES (2, '0002_silver_canonical');

COMMIT;
