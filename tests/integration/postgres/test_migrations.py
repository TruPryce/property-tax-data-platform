"""The migrations, applied to a real PostgreSQL and then attacked.

A migration that parses is not a migration that works, and a constraint that
exists is not a constraint that binds. Every invariant the schema claims is
tested here by trying to violate it.

These need a database. Set `PTDP_TEST_DATABASE_URL` and they run; leave it unset
and they skip:

    export PGPASSWORD="$(openssl rand -hex 16)"
    docker run -d --name ptdp-test -p 5433:5432 \
        -e POSTGRES_PASSWORD="$PGPASSWORD" -e POSTGRES_DB=ptdp postgres:16-alpine
    PTDP_TEST_DATABASE_URL=postgresql://postgres@localhost:5433/ptdp \
        uv run pytest tests/integration/postgres

The password goes in `PGPASSWORD`, which libpq reads, rather than into the
connection string, so it stays out of shell history and process listings.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg", reason="psycopg is required to talk to PostgreSQL")

MIGRATIONS = Path(__file__).resolve().parents[3] / "infra" / "postgres" / "migrations"
SCHEMAS = ("publication", "quality", "ingestion", "silver", "bronze", "platform")
ROLES = ("property_tax_migrator", "property_tax_ingestion", "property_tax_api")


def _dsn() -> str:
    dsn = os.environ.get("PTDP_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("PTDP_TEST_DATABASE_URL is not set")
    return dsn


def migration_files() -> list[Path]:
    return sorted(path for path in MIGRATIONS.glob("[0-9]*.sql"))


def render(path: Path) -> str:
    """Render a migration the way psql would, for the two features it uses.

    psycopg speaks the wire protocol and knows nothing about psql meta-commands
    or variables, so the `\\if` guard and `:'file_sha256'` are resolved here.
    That means these tests exercise the SQL rather than the psql invocation; the
    documented command is in infra/postgres/README.md.
    """
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    body = "\n".join(line for line in path.read_text().splitlines() if not line.startswith("\\"))
    return body.replace(":'file_sha256'", f"'{digest}'")


@pytest.fixture(scope="module")
def connection() -> Iterator[object]:
    dsn = _dsn()
    try:
        handle = psycopg.connect(dsn, connect_timeout=5)
    except psycopg.OperationalError as error:  # pragma: no cover - environment dependent
        pytest.skip(f"no PostgreSQL at PTDP_TEST_DATABASE_URL: {error}")
    handle.autocommit = True
    with handle:
        # Start from nothing, so a leftover schema cannot make a broken
        # migration look applied.
        with handle.cursor() as cursor:
            for schema in SCHEMAS:
                cursor.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            # The migrations grant to roles the cluster bootstrap creates. A test
            # database has not run init/, so stand them up here rather than let a
            # GRANT to a missing role look like a broken migration.
            for role in ROLES:
                cursor.execute(
                    "DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') "
                    f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
                )
        for path in migration_files():
            with handle.cursor() as cursor:
                cursor.execute(render(path))
        yield handle


def refuses(connection: object, statement: str) -> str:
    """Run a statement that must be rejected, and return why it was.

    The rollback is not tidiness. These files carry their own `BEGIN`, so a
    migration that raises leaves an open aborted transaction behind, and every
    later statement then fails with "current transaction is aborted" rather
    than with the constraint it was actually testing. A whole suite can turn
    red for one reason while appearing to prove twenty things.
    """

    with pytest.raises(psycopg.errors.Error) as raised:  # type: ignore[union-attr]
        with connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute(statement)
    message = str(raised.value)
    connection.rollback()  # type: ignore[attr-defined]
    return message


def accepts(connection: object, statement: str) -> None:
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(statement)
    connection.commit()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The files themselves
# ---------------------------------------------------------------------------


def test_there_are_no_inverse_scripts() -> None:
    """Forward-only: a DROP SCHEMA CASCADE script is a production footgun.

    A disposable database is rebuilt from empty; a real one is corrected by a
    forward migration and recovered by restore.
    """

    assert not (MIGRATIONS / "rollback").exists()


def test_migration_versions_are_contiguous_and_unique() -> None:
    versions = [int(path.name[:4]) for path in migration_files()]

    assert versions == list(range(1, len(versions) + 1))


def test_every_migration_is_one_transaction() -> None:
    """Half-applied is worse than failed, because failed is obvious."""

    for path in migration_files():
        body = path.read_text()
        assert body.count("BEGIN;") == 1, path.name
        assert body.rstrip().endswith("COMMIT;"), path.name


def test_the_ledger_records_every_applied_file(connection: object) -> None:
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute("SELECT version, name FROM platform.schema_migration ORDER BY version")
        applied = cursor.fetchall()

    assert [(version, name) for version, name in applied] == [
        (int(path.name[:4]), path.stem) for path in migration_files()
    ]


@pytest.mark.parametrize("path", migration_files(), ids=lambda path: path.stem)
def test_applying_a_migration_twice_is_refused(connection: object, path: Path) -> None:
    """The DBA runs these by hand, so running one twice is a real Tuesday.

    Every file, including 0001: it creates the ledger it checks, so its guard has
    to survive the table not existing on a first run and existing on a second.
    """

    message = refuses(connection, render(path))

    assert "already applied" in message

    # And the refusal changed nothing, which is the half worth checking: a
    # guard that raises after creating three tables is not a guard.
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute("SELECT count(*) FROM platform.schema_migration")
        assert cursor.fetchone()[0] == len(migration_files())


# ---------------------------------------------------------------------------
# Bronze
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "statement"),
    [
        (
            "an uppercase checksum",
            "INSERT INTO bronze.artifact(sha256,locator,byte_count) "
            f"VALUES ('{'A' * 64}','s3://b/k',1)",
        ),
        (
            "a locator carrying a control character",
            "INSERT INTO bronze.artifact(sha256,locator,byte_count) "
            f"VALUES ('{'b' * 64}','s3://b/'||chr(10)||'k',1)",
        ),
        (
            "a negative byte count",
            "INSERT INTO bronze.artifact(sha256,locator,byte_count) "
            f"VALUES ('{'c' * 64}','s3://b/k',-1)",
        ),
        (
            "a jurisdiction that is not state-and-county",
            "INSERT INTO bronze.release_manifest"
            "(jurisdiction_code,artifact_sha256,acquired_at,source_url,response_status,manifest_version)"
            f" VALUES ('COLLIN','{'a' * 64}',now(),'https://x',200,1)",
        ),
    ],
)
def test_bronze_refuses_malformed_evidence(connection: object, label: str, statement: str) -> None:
    assert "violates" in refuses(connection, statement)


def test_the_same_release_identity_with_different_bytes_is_kept_twice(
    connection: object,
) -> None:
    """Not an error to retry and not a duplicate to ignore.

    Both versions are kept and the release is flagged, never overwritten — so
    the schema has to permit two artifacts under one identity, and the conflict
    has to be derived rather than stored.
    """

    for digest, locator in ((("1" * 64), "s3://b/first"), (("2" * 64), "s3://b/second")):
        accepts(
            connection,
            "INSERT INTO bronze.artifact(sha256,locator,byte_count) "
            f"VALUES ('{digest}','{locator}',10)",
        )
    for digest in ("1" * 64, "2" * 64):
        accepts(
            connection,
            "INSERT INTO bronze.release_manifest"
            "(jurisdiction_code,artifact_sha256,acquired_at,source_url,response_status,manifest_version)"
            f" VALUES ('tx-collin','{digest}',now(),'https://collin/roll.zip',200,1)",
        )
    accepts(
        connection,
        "INSERT INTO bronze.release_partition "
        "SELECT manifest_id,'tx-collin',2025,'certified' FROM bronze.release_manifest "
        "WHERE jurisdiction_code='tx-collin'",
    )

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT distinct_artifact_count FROM bronze.diverged_release "
            "WHERE jurisdiction_code='tx-collin' AND tax_year=2025"
        )
        assert cursor.fetchone()[0] == 2

    # And no table carries the verdict. Scoped to the tables that describe a
    # release identity: `release_redirect.status` is an HTTP status and has
    # nothing to do with this, so a blanket search for "status" across the
    # schema would fail for the wrong reason and then be relaxed for the wrong
    # reason too.
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema='bronze' "
            "AND table_name IN ('artifact','release_manifest','release_partition') "
            "AND column_name IN ('conflict','divergence','conflict_state','is_diverged')"
        )
        assert cursor.fetchall() == [], "a stored verdict would be a claim, not an answer"


# ---------------------------------------------------------------------------
# Privileges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "relation", "privilege", "expected"),
    [
        ("property_tax_ingestion", "silver.source_record", "INSERT", True),
        ("property_tax_ingestion", "bronze.release_manifest", "INSERT", True),
        ("property_tax_ingestion", "ingestion.release_diagnostic", "INSERT", True),
        ("property_tax_ingestion", "quality.evaluation", "INSERT", True),
        ("property_tax_api", "silver.source_record", "SELECT", True),
        ("property_tax_api", "publication.publication", "SELECT", True),
        # Bronze is acquisition evidence, so nobody may rewrite it.
        ("property_tax_ingestion", "bronze.release_manifest", "UPDATE", False),
        ("property_tax_ingestion", "bronze.artifact", "DELETE", False),
        # The API reads. It does not write, and it does not define quality rules.
        ("property_tax_api", "silver.source_record", "INSERT", False),
        ("property_tax_api", "quality.rule", "INSERT", False),
        ("property_tax_ingestion", "quality.rule", "INSERT", False),
    ],
)
def test_the_roles_reach_exactly_what_they_were_granted(
    connection: object, role: str, relation: str, privilege: str, expected: bool
) -> None:
    """The bootstrap leaves both roles connect-only, so an ungranted table is invisible."""

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(f"SELECT has_table_privilege('{role}', '{relation}', '{privilege}')")
        assert cursor.fetchone()[0] is expected


@pytest.mark.parametrize("schema", ["silver", "bronze", "ingestion", "quality", "publication"])
def test_a_table_added_later_is_reachable_without_anyone_remembering(
    connection: object, schema: str
) -> None:
    """ALTER DEFAULT PRIVILEGES is the line usually forgotten.

    Without it the granted tables work and every table added afterwards is
    invisible to the reading role until someone notices in production.
    """

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT count(*) FROM pg_default_acl acl "
            "JOIN pg_namespace ns ON ns.oid = acl.defaclnamespace "
            f"WHERE ns.nspname = '{schema}' AND acl.defaclobjtype = 'r'"
        )
        assert cursor.fetchone()[0] >= 1, f"{schema} grants nothing to objects created later"


# ---------------------------------------------------------------------------
# Silver
# ---------------------------------------------------------------------------

_RECORD = (
    "INSERT INTO silver.source_record"
    "(jurisdiction_code,appraisal_year,release_identifier,source_member_name,"
    "source_row_number,parser_contract_version,layout_fingerprint{extra_columns})"
    " VALUES ('{jurisdiction}',{year},'{release}','{member}',{row},1,'fp'{extra_values})"
)


def _record(
    connection: object,
    *,
    jurisdiction: str = "tx-collin",
    year: int = 2025,
    release: str = "rel-1",
    member: str = "prop.csv",
    row: int = 1,
    family: str | None = None,
    status: str | None = None,
) -> str:
    columns = ""
    values = ""
    if family is not None:
        columns += ",source_family"
        values += f",'{family}'"
    if status is not None:
        columns += ",source_status"
        values += f",'{status}'"
    return _RECORD.format(
        extra_columns=columns,
        extra_values=values,
        jurisdiction=jurisdiction,
        year=year,
        release=release,
        member=member,
        row=row,
    )


def test_loading_the_same_record_again_is_refused(connection: object) -> None:
    """Retrying a Silver load must not produce duplicate logical records."""

    statement = _record(connection, release="retry", family="pacs", status="certified")
    accepts(connection, statement)

    assert "duplicate key" in refuses(connection, statement)


def test_one_row_may_emit_current_and_certified_observations(connection: object) -> None:
    """Not deduplicated and not treated as equivalent: they are different facts."""

    accepts(connection, _record(connection, release="two-obs", year=2025, status="certified"))
    accepts(connection, _record(connection, release="two-obs", year=2026, status="current"))

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT count(*) FROM silver.source_record WHERE release_identifier='two-obs'"
        )
        assert cursor.fetchone()[0] == 2


def test_two_counties_may_share_a_release_name_member_and_row(connection: object) -> None:
    """release_identifier is caller-supplied and local, so it cannot be the key alone.

    Dallas and Collin can each publish a "certified-2025" containing a
    "property.txt" whose row 100 is a different property. Without
    jurisdiction_code leading the identity, whichever county loads second has its
    rows silently swallowed as retries of the first.
    """

    shared = {"release": "certified-2025", "member": "property.txt", "row": 100, "year": 2025}
    accepts(connection, _record(connection, jurisdiction="tx-dallas", **shared))
    accepts(connection, _record(connection, jurisdiction="tx-collin", **shared))

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT jurisdiction_code FROM silver.source_record "
            "WHERE release_identifier='certified-2025' AND source_member_name='property.txt' "
            "AND source_row_number=100 ORDER BY jurisdiction_code"
        )
        assert [row[0] for row in cursor.fetchall()] == ["tx-collin", "tx-dallas"]

    # Within one county the retry still collides, which is the property the key
    # exists for and the one a wider key could have broken.
    message = refuses(connection, _record(connection, jurisdiction="tx-dallas", **shared))
    assert "duplicate key" in message


def test_a_record_with_no_family_still_collides_with_itself(connection: object) -> None:
    """NULLS NOT DISTINCT.

    Without it an absent source_family reads as "unknown", two unknowns are
    never equal, and every retry inserts a fresh row — the retry key would look
    correct and enforce nothing.
    """

    statement = _record(connection, release="null-key", member="acct.txt")
    accepts(connection, statement)

    assert "duplicate key" in refuses(connection, statement)


@pytest.mark.parametrize(
    ("label", "columns", "values"),
    [
        ("no representation at all", "", ""),
        ("two representations at once", ",text_value,integer_value", ",'7',7"),
        ("precision without scale", ",numeric_value,numeric_precision", ",1.0,4"),
        (
            "precision describing no number",
            ",text_value,numeric_precision,numeric_scale",
            ",'x',4,2",
        ),
        ("a classification of its own", ",text_value,classification", ",'x','derived'"),
    ],
)
def test_a_native_value_must_be_exactly_one_observed_thing(
    connection: object, label: str, columns: str, values: str
) -> None:
    record_id = _one_record_id(connection)
    statement = (
        f"INSERT INTO silver.source_native_value(record_id,source_field{columns}) "
        f"VALUES ({record_id},'field_{abs(hash(label))}'{values})"
    )

    assert "violates" in refuses(connection, statement)


def test_an_observed_empty_string_is_a_fact_about_the_source(connection: object) -> None:
    """Exempt from the blank rule on purpose: one county emits it today."""

    record_id = _one_record_id(connection)
    accepts(
        connection,
        "INSERT INTO silver.source_native_value(record_id,source_field,lexical_text,text_value) "
        f"VALUES ({record_id},'owner_note','','')",
    )


def _one_record_id(connection: object) -> int:
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute("SELECT min(record_id) FROM silver.source_record")
        return int(cursor.fetchone()[0])


def test_publishing_a_field_requires_a_recorded_approval(connection: object) -> None:
    """Default-deny, and permission cannot be granted by a default."""

    accepts(
        connection,
        "INSERT INTO silver.field_publication_policy(jurisdiction_code,source_field,sensitivity) "
        "VALUES ('tx-collin','owner_name','sensitive')",
    )
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT publication_allowed FROM silver.field_publication_policy "
            "WHERE source_field='owner_name'"
        )
        assert cursor.fetchone()[0] is False

    message = refuses(
        connection,
        "INSERT INTO silver.field_publication_policy"
        "(jurisdiction_code,source_field,sensitivity,publication_allowed) "
        "VALUES ('tx-collin','mail_addr','sensitive',true)",
    )
    assert "violates" in message

    accepts(
        connection,
        "INSERT INTO silver.field_publication_policy"
        "(jurisdiction_code,source_field,sensitivity,publication_allowed,"
        "approved_by,approved_at,review_reference) "
        "VALUES ('tx-collin','situs_addr','ordinary',true,'maintainer',now(),'issue-78')",
    )


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_a_diagnostic_has_nowhere_to_put_content(connection: object) -> None:
    """Four columns and no fifth.

    A free-text detail column is where a complete row, an exception message, a
    credential, or an address would end up, so the table does not have one.
    """

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='ingestion' AND table_name='release_diagnostic' "
            "ORDER BY ordinal_position"
        )
        columns = [name for (name,) in cursor.fetchall()]

    assert columns == [
        "outcome_id",
        "diagnostic_index",
        "code",
        "field_name",
        "physical_row_number",
        "layout_fingerprint",
    ]


def test_the_diagnostic_vocabulary_is_closed(connection: object) -> None:
    run_id, outcome_id = _one_outcome(connection)

    accepts(
        connection,
        f"INSERT INTO ingestion.release_diagnostic VALUES ({outcome_id},0,'record_rejected',"
        "'curr_market',42,'fp-1')",
    )
    message = refuses(
        connection,
        f"INSERT INTO ingestion.release_diagnostic VALUES ({outcome_id},1,"
        "'something_went_wrong',NULL,NULL,NULL)",
    )

    assert "violates" in message


@pytest.mark.parametrize(
    ("label", "disposition", "staged", "committed"),
    [
        ("a rejection that committed rows", "rejected", 10, 10),
        ("committing more than was staged", "accepted", 5, 9),
    ],
)
def test_an_outcome_cannot_record_a_plausible_lie(
    connection: object, label: str, disposition: str, staged: int, committed: int
) -> None:
    run_id, _ = _one_outcome(connection)
    accepts(
        connection,
        "INSERT INTO ingestion.run(jurisdiction_code,release_identifier) "
        f"VALUES ('tx-denton','{label.replace(' ', '-')}') RETURNING run_id",
    )
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute("SELECT max(run_id) FROM ingestion.run")
        fresh_run = int(cursor.fetchone()[0])

    message = refuses(
        connection,
        "INSERT INTO ingestion.release_outcome"
        "(run_id,disposition,boundary_contract_version,staged_record_count,committed_record_count) "
        f"VALUES ({fresh_run},'{disposition}',1,{staged},{committed})",
    )

    assert "violates" in message


def _one_outcome(connection: object) -> tuple[int, int]:
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute("SELECT run_id FROM ingestion.run WHERE release_identifier='seed' LIMIT 1")
        row = cursor.fetchone()
        if row is None:
            cursor.execute(
                "INSERT INTO ingestion.run(jurisdiction_code,release_identifier) "
                "VALUES ('tx-collin','seed') RETURNING run_id"
            )
            run_id = int(cursor.fetchone()[0])
            cursor.execute(
                "INSERT INTO ingestion.release_outcome"
                "(run_id,disposition,boundary_contract_version,staged_record_count,"
                "committed_record_count) "
                f"VALUES ({run_id},'accepted',1,500,500) RETURNING outcome_id"
            )
            return run_id, int(cursor.fetchone()[0])
        run_id = int(row[0])
        cursor.execute(f"SELECT outcome_id FROM ingestion.release_outcome WHERE run_id={run_id}")
        return run_id, int(cursor.fetchone()[0])


# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------


def test_a_failing_rule_must_say_what_it_saw_and_what_it_wanted(connection: object) -> None:
    """A failure an operator cannot act on is one they will learn to ignore."""

    run_id, _ = _one_outcome(connection)
    accepts(
        connection,
        "INSERT INTO quality.rule(rule_id,version,description,severity,rule_family) "
        "VALUES ('account_key_present',1,'required key','blocking','required_key_completeness')",
    )

    message = refuses(
        connection,
        "INSERT INTO quality.evaluation(run_id,rule_id,rule_version,passed,subject) "
        f"VALUES ({run_id},'account_key_present',1,false,'prop.csv')",
    )
    assert "violates" in message

    accepts(
        connection,
        "INSERT INTO quality.evaluation"
        "(run_id,rule_id,rule_version,passed,measured_value,expected_value,subject) "
        f"VALUES ({run_id},'account_key_present',1,false,'461219','>= 461510','p.csv')",
    )
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            f"SELECT measured_value, expected_value FROM quality.blocking_failure "
            f"WHERE run_id={run_id}"
        )
        assert cursor.fetchone() == ("461219", ">= 461510")


def test_there_is_no_third_severity(connection: object) -> None:
    """So failing rules cannot quietly be moved to "advisory"."""

    message = refuses(
        connection,
        "INSERT INTO quality.rule(rule_id,version,description,severity,rule_family) "
        "VALUES ('advisory_thing',1,'x','advisory','value_validity')",
    )

    assert "violates" in message


def test_a_loader_cannot_restate_the_severity_it_was_judged_by(connection: object) -> None:
    """The forgeable copy is gone: severity lives on the rule and nowhere else.

    A loader that wrote 'warning' beside a blocking rule would make the failure
    vanish from quality.blocking_failure while every row still looked well formed.
    """

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema='quality' AND table_name='evaluation' AND column_name='severity'"
        )
        assert cursor.fetchone()[0] == 0

    run_id, _ = _one_outcome(connection)
    accepts(
        connection,
        "INSERT INTO quality.rule(rule_id,version,description,severity,rule_family) "
        "VALUES ('dupes',1,'duplicate accounts','blocking','logical_uniqueness')",
    )
    accepts(
        connection,
        "INSERT INTO quality.evaluation"
        "(run_id,rule_id,rule_version,passed,measured_value,expected_value) "
        f"VALUES ({run_id},'dupes',1,false,'3','0')",
    )

    # The blocking failure is visible because the rule says blocking. Scoped to
    # this rule: the run legitimately carries failures from other rules.
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            f"SELECT count(*) FROM quality.blocking_failure "
            f"WHERE run_id={run_id} AND rule_id='dupes'"
        )
        assert cursor.fetchone()[0] == 1

    # Softening the rule later cannot rewrite what this run was judged by,
    # because the evaluation pins the version rather than copying the severity.
    accepts(
        connection,
        "INSERT INTO quality.rule(rule_id,version,description,severity,rule_family) "
        "VALUES ('dupes',2,'duplicate accounts','warning','logical_uniqueness')",
    )
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            f"SELECT count(*) FROM quality.blocking_failure "
            f"WHERE run_id={run_id} AND rule_id='dupes'"
        )
        assert cursor.fetchone()[0] == 1


def test_an_evaluation_cannot_pin_a_rule_version_that_does_not_exist(
    connection: object,
) -> None:
    run_id, _ = _one_outcome(connection)
    accepts(
        connection,
        "INSERT INTO quality.rule(rule_id,version,description,severity,rule_family) "
        "VALUES ('only_v1',1,'x','warning','value_validity')",
    )

    message = refuses(
        connection,
        "INSERT INTO quality.evaluation(run_id,rule_id,rule_version,passed) "
        f"VALUES ({run_id},'only_v1',7,true)",
    )

    assert "foreign key" in message.lower()


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------


def test_only_one_publication_is_current_per_product_and_jurisdiction(
    connection: object,
) -> None:
    """This is what makes publication atomic.

    Promoting a build and demoting its predecessor is one transaction, and a
    half-finished swap cannot leave two rows claiming to be what consumers read.
    """

    accepts(
        connection,
        "INSERT INTO publication.publication"
        "(product,jurisdiction_code,tax_year,release_kind,release_identifier,state,published_at) "
        "VALUES ('latest_certified','tx-ellis',2025,'certified','rel-a','current',now())",
    )
    message = refuses(
        connection,
        "INSERT INTO publication.publication"
        "(product,jurisdiction_code,tax_year,release_kind,release_identifier,state,published_at) "
        "VALUES ('latest_certified','tx-ellis',2025,'certified','rel-b','current',now())",
    )

    assert "duplicate key" in message


def test_proposed_values_may_move_available_without_moving_certified(
    connection: object,
) -> None:
    """Which is only possible if they are separate products, not one with a flag."""

    accepts(
        connection,
        "INSERT INTO publication.publication"
        "(product,jurisdiction_code,tax_year,release_kind,release_identifier,state,published_at) "
        "VALUES ('latest_available','tx-ellis',2026,'preliminary','rel-c','current',now())",
    )

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT product, tax_year FROM publication.current_publication "
            "WHERE jurisdiction_code='tx-ellis' ORDER BY product"
        )
        assert cursor.fetchall() == [("latest_available", 2026), ("latest_certified", 2025)]


def test_a_build_is_never_current_without_being_published(connection: object) -> None:
    message = refuses(
        connection,
        "INSERT INTO publication.publication"
        "(product,jurisdiction_code,tax_year,release_kind,release_identifier,state) "
        "VALUES ('history','tx-rockwall',2025,'certified','rel-d','current')",
    )

    assert "violates" in message


def test_current_publication_carries_the_lineage_a_consumer_needs(
    connection: object,
) -> None:
    """County, tax year, release kind, source as-of, publication time, release identity."""

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='publication' AND table_name='current_publication'"
        )
        columns = {name for (name,) in cursor.fetchall()}

    assert {
        "jurisdiction_code",
        "tax_year",
        "release_kind",
        "release_identifier",
        "source_as_of",
        "published_at",
    } <= columns
