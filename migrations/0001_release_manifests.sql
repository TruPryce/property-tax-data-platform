-- 0001_release_manifests.sql
--
-- Bronze lineage: the bytes that arrived, where they came from, and which
-- logical releases they carry.
--
-- Run with:  psql --single-transaction --set ON_ERROR_STOP=on -f 0001_release_manifests.sql
--
-- The whole file is one transaction. A migration that half-applies is worse
-- than one that fails, because the second is obvious.

BEGIN;

DO $$
BEGIN
    -- Checked before anything is created, so a too-old server fails on line one
    -- rather than on the first index that needs the feature.
    IF current_setting('server_version_num')::integer < 150000 THEN
        RAISE EXCEPTION
            'PostgreSQL 15 or newer is required for NULLS NOT DISTINCT indexes; this server reports %',
            current_setting('server_version');
    END IF;
END $$;

CREATE SCHEMA platform;
CREATE SCHEMA bronze;

COMMENT ON SCHEMA platform IS
    'Facts about the database itself rather than about any county.';
COMMENT ON SCHEMA bronze IS
    'Immutable acquisition evidence. Nothing here is derived, corrected, or normalized.';

-- ---------------------------------------------------------------------------
-- What has been applied
-- ---------------------------------------------------------------------------

CREATE TABLE platform.schema_migration (
    version           integer     PRIMARY KEY,
    name              text        NOT NULL,
    applied_at        timestamptz NOT NULL DEFAULT now(),
    applied_by        text        NOT NULL DEFAULT current_user,

    CONSTRAINT schema_migration_name_not_blank CHECK (btrim(name) <> '')
);

COMMENT ON TABLE platform.schema_migration IS
    'One row per applied migration. These files are run by hand, so this is where '
    '"what is applied" is recorded rather than inferred from which tables happen to exist.';

-- ---------------------------------------------------------------------------
-- The bytes
-- ---------------------------------------------------------------------------

CREATE TABLE bronze.artifact (
    sha256            text        PRIMARY KEY,
    locator           text        NOT NULL,
    byte_count        bigint      NOT NULL,
    media_type        text,
    first_recorded_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT artifact_sha256_is_lowercase_hex
        CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT artifact_byte_count_not_negative
        CHECK (byte_count >= 0),
    CONSTRAINT artifact_locator_not_blank
        CHECK (btrim(locator) <> ''),
    CONSTRAINT artifact_locator_carries_no_control_character
        CHECK (locator !~ '[[:cntrl:]]'),
    CONSTRAINT artifact_media_type_not_blank
        CHECK (media_type IS NULL OR btrim(media_type) <> '')
);

COMMENT ON TABLE bronze.artifact IS
    'One row per distinct set of bytes, keyed by content. Two acquisitions of the '
    'same bytes are one artifact; the same release identity arriving with different '
    'bytes is two, which is what makes divergence visible rather than destructive.';
COMMENT ON COLUMN bronze.artifact.locator IS
    'Where the object durably lives. Constrained against control characters so a '
    'host-local path cannot be smuggled in.';

-- ---------------------------------------------------------------------------
-- The acquisition
-- ---------------------------------------------------------------------------

