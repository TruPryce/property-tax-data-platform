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
        uv run pytest tests/migrations

The password goes in `PGPASSWORD`, which libpq reads, rather than into the
connection string, so it stays out of shell history and process listings.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg", reason="psycopg is required to talk to PostgreSQL")

MIGRATIONS = Path(__file__).resolve().parents[2] / "infra" / "postgres" / "migrations"
SCHEMAS = ("publication", "quality", "ingestion", "silver", "bronze", "platform")


def _dsn() -> str:
    dsn = os.environ.get("PTDP_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("PTDP_TEST_DATABASE_URL is not set")
    return dsn


def migration_files() -> list[Path]:
    return sorted(path for path in MIGRATIONS.glob("[0-9]*.sql"))


def rollback_files() -> list[Path]:
    return sorted(path for path in (MIGRATIONS / "rollback").glob("[0-9]*.sql"))


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
        for path in migration_files():
            with handle.cursor() as cursor:
                cursor.execute(path.read_text())
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


def test_every_migration_has_a_rollback() -> None:
    """A schema change nobody can undo is a decision, not a migration."""

    assert [path.name for path in migration_files()] == [path.name for path in rollback_files()]


def test_migration_versions_are_contiguous_and_unique() -> None:
    versions = [int(path.name[:4]) for path in migration_files()]

    assert versions == list(range(1, len(versions) + 1))


def test_every_migration_is_one_transaction() -> None:
    """Half-applied is worse than failed, because failed is obvious."""

    for path in migration_files() + rollback_files():
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


def test_applying_a_migration_twice_is_refused(connection: object) -> None:
    """The DBA runs these by hand, so running one twice is a real Tuesday."""

    message = refuses(connection, migration_files()[2].read_text())

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
        "INSERT INTO quality.rule(rule_id,description,severity,rule_family) "
        "VALUES ('account_key_present','required key','blocking','required_key_completeness')",
    )

    message = refuses(
        connection,
        "INSERT INTO quality.evaluation(run_id,rule_id,severity,passed,subject) "
        f"VALUES ({run_id},'account_key_present','blocking',false,'prop.csv')",
    )
    assert "violates" in message

    accepts(
        connection,
        "INSERT INTO quality.evaluation"
        "(run_id,rule_id,severity,passed,measured_value,expected_value,subject) "
        f"VALUES ({run_id},'account_key_present','blocking',false,'461219','>= 461510','p.csv')",
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
        "INSERT INTO quality.rule(rule_id,description,severity,rule_family) "
        "VALUES ('advisory_thing','x','advisory','value_validity')",
    )

    assert "violates" in message


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
