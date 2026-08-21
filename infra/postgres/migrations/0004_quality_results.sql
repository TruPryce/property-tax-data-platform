-- 0004_quality_results.sql
--
-- Every evaluated rule, whether it passed, and what it measured.
--
-- Run with:  psql --set ON_ERROR_STOP=on \
--              -v file_sha256="$(sha256sum 0004_quality_results.sql | cut -d' ' -f1)" \
--              -f 0004_quality_results.sql

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
    IF NOT EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 3) THEN
        RAISE EXCEPTION 'migration 0003 must be applied first';
    END IF;
    IF EXISTS (SELECT 1 FROM platform.schema_migration WHERE version = 4) THEN
        RAISE EXCEPTION 'migration 0004 is already applied';
    END IF;
END $$;

CREATE SCHEMA quality;

COMMENT ON SCHEMA quality IS
    'Data-quality rules and the results of evaluating them against a run.';

CREATE TABLE quality.rule (
    rule_id      text        NOT NULL,
    version      integer     NOT NULL,
    description  text        NOT NULL,
    severity     text        NOT NULL,
    rule_family  text        NOT NULL,
    threshold    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    active       boolean     NOT NULL DEFAULT true,
    defined_at   timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (rule_id, version),
    CONSTRAINT rule_version_is_positive CHECK (version >= 1),
    CONSTRAINT rule_id_is_a_lowercase_name
        CHECK (rule_id ~ '^[a-z][a-z0-9_]{0,63}$'),
    CONSTRAINT rule_description_not_blank
        CHECK (btrim(description) <> ''),
    CONSTRAINT rule_severity_is_blocking_or_warning
        CHECK (severity IN ('blocking', 'warning')),
    CONSTRAINT rule_threshold_is_an_object
        CHECK (jsonb_typeof(threshold) = 'object'),
    CONSTRAINT rule_family_is_known CHECK (rule_family IN (
        'required_key_completeness',
        'logical_uniqueness',
        'child_relationship',
        'schema_compatibility',
        'record_count_drift',
        'value_validity',
        'archive_completeness',
        'source_specific'
    ))
);

COMMENT ON TABLE quality.rule IS
    'Rules are rows, not code. Thresholds are configuration so a county whose export '
    'legitimately grew is admitted by changing a value rather than by weakening a '
    'rule for everyone.';
COMMENT ON COLUMN quality.rule.severity IS
    'Blocking prevents publication and quarantines the release. Warning stays visible '
    'without blocking. There is no third level, so "advisory" cannot quietly become '
    'the place failing rules are moved to. This is the only place severity is stated.';
COMMENT ON COLUMN quality.rule.version IS
    'Changing what a rule means inserts a new version rather than updating a row. An '
    'evaluation pins the version it was judged under, so history stays true without '
    'the evaluation restating the severity it was judged by.';

-- ---------------------------------------------------------------------------
-- Results
-- ---------------------------------------------------------------------------

CREATE TABLE quality.evaluation (
    evaluation_id  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         bigint      NOT NULL
                               REFERENCES ingestion.run (run_id) ON DELETE CASCADE,
    rule_id        text        NOT NULL,
    rule_version   integer     NOT NULL,
    passed         boolean     NOT NULL,
    measured_value text,
    expected_value text,
    subject        text,
    evaluated_at   timestamptz NOT NULL DEFAULT now(),

    FOREIGN KEY (rule_id, rule_version)
        REFERENCES quality.rule (rule_id, version),
    -- NULLS NOT DISTINCT because a NULL subject means "evaluated once for this
    -- run", which is a value rather than an unknown. Under ordinary UNIQUE two
    -- such rows are distinct and the same rule records two verdicts for one run.
    UNIQUE NULLS NOT DISTINCT (run_id, rule_id, subject),
    CONSTRAINT evaluation_failure_states_what_it_saw_and_wanted CHECK (
        passed OR (measured_value IS NOT NULL AND expected_value IS NOT NULL)
    )
);

COMMENT ON TABLE quality.evaluation IS
    'One row per rule evaluated against a run, passing or failing. Every evaluated '
    'rule is recorded, not only the failures: a release that passed because a rule '
    'never ran looks identical afterwards to one that passed because it did.';
COMMENT ON COLUMN quality.evaluation.rule_version IS
    'Which version of the rule judged this run. There is deliberately no severity '
    'column here: a copy is something a loader can write, and a loader that recorded '
    'warning against a blocking rule would make the failure vanish from '
    'quality.blocking_failure while every row still looked well formed.';
COMMENT ON COLUMN quality.evaluation.measured_value IS
    'Required whenever the rule failed, together with what was expected, because a '
    'failure an operator cannot act on is a failure they will learn to ignore. Holds '
    'an aggregate or a rule-level fact, never a source record value.';
COMMENT ON COLUMN quality.evaluation.subject IS
    'Which member, table, or field the rule was evaluated against, when a rule runs '
    'more than once per release. NULL means the rule was evaluated once for the run.';

CREATE INDEX evaluation_failures_by_run
    ON quality.evaluation (run_id)
    WHERE NOT passed;

-- ---------------------------------------------------------------------------
-- Whether a run may publish, derived
-- ---------------------------------------------------------------------------

CREATE VIEW quality.blocking_failure AS
SELECT
    evaluation.run_id,
    evaluation.rule_id,
    evaluation.subject,
    evaluation.measured_value,
    evaluation.expected_value,
    evaluation.evaluated_at
FROM quality.evaluation
JOIN quality.rule
  ON  rule.rule_id = evaluation.rule_id
  AND rule.version = evaluation.rule_version
WHERE NOT evaluation.passed
  AND rule.severity = 'blocking';

COMMENT ON VIEW quality.blocking_failure IS
    'What stands between a run and publication. Derived rather than stored so a run '
    'cannot be marked publishable while a failing blocking rule sits beside it, and '
    'severity is read from the rule version the evaluation pinned rather than from '
    'anything the loader wrote.';

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

GRANT USAGE ON SCHEMA quality TO property_tax_ingestion;

-- Rules are configuration the migrator owns; a loader reads them and records
-- results against them, and may not redefine what blocks.
GRANT SELECT ON quality.rule TO property_tax_ingestion;
GRANT SELECT, INSERT ON quality.evaluation TO property_tax_ingestion;
GRANT SELECT ON quality.blocking_failure TO property_tax_ingestion;

ALTER DEFAULT PRIVILEGES FOR ROLE property_tax_migrator IN SCHEMA quality
    GRANT SELECT ON TABLES TO property_tax_ingestion;

-- property_tax_api is granted nothing in quality: an evaluation names the
-- measured and expected values of a rule over a release, which is internal
-- detail rather than an approved product.

INSERT INTO platform.schema_migration (version, name, file_sha256)
VALUES (4, '0004_quality_results', :'file_sha256');

COMMIT;
