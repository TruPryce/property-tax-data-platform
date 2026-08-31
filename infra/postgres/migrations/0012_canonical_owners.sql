-- 0012_canonical_owners.sql
--
-- Owners as observations, their association with an account, and the value
-- allocations that association carries.
--
-- An owner observation is not a person or entity master: nothing here derives an
-- identity from a name or an address, and no column, view, or trigger can produce
-- an account-level total from allocations.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0012_canonical_owners.sql | cut -d' ' -f1)" \
--              -f 0012_canonical_owners.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 11) THEN
        RAISE EXCEPTION 'migration 0011 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 12) THEN
        RAISE EXCEPTION 'migration 0012 is already applied';
    END IF;
END $$;

-- Every canonical migration references a relation that may hold rows by the time
-- it is applied, and adding a foreign key takes ShareRowExclusiveLock on the
-- referenced one. Yield rather than queue production traffic behind this.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '300s';

CREATE TABLE canonical.owner_observation (
    owner_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_key   bigint NOT NULL,
    release_key    bigint NOT NULL,
    load_key       bigint NOT NULL,
    provenance_key bigint NOT NULL,
    owner_name             text NOT NULL,

    mailing_addressee      text,
    mailing_street_address text,
    mailing_unit           text,
    mailing_city           text,
    mailing_state_code     text,
    mailing_postal_code    text,
    mailing_country_code   text,

    CONSTRAINT owner_observation_name_is_a_label
        CHECK (canonical.is_bounded_text(owner_name, 256)),
    CONSTRAINT owner_observation_mailing_components_are_bounded CHECK (
        canonical.is_bounded_text(mailing_addressee, 128)      IS NOT FALSE AND
        canonical.is_bounded_text(mailing_street_address, 128) IS NOT FALSE AND
        canonical.is_bounded_text(mailing_unit, 128)           IS NOT FALSE AND
        canonical.is_bounded_text(mailing_city, 128)           IS NOT FALSE AND
        canonical.is_bounded_text(mailing_state_code, 128)     IS NOT FALSE AND
        canonical.is_bounded_text(mailing_postal_code, 128)    IS NOT FALSE AND
        canonical.is_bounded_text(mailing_country_code, 128)   IS NOT FALSE
    ),

    -- A composite target so an association stays inside its own snapshot. It
    -- includes this relation's own locator, so it limits nothing about how many
    -- owner observations a snapshot may carry.
    CONSTRAINT owner_observation_carries_its_snapshot UNIQUE (owner_key, snapshot_key),

    -- The parent must be a snapshot of this record's own release. It need not be
    -- of the same load or artifact: the promoted capability permits two snapshots
    -- at one grain with different artifact lineage, and a same-release enrichment
    -- from a second artifact would otherwise be unrepresentable.
    CONSTRAINT owner_observation_parent_is_of_its_release
        FOREIGN KEY (snapshot_key, release_key)
        REFERENCES canonical.account_snapshot (snapshot_key, release_key),
    -- This record's own release and load are its provenance's, so neither can be
    -- moved independently of the lineage it claims.
    CONSTRAINT owner_observation_lineage_is_its_provenance
        FOREIGN KEY (provenance_key, release_key, load_key)
        REFERENCES canonical.provenance (provenance_key, release_key, load_key)
);

COMMENT ON TABLE canonical.owner_observation IS
    'One owner as one release observed it. No natural key over the name or the mailing '
    'address, and no cross-release or cross-county resolution: the same name and address '
    'in two releases are two observations and nothing links them. The mailing address '
    'composes as named columns rather than a relation, because it has no independent grain.';

CREATE INDEX owner_observation_by_snapshot
    ON canonical.owner_observation (snapshot_key, release_key);

