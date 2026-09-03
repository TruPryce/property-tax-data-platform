-- 0011_canonical_accounts.sql
--
-- Account identity, and one account as one logical release observed it.
--
-- The grain is the account identity and the release its provenance names. It is
-- an index and not a constraint: two observations of one account in one release,
-- from two artifacts, share that grain, carry different lineage, and must both
-- survive.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0011_canonical_accounts.sql | cut -d' ' -f1)" \
--              -f 0011_canonical_accounts.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 10) THEN
        RAISE EXCEPTION 'migration 0010 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 11) THEN
        RAISE EXCEPTION 'migration 0011 is already applied';
    END IF;
END $$;

-- Every canonical migration references a relation that may hold rows by the time
-- it is applied, and adding a foreign key takes ShareRowExclusiveLock on the
-- referenced one. Yield rather than queue production traffic behind this.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '300s';

CREATE TABLE canonical.account (
    account_key       bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    jurisdiction_code text        NOT NULL REFERENCES canonical.jurisdiction (jurisdiction_code),
    source_account_id text        NOT NULL,
    first_recorded_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT account_source_id_is_an_identifier
        CHECK (canonical.is_identifier(source_account_id)),

    -- The business identity: county-qualified, so two counties publishing one
    -- source account identifier are two accounts. There is deliberately no
    -- constraint making source_account_id unique on its own.
    CONSTRAINT account_identity UNIQUE (jurisdiction_code, source_account_id),
    CONSTRAINT account_identity_by_county UNIQUE (account_key, jurisdiction_code)
);

COMMENT ON TABLE canonical.account IS
    'A canonical appraisal account: exactly a registered jurisdiction and the source '
    'account identifier its county contract approved. Whether a given source field is an '
    'approved account key is county knowledge that stops at the adapter boundary; this '
    'relation validates the identifier''s lexical contract and nothing more.';
COMMENT ON COLUMN canonical.account.account_key IS
    'A persistence locator for foreign-key mechanics. Not business identity, which is the '
    'jurisdiction and source account identifier together.';

-- No county_fips column, here or on any record relation. It is registry metadata
-- reachable through canonical.jurisdiction, keyed by the identity rather than
-- part of it, and a copy here would be a second, independent county identity.

CREATE TABLE canonical.account_snapshot (
    snapshot_key         bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_key          bigint      NOT NULL,
    load_key             bigint      NOT NULL,
    release_key          bigint      NOT NULL,
    provenance_key       bigint      NOT NULL,
    jurisdiction_code    text        NOT NULL,
    source_as_of         timestamptz,

    situs_street_address text,
    situs_unit           text,
    situs_city           text,
    situs_state_code     text,
    situs_postal_code    text,

    legal_text           text,
    legal_subdivision    text,
    legal_block          text,
    legal_lot            text,

    -- The root invariant, as two composite keys rather than a check. An account
    -- identity from one county under another county's release fails here, at the
    -- root, instead of producing an internally consistent tree every child agrees
    -- with and which is wrong only where nobody looks.
    CONSTRAINT account_snapshot_account_is_of_its_county
        FOREIGN KEY (account_key, jurisdiction_code)
        REFERENCES canonical.account (account_key, jurisdiction_code),
    CONSTRAINT account_snapshot_provenance_is_of_its_county
        FOREIGN KEY (provenance_key, jurisdiction_code)
        REFERENCES canonical.provenance (provenance_key, jurisdiction_code),

    -- Release and load are the provenance's own, so neither can be repointed
    -- independently of the lineage the snapshot claims.
    CONSTRAINT account_snapshot_lineage_is_its_provenance
        FOREIGN KEY (provenance_key, release_key, load_key)
        REFERENCES canonical.provenance (provenance_key, release_key, load_key),

    -- The only uniqueness, and it exists solely so a child can point at a snapshot
    -- of its own release.
    CONSTRAINT account_snapshot_carries_its_release UNIQUE (snapshot_key, release_key),

    CONSTRAINT account_snapshot_situs_components_are_bounded CHECK (
        canonical.is_bounded_text(situs_street_address, 128) IS NOT FALSE AND
        canonical.is_bounded_text(situs_unit, 128)           IS NOT FALSE AND
        canonical.is_bounded_text(situs_city, 128)           IS NOT FALSE AND
        canonical.is_bounded_text(situs_state_code, 128)     IS NOT FALSE AND
        canonical.is_bounded_text(situs_postal_code, 128)    IS NOT FALSE
    ),
    CONSTRAINT account_snapshot_legal_components_are_bounded CHECK (
        canonical.is_bounded_text(legal_text, 256)        IS NOT FALSE AND
        canonical.is_bounded_text(legal_subdivision, 128) IS NOT FALSE AND
        canonical.is_bounded_text(legal_block, 128)       IS NOT FALSE AND
        canonical.is_bounded_text(legal_lot, 128)         IS NOT FALSE
    ),
    -- A legal description has one required field. Its parts without it would be a
    -- present value object whose required member is absent, which the domain refuses.
    CONSTRAINT account_snapshot_legal_parts_need_their_text CHECK (
        legal_text IS NOT NULL
        OR (legal_subdivision IS NULL AND legal_block IS NULL AND legal_lot IS NULL)
    )
);

COMMENT ON TABLE canonical.account_snapshot IS
    'One account as one logical release observed it. Apart from its surrogate primary key '
    'and the composite key a child points at, this relation carries no UNIQUE. In '
    'particular there is no uniqueness over load, account, and provenance: snapshot '
    'equality is structural over every field but source_as_of, so two snapshots sharing '
    'those three while differing in a situs or legal value are unequal values at one grain '
    'and both must persist. Retry is answered once, at canonical.release_load.';
COMMENT ON COLUMN canonical.account_snapshot.source_as_of IS
    'When the county''s data was current. Observation metadata: excluded from the domain''s '
    'equality, hashing, and grain, because it is a property of the release rather than of '
    'one account within it.';
COMMENT ON COLUMN canonical.account_snapshot.release_key IS
    'The provenance''s own release, pinned by composite key rather than a second authority. '
    'Present so the grain index below can exist and so a child can be held to its parent''s '
    'release.';

-- The grain, deliberately not unique. A UNIQUE here would collapse exactly the
-- divergence the promoted capability preserves: one account, one release, two
-- artifacts, two snapshots, each keeping its own lineage.
CREATE INDEX account_snapshot_grain
    ON canonical.account_snapshot (account_key, release_key);

CREATE INDEX account_snapshot_by_load ON canonical.account_snapshot (load_key);

COMMENT ON COLUMN canonical.account_snapshot.snapshot_key IS
    'A persistence locator for foreign-key mechanics, not business identity. A snapshot '
    'has a grain rather than an identity: the account and release pair the non-unique '
    'index below serves.';

GRANT SELECT, INSERT ON
    canonical.account,
    canonical.account_snapshot
    TO property_tax_ingestion;

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (11, '0011_canonical_accounts', :'file_sha256');

COMMIT;
