-- 0005_publication_metadata.sql
--
-- What is published, from which release, and since when. Publication is a
-- swap: the previous version stays readable until the new one is complete.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0005_publication_metadata.sql | cut -d' ' -f1)" \
--              -f 0005_publication_metadata.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 4) THEN
        RAISE EXCEPTION 'migration 0004 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 5) THEN
        RAISE EXCEPTION 'migration 0005 is already applied';
    END IF;
END $$;

CREATE SCHEMA publication;

COMMENT ON SCHEMA publication IS
    'Publication lineage: which release backs what a consumer is reading right now.';

CREATE TABLE publication.product (
    product     text PRIMARY KEY,
    description text NOT NULL,

    CONSTRAINT product_is_one_of_three
        CHECK (product IN ('latest_available', 'latest_certified', 'history'))
);

INSERT INTO publication.product (product, description) VALUES
    ('latest_available',
     'The newest validated appraisal data, which may be proposed rather than certified.'),
    ('latest_certified',
     'The newest validated certified appraisal data, which does not move for proposed values.'),
    ('history',
     'Retained snapshots, including versions superseded by supplemental releases.');

COMMENT ON TABLE publication.product IS
    'Three products, seeded here rather than left to a loader. Proposed values must be '
    'able to move latest-available without moving latest-certified, which is only '
    'possible if they are separate products rather than one product with a flag.';

-- ---------------------------------------------------------------------------
-- One publication attempt
-- ---------------------------------------------------------------------------

CREATE TABLE publication.publication (
    publication_id     bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product            text        NOT NULL REFERENCES publication.product (product),
    jurisdiction_code  text        NOT NULL,
    tax_year           integer     NOT NULL,
    release_kind       text        NOT NULL,
    release_identifier text        NOT NULL,
    run_id             bigint      NOT NULL REFERENCES ingestion.run (run_id),
    source_as_of       timestamptz,
    state              text        NOT NULL DEFAULT 'building',
    built_at           timestamptz NOT NULL DEFAULT now(),
    published_at       timestamptz,
    superseded_at      timestamptz,
    superseded_by      bigint      REFERENCES publication.publication (publication_id),

    CONSTRAINT publication_jurisdiction_is_state_and_county
        CHECK (jurisdiction_code ~ '^[a-z]{2}-[a-z0-9]+(-[a-z0-9]+)*$'),
    CONSTRAINT publication_tax_year_plausible
        CHECK (tax_year BETWEEN 1900 AND 2200),
    CONSTRAINT publication_release_kind_is_an_identifier
        CHECK (release_kind ~ '^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$'),
    CONSTRAINT publication_release_identifier_not_blank
        CHECK (btrim(release_identifier) <> ''),
    CONSTRAINT publication_state_is_known
        CHECK (state IN ('building', 'current', 'superseded', 'failed')),
    CONSTRAINT publication_current_has_a_publication_time
        CHECK (state <> 'current' OR published_at IS NOT NULL),
    CONSTRAINT publication_building_has_no_publication_time
        CHECK (state <> 'building' OR published_at IS NULL),
    CONSTRAINT publication_superseded_records_when_and_by_what CHECK (
        state <> 'superseded'
        OR (superseded_at IS NOT NULL AND superseded_by IS NOT NULL)
    ),
    CONSTRAINT publication_supersedes_something_other_than_itself
        CHECK (superseded_by IS DISTINCT FROM publication_id)
);

COMMENT ON TABLE publication.publication IS
    'One attempt to publish one product for one jurisdiction. A failed build stays as '
    'a row in state failed rather than disappearing, because the question an operator '
    'asks after an incident is what was attempted, not what succeeded.';
COMMENT ON COLUMN publication.publication.state IS
    'building -> current -> superseded, or building -> failed. A build is never '
    'current until every blocking check has passed, which is why building and current '
    'are separate states rather than a boolean.';
COMMENT ON COLUMN publication.publication.source_as_of IS
    'When the county''s data was current, as distinct from when this platform '
    'published it. A consumer asking how fresh a value is means this one.';

-- At most one current publication per product and jurisdiction. This is what
-- makes publication atomic: promoting a build and demoting its predecessor is
-- one transaction, and a half-finished swap cannot leave two rows claiming to
-- be what consumers read.
CREATE UNIQUE INDEX publication_one_current_per_product_and_jurisdiction
    ON publication.publication (product, jurisdiction_code)
    WHERE state = 'current';

CREATE INDEX publication_by_release
    ON publication.publication (release_identifier);
CREATE INDEX publication_by_jurisdiction_and_year
    ON publication.publication (jurisdiction_code, tax_year, product);

-- ---------------------------------------------------------------------------
-- What a consumer is reading, and how fresh it is
-- ---------------------------------------------------------------------------

CREATE VIEW publication.current_publication AS
SELECT
    publication.product,
    publication.jurisdiction_code,
    publication.tax_year,
    publication.release_kind,
    publication.release_identifier,
    publication.source_as_of,
    publication.published_at,
    publication.run_id
FROM publication.publication
WHERE publication.state = 'current';

