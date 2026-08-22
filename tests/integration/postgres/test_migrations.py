"""The migrations, applied to a real PostgreSQL and then attacked.

A migration that parses is not a migration that works, and a constraint that
exists is not a constraint that binds. Every invariant the schema claims is
tested here by trying to violate it.

These need a database. Set `PTDP_TEST_DATABASE_URL` and they run; leave it unset
and they skip:

    export PGPASSWORD="$(openssl rand -hex 16)"
    docker run -d --name ptdp-test -p 5433:5432 \
        -e POSTGRES_PASSWORD="$PGPASSWORD" -e POSTGRES_DB=ptdp postgres:16.11-bookworm
    PTDP_TEST_DATABASE_URL=postgresql://postgres@localhost:5433/ptdp \
        uv run pytest tests/integration/postgres

The password goes in `PGPASSWORD`, which libpq reads, rather than into the
connection string, so it stays out of shell history and process listings.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
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

    # Evaluate the one conditional rather than only stripping its markers: the
    # \else branch raises on a missing checksum, and dropping the marker while
    # keeping the block would run the raise on every render.
    kept: list[str] = []
    in_else = False
    for line in path.read_text().splitlines():
        if line.startswith("\\if "):
            in_else = False  # the variable is always supplied here
            continue
        if line.startswith("\\else"):
            in_else = True
            continue
        if line.startswith("\\endif"):
            in_else = False
            continue
        if in_else or line.startswith("\\"):
            continue
        kept.append(line)
    return "\n".join(kept).replace(":'file_sha256'", f"'{digest}'")


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
                    f"THEN CREATE ROLE {role} NOINHERIT; END IF; END $$"
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


def commits(connection: object, *statements: str) -> str | None:
    """Run statements as one transaction; return the failure, or None.

    The outcome seal is a deferred constraint trigger judged at COMMIT, so an
    outcome and its evidence have to arrive together. This module's connection is
    autocommit, which would seal after every statement and make that impossible --
    which is itself the contract: a loader writes the pair in one transaction.
    """

    connection.autocommit = False  # type: ignore[attr-defined]
    try:
        with connection.cursor() as cursor:  # type: ignore[attr-defined]
            for statement in statements:
                cursor.execute(statement)
        connection.commit()  # type: ignore[attr-defined]
        return None
    except psycopg.Error as error:
        connection.rollback()  # type: ignore[attr-defined]
        return str(error)
    finally:
        connection.autocommit = True  # type: ignore[attr-defined]


def _rejected_outcome(connection: object, release: str, diagnostics: int) -> int:
    """A rejected outcome whose declared and retained diagnostics already agree."""

    _, run_id = _lineage(connection, jurisdiction="tx-denton", release=release)
    connection.autocommit = False  # type: ignore[attr-defined]
    try:
        with connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                "INSERT INTO ingestion.release_outcome"
                "(run_id,disposition,boundary_contract_version,total_diagnostic_count,"
                "parser_contract_version,layout_fingerprint) "
                f"VALUES ({run_id},'rejected',1,{diagnostics},1,'fp-1') RETURNING outcome_id"
            )
            outcome_id = int(cursor.fetchone()[0])
            for index in range(diagnostics):
                cursor.execute(
                    "INSERT INTO ingestion.release_diagnostic"
                    "(outcome_id,diagnostic_index,code,layout_fingerprint) "
                    f"VALUES ({outcome_id},{index},'record_rejected','fp-1')"
                )
        connection.commit()  # type: ignore[attr-defined]
    finally:
        connection.autocommit = True  # type: ignore[attr-defined]
    return outcome_id


def accepts(connection: object, statement: str) -> None:
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(statement)
    connection.commit()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The files themselves
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("psql") is None, reason="requires the psql client")
def test_omitting_the_checksum_exits_nonzero() -> None:
    """`\\quit` terminates normally and exits 0, so an operator script reads success.

    Against the live server, deliberately. psql connects before it reads `-f`, so
    an unreachable DSN exits 2 for the name lookup and never reaches the guard at
    all -- a probe pointed at one passes whether the guard exists or not.

    Exercised through psql because render() strips the meta-commands this defect
    lived in, so no in-process test can see it.
    """

    dsn = _dsn()
    completed = subprocess.run(
        ["psql", "--set", "ON_ERROR_STOP=on", "-f", str(migration_files()[0]), dsn],
        capture_output=True,
        text=True,
        check=False,
    )

    # 3 is psql's "error in script under ON_ERROR_STOP"; 2 would be the
    # connection failing, which is what this test exists not to measure.
    assert completed.returncode == 3, completed.stderr

    # The message, not the status, is what discriminates. Deleting the guard
    # still exits 3 -- the unset variable becomes a syntax error further down --
    # so a status-only assertion would pass against a migration with no guard.
    assert "file_sha256 was not supplied" in completed.stderr


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


def test_silver_lineage_must_describe_one_release(connection: object) -> None:
    """Four individually valid facts are not one release.

    Before the composite reference a row could name tx-dallas and certified-2025
    while pointing at a Collin run reading a Collin manifest, and every foreign
    key still held.
    """

    dallas_manifest, dallas_run = _lineage(
        connection, jurisdiction="tx-dallas", release="dallas-2025"
    )
    _, collin_run = _lineage(connection, jurisdiction="tx-collin", release="collin-2025")

    message = refuses(
        connection,
        "INSERT INTO silver.source_record"
        "(jurisdiction_code,appraisal_year,release_identifier,source_member_name,"
        "source_row_number,parser_contract_version,layout_fingerprint,manifest_id,run_id) "
        f"VALUES ('tx-dallas',2025,'dallas-2025','p.csv',1,1,'fp',"
        f"{dallas_manifest},{collin_run})",
    )

    assert "foreign key" in message.lower()


def test_a_run_belongs_to_the_county_whose_bytes_it_read(connection: object) -> None:
    """The forged partition is attempted first, because that is the real attack.

    A run now references a partition rather than a manifest, so refusing a Dallas
    run against a Collin manifest proves nothing unless the Dallas partition it
    would need is itself refused. Creating the run without that row fails for the
    uninteresting reason that no such partition exists.
    """

    manifest_id, _ = _lineage(connection, jurisdiction="tx-collin", release="county-bind")

    partition_message = refuses(
        connection,
        "INSERT INTO bronze.release_partition"
        "(manifest_id,jurisdiction_code,tax_year,release_kind) "
        f"VALUES ({manifest_id},'tx-dallas',2025,'certified')",
    )

    assert "foreign key" in partition_message.lower()

    # And with the forgery refused, the run that would have inherited it has
    # nothing to point at.
    run_message = refuses(
        connection,
        "INSERT INTO ingestion.run"
        "(jurisdiction_code,release_identifier,manifest_id,tax_year,release_kind) "
        f"VALUES ('tx-dallas','borrowed',{manifest_id},2025,'certified')",
    )

    assert "foreign key" in run_message.lower()


# ---------------------------------------------------------------------------
# The persisted outcome mirrors the carrier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "columns", "values"),
    [
        (
            "accepted with a diagnostic",
            "disposition,boundary_contract_version,total_diagnostic_count",
            "'accepted',1,3",
        ),
        (
            "rejected with none",
            "disposition,boundary_contract_version,total_diagnostic_count",
            "'rejected',1,0",
        ),
        (
            "accepted committing less than it staged",
            "disposition,boundary_contract_version,staged_record_count,committed_record_count",
            "'accepted',1,100,50",
        ),
        (
            "accepted having rejected a row",
            "disposition,boundary_contract_version,rejected_row_count",
            "'accepted',1,12",
        ),
        (
            "a boundary contract that is not one",
            "disposition,boundary_contract_version",
            "'accepted',2",
        ),
        (
            "half a prepared release",
            "disposition,boundary_contract_version,parser_contract_version",
            "'accepted',1,1",
        ),
    ],
)
def test_the_database_refuses_outcomes_the_carrier_refuses(
    connection: object, label: str, columns: str, values: str
) -> None:
    """ReleaseOutcome.__post_init__ rejects each of these; so must persistence.

    The publication gate reads `disposition = accepted` as authoritative, so an
    outcome the boundary could never have produced would be trusted by it.
    """

    _, run_id = _lineage(connection, jurisdiction="tx-rockwall", release=f"carrier-{len(values)}")

    message = refuses(
        connection,
        f"INSERT INTO ingestion.release_outcome(run_id,{columns}) VALUES ({run_id},{values})",
    )

    assert "violates" in message


def test_retained_evidence_stops_at_the_retention_limit(connection: object) -> None:
    """DIAGNOSTIC_RETENTION_LIMIT is 100, so index 100 is not a thing the carrier made."""

    _, outcome_id = _one_outcome(connection)

    message = refuses(
        connection,
        "INSERT INTO ingestion.release_diagnostic(outcome_id,diagnostic_index,code) "
        f"VALUES ({outcome_id},100,'layout_rejected')",
    )

    assert "violates" in message


def test_an_outcome_cannot_be_rewritten_after_the_fact(connection: object) -> None:
    """A verdict about a finished run, which something may already have published."""

    error = _as_role(
        connection,
        "property_tax_ingestion",
        "UPDATE ingestion.release_outcome SET disposition='rejected'",
    )

    assert error is not None
    assert "permission denied" in error.lower()


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
        # The API role reaches nothing these migrations create. Gold projections
        # do not exist yet, and field_publication_policy is metadata no privilege
        # applies, so SELECT on a value table would return denied values too.
        ("property_tax_api", "silver.source_record", "SELECT", False),
        ("property_tax_api", "silver.source_native_value", "SELECT", False),
        ("property_tax_api", "publication.publication", "SELECT", False),
        ("property_tax_api", "publication.current_publication", "SELECT", False),
        ("property_tax_api", "quality.evaluation", "SELECT", False),
        ("property_tax_api", "ingestion.release_diagnostic", "SELECT", False),
        # Bronze is acquisition evidence, so nobody may rewrite it.
        ("property_tax_ingestion", "bronze.release_manifest", "UPDATE", False),
        ("property_tax_ingestion", "bronze.artifact", "DELETE", False),
        # The API reads. It does not write, and it does not define quality rules.
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


def _as_role(connection: object, role: str, statement: str) -> str | None:
    """Run a statement as the consuming role. Returns the error, or None if it ran.

    ACL catalogues say what was granted; this says what the role can do. They
    differ whenever a grant is right and something else — a schema USAGE, a view's
    underlying table — is not.
    """

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(f"SET ROLE {role}")
        try:
            cursor.execute(statement)
        except psycopg.Error as error:
            return str(error)
        finally:
            cursor.execute("RESET ROLE")
            connection.rollback()  # type: ignore[attr-defined]
    return None


def test_the_api_role_cannot_read_silver_as_itself(connection: object) -> None:
    """The blocking case, exercised as the consumer rather than inferred from ACLs."""

    error = _as_role(connection, "property_tax_api", "SELECT 1 FROM silver.source_native_value")

    assert error is not None
    assert "permission denied" in error.lower()


def test_the_ingestion_role_can_write_silver_as_itself(connection: object) -> None:
    connection.rollback()  # type: ignore[attr-defined]
    statement = _record(connection, jurisdiction="tx-dallas", release="as-role", row=4242)

    assert _as_role(connection, "property_tax_ingestion", statement) is None


def test_the_ingestion_role_cannot_rewrite_acquisition_evidence(connection: object) -> None:
    """Bronze immutability is a privilege, not an intention."""

    error = _as_role(
        connection, "property_tax_ingestion", "UPDATE bronze.release_manifest SET source_url='x'"
    )

    assert error is not None
    assert "permission denied" in error.lower()


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
    "source_row_number,parser_contract_version,layout_fingerprint,manifest_id,run_id"
    "{extra_columns})"
    " VALUES ('{jurisdiction}',{year},'{release}','{member}',{row},1,'fp',"
    "{manifest_id},{run_id}{extra_values})"
)


def _lineage(
    connection: object,
    *,
    jurisdiction: str = "tx-collin",
    release: str = "rel-1",
    tax_year: int = 2025,
    release_kind: str = "certified",
) -> tuple[int, int]:
    """Build one coherent artifact -> manifest -> partition -> run chain.

    Explicit rather than borrowing whatever manifest happens to exist: Silver now
    binds run, manifest, county, and release as a single composite reference, so a
    fixture that mixes one county's manifest with another's release would fail for
    a reason unrelated to the test asking for it.
    """

    digest = hashlib.sha256(f"{jurisdiction}/{release}".encode()).hexdigest()
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT run_id, manifest_id FROM ingestion.run "
            f"WHERE jurisdiction_code='{jurisdiction}' AND release_identifier='{release}'"
        )
        row = cursor.fetchone()
        if row is not None:
            return int(row[1]), int(row[0])

        cursor.execute(
            "INSERT INTO bronze.artifact(sha256,locator,byte_count,media_type) "
            f"VALUES ('{digest}','s3://fixture/{digest}.zip',10,'application/zip') "
            "ON CONFLICT (sha256) DO NOTHING"
        )
        cursor.execute(
            "INSERT INTO bronze.release_manifest"
            "(jurisdiction_code,artifact_sha256,acquired_at,source_url,response_status,"
            "manifest_version) "
            f"VALUES ('{jurisdiction}','{digest}',now(),"
            "'https://example.invalid/a.zip',200,1) RETURNING manifest_id"
        )
        manifest_id = int(cursor.fetchone()[0])
        cursor.execute(
            "INSERT INTO bronze.release_partition"
            "(manifest_id,jurisdiction_code,tax_year,release_kind) "
            f"VALUES ({manifest_id},'{jurisdiction}',{tax_year},'{release_kind}') "
            "ON CONFLICT DO NOTHING"
        )
        cursor.execute(
            "INSERT INTO ingestion.run"
            "(jurisdiction_code,release_identifier,manifest_id,tax_year,release_kind) "
            f"VALUES ('{jurisdiction}','{release}',{manifest_id},{tax_year},"
            f"'{release_kind}') RETURNING run_id"
        )
        run_id = int(cursor.fetchone()[0])
    return manifest_id, run_id


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
    manifest_id, run_id = _lineage(connection, jurisdiction=jurisdiction, release=release)
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
        manifest_id=manifest_id,
        run_id=run_id,
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


@pytest.mark.parametrize(
    ("label", "approver", "reference"),
    [
        ("empty strings", "''", "''"),
        ("whitespace", "'   '", "'  '"),
        ("a pasted tab", "E'\\t'", "'REV-1'"),
    ],
)
def test_a_blank_approval_is_not_a_named_approver(
    connection: object, label: str, approver: str, reference: str
) -> None:
    """NOT NULL is not the same as named, and the policy says named."""

    message = refuses(
        connection,
        "INSERT INTO silver.field_publication_policy"
        "(jurisdiction_code,source_field,sensitivity,publication_allowed,"
        "approved_by,approved_at,review_reference) "
        f"VALUES ('tx-collin','owner_name_{len(label)}','sensitive',true,"
        f"{approver},now(),{reference})",
    )

    assert "violates" in message


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
    # A rejected outcome declaring one diagnostic, so the row below is legal
    # evidence rather than a contradiction of an accepted outcome.
    outcome_id = _rejected_outcome(connection, "closed-vocabulary", 1)

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
    _, fresh_run = _lineage(connection, jurisdiction="tx-denton", release=label.replace(" ", "-"))

    message = refuses(
        connection,
        "INSERT INTO ingestion.release_outcome"
        "(run_id,disposition,boundary_contract_version,staged_record_count,committed_record_count) "
        f"VALUES ({fresh_run},'{disposition}',1,{staged},{committed})",
    )

    assert "violates" in message


def _one_outcome(connection: object) -> tuple[int, int]:
    """A run with an accepted outcome, built on a coherent lineage chain."""

    _, run_id = _lineage(connection, jurisdiction="tx-collin", release="seed")
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(f"SELECT outcome_id FROM ingestion.release_outcome WHERE run_id={run_id}")
        row = cursor.fetchone()
        if row is not None:
            return run_id, int(row[0])
        cursor.execute(
            "INSERT INTO ingestion.release_outcome"
            "(run_id,disposition,boundary_contract_version,staged_record_count,"
            "committed_record_count) "
            f"VALUES ({run_id},'accepted',1,500,500) RETURNING outcome_id"
        )
        return run_id, int(cursor.fetchone()[0])


def test_a_run_is_bound_to_one_logical_partition(connection: object) -> None:
    """One artifact carries several releases, so the manifest alone does not say which.

    A measured Collin archive holds current values for one year and certified
    values for another. Binding a run to the artifact left which of them it
    processed unstated, and a publication could then claim the other.
    """

    manifest_id, _ = _lineage(
        connection,
        jurisdiction="tx-collin",
        release="current-2026",
        tax_year=2026,
        release_kind="current",
    )
    # The same artifact also carries 2025/certified.
    accepts(
        connection,
        "INSERT INTO bronze.release_partition"
        "(manifest_id,jurisdiction_code,tax_year,release_kind) "
        f"VALUES ({manifest_id},'tx-collin',2025,'certified')",
    )

    message = refuses(
        connection,
        "INSERT INTO ingestion.run"
        "(jurisdiction_code,release_identifier,manifest_id,tax_year,release_kind) "
        f"VALUES ('tx-collin','no-such-partition',{manifest_id},2099,'certified')",
    )

    assert "foreign key" in message.lower()


def test_a_publication_cannot_claim_a_partition_its_run_did_not_process(
    connection: object,
) -> None:
    """The artifact carrying a partition is not the run having processed it."""

    manifest_id, run_id = _lineage(
        connection,
        jurisdiction="tx-collin",
        release="multi-2026",
        tax_year=2026,
        release_kind="current",
    )
    accepts(
        connection,
        "INSERT INTO bronze.release_partition"
        "(manifest_id,jurisdiction_code,tax_year,release_kind) "
        f"VALUES ({manifest_id},'tx-collin',2025,'certified')",
    )
    accepts(
        connection,
        "INSERT INTO ingestion.release_outcome"
        "(run_id,disposition,boundary_contract_version,staged_record_count,"
        f"committed_record_count) VALUES ({run_id},'accepted',1,1,1)",
    )

    # The run processed 2026/current; this claims the artifact's other partition.
    message = refuses(
        connection,
        "INSERT INTO publication.publication"
        "(product,jurisdiction_code,tax_year,release_kind,release_identifier,run_id,"
        "state,published_at) "
        f"VALUES ('latest_certified','tx-collin',2025,'certified','multi-2026',{run_id},"
        "'current',now())",
    )

    assert "foreign key" in message.lower()


def test_the_loader_cannot_repoint_a_run_after_publication(connection: object) -> None:
    """Run identity is what silver and publications bind to."""

    error = _as_role(
        connection,
        "property_tax_ingestion",
        "UPDATE ingestion.run SET release_identifier='rewritten-after-publication'",
    )

    assert error is not None
    assert "permission denied" in error.lower()


def test_the_loader_may_still_close_a_run(connection: object) -> None:
    """Column-level, so lifecycle stays writable while identity does not."""

    assert (
        _as_role(
            connection, "property_tax_ingestion", "UPDATE ingestion.run SET finished_at = now()"
        )
        is None
    )


def test_an_accepted_outcome_cannot_retain_a_diagnostic(connection: object) -> None:
    """The contradiction the earlier suite demonstrated by accident.

    An accepted outcome declares zero diagnostics, so a retained one means the
    scalar and the rows describe different releases -- and the publication gate
    trusts the scalar.
    """

    _, outcome_id = _one_outcome(connection)

    message = refuses(
        connection,
        "INSERT INTO ingestion.release_diagnostic(outcome_id,diagnostic_index,code) "
        f"VALUES ({outcome_id},0,'record_rejected')",
    )

    assert "retains 1, expected 0" in message


def test_declared_and_retained_evidence_must_agree(connection: object) -> None:
    _, run_id = _lineage(connection, jurisdiction="tx-denton", release="counts-disagree")

    message = commits(
        connection,
        "INSERT INTO ingestion.release_outcome"
        "(run_id,disposition,boundary_contract_version,total_diagnostic_count) "
        f"VALUES ({run_id},'rejected',1,3)",
    )

    assert message is not None and "retains 0, expected 3" in message


def test_truncation_is_true_exactly_when_evidence_overflowed(connection: object) -> None:
    _, run_id = _lineage(connection, jurisdiction="tx-denton", release="truncation-lie")

    message = commits(
        connection,
        "INSERT INTO ingestion.release_outcome"
        "(run_id,disposition,boundary_contract_version,total_diagnostic_count,"
        f"diagnostics_truncated) VALUES ({run_id},'rejected',1,2,true)",
        "INSERT INTO ingestion.release_diagnostic(outcome_id,diagnostic_index,code) "
        "SELECT max(outcome_id),0,'record_rejected' FROM ingestion.release_outcome",
        "INSERT INTO ingestion.release_diagnostic(outcome_id,diagnostic_index,code) "
        "SELECT max(outcome_id),1,'record_rejected' FROM ingestion.release_outcome",
    )

    # PostgreSQL renders a boolean as t, so match the stable half.
    assert message is not None and "declares 2 diagnostic(s) with diagnostics_truncated" in message


@pytest.mark.parametrize(
    ("label", "outcome_fingerprint", "diagnostic_fingerprint"),
    [
        ("value against a different value", "'fp-outcome'", "'fp-somewhere-else'"),
        ("value against absent", "'fp-outcome'", "NULL"),
        ("absent against value", "NULL", "'fp-appeared'"),
    ],
)
def test_a_diagnostic_fingerprint_disagreeing_with_its_outcome_is_refused(
    connection: object, label: str, outcome_fingerprint: str, diagnostic_fingerprint: str
) -> None:
    """The carrier compares with plain inequality, so NULL is a value here.

    An exemption for a NULL diagnostic fingerprint would admit exactly the pair
    ReleaseOutcome.__post_init__ rejects.
    """

    parser_version = "NULL" if outcome_fingerprint == "NULL" else "1"
    _, run_id = _lineage(
        connection, jurisdiction="tx-denton", release=f"fp-{len(label)}-{label[0]}"
    )

    message = commits(
        connection,
        "INSERT INTO ingestion.release_outcome"
        "(run_id,disposition,boundary_contract_version,total_diagnostic_count,"
        "parser_contract_version,layout_fingerprint) "
        f"VALUES ({run_id},'rejected',1,1,{parser_version},{outcome_fingerprint})",
        "INSERT INTO ingestion.release_diagnostic"
        "(outcome_id,diagnostic_index,code,layout_fingerprint) "
        f"SELECT max(outcome_id),0,'layout_rejected',{diagnostic_fingerprint} "
        "FROM ingestion.release_outcome",
    )

    assert message is not None and "layout fingerprint is not its own" in message


@pytest.mark.parametrize(
    ("label", "columns", "values"),
    [
        (
            "an outcome fingerprint that is blank",
            "disposition,boundary_contract_version,parser_contract_version,layout_fingerprint",
            "'accepted',1,1,''",
        ),
        (
            "an outcome fingerprint that is whitespace",
            "disposition,boundary_contract_version,parser_contract_version,layout_fingerprint",
            "'accepted',1,1,'   '",
        ),
    ],
)
def test_an_optional_name_is_absent_or_named(
    connection: object, label: str, columns: str, values: str
) -> None:
    """_require_optional_name: None, or a non-blank str. '' is neither."""

    _, run_id = _lineage(connection, jurisdiction="tx-ellis", release=f"blank-{len(values)}")

    message = refuses(
        connection,
        f"INSERT INTO ingestion.release_outcome(run_id,{columns}) VALUES ({run_id},{values})",
    )

    assert "violates" in message


@pytest.mark.parametrize(
    ("label", "column", "value"),
    [
        ("a diagnostic field name", "field_name", "'  '"),
        ("a diagnostic fingerprint", "layout_fingerprint", "''"),
    ],
)
def test_a_blank_diagnostic_name_is_refused(
    connection: object, label: str, column: str, value: str
) -> None:
    outcome_id = _rejected_outcome(connection, f"blank-diag-{column}", 1)

    message = refuses(
        connection,
        f"INSERT INTO ingestion.release_diagnostic(outcome_id,diagnostic_index,code,{column}) "
        f"VALUES ({outcome_id},1,'record_rejected',{value})",
    )

    assert "violates" in message


PYTHON_WHITESPACE = sorted(
    {chr(codepoint) for codepoint in range(0x110000) if chr(codepoint).isspace()}
)


def test_the_database_and_the_carrier_agree_on_what_whitespace_is() -> None:
    """Enumerated from Python rather than transcribed, so the two cannot drift.

    `_require_optional_name` rejects anything blank under `str.strip()`, which
    removes 29 Unicode characters and not the six ASCII ones a naive `btrim`
    would. A U+00A0-only fingerprint was blank to the carrier and a name here.
    """

    assert len(PYTHON_WHITESPACE) == 29


@pytest.mark.parametrize("character", PYTHON_WHITESPACE, ids=lambda c: f"U+{ord(c):04X}")
def test_no_whitespace_character_alone_is_a_name(connection: object, character: str) -> None:
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute("SELECT platform.is_named(%s)", (character * 3,))
        assert cursor.fetchone()[0] is False, f"U+{ord(character):04X} accepted as a name"


NBSP = "\u00a0"


@pytest.mark.parametrize(
    ("label", "column"),
    [
        ("release identifier", "release_identifier"),
        ("source member name", "source_member_name"),
        ("layout fingerprint", "layout_fingerprint"),
        ("source account id", "source_account_id"),
        ("source family", "source_family"),
        ("source status", "source_status"),
        ("parcel reference", "parcel_reference"),
        ("provenance table name", "provenance_table_name"),
        ("provenance source family", "provenance_source_family"),
        ("provenance source status", "provenance_source_status"),
    ],
)
def test_the_loader_cannot_store_a_unicode_blank_source_record_field(
    connection: object, label: str, column: str
) -> None:
    """As the runtime role, end to end, against every carrier-backed field.

    The helper being right does not prove each constraint calls it: these fields
    map to SourceProvenance and AppraisalSourceRecord, whose carriers reject
    anything blank under `.strip()`, and they were still trimming ASCII only.
    """

    manifest_id, run_id = _lineage(connection, jurisdiction="tx-collin", release=f"nbsp-{column}")
    columns = {
        "jurisdiction_code": "'tx-collin'",
        "appraisal_year": "2025",
        "release_identifier": f"'nbsp-{column}'",
        "source_member_name": "'p.csv'",
        "source_row_number": "1",
        "parser_contract_version": "1",
        "layout_fingerprint": "'fp'",
        "manifest_id": str(manifest_id),
        "run_id": str(run_id),
    }
    # The composite lineage key needs release_identifier to stay the run's, so
    # that case is exercised through a run whose own identifier is the blank.
    if column == "release_identifier":
        # The composite lineage key forces this to equal the run's, so a blank
        # here cannot be reached without a blank run identifier. That is where
        # the field is settable, and the test below covers it there.
        pytest.skip("settable on the run, not the record; see the run identity test")
    columns[column] = f"'{NBSP}'"

    error = _as_role(
        connection,
        "property_tax_ingestion",
        f"INSERT INTO silver.source_record({','.join(columns)}) "
        f"VALUES ({','.join(columns.values())})",
    )

    assert error is not None, f"{label} accepted a non-breaking space"
    assert "violates check constraint" in error


def test_the_loader_cannot_open_a_run_with_a_unicode_blank_release(
    connection: object,
) -> None:
    """Where a blank release identifier is actually settable.

    silver.source_record inherits this value through the composite lineage key,
    so constraining it at the run is what makes the record's copy unreachable.
    """

    manifest_id, _ = _lineage(connection, jurisdiction="tx-collin", release="nbsp-run")

    error = _as_role(
        connection,
        "property_tax_ingestion",
        "INSERT INTO ingestion.run"
        "(jurisdiction_code,release_identifier,manifest_id,tax_year,release_kind) "
        f"VALUES ('tx-collin','{NBSP}',{manifest_id},2025,'certified')",
    )

    assert error is not None
    assert "violates check constraint" in error


_BTRIM_CALL = re.compile(r"\bbtrim\s*\(", re.IGNORECASE)
_HELPER_FILE = "0001_release_manifests.sql"
_HELPER_DEFINITION = re.compile(
    r"CREATE\s+FUNCTION\s+platform\.is_named\b.*?\$named\$(?P<body>.*?)\$named\$",
    re.DOTALL | re.IGNORECASE,
)


def plain_btrim_offenders(sources: dict[str, str]) -> list[str]:
    """Lines that trim without going through platform.is_named.

    Case-insensitive and whitespace-tolerant, because `BTRIM(` and `btrim (` are
    the same call, and a literal search for one spelling only stops the mutation
    nobody would make.

    Exactly one call is excused: the one inside `platform.is_named`'s body in
    `0001`. Anything reusable is not an exemption but a bypass waiting to be
    written -- skipping any `$named$` block would hide a second function using
    the same tag, and skipping lines that mention `platform.is_named` would hide
    `CHECK (platform.is_named(x) OR BTRIM(x) <> '')`, which reads as compliant
    and accepts a non-breaking space.
    """

    offenders: list[str] = []
    for name, body in sorted(sources.items()):
        scannable = body
        if name == _HELPER_FILE:
            match = _HELPER_DEFINITION.search(body)
            if match is None:
                offenders.append(f"{name}: platform.is_named is not defined here")
            else:
                start, end = match.span("body")
                # Blank the body, keeping newlines so line numbers still point
                # at the file a reader will open.
                scannable = body[:start] + re.sub(r"[^\n]", " ", body[start:end]) + body[end:]
        for number, line in enumerate(scannable.splitlines(), 1):
            if line.strip().startswith("--"):
                continue
            if _BTRIM_CALL.search(line):
                offenders.append(f"{name}:{number}")
    return offenders


def _migration_sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in MIGRATIONS.glob("[0-9]*.sql")}


def test_every_blank_check_uses_the_shared_definition() -> None:
    """The split between ASCII and Unicode trimming was the defect, twice.

    A field left on plain btrim looks correct beside one that is not, so the
    class is closed rather than the instances: the only btrim in the migrations
    is the one inside platform.is_named.
    """

    offenders = plain_btrim_offenders(_migration_sources())

    assert not offenders, f"plain btrim bypasses platform.is_named at {offenders}"


@pytest.mark.parametrize(
    ("label", "mutation"),
    [
        ("lowercase", "btrim(locator) <> ''"),
        ("uppercase", "BTRIM(locator) <> ''"),
        ("mixed case", "BTrim(locator) <> ''"),
        ("space before the paren", "btrim (locator) <> ''"),
        ("uppercase and spaced", "BTRIM  (locator) <> ''"),
        # Reads as compliant and accepts a non-breaking space: the disjunction
        # means the plain trim is enough on its own.
        (
            "a valid call beside an invalid one",
            "platform.is_named(locator) OR BTRIM(locator) <> ''",
        ),
    ],
)
def test_the_guard_catches_every_spelling_of_a_bypass(label: str, mutation: str) -> None:
    """A guard nobody attacks is a guard nobody knows the shape of.

    The first version matched the literal `btrim(`, so `BTRIM(` and `btrim (`
    restored the Unicode mismatch while the regression stayed green.
    """

    sources = _migration_sources()
    target = "0001_release_manifests.sql"
    sources[target] = sources[target].replace(
        "CHECK (platform.is_named(locator)),", f"CHECK ({mutation}),", 1
    )

    offenders = plain_btrim_offenders(sources)

    assert offenders, f"{label} bypass went undetected"
    assert any(item.startswith(target) for item in offenders)


def test_a_second_function_cannot_borrow_the_helper_s_dollar_tag() -> None:
    """`$named$` is a tag anyone may reuse, so it cannot be what earns the exemption.

    Skipping every block with that tag would hide a second function trimming
    plainly, in a different migration, with no mention of platform.is_named.
    """

    sources = _migration_sources()
    sources["0004_quality_results.sql"] += (
        "\n\nCREATE FUNCTION quality.looks_named(value text) RETURNS boolean\n"
        "LANGUAGE sql IMMUTABLE AS $named$\n"
        "    SELECT btrim(value) <> ''\n"
        "$named$;\n"
    )

    offenders = plain_btrim_offenders(sources)

    assert any(item.startswith("0004_quality_results.sql") for item in offenders)


def test_the_guard_notices_if_the_helper_stops_being_defined_where_it_looks() -> None:
    """The exemption is anchored to one function in one file, so it can go missing."""

    sources = _migration_sources()
    sources[_HELPER_FILE] = sources[_HELPER_FILE].replace(
        "CREATE FUNCTION platform.is_named", "CREATE FUNCTION platform.was_named", 1
    )

    offenders = plain_btrim_offenders(sources)

    assert any("is not defined here" in item for item in offenders)


def test_the_guard_does_not_flag_the_helper_itself() -> None:
    """Excused by location, so the exemption is not a phrase a new line can carry."""

    assert not plain_btrim_offenders(_migration_sources())
    assert "btrim" in (MIGRATIONS / _HELPER_FILE).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("label", "statement"),
    [
        (
            "native identifier name",
            "INSERT INTO silver.source_native_identifier"
            "(record_id,identifier_name,identifier_value) VALUES ({record},'{nbsp}','v')",
        ),
        (
            "native identifier value",
            "INSERT INTO silver.source_native_identifier"
            "(record_id,identifier_name,identifier_value) VALUES ({record},'geo','{nbsp}')",
        ),
        (
            "native value source field",
            "INSERT INTO silver.source_native_value"
            "(record_id,source_field,lexical_text,text_value) "
            "VALUES ({record},'{nbsp}','x','x')",
        ),
    ],
)
def test_the_loader_cannot_store_a_unicode_blank_child_field(
    connection: object, label: str, statement: str
) -> None:
    record_id = _one_record_id(connection)

    error = _as_role(
        connection,
        "property_tax_ingestion",
        statement.format(record=record_id, nbsp=NBSP),
    )

    assert error is not None, f"{label} accepted a non-breaking space"
    assert "violates check constraint" in error


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("a non-breaking space", "\u00a0"),
        ("an em space", "\u2003"),
        ("an ideographic space", "\u3000"),
    ],
)
def test_a_unicode_blank_fingerprint_is_refused(connection: object, label: str, value: str) -> None:
    """The carrier rejects these; the ASCII-only trim accepted them."""

    _, run_id = _lineage(connection, jurisdiction="tx-ellis", release=f"ws-{ord(value):04x}")

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        try:
            cursor.execute(
                "INSERT INTO ingestion.release_outcome"
                "(run_id,disposition,boundary_contract_version,parser_contract_version,"
                "layout_fingerprint) VALUES (%s,'accepted',1,1,%s)",
                (run_id, value),
            )
        except psycopg.Error as error:
            message = str(error)
        else:  # pragma: no cover - the constraint is what this test is about
            message = ""
        connection.rollback()  # type: ignore[attr-defined]

    assert "violates" in message


def test_a_blank_notice_field_name_is_refused(connection: object) -> None:
    outcome_id = _rejected_outcome(connection, "blank-notice", 1)

    message = refuses(
        connection,
        "INSERT INTO ingestion.release_notice(outcome_id,notice_index,code,field_name) "
        f"VALUES ({outcome_id},0,'extra_column_present','')",
    )

    assert "violates" in message


@pytest.mark.parametrize("table", ["release_diagnostic", "release_notice"])
def test_reparenting_evidence_leaves_neither_outcome_unsealed(
    connection: object, table: str
) -> None:
    """Moving a row changes two aggregates, so both are judged.

    Checking only the row's new parent left its former outcome declaring evidence
    it no longer holds -- reached through UPDATE, an event the trigger already
    fires on, so the gap was in which id it looked at rather than in coverage.
    """

    index_column = "diagnostic_index" if table == "release_diagnostic" else "notice_index"
    code = "'record_rejected'" if table == "release_diagnostic" else "'extra_column_present'"
    source = _rejected_outcome(connection, f"reparent-from-{table}", 1)
    target = _rejected_outcome(connection, f"reparent-to-{table}", 1)
    if table == "release_notice":
        # _rejected_outcome seeds diagnostics; give each outcome one notice too.
        for outcome_id in (source, target):
            assert (
                commits(
                    connection,
                    "UPDATE ingestion.release_outcome SET total_notice_count = 1 "
                    f"WHERE outcome_id = {outcome_id}",
                    f"INSERT INTO ingestion.release_notice(outcome_id,notice_index,code) "
                    f"VALUES ({outcome_id},0,{code})",
                )
                is None
            )

    # Raise the target's declared total and move the source's row into it. The
    # target ends valid; the source is left declaring one and holding none.
    message = commits(
        connection,
        "UPDATE ingestion.release_outcome "
        f"SET total_{'diagnostic' if table == 'release_diagnostic' else 'notice'}_count = 2 "
        f"WHERE outcome_id = {target}",
        f"UPDATE ingestion.{table} SET outcome_id = {target}, {index_column} = 1 "
        f"WHERE outcome_id = {source}",
    )

    assert message is not None, "the source outcome was left unsealed"
    assert f"outcome {source}" in message


def test_evidence_cannot_be_appended_after_the_outcome_is_sealed(connection: object) -> None:
    """A second transaction re-runs the check against a total that is now wrong."""

    outcome_id = _rejected_outcome(connection, "sealed", 1)

    message = refuses(
        connection,
        "INSERT INTO ingestion.release_diagnostic(outcome_id,diagnostic_index,code) "
        f"VALUES ({outcome_id},1,'record_rejected')",
    )

    assert "retains 2, expected 1" in message


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


def test_one_rule_records_one_verdict_per_run_even_with_no_subject(
    connection: object,
) -> None:
    """NULL subject means "evaluated once for the run", which is a value.

    Under ordinary UNIQUE two NULLs are distinct, so the same rule could record
    two verdicts for one run and a reader would have to guess which counted.
    """

    run_id, _ = _one_outcome(connection)
    accepts(
        connection,
        "INSERT INTO quality.rule(rule_id,version,description,severity,rule_family) "
        "VALUES ('run_wide',1,'once per run','warning','record_count_drift')",
    )
    accepts(
        connection,
        "INSERT INTO quality.evaluation(run_id,rule_id,rule_version,passed) "
        f"VALUES ({run_id},'run_wide',1,true)",
    )

    message = refuses(
        connection,
        "INSERT INTO quality.evaluation(run_id,rule_id,rule_version,passed) "
        f"VALUES ({run_id},'run_wide',1,true)",
    )

    assert "duplicate key" in message


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


def _accepted_run(
    connection: object,
    jurisdiction: str,
    release: str,
    *,
    tax_year: int = 2025,
    release_kind: str = "certified",
) -> int:
    _, run_id = _lineage(
        connection,
        jurisdiction=jurisdiction,
        release=release,
        tax_year=tax_year,
        release_kind=release_kind,
    )
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "INSERT INTO ingestion.release_outcome"
            "(run_id,disposition,boundary_contract_version,staged_record_count,"
            f"committed_record_count) VALUES ({run_id},'accepted',1,10,10)"
        )
    return run_id


def _publish(jurisdiction: str, release: str, run_id: int | str, state: str = "current") -> str:
    published = "now()" if state == "current" else "NULL"
    return (
        "INSERT INTO publication.publication"
        "(product,jurisdiction_code,tax_year,release_kind,release_identifier,run_id,"
        "state,published_at) "
        f"VALUES ('latest_available','{jurisdiction}',2025,'certified','{release}',"
        f"{run_id},'{state}',{published})"
    )


def test_a_publication_cannot_become_current_without_a_run(connection: object) -> None:
    message = refuses(connection, _publish("tx-collin", "no-run", "NULL"))

    assert "must name the ingestion run" in message


def test_a_publication_cannot_become_current_without_an_accepted_outcome(
    connection: object,
) -> None:
    """A run nothing has judged is not a release anyone accepted."""

    _, run_id = _lineage(connection, jurisdiction="tx-collin", release="unjudged")

    message = refuses(connection, _publish("tx-collin", "unjudged", run_id))

    assert "no release outcome" in message


def test_a_rejected_release_does_not_become_current(connection: object) -> None:
    _, run_id = _lineage(connection, jurisdiction="tx-collin", release="rejected-rel")
    # Rejected means at least one diagnostic, and the seal requires the row to
    # exist alongside the count, so both arrive in one transaction.
    assert (
        commits(
            connection,
            "INSERT INTO ingestion.release_outcome"
            "(run_id,disposition,boundary_contract_version,total_diagnostic_count) "
            f"VALUES ({run_id},'rejected',1,1)",
            "INSERT INTO ingestion.release_diagnostic(outcome_id,diagnostic_index,code) "
            "SELECT max(outcome_id),0,'record_rejected' FROM ingestion.release_outcome",
        )
        is None
    )

    message = refuses(connection, _publish("tx-collin", "rejected-rel", run_id))

    assert "rejected" in message


def test_a_blocking_quality_failure_keeps_the_prior_publication_current(
    connection: object,
) -> None:
    """The accepted rule: a blocking failure prevents publication."""

    run_id = _accepted_run(connection, "tx-collin", "blocked-rel")
    accepts(
        connection,
        "INSERT INTO quality.rule(rule_id,version,description,severity,rule_family) "
        "VALUES ('blocker_rule',1,'x','blocking','value_validity')",
    )
    accepts(
        connection,
        "INSERT INTO quality.evaluation"
        "(run_id,rule_id,rule_version,passed,measured_value,expected_value) "
        f"VALUES ({run_id},'blocker_rule',1,false,'9','0')",
    )

    message = refuses(connection, _publish("tx-collin", "blocked-rel", run_id))

    assert "blocking quality failure" in message

    # And it is not merely the insert that is refused: the pointer never moved.
    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT count(*) FROM publication.current_publication "
            "WHERE release_identifier='blocked-rel'"
        )
        assert cursor.fetchone()[0] == 0


def test_a_publication_cannot_claim_a_run_from_another_release(connection: object) -> None:
    """Accepted lineage has to be *this* release's, not merely some accepted one."""

    run_id = _accepted_run(connection, "tx-collin", "the-real-one")

    message = refuses(connection, _publish("tx-collin", "a-different-one", run_id))

    # A key now, not a comparison: it holds against every writer rather than only
    # when this table is touched.
    assert "foreign key" in message.lower()


