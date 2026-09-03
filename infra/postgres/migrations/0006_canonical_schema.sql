-- 0006_canonical_schema.sql
--
-- The canonical schema and the lexical vocabulary every relation in it uses.
--
-- silver persists adapter-grain evidence: one row per physical source row under
-- its exact source names. This schema persists the promoted canonical domain.
-- They sit beside each other on purpose and neither replaces the other.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0006_canonical_schema.sql | cut -d' ' -f1)" \
--              -f 0006_canonical_schema.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 5) THEN
        RAISE EXCEPTION 'migration 0005 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 6) THEN
        RAISE EXCEPTION 'migration 0006 is already applied';
    END IF;
END $$;

-- Every canonical migration references a relation that may hold rows by the time
-- it is applied, and adding a foreign key takes ShareRowExclusiveLock on the
-- referenced one. Yield rather than queue production traffic behind this.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '300s';

CREATE SCHEMA canonical;

COMMENT ON SCHEMA canonical IS
    'The promoted canonical appraisal domain, at the grain a county roll actually has. '
    'Distinct from silver, which persists one row per physical source row under its exact '
    'source names: that is adapter evidence and this is the canonical model, and neither '
    'is derived from the other by this schema.';

-- ---------------------------------------------------------------------------
-- The lexical vocabulary
--
-- Written once here rather than copied into every constraint, for the reason
-- platform.is_named already exists: a hand-copied character class is the drift
-- the function prevents.  Each mirrors a rule the promoted capability fixes, and
-- a test enumerates the rule from Python and asserts the database agrees.
-- ---------------------------------------------------------------------------

CREATE FUNCTION canonical.is_identifier(value text) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $identifier$
    SELECT value ~ '^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$'
$identifier$;

COMMENT ON FUNCTION canonical.is_identifier(text) IS
    'The identifier alphabet accepted across this repository: 1 to 128 characters of '
    '[A-Za-z0-9._-] not beginning with a dot or a hyphen. The same expression 0001 '
    'already uses for release_kind, and the exact behaviour of the domain''s '
    'require_identifier. It admits no path separator, whitespace, or control character.';

CREATE FUNCTION canonical.has_no_control_character(value text) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $control$
    SELECT value !~ '[\u0000-\u001F\u007F-\u009F]'
$control$;

COMMENT ON FUNCTION canonical.has_no_control_character(text) IS
    'True when the value carries no Unicode Cc character. The range is written out '
    'rather than spelled with the POSIX cntrl class, whose membership is locale-dependent: '
    'this one is exactly Python''s unicodedata.category(c) = ''Cc'', which is the rule the '
    'promoted capability states, and a test enumerates that set and asserts each is refused.';

CREATE FUNCTION canonical.is_bounded_text(value text, max_chars integer) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $bounded$
    SELECT length(value) BETWEEN 1 AND max_chars
       AND platform.is_named(value)
       AND canonical.has_no_control_character(value)
$bounded$;

COMMENT ON FUNCTION canonical.is_bounded_text(text, integer) IS
    'One bounded human-supplied string: within its length, carrying at least one '
    'non-whitespace character by platform.is_named''s definition, and free of control '
    'characters. A label passes 256, an address component 128, a coordinate reference 64. '
    'STRICT, so an absent optional value yields NULL and the check does not fail on it.';

CREATE FUNCTION canonical.is_finite(value numeric) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $finite$
    SELECT value <> 'NaN'::numeric
       AND value <> 'Infinity'::numeric
       AND value <> '-Infinity'::numeric
$finite$;

COMMENT ON FUNCTION canonical.is_finite(numeric) IS
    'True for a real number. Three inequalities rather than one, because '
    '''NaN''::numeric = ''NaN''::numeric is true in PostgreSQL and a single equality '
    'would admit it. The domain rejects a non-finite Decimal at construction; this is '
    'the same rule where a loader writes rather than where a constructor runs.';

-- ---------------------------------------------------------------------------
-- Privileges
--
-- Set before any relation exists, which is the only ordering where the default
-- covers all of them.  Exactly SELECT and INSERT: a canonical record is evidence,
-- and a role that could UPDATE it could resolve an insert conflict by overwriting
-- divergent lineage rather than by keeping both.  Every migration below also
-- grants explicitly for the relations it creates, because a default privilege
-- applies only to relations created by the role it names.
-- ---------------------------------------------------------------------------

GRANT USAGE ON SCHEMA canonical TO property_tax_ingestion;

ALTER DEFAULT PRIVILEGES FOR ROLE property_tax_migrator IN SCHEMA canonical
    GRANT SELECT, INSERT ON TABLES TO property_tax_ingestion;

-- property_tax_api is granted nothing here, not even USAGE on the schema.
--
-- The canonical relations hold owner names, mailing addresses, situs addresses,
-- and legal descriptions. silver.field_publication_policy is metadata: no view,
-- row policy, or privilege applies it, so a SELECT would return every value
-- including those the policy denies. Representing a field is not permission to
-- publish it, and the API reads approved Gold products through bounded
-- projections that do not exist yet. Withholding schema usage means a table
-- grant added by mistake later is still unreachable.

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (6, '0006_canonical_schema', :'file_sha256');

COMMIT;