COMMENT ON VIEW publication.current_publication IS
    'County, tax year, release kind, source as-of, publication time, and release '
    'identity — everything the lineage and freshness requirement asks a consumer to '
    'be able to determine, in one place rather than assembled per query.';

-- ---------------------------------------------------------------------------
-- What may become current
--
-- A CHECK cannot see another table, so the rule that a release must be accepted
-- and free of blocking failures before it is what consumers read has to be a
-- trigger. It is enforced here rather than in a loader because the loader is the
-- thing being constrained: whoever writes the row is who must not be trusted to
-- have checked.
--
-- Task 6.2 owns the full promotion path, including demoting the predecessor in
-- the same transaction. This is the floor beneath it, not a replacement for it.
-- ---------------------------------------------------------------------------

CREATE FUNCTION publication.assert_current_is_validated() RETURNS trigger
LANGUAGE plpgsql AS $assert$
DECLARE
    run_jurisdiction text;
    run_release      text;
    run_manifest     bigint;
    run_disposition  text;
    blocking_count   integer;
BEGIN
    IF NEW.state <> 'current' THEN
        RETURN NEW;
    END IF;

    -- A BEFORE trigger runs ahead of the NOT NULL check, so say this plainly
    -- rather than let the column's error arrive after a confusing one.
    IF NEW.run_id IS NULL THEN
        RAISE EXCEPTION
            'a current publication must name the ingestion run it was built from';
    END IF;

    SELECT run.jurisdiction_code, run.release_identifier, run.manifest_id,
           outcome.disposition
      INTO run_jurisdiction, run_release, run_manifest, run_disposition
      FROM ingestion.run AS run
      LEFT JOIN ingestion.release_outcome AS outcome ON outcome.run_id = run.run_id
     WHERE run.run_id = NEW.run_id;

    IF run_disposition IS NULL THEN
        RAISE EXCEPTION
            'run % has no release outcome, so nothing has accepted it', NEW.run_id;
    END IF;
    IF run_disposition <> 'accepted' THEN
        RAISE EXCEPTION
            'run % was %, and a rejected release does not become current',
            NEW.run_id, run_disposition;
    END IF;

    -- The lineage must be the same release, not merely some accepted one.
    IF run_jurisdiction IS DISTINCT FROM NEW.jurisdiction_code
       OR run_release IS DISTINCT FROM NEW.release_identifier THEN
        RAISE EXCEPTION
            'run % processed %/%, not %/%',
            NEW.run_id, run_jurisdiction, run_release,
            NEW.jurisdiction_code, NEW.release_identifier;
    END IF;

    -- The year and kind are the publication's own claim, and the run does not
    -- carry them. They have to be a partition of the artifact the run read, or a
    -- row could name any year it liked over an accepted release.
    IF NOT EXISTS (
        SELECT 1 FROM bronze.release_partition AS partition
         WHERE partition.manifest_id       = run_manifest
           AND partition.jurisdiction_code = NEW.jurisdiction_code
           AND partition.tax_year          = NEW.tax_year
           AND partition.release_kind      = NEW.release_kind
    ) THEN
        RAISE EXCEPTION
            'the artifact run % read carries no %/% partition for %',
            NEW.run_id, NEW.tax_year, NEW.release_kind, NEW.jurisdiction_code;
    END IF;

    SELECT count(*) INTO blocking_count
      FROM quality.blocking_failure
     WHERE quality.blocking_failure.run_id = NEW.run_id;

    IF blocking_count > 0 THEN
        RAISE EXCEPTION
            'run % has % blocking quality failure(s), so the prior publication stays current',
            NEW.run_id, blocking_count;
    END IF;

    RETURN NEW;
END
$assert$;

CREATE TRIGGER publication_current_is_validated
    BEFORE INSERT OR UPDATE ON publication.publication
    FOR EACH ROW EXECUTE FUNCTION publication.assert_current_is_validated();

COMMENT ON FUNCTION publication.assert_current_is_validated() IS
    'Admission, not maintenance. It runs when a publication row is written and checks '
    'what is true then: an accepted outcome, a run that read this release and an '
    'artifact carrying this year and kind, and no blocking quality failure. It does '
    'NOT re-evaluate afterwards, so a blocking evaluation recorded later leaves an '
    'already-current row current. Sealing quality for a published release is task 6.2 '
    'and is deliberately not attempted here; this is a floor beneath that, and the '
    'guarantee it gives is point-in-time rather than durable.';

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

GRANT USAGE ON SCHEMA publication TO property_tax_ingestion;

GRANT SELECT ON publication.product TO property_tax_ingestion;
GRANT SELECT, INSERT, UPDATE ON publication.publication TO property_tax_ingestion;

ALTER DEFAULT PRIVILEGES FOR ROLE property_tax_migrator IN SCHEMA publication
    GRANT SELECT ON TABLES TO property_tax_ingestion;

-- property_tax_api is granted nothing here either. current_publication is a
-- pointer the loader writes, and task 6.2 owns the promotion path that makes it
-- trustworthy; exposing it now would let the API read a pointer whose gate is
-- still being built.

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (5, '0005_publication_metadata', :'file_sha256');

COMMIT;