def test_a_publication_cannot_claim_a_year_the_artifact_does_not_carry(
    connection: object,
) -> None:
    """The run does not carry year or kind, so they are checked against the artifact."""

    run_id = _accepted_run(connection, "tx-tarrant", "year-bind")

    message = refuses(
        connection,
        "INSERT INTO publication.publication"
        "(product,jurisdiction_code,tax_year,release_kind,release_identifier,run_id,"
        "state,published_at) "
        f"VALUES ('history','tx-tarrant',2099,'certified','year-bind',{run_id},"
        "'current',now())",
    )

    assert "foreign key" in message.lower()


def test_the_gate_admits_at_promotion_and_does_not_maintain_afterwards(
    connection: object,
) -> None:
    """A known limit, recorded so it is a decision rather than a surprise.

    The trigger fires when a publication row is written. A blocking evaluation
    recorded afterwards leaves an already-current row current, because sealing
    quality for a published release needs a finalization model that task 6.2
    owns. This test exists to keep that gap visible and to fail loudly if 6.2
    later closes it, at which point it should be replaced rather than deleted.
    """

    run_id = _accepted_run(connection, "tx-rockwall", "later-blocked")
    accepts(connection, _publish("tx-rockwall", "later-blocked", run_id))
    accepts(
        connection,
        "INSERT INTO quality.rule(rule_id,version,description,severity,rule_family) "
        "VALUES ('late_blocker',1,'x','blocking','value_validity')",
    )
    accepts(
        connection,
        "INSERT INTO quality.evaluation"
        "(run_id,rule_id,rule_version,passed,measured_value,expected_value) "
        f"VALUES ({run_id},'late_blocker',1,false,'1','0')",
    )

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT count(*) FROM publication.current_publication "
            "WHERE release_identifier='later-blocked'"
        )
        still_current = cursor.fetchone()[0]

    assert still_current == 1, (
        "if this now reads 0 the invariant became durable; replace this test "
        "with one asserting the maintained behaviour rather than removing it"
    )


