-- 0004_quality_results.sql
--
-- Every evaluated rule, whether it passed, and what it measured.
--
-- Run with:  psql --single-transaction --set ON_ERROR_STOP=on -f 0004_quality_results.sql

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
    rule_id      text        PRIMARY KEY,
    description  text        NOT NULL,
    severity     text        NOT NULL,
    rule_family  text        NOT NULL,
    threshold    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    active       boolean     NOT NULL DEFAULT true,
    defined_at   timestamptz NOT NULL DEFAULT now(),

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
    'the place failing rules are moved to.';

-- ---------------------------------------------------------------------------
-- Results
-- ---------------------------------------------------------------------------

CREATE TABLE quality.evaluation (
    evaluation_id  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         bigint      NOT NULL
                               REFERENCES ingestion.run (run_id) ON DELETE CASCADE,
    rule_id        text        NOT NULL REFERENCES quality.rule (rule_id),
    severity       text        NOT NULL,
    passed         boolean     NOT NULL,
    measured_value text,
    expected_value text,
    subject        text,
    evaluated_at   timestamptz NOT NULL DEFAULT now(),

    UNIQUE (run_id, rule_id, subject),
    CONSTRAINT evaluation_severity_is_blocking_or_warning
        CHECK (severity IN ('blocking', 'warning')),
    CONSTRAINT evaluation_failure_states_what_it_saw_and_wanted CHECK (
        passed OR (measured_value IS NOT NULL AND expected_value IS NOT NULL)
    )
);

COMMENT ON TABLE quality.evaluation IS
    'One row per rule evaluated against a run, passing or failing. Every evaluated '
    'rule is recorded, not only the failures: a release that passed because a rule '
    'never ran looks identical afterwards to one that passed because it did.';
COMMENT ON COLUMN quality.evaluation.severity IS
    'Copied from the rule as it stood when this ran. Editing a rule later must not '
    'silently restate what an old release was judged against.';
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
WHERE NOT evaluation.passed
  AND evaluation.severity = 'blocking';

COMMENT ON VIEW quality.blocking_failure IS
    'What stands between a run and publication. Derived rather than stored so a run '
    'cannot be marked publishable while a failing blocking rule sits beside it.';

INSERT INTO platform.schema_migration (version, name)
VALUES (4, '0004_quality_results');

COMMIT;