CREATE TABLE bronze.release_manifest (
    manifest_id       bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    jurisdiction_code text        NOT NULL,
    artifact_sha256   text        NOT NULL REFERENCES bronze.artifact (sha256),
    acquired_at       timestamptz NOT NULL,
    source_url        text        NOT NULL,
    response_status   integer     NOT NULL,
    response_headers  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    manifest_version  integer     NOT NULL,
    tool_versions     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    recorded_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT manifest_jurisdiction_is_state_and_county
        CHECK (jurisdiction_code ~ '^[a-z]{2}-[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT manifest_response_status_is_a_status
        CHECK (response_status BETWEEN 100 AND 599),
    CONSTRAINT manifest_version_positive
        CHECK (manifest_version >= 1),
    CONSTRAINT manifest_source_url_not_blank
        CHECK (btrim(source_url) <> ''),
    CONSTRAINT manifest_headers_is_an_object
        CHECK (jsonb_typeof(response_headers) = 'object'),
    CONSTRAINT manifest_tool_versions_is_an_object
        CHECK (jsonb_typeof(tool_versions) = 'object')
);

COMMENT ON TABLE bronze.release_manifest IS
    'One acquisition event. Response metadata is bounded and sanitized before it '
    'arrives here; there is no column for a response body, a credential, or a header '
    'the acquisition layer did not admit.';

CREATE INDEX release_manifest_by_artifact
    ON bronze.release_manifest (artifact_sha256);
CREATE INDEX release_manifest_by_jurisdiction_and_time
    ON bronze.release_manifest (jurisdiction_code, acquired_at DESC);

CREATE TABLE bronze.release_redirect (
    manifest_id       bigint      NOT NULL
                                  REFERENCES bronze.release_manifest (manifest_id)
                                  ON DELETE CASCADE,
    hop_index         integer     NOT NULL,
    from_url          text        NOT NULL,
    to_url            text        NOT NULL,
    status            integer     NOT NULL,

    PRIMARY KEY (manifest_id, hop_index),
    CONSTRAINT redirect_hop_index_zero_based CHECK (hop_index >= 0),
    CONSTRAINT redirect_status_is_a_status    CHECK (status BETWEEN 100 AND 599),
    CONSTRAINT redirect_urls_not_blank
        CHECK (btrim(from_url) <> '' AND btrim(to_url) <> '')
);

COMMENT ON TABLE bronze.release_redirect IS
    'The validated hop chain, ordered. Kept because where a download actually went '
    'is provenance, and a county that starts redirecting somewhere new is a fact.';

-- ---------------------------------------------------------------------------
-- The logical releases those bytes carry
-- ---------------------------------------------------------------------------

CREATE TABLE bronze.release_partition (
    manifest_id       bigint      NOT NULL
                                  REFERENCES bronze.release_manifest (manifest_id)
                                  ON DELETE CASCADE,
    jurisdiction_code text        NOT NULL,
    tax_year          integer     NOT NULL,
    release_kind      text        NOT NULL,

    PRIMARY KEY (manifest_id, jurisdiction_code, tax_year, release_kind),
    CONSTRAINT partition_jurisdiction_is_state_and_county
        CHECK (jurisdiction_code ~ '^[a-z]{2}-[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT partition_tax_year_plausible
        CHECK (tax_year BETWEEN 1900 AND 2200),
    CONSTRAINT partition_release_kind_is_an_identifier
        CHECK (release_kind ~ '^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$')
);

COMMENT ON TABLE bronze.release_partition IS
    'One logical release backed by an artifact. Separate from the artifact because '
    'they are different counts: one measured Collin archive carries current values '
    'for one tax year and certified values for another, and both are releases '
    'sharing one set of bytes and one acquisition event.';

CREATE INDEX release_partition_by_identity
    ON bronze.release_partition (jurisdiction_code, tax_year, release_kind);

-- ---------------------------------------------------------------------------
-- Divergence, derived
-- ---------------------------------------------------------------------------

CREATE VIEW bronze.diverged_release AS
SELECT
    partition.jurisdiction_code,
    partition.tax_year,
    partition.release_kind,
    count(DISTINCT manifest.artifact_sha256) AS distinct_artifact_count,
    min(manifest.acquired_at)                AS first_acquired_at,
    max(manifest.acquired_at)                AS last_acquired_at
FROM bronze.release_partition AS partition
JOIN bronze.release_manifest  AS manifest USING (manifest_id)
GROUP BY partition.jurisdiction_code, partition.tax_year, partition.release_kind
HAVING count(DISTINCT manifest.artifact_sha256) > 1;

COMMENT ON VIEW bronze.diverged_release IS
    'The same release identity recorded against different bytes. A view rather than '
    'a column on purpose: a stored verdict is a claim about what else existed when '
    'some writer looked, and two writers can both look, both see nothing, and both '
    'write. The only honest answer is computed when the question is asked.';

INSERT INTO platform.schema_migration (version, name)
VALUES (1, '0001_release_manifests');

COMMIT;