def test_an_accepted_clean_release_may_become_current(connection: object) -> None:
    """The gate admits what it should, which is the half that proves it is a gate."""

    # A jurisdiction of its own: one publication is current per product and
    # jurisdiction, so reusing another test's county would collide on that index
    # rather than on the gate this test is about.
    run_id = _accepted_run(connection, "tx-denton", "clean-rel")

    accepts(connection, _publish("tx-denton", "clean-rel", run_id))

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT run_id FROM publication.current_publication "
            "WHERE release_identifier='clean-rel'"
        )
        assert cursor.fetchone()[0] == run_id


def test_only_one_publication_is_current_per_product_and_jurisdiction(
    connection: object,
) -> None:
    """This is what makes publication atomic.

    Promoting a build and demoting its predecessor is one transaction, and a
    half-finished swap cannot leave two rows claiming to be what consumers read.
    """

    run_a = _accepted_run(connection, "tx-ellis", "rel-a")
    run_b = _accepted_run(connection, "tx-ellis", "rel-b")
    accepts(
        connection,
        "INSERT INTO publication.publication"
        "(product,jurisdiction_code,tax_year,release_kind,release_identifier,run_id,"
        "state,published_at) "
        f"VALUES ('latest_certified','tx-ellis',2025,'certified','rel-a',{run_a},'current',now())",
    )
    message = refuses(
        connection,
        "INSERT INTO publication.publication"
        "(product,jurisdiction_code,tax_year,release_kind,release_identifier,run_id,"
        "state,published_at) "
        f"VALUES ('latest_certified','tx-ellis',2025,'certified','rel-b',{run_b},'current',now())",
    )

    assert "duplicate key" in message


def test_proposed_values_may_move_available_without_moving_certified(
    connection: object,
) -> None:
    """Which is only possible if they are separate products, not one with a flag."""

    run_c = _accepted_run(
        connection, "tx-ellis", "rel-c", tax_year=2026, release_kind="preliminary"
    )
    accepts(
        connection,
        "INSERT INTO publication.publication"
        "(product,jurisdiction_code,tax_year,release_kind,release_identifier,run_id,"
        "state,published_at) "
        "VALUES ('latest_available','tx-ellis',2026,'preliminary','rel-c',"
        f"{run_c},'current',now())",
    )

    with connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT product, tax_year FROM publication.current_publication "
            "WHERE jurisdiction_code='tx-ellis' ORDER BY product"
        )
        assert cursor.fetchall() == [("latest_available", 2026), ("latest_certified", 2025)]


def test_a_build_is_never_current_without_being_published(connection: object) -> None:
    run_d = _accepted_run(connection, "tx-rockwall", "rel-d")
    message = refuses(
        connection,
        "INSERT INTO publication.publication"
        "(product,jurisdiction_code,tax_year,release_kind,release_identifier,run_id,state) "
        f"VALUES ('history','tx-rockwall',2025,'certified','rel-d',{run_d},'current')",
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
