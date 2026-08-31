-- 0014_canonical_exemptions.sql
--
-- Exemptions, with the county's own classification and an explicit scope.
--
-- The scope is stated rather than inferred from whether an association reference
-- is present, so an exemption whose scope was never determined cannot be created
-- by omission.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0014_canonical_exemptions.sql | cut -d' ' -f1)" \
--              -f 0014_canonical_exemptions.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 13) THEN
        RAISE EXCEPTION 'migration 0013 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 14) THEN
        RAISE EXCEPTION 'migration 0014 is already applied';
    END IF;
END $$;

-- Every canonical migration references a relation that may hold rows by the time
-- it is applied, and adding a foreign key takes ShareRowExclusiveLock on the
-- referenced one. Yield rather than queue production traffic behind this.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '300s';

CREATE TABLE canonical.exemption_observation (
    exemption_key bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_key   bigint NOT NULL,
    release_key    bigint NOT NULL,
    load_key       bigint NOT NULL,
    provenance_key bigint NOT NULL,
    classification  text    NOT NULL,
    scope           text    NOT NULL,
    amount          numeric,
    association_key bigint,

    CONSTRAINT exemption_classification_is_a_label
        CHECK (canonical.is_bounded_text(classification, 256)),
    CONSTRAINT exemption_scope_is_known
        CHECK (scope IN ('account', 'owner_association')),
    CONSTRAINT exemption_amount_is_finite
        CHECK (amount IS NULL OR canonical.is_finite(amount)),
    -- Present when and only when the scope says so, in both directions.
    CONSTRAINT exemption_reference_matches_its_scope
        CHECK ((scope = 'owner_association') = (association_key IS NOT NULL)),

    CONSTRAINT exemption_association_is_of_its_snapshot
        FOREIGN KEY (association_key, snapshot_key)
        REFERENCES canonical.owner_association (association_key, snapshot_key),

    -- The parent must be a snapshot of this record's own release. It need not be
    -- of the same load or artifact: the promoted capability permits two snapshots
    -- at one grain with different artifact lineage, and a same-release enrichment
    -- from a second artifact would otherwise be unrepresentable.
    CONSTRAINT exemption_observation_parent_is_of_its_release
        FOREIGN KEY (snapshot_key, release_key)
        REFERENCES canonical.account_snapshot (snapshot_key, release_key),
    -- This record's own release and load are its provenance's, so neither can be
    -- moved independently of the lineage it claims.
    CONSTRAINT exemption_observation_lineage_is_its_provenance
        FOREIGN KEY (provenance_key, release_key, load_key)
        REFERENCES canonical.provenance (provenance_key, release_key, load_key)
);

COMMENT ON TABLE canonical.exemption_observation IS
    'An exemption as the county classified it. There is no canonical exemption vocabulary '
    'and no constraint on the classification: none is established by an accepted contract, '
    'so an unknown county label is retained verbatim rather than mapped to the '
    'nearest-looking member of a set this schema would have had to invent. No taxable '
    'value is derived from these.';

CREATE INDEX exemption_observation_by_snapshot
    ON canonical.exemption_observation (snapshot_key, release_key);

CREATE INDEX exemption_observation_by_association
    ON canonical.exemption_observation (association_key, snapshot_key)
    WHERE association_key IS NOT NULL;

COMMENT ON COLUMN canonical.exemption_observation.exemption_key IS
    'A persistence locator for foreign-key mechanics, not business identity.';

GRANT SELECT, INSERT ON canonical.exemption_observation TO property_tax_ingestion;

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (14, '0014_canonical_exemptions', :'file_sha256');

COMMIT;
