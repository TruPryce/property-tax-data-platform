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
    tax_year           integer     NOT NULL,
    release_kind       text        NOT NULL,
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz,

    CONSTRAINT run_jurisdiction_is_state_and_county
        CHECK (jurisdiction_code ~ '^[a-z]{2}-[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT run_release_identifier_not_blank
        CHECK (btrim(release_identifier) <> ''),
    CONSTRAINT run_finishes_after_it_starts
        CHECK (finished_at IS NULL OR finished_at >= started_at),

    CONSTRAINT run_tax_year_plausible
        CHECK (tax_year BETWEEN 1900 AND 2200),
    CONSTRAINT run_release_kind_is_an_identifier
        CHECK (release_kind ~ '^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$'),

    -- One logical partition, not an artifact and a hope. An artifact carries
    -- more than one release -- a measured Collin archive holds current values
    -- for one year and certified values for another -- so binding a run to the
    -- manifest alone leaves which of them it processed unstated, and anything
    -- downstream asking "does this artifact carry that partition" gets yes for
    -- a partition the run never touched.
    FOREIGN KEY (manifest_id, jurisdiction_code, tax_year, release_kind)
        REFERENCES bronze.release_partition
                   (manifest_id, jurisdiction_code, tax_year, release_kind),

    -- The target silver.source_record binds to below. Silver reaches the
    -- partition through the run rather than repeating it: one run processes one
    -- partition, so a record bound to the run is bound to the partition.
    UNIQUE (run_id, manifest_id, jurisdiction_code, release_identifier),

    -- The target publication.publication binds to, so a publication's county,
    -- release, year, and kind are the run's rather than a second set of claims
    -- a trigger has to keep comparing.
    UNIQUE (run_id, jurisdiction_code, release_identifier, tax_year, release_kind)
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
    -- _require_optional_name: absent, or a name. '' and '   ' are neither, and
    -- the carrier refuses both.
    CONSTRAINT outcome_layout_fingerprint_is_absent_or_named CHECK (
        layout_fingerprint IS NULL
        OR btrim(layout_fingerprint, E' \t\r\n\v\f') <> ''
    ),
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
    CONSTRAINT diagnostic_field_name_is_absent_or_named CHECK (
        field_name IS NULL OR btrim(field_name, E' \t\r\n\v\f') <> ''
    ),
    CONSTRAINT diagnostic_layout_fingerprint_is_absent_or_named CHECK (
        layout_fingerprint IS NULL
        OR btrim(layout_fingerprint, E' \t\r\n\v\f') <> ''
    ),
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
    CONSTRAINT notice_field_name_is_absent_or_named CHECK (
        field_name IS NULL OR btrim(field_name, E' \t\r\n\v\f') <> ''
    ),
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
-- The outcome and its evidence are one sealed unit
--
-- The scalar counts on release_outcome and the rows in release_diagnostic /
-- release_notice are two descriptions of the same thing, and a CHECK can only
-- see one row of one of them.  Until now an accepted outcome declaring zero
-- diagnostics could carry a record_rejected diagnostic underneath it, and the
-- publication gate -- which trusts `accepted` -- would promote that release.
--
-- Deferred constraint triggers close it at COMMIT rather than per statement, so
-- a loader may insert the outcome and its evidence in any order within one
-- transaction and cannot leave the pair disagreeing at the end of it.  That also
-- makes the aggregate sealed: appending evidence in a later transaction re-runs
-- the check against a total that is now wrong, and fails.
-- ---------------------------------------------------------------------------

CREATE FUNCTION ingestion.assert_outcome_evidence_agrees(target_outcome bigint)
RETURNS void LANGUAGE plpgsql AS $agree$
DECLARE
    outcome              ingestion.release_outcome%ROWTYPE;
    retained_diagnostics integer;
    retained_notices     integer;
    disagreeing          integer;
BEGIN
    SELECT * INTO outcome FROM ingestion.release_outcome WHERE outcome_id = target_outcome;
    IF NOT FOUND THEN
        RETURN;  -- deleted within the same transaction; nothing to agree with
    END IF;

    SELECT count(*) INTO retained_diagnostics
      FROM ingestion.release_diagnostic WHERE outcome_id = target_outcome;
    SELECT count(*) INTO retained_notices
      FROM ingestion.release_notice WHERE outcome_id = target_outcome;

    -- DIAGNOSTIC_RETENTION_LIMIT is 100: the carrier retains every entry up to
    -- that and then truncates, so the retained count is not free of the total.
    IF retained_diagnostics <> least(outcome.total_diagnostic_count, 100) THEN
        RAISE EXCEPTION
            'outcome % declares % diagnostic(s) and retains %, expected %',
            target_outcome, outcome.total_diagnostic_count, retained_diagnostics,
            least(outcome.total_diagnostic_count, 100);
    END IF;
    IF retained_notices <> least(outcome.total_notice_count, 100) THEN
        RAISE EXCEPTION
            'outcome % declares % notice(s) and retains %, expected %',
            target_outcome, outcome.total_notice_count, retained_notices,
            least(outcome.total_notice_count, 100);
    END IF;

    IF outcome.diagnostics_truncated <> (outcome.total_diagnostic_count > 100) THEN
        RAISE EXCEPTION
            'outcome % declares % diagnostic(s) with diagnostics_truncated = %',
            target_outcome, outcome.total_diagnostic_count, outcome.diagnostics_truncated;
    END IF;
    IF outcome.notices_truncated <> (outcome.total_notice_count > 100) THEN
        RAISE EXCEPTION
            'outcome % declares % notice(s) with notices_truncated = %',
            target_outcome, outcome.total_notice_count, outcome.notices_truncated;
    END IF;

    -- A diagnostic names the layout it was raised against, and the outcome names
    -- the layout it prepared. Two fingerprints for one release is one of them
    -- being wrong.
    SELECT count(*) INTO disagreeing
      FROM ingestion.release_diagnostic AS diagnostic
     WHERE diagnostic.outcome_id = target_outcome
       -- No IS NOT NULL exemption: the carrier compares with plain inequality,
       -- so a NULL fingerprint under an outcome that has one is a disagreement
       -- too. IS DISTINCT FROM is what makes NULL compare rather than vanish.
       AND diagnostic.layout_fingerprint IS DISTINCT FROM outcome.layout_fingerprint;
    IF disagreeing > 0 THEN
        RAISE EXCEPTION
            'outcome % retains % diagnostic(s) whose layout fingerprint is not its own',
            target_outcome, disagreeing;
    END IF;
END
$agree$;

COMMENT ON FUNCTION ingestion.assert_outcome_evidence_agrees(bigint) IS
    'Checks one outcome against the evidence rows beneath it. Called from deferred '
    'constraint triggers so the pair is judged at COMMIT, when both halves exist.';

CREATE FUNCTION ingestion.assert_outcome_seal() RETURNS trigger
LANGUAGE plpgsql AS $seal$
BEGIN
    PERFORM ingestion.assert_outcome_evidence_agrees(
        CASE WHEN TG_OP = 'DELETE' THEN OLD.outcome_id ELSE NEW.outcome_id END
    );
    RETURN NULL;
END
$seal$;

CREATE CONSTRAINT TRIGGER release_outcome_agrees_with_its_evidence
    AFTER INSERT OR UPDATE ON ingestion.release_outcome
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ingestion.assert_outcome_seal();

CREATE CONSTRAINT TRIGGER release_diagnostic_agrees_with_its_outcome
    AFTER INSERT OR UPDATE OR DELETE ON ingestion.release_diagnostic
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ingestion.assert_outcome_seal();

CREATE CONSTRAINT TRIGGER release_notice_agrees_with_its_outcome
    AFTER INSERT OR UPDATE OR DELETE ON ingestion.release_notice
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ingestion.assert_outcome_seal();

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

COMMENT ON COLUMN ingestion.run.tax_year IS
    'With release_kind, the logical partition of the artifact this run processed. '
    'Immutable once written: a publication binds to it, and a run that could be '
    'repointed afterwards would make that binding a description rather than a fact.';

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

-- Column-level, so a run may be closed but never repointed. Its identity --
-- manifest, county, partition, release -- is what silver records and
-- publications bind to, and an UPDATE that moved it would invalidate both while
-- every foreign key still held.
GRANT SELECT, INSERT ON ingestion.run TO property_tax_ingestion;
GRANT UPDATE (finished_at) ON ingestion.run TO property_tax_ingestion;

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
