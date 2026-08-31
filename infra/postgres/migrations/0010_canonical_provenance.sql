-- 0010_canonical_provenance.sql
--
-- Bounded lineage, normalized once rather than inlined eleven times.
--
-- Every canonical record reaches its release, artifact, member, row, parser
-- contract, and layout through one key, so the anti-cross-wiring rule lives in
-- one place instead of being repeated -- and omitted -- per relation.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0010_canonical_provenance.sql | cut -d' ' -f1)" \
--              -f 0010_canonical_provenance.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 9) THEN
        RAISE EXCEPTION 'migration 0009 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 10) THEN
        RAISE EXCEPTION 'migration 0010 is already applied';
    END IF;
END $$;

-- Every canonical migration references a relation that may hold rows by the time
-- it is applied, and adding a foreign key takes ShareRowExclusiveLock on the
-- referenced one. Yield rather than queue production traffic behind this.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '300s';

CREATE TABLE canonical.provenance (
    provenance_key          bigint  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    load_key                bigint  NOT NULL,
    release_key             bigint  NOT NULL,
    jurisdiction_code       text    NOT NULL,
    artifact_sha256         text    NOT NULL,
    source_member_name      text    NOT NULL,
    parser_contract_version integer NOT NULL,
    source_row_number       bigint,
    layout_fingerprint      text,

    -- The identifier grammar, not the looser not-blank rule the adapter-grain
    -- relation uses. Canonical provenance enforces its own contract rather than
    -- inheriting one written for a different purpose.
    CONSTRAINT provenance_source_member_name_is_an_identifier
        CHECK (canonical.is_identifier(source_member_name)),
    CONSTRAINT provenance_parser_contract_version_positive
        CHECK (parser_contract_version >= 1),
    CONSTRAINT provenance_source_row_number_one_based
        CHECK (source_row_number IS NULL OR source_row_number >= 1),
    CONSTRAINT provenance_layout_fingerprint_is_a_digest
        CHECK (layout_fingerprint IS NULL OR layout_fingerprint ~ '^[0-9a-f]{64}$'),

    -- Release, artifact, and county are the load's own rather than three
    -- independently supplied values. This is what stops a record claiming bytes
    -- its run never read: the load's artifact is already the artifact of the
    -- manifest its run acquired.
    CONSTRAINT provenance_release_is_its_load_release
        FOREIGN KEY (load_key, release_key)
        REFERENCES canonical.release_load (load_key, release_key),
    CONSTRAINT provenance_artifact_is_its_load_artifact
        FOREIGN KEY (load_key, artifact_sha256)
        REFERENCES canonical.release_load (load_key, artifact_sha256),
    CONSTRAINT provenance_jurisdiction_is_its_load_jurisdiction
        FOREIGN KEY (load_key, jurisdiction_code)
        REFERENCES canonical.release_load (load_key, jurisdiction_code),

    -- One source row resolves to one provenance row on retry. Release and artifact
    -- are omitted because the load already determines them; NULLS NOT DISTINCT
    -- because an absent row number is a value here, not an unknown, so two loads
    -- of a member with no row grain collide rather than quietly becoming two.
    CONSTRAINT provenance_source_position
        UNIQUE NULLS NOT DISTINCT (load_key, source_member_name, parser_contract_version,
                                   source_row_number, layout_fingerprint),

    -- The composite targets. The first is what every record reaches provenance
    -- through; the second is half of the snapshot's root jurisdiction invariant.
    CONSTRAINT provenance_carries_its_release_and_load
        UNIQUE (provenance_key, release_key, load_key),
    CONSTRAINT provenance_carries_its_jurisdiction
        UNIQUE (provenance_key, jurisdiction_code)
);

COMMENT ON TABLE canonical.provenance IS
    'The single lineage authority. No record relation carries a release identifier, tax '
    'year, release kind, or artifact of its own: a record needing any of them reaches them '
    'here, so there are never two representations to disagree. Examined without its parent, '
    'a record still yields its jurisdiction, release, artifact, member, row position, '
    'parser contract version, and layout identity through this one key.';
COMMENT ON COLUMN canonical.provenance.jurisdiction_code IS
    'The load''s own county, pinned by composite key rather than supplied a second time. '
    'The same technique 0001 uses when it makes a partition''s county the county of the '
    'artifact it partitions.';

CREATE INDEX provenance_by_load ON canonical.provenance (load_key);

COMMENT ON COLUMN canonical.provenance.provenance_key IS
    'A persistence locator for foreign-key mechanics, not business identity. Lineage '
    'identity is the source position the unique constraint above names, and a record '
    'reaches its whole lineage through this column rather than being identified by it.';

GRANT SELECT, INSERT ON canonical.provenance TO property_tax_ingestion;

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (10, '0010_canonical_provenance', :'file_sha256');

COMMIT;