CREATE TABLE canonical.owner_association (
    association_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_key   bigint NOT NULL,
    release_key    bigint NOT NULL,
    load_key       bigint NOT NULL,
    provenance_key bigint NOT NULL,
    owner_key            bigint  NOT NULL,
    ownership_percentage numeric,
    source_discriminator text,

    CONSTRAINT owner_association_percentage_is_a_percentage CHECK (
        ownership_percentage IS NULL
        OR (canonical.is_finite(ownership_percentage)
            AND ownership_percentage BETWEEN 0 AND 100)
    ),
    CONSTRAINT owner_association_discriminator_is_an_identifier
        CHECK (source_discriminator IS NULL OR canonical.is_identifier(source_discriminator)),

    CONSTRAINT owner_association_owner_is_of_its_snapshot
        FOREIGN KEY (owner_key, snapshot_key)
        REFERENCES canonical.owner_observation (owner_key, snapshot_key),

    CONSTRAINT owner_association_carries_its_snapshot UNIQUE (association_key, snapshot_key),
    CONSTRAINT owner_association_carries_its_release  UNIQUE (association_key, release_key),

    -- The parent must be a snapshot of this record's own release. It need not be
    -- of the same load or artifact: the promoted capability permits two snapshots
    -- at one grain with different artifact lineage, and a same-release enrichment
    -- from a second artifact would otherwise be unrepresentable.
    CONSTRAINT owner_association_parent_is_of_its_release
        FOREIGN KEY (snapshot_key, release_key)
        REFERENCES canonical.account_snapshot (snapshot_key, release_key),
    -- This record's own release and load are its provenance's, so neither can be
    -- moved independently of the lineage it claims.
    CONSTRAINT owner_association_lineage_is_its_provenance
        FOREIGN KEY (provenance_key, release_key, load_key)
        REFERENCES canonical.provenance (provenance_key, release_key, load_key)
);

COMMENT ON TABLE canonical.owner_association IS
    'The relationship between an owner observation and an account snapshot, and its own '
    'record rather than a field on either. Undivided-interest rows become several '
    'associations, none deduplicated, summed, or selected as the account total.';
COMMENT ON COLUMN canonical.owner_association.source_discriminator IS
    'Absent where a county contract approves none. Nullable on purpose: no constraint may '
    'demand evidence a contract has not established, and a row number is not a business key.';

CREATE INDEX owner_association_by_snapshot
    ON canonical.owner_association (snapshot_key, release_key);

CREATE TABLE canonical.owner_value_allocation (
    allocation_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    association_key bigint  NOT NULL,
    release_key     bigint  NOT NULL,
    load_key        bigint  NOT NULL,
    provenance_key  bigint  NOT NULL,
    kind            text    NOT NULL,
    amount          numeric NOT NULL,

    CONSTRAINT owner_value_allocation_kind_is_canonical
        CHECK (kind IN ('market', 'appraised', 'assessed')),
    CONSTRAINT owner_value_allocation_amount_is_finite
        CHECK (canonical.is_finite(amount)),

    -- Parented by the association, not by the snapshot: there is deliberately no
    -- snapshot_key here, because the domain gives this record one parent and it is
    -- the association. The snapshot is reached through it.
    CONSTRAINT owner_value_allocation_parent_is_of_its_release
        FOREIGN KEY (association_key, release_key)
        REFERENCES canonical.owner_association (association_key, release_key),
    CONSTRAINT owner_value_allocation_lineage_is_its_provenance
        FOREIGN KEY (provenance_key, release_key, load_key)
        REFERENCES canonical.provenance (provenance_key, release_key, load_key)
);

COMMENT ON TABLE canonical.owner_value_allocation IS
    'An owner-scoped value at owner-association grain. No field on the snapshot, the '
    'association, or this relation holds an account-level total assembled from these, and '
    'no generated column, view, materialized view, trigger, or default produces one: '
    'making that total is unrepresentable rather than merely prohibited.';

CREATE INDEX owner_value_allocation_by_association
    ON canonical.owner_value_allocation (association_key, release_key);

COMMENT ON COLUMN canonical.owner_observation.owner_key IS
    'A persistence locator for foreign-key mechanics, not business identity. An owner '
    'observation asserts no person or entity identity, so there is none for this column '
    'to stand in for.';

COMMENT ON COLUMN canonical.owner_association.association_key IS
    'A persistence locator for foreign-key mechanics, not business identity.';

COMMENT ON COLUMN canonical.owner_value_allocation.allocation_key IS
    'A persistence locator for foreign-key mechanics, not business identity.';

GRANT SELECT, INSERT ON
    canonical.owner_observation,
    canonical.owner_association,
    canonical.owner_value_allocation
    TO property_tax_ingestion;

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (12, '0012_canonical_owners', :'file_sha256');

COMMIT;
