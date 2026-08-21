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
    manifest_id        bigint      NOT NULL,
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz,

    CONSTRAINT run_jurisdiction_is_state_and_county
        CHECK (jurisdiction_code ~ '^[a-z]{2}-[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT run_release_identifier_not_blank
        CHECK (btrim(release_identifier) <> ''),
    CONSTRAINT run_finishes_after_it_starts
        CHECK (finished_at IS NULL OR finished_at >= started_at),

    -- Composite, not two independent facts: a run reads one manifest, and its
    -- county is that manifest's county rather than a second string a caller
    -- supplied.
    FOREIGN KEY (manifest_id, jurisdiction_code)
        REFERENCES bronze.release_manifest (manifest_id, jurisdiction_code),

    -- The target silver.source_record binds to below.
    UNIQUE (run_id, manifest_id, jurisdiction_code, release_identifier)
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

    -- The rest of this block mirrors ReleaseOutcome.__post_init__ in
    -- property_tax_adapters.release.outcome. The carrier already refuses these
    -- states; persistence that admits them stores outcomes the boundary could
    -- never have produced, and the publication gate trusts `accepted`.
    CONSTRAINT outcome_boundary_contract_version_is_one
        CHECK (boundary_contract_version = 1),
    CONSTRAINT outcome_prepared_fields_are_set_together CHECK (
        (parser_contract_version IS NULL) = (layout_fingerprint IS NULL)
    ),
    CONSTRAINT outcome_is_accepted_exactly_when_it_produced_no_diagnostic CHECK (
        (disposition = 'accepted') = (total_diagnostic_count = 0)
    ),
    CONSTRAINT outcome_accepted_commits_what_it_staged CHECK (
        disposition <> 'accepted' OR committed_record_count = staged_record_count
    ),
    CONSTRAINT outcome_accepted_rejected_no_row CHECK (
        disposition <> 'accepted' OR rejected_row_count = 0
    ),
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
    -- DIAGNOSTIC_RETENTION_LIMIT is 100, so a retained entry is 0..99. A row at
    -- index 100 is evidence the carrier could not have produced.
    CONSTRAINT diagnostic_index_within_retention
        CHECK (diagnostic_index BETWEEN 0 AND 99),
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
    CONSTRAINT notice_index_within_retention
        CHECK (notice_index BETWEEN 0 AND 99),
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
    ADD COLUMN run_id bigint NOT NULL;

-- One composite reference rather than four facts that happen to be individually
-- valid. Without it a row may name tx-dallas and certified-2025 while pointing
-- at a Collin run reading a Collin manifest, and every foreign key still holds.
ALTER TABLE silver.source_record
    ADD CONSTRAINT source_record_lineage_is_one_release
    FOREIGN KEY (run_id, manifest_id, jurisdiction_code, release_identifier)
    REFERENCES ingestion.run (run_id, manifest_id, jurisdiction_code, release_identifier);

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

GRANT SELECT, INSERT, UPDATE ON ingestion.run TO property_tax_ingestion;

-- No UPDATE on the outcome or its evidence. A disposition is a verdict about a
-- run that has finished, and the publication gate reads it; allowing a rewrite
-- would let an accepted release become rejected after something was published
-- from it.
GRANT SELECT, INSERT ON
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
