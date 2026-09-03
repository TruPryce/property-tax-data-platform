-- 0009_canonical_release_load.sql
--
-- One canonical load: which release, which run, and the artifact that run read.
--
-- Binding only the four release components leaves the artifact free -- provenance
-- could name artifact B while the run read artifact A, and binding B to the
-- release as well would not help, because the record's artifact was never tied to
-- its run. The manifest is the only relation that says which artifact an
-- acquisition carried, so the load keys into that pair.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0009_canonical_release_load.sql | cut -d' ' -f1)" \
--              -f 0009_canonical_release_load.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 8) THEN
        RAISE EXCEPTION 'migration 0008 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 9) THEN
        RAISE EXCEPTION 'migration 0009 is already applied';
    END IF;
END $$;

-- Every canonical migration references a relation that may hold rows by the time
-- it is applied, and adding a foreign key takes ShareRowExclusiveLock on the
-- referenced one. Yield rather than queue production traffic behind this.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '300s';

-- ---------------------------------------------------------------------------
-- The one forward extension to a pre-existing relation
--
-- A unique index and nothing else: no column, no NOT NULL, no check.  It cannot
-- fail against existing rows, because manifest_id is already the primary key and
-- a pair whose first column is unique is unique.  Without it there is nothing for
-- the load to key into, and a record could claim bytes its run never opened.
-- ---------------------------------------------------------------------------

ALTER TABLE bronze.release_manifest
    ADD CONSTRAINT release_manifest_identifies_its_artifact
    UNIQUE (manifest_id, artifact_sha256);

COMMENT ON CONSTRAINT release_manifest_identifies_its_artifact ON bronze.release_manifest IS
    'A key target, added by 0009. The canonical load names both a manifest and an artifact, '
    'and this is what makes the second the first''s own rather than a second independently '
    'supplied digest.';

CREATE TABLE canonical.release_load (
    load_key           bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_key        bigint      NOT NULL,
    run_id             bigint      NOT NULL,
    manifest_id        bigint      NOT NULL,
    artifact_sha256    text        NOT NULL,
    jurisdiction_code  text        NOT NULL,
    tax_year           integer     NOT NULL,
    release_kind       text        NOT NULL,
    release_identifier text        NOT NULL,
    loaded_at          timestamptz NOT NULL DEFAULT now(),

    -- The composite key below already pins these three to the canonical release's
    -- own, so a violating value is unreachable through it. They are stated here as
    -- well because a reader of this relation should not have to trace a foreign
    -- key to learn that a release kind is one of four, and because a constraint
    -- that is only reachable indirectly is one a later migration can lose without
    -- anything failing.
    CONSTRAINT release_load_tax_year_plausible
        CHECK (tax_year BETWEEN 1900 AND 2200),
    CONSTRAINT release_load_kind_is_canonical
        CHECK (release_kind IN ('proposed', 'certified', 'supplemental', 'current')),
    CONSTRAINT release_load_identifier_is_an_identifier
        CHECK (canonical.is_identifier(release_identifier)),

    -- The canonical release this load writes.
    CONSTRAINT release_load_names_its_release
        FOREIGN KEY (release_key, jurisdiction_code, tax_year, release_kind, release_identifier)
        REFERENCES canonical.release
                   (release_key, jurisdiction_code, tax_year, release_kind, release_identifier),

    -- The run, twice over two keys that already exist on ingestion.run, so no
    -- index is added there. The first pins the manifest; the second pins the tax
    -- year and kind. Both read the same component columns as the release key
    -- above, so the release a run loads is the release that run processed.
    CONSTRAINT release_load_names_the_run_and_its_manifest
        FOREIGN KEY (run_id, manifest_id, jurisdiction_code, release_identifier)
        REFERENCES ingestion.run (run_id, manifest_id, jurisdiction_code, release_identifier),
    CONSTRAINT release_load_names_the_run_and_its_partition
        FOREIGN KEY (run_id, jurisdiction_code, release_identifier, tax_year, release_kind)
        REFERENCES ingestion.run
                   (run_id, jurisdiction_code, release_identifier, tax_year, release_kind),

    -- The artifact is the artifact of the acquisition the run read...
    CONSTRAINT release_load_reads_its_manifest_artifact
        FOREIGN KEY (manifest_id, artifact_sha256)
        REFERENCES bronze.release_manifest (manifest_id, artifact_sha256),
    -- ...and it is bound to the release claimed.
    CONSTRAINT release_load_artifact_is_bound_to_the_release
        FOREIGN KEY (artifact_sha256, release_key)
        REFERENCES canonical.artifact_release_binding (artifact_sha256, release_key),

    -- The retry key, and the only one. A repeated load for one release and one run
    -- resolves here and never reaches a record insert.
    CONSTRAINT release_load_is_one_per_release_and_run
        UNIQUE (release_key, run_id),

    -- The composite targets every canonical record pivots on.
    CONSTRAINT release_load_carries_its_release      UNIQUE (load_key, release_key),
    CONSTRAINT release_load_carries_its_artifact     UNIQUE (load_key, artifact_sha256),
    CONSTRAINT release_load_carries_its_jurisdiction UNIQUE (load_key, jurisdiction_code)
);

