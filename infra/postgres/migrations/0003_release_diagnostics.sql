-- 0003_release_diagnostics.sql
--
-- What happened during one processing run, in the closed vocabulary the
-- boundary already speaks.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0003_release_diagnostics.sql | cut -d' ' -f1)" \
--              -f 0003_release_diagnostics.sql

\if :{?file_sha256}
\else
\echo 'ERROR: pass -v file_sha256="$(sha256sum <this file> | cut -d\' \' -f1)"'
\quit
\endif

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 2) THEN
        RAISE EXCEPTION 'migration 0002 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 3) THEN
        RAISE EXCEPTION 'migration 0003 is already applied';
    END IF;
END $$;

CREATE SCHEMA ingestion;

COMMENT ON SCHEMA ingestion IS
    'Processing runs and their outcomes. Evidence about a release, never content from it.';

CREATE TABLE ingestion.run (
    run_id             bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    jurisdiction_code  text        NOT NULL,
    release_identifier text        NOT NULL,
    manifest_id        bigint      REFERENCES bronze.release_manifest (manifest_id),
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz,

    CONSTRAINT run_jurisdiction_is_state_and_county
        CHECK (jurisdiction_code ~ '^[a-z]{2}-[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT run_release_identifier_not_blank
        CHECK (btrim(release_identifier) <> ''),
    CONSTRAINT run_finishes_after_it_starts
        CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE INDEX run_by_release ON ingestion.run (release_identifier, started_at DESC);

-- ---------------------------------------------------------------------------
-- The verdict
-- ---------------------------------------------------------------------------

CREATE TABLE ingestion.release_outcome (
    outcome_id                bigint  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                    bigint  NOT NULL UNIQUE
                                      REFERENCES ingestion.run (run_id) ON DELETE CASCADE,
    disposition               text    NOT NULL,
    boundary_contract_version integer NOT NULL,
    parser_contract_version   integer,
    layout_fingerprint        text,

    physical_rows_processed   bigint  NOT NULL DEFAULT 0,
    staged_record_count       bigint  NOT NULL DEFAULT 0,
    committed_record_count    bigint  NOT NULL DEFAULT 0,
    rejected_row_count        bigint  NOT NULL DEFAULT 0,

    total_diagnostic_count    integer NOT NULL DEFAULT 0,
    diagnostics_truncated     boolean NOT NULL DEFAULT false,
    total_notice_count        integer NOT NULL DEFAULT 0,
    notices_truncated         boolean NOT NULL DEFAULT false,

    CONSTRAINT outcome_disposition_is_one_of_two
        CHECK (disposition IN ('accepted', 'rejected')),
    CONSTRAINT outcome_boundary_contract_version_positive
        CHECK (boundary_contract_version >= 1),
    CONSTRAINT outcome_counts_not_negative CHECK (
        physical_rows_processed >= 0 AND staged_record_count    >= 0 AND
        committed_record_count  >= 0 AND rejected_row_count     >= 0 AND
        total_diagnostic_count  >= 0 AND total_notice_count     >= 0
    ),
    CONSTRAINT outcome_rejection_commits_nothing
        CHECK (disposition <> 'rejected' OR committed_record_count = 0),
    CONSTRAINT outcome_commits_no_more_than_it_staged
        CHECK (committed_record_count <= staged_record_count)
);

COMMENT ON TABLE ingestion.release_outcome IS
    'One verdict per run, with the counts that make it checkable. A rejected release '
    'commits nothing and a run cannot commit more than it staged: both are stated as '
    'constraints because a loader that got them wrong would otherwise record a '
    'plausible lie.';

-- ---------------------------------------------------------------------------
-- Diagnostics, and what they deliberately cannot hold
-- ---------------------------------------------------------------------------

CREATE TABLE ingestion.release_diagnostic (
    outcome_id          bigint  NOT NULL
                                REFERENCES ingestion.release_outcome (outcome_id)
                                ON DELETE CASCADE,
    diagnostic_index    integer NOT NULL,
    code                text    NOT NULL,
    field_name          text,
    physical_row_number bigint,
    layout_fingerprint  text,

    PRIMARY KEY (outcome_id, diagnostic_index),
    CONSTRAINT diagnostic_index_zero_based
        CHECK (diagnostic_index >= 0),
    CONSTRAINT diagnostic_row_number_one_based
        CHECK (physical_row_number IS NULL OR physical_row_number >= 1),
    CONSTRAINT diagnostic_code_is_in_the_closed_vocabulary CHECK (code IN (
        'source_open_failed',
        'layout_rejected',
        'record_rejected',
        'duplicate_record_key',
        'stage_open_failed',
        'stage_write_failed',
        'stage_finalize_failed',
        'stage_commit_failed',
        'stage_abort_failed',
        'source_close_failed',
        'progress_callback_failed',
        'resource_limit_exceeded'
    ))
);

COMMENT ON TABLE ingestion.release_diagnostic IS
    'Four columns and no fifth. There is deliberately nowhere to put a complete row, '
    'an arbitrary source value, exception text, a credential, an identity, an address, '
    'or a host-local path — a table with a free-text detail column would become the '
    'place all of those end up.';
COMMENT ON COLUMN ingestion.release_diagnostic.code IS
    'Twelve codes, no thirteenth. Enumerated as a constraint rather than left open so '
    'a new failure mode has to be named in a migration someone reviews.';

CREATE TABLE ingestion.release_notice (
    outcome_id          bigint  NOT NULL
                                REFERENCES ingestion.release_outcome (outcome_id)
                                ON DELETE CASCADE,
    notice_index        integer NOT NULL,
    code                text    NOT NULL,
    field_name          text,
    physical_row_number bigint,

    PRIMARY KEY (outcome_id, notice_index),
    CONSTRAINT notice_index_zero_based
        CHECK (notice_index >= 0),
    CONSTRAINT notice_row_number_one_based
        CHECK (physical_row_number IS NULL OR physical_row_number >= 1),
    CONSTRAINT notice_code_is_a_lowercase_name
        CHECK (code ~ '^[a-z][a-z0-9_]{0,63}$')
);

COMMENT ON TABLE ingestion.release_notice IS
    'Non-fatal observations. The code vocabulary is open where the diagnostic one is '
    'closed, so the shape is constrained instead: a lowercase name, and still nowhere '
    'to put content.';

-- ---------------------------------------------------------------------------
-- Silver gains its run lineage
--
-- silver.source_record is created in 0002 and ingestion.run here, so the
-- reference can only be added once both exist. Without it a Silver row records
-- which bytes it came from and not which processing run produced it, and the
-- accepted contract requires both.
-- ---------------------------------------------------------------------------

ALTER TABLE silver.source_record
    ADD COLUMN run_id bigint NOT NULL REFERENCES ingestion.run (run_id);

COMMENT ON COLUMN silver.source_record.run_id IS
    'The processing run that produced this row. NOT NULL: a record whose run is '
    'unknown cannot be attributed, re-run, or withdrawn with the release it came from.';

CREATE INDEX source_record_by_run ON silver.source_record (run_id);

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

GRANT USAGE ON SCHEMA ingestion TO property_tax_ingestion;

GRANT SELECT, INSERT, UPDATE ON
    ingestion.run,
    ingestion.release_outcome,
    ingestion.release_diagnostic,
    ingestion.release_notice
    TO property_tax_ingestion;

ALTER DEFAULT PRIVILEGES FOR ROLE property_tax_migrator IN SCHEMA ingestion
    GRANT SELECT, INSERT, UPDATE ON TABLES TO property_tax_ingestion;

-- property_tax_api is granted nothing in ingestion. Diagnostics are bounded but
-- they are operational detail, not an approved consumer product.

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (3, '0003_release_diagnostics', :'file_sha256');

COMMIT;
