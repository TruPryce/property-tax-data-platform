-- 0005_publication_metadata.sql
--
-- What is published, from which release, and since when. Publication is a
-- swap: the previous version stays readable until the new one is complete.
--
-- Run with:  psql --single-transaction --set ON_ERROR_STOP=on -f 0005_publication_metadata.sql

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
    run_id             bigint      REFERENCES ingestion.run (run_id),
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

INSERT INTO platform.schema_migration (version, name)
VALUES (5, '0005_publication_metadata');

COMMIT;