COMMENT ON TABLE canonical.release_load IS
    'One canonical load: one release, one run, one artifact. Two runs loading one release '
    'produce two loads and two record sets, which is divergence kept rather than a defect '
    'and is also how a release observed in two artifacts is represented. Which load a '
    'consumer reads is chosen by run, the way publication.publication already chooses.';
COMMENT ON COLUMN canonical.release_load.load_key IS
    'A persistence locator, and the handle a load is attributed or withdrawn by. Not '
    'business identity: a load event has none.';

CREATE INDEX release_load_by_run ON canonical.release_load (run_id);

-- ---------------------------------------------------------------------------
-- A canonical load rests on an accepted release
--
-- Issue #43 left durable persistence to this task and kept one invariant: a
-- rejected release commits and publishes zero accepted records.  Every canonical
-- record references a load, and the whole load is one transaction, so gating the
-- load makes that structural rather than a loader's promise.
--
-- Deferred, mirroring 0003's own seal, because the loader may legitimately write
-- canonical rows before the outcome row exists within the same transaction. The
-- judgement belongs at COMMIT, when both halves exist.
-- ---------------------------------------------------------------------------

CREATE FUNCTION canonical.assert_load_rests_on_an_accepted_run() RETURNS trigger
LANGUAGE plpgsql AS $accepted$
DECLARE
    run_disposition text;
BEGIN
    SELECT outcome.disposition INTO run_disposition
      FROM ingestion.release_outcome AS outcome
     WHERE outcome.run_id = NEW.run_id;

    IF run_disposition IS NULL THEN
        RAISE EXCEPTION
            'run % has no release outcome, so nothing has accepted it', NEW.run_id;
    END IF;
    IF run_disposition <> 'accepted' THEN
        RAISE EXCEPTION
            'run % was %, and a rejected release commits no canonical record',
            NEW.run_id, run_disposition;
    END IF;
    RETURN NULL;
END
$accepted$;

COMMENT ON FUNCTION canonical.assert_load_rests_on_an_accepted_run() IS
    'Judged at COMMIT by a deferred constraint trigger, so a loader may write canonical '
    'rows and the outcome in either order within one transaction and cannot leave the pair '
    'disagreeing at the end of it.';

CREATE CONSTRAINT TRIGGER release_load_rests_on_an_accepted_run
    AFTER INSERT OR UPDATE ON canonical.release_load
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION canonical.assert_load_rests_on_an_accepted_run();

GRANT SELECT, INSERT ON canonical.release_load TO property_tax_ingestion;

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (9, '0009_canonical_release_load', :'file_sha256');

COMMIT;
