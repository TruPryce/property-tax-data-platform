"""The privilege boundary, judged as the roles that hold it.

Task 2.4 of the accepted change. The owner can see everything, which is why every
grant here is checked as the role that will use it in production rather than as
the role that created the relation.

These need a database. Set `PTDP_TEST_DATABASE_URL` and they run; leave it unset
and they skip. See `infra/postgres/README.md` for the container command.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

psycopg = pytest.importorskip("psycopg", reason="psycopg is required to talk to PostgreSQL")

MIGRATIONS = Path(__file__).resolve().parents[3] / "infra" / "postgres" / "migrations"
SCHEMAS = ("canonical", "publication", "quality", "ingestion", "silver", "bronze", "platform")
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
    """
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    kept: list[str] = []
    in_else = False
    for line in path.read_text().splitlines():
        if line.startswith("\\if "):
            in_else = False
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


def apply_migrations(handle: Any, upto: int | None = None, start: int = 1) -> None:
    """Apply the migrations numbered `start` through `upto`, in order.

    `start` matters: a migration refuses to re-apply, so continuing a database
    that already stopped at 0005 has to begin at 0006 rather than at the top.
    """
    for path in migration_files():
        version = int(path.name[:4])
        if version < start:
            continue
        if upto is not None and version > upto:
            break
        with handle.cursor() as cursor:
            cursor.execute(render(path))


def reset(handle: Any) -> None:
    """Start from nothing, so a leftover schema cannot make a migration look applied."""
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


@pytest.fixture(scope="module")
def connection() -> Iterator[Any]:
    dsn = _dsn()
    try:
        handle = psycopg.connect(dsn, connect_timeout=5)
    except psycopg.OperationalError as error:  # pragma: no cover - environment dependent
        pytest.skip(f"no PostgreSQL at PTDP_TEST_DATABASE_URL: {error}")
    handle.autocommit = True
    with handle:
        reset(handle)
        apply_migrations(handle)
        yield handle


def refuses(connection: Any, statement: str, *params: Any) -> str:
    """Run a statement that must be rejected, and return why it was.

    The rollback is not tidiness. A migration carries its own BEGIN, so a raise
    can leave an aborted transaction behind and every later statement then fails
    with "current transaction is aborted" rather than with the constraint it was
    actually testing.
    """
    with pytest.raises(psycopg.Error) as raised:
        with connection.cursor() as cursor:
            cursor.execute(statement, params or None)
    message = str(raised.value)
    connection.rollback()
    return message


def commits(connection: Any, *statements: str) -> str | None:
    """Run statements as one transaction; return the failure, or None.

    The release-load gate is a deferred constraint trigger judged at COMMIT, so
    the load and its accepted outcome may arrive in either order within one
    transaction. This module's connection is autocommit, which would judge after
    every statement and make that impossible.
    """
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        connection.commit()
        return None
    except psycopg.Error as error:
        connection.rollback()
        return str(error)
    finally:
        connection.autocommit = True


def scalar(connection: Any, query: str, *params: Any) -> Any:
    with connection.cursor() as cursor:
        cursor.execute(query, params or None)
        row = cursor.fetchone()
    return None if row is None else row[0]


def fetch(connection: Any, query: str, *params: Any) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(query, params or None)
        return list(cursor.fetchall())


def execute(connection: Any, statement: str, *params: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(statement, params or None)


# ---------------------------------------------------------------------------
# Fixture builders
#
# Every key is resolved from the database rather than assumed: a refused insert
# still consumes an identity value, so a hard-coded key drifts the moment a test
# above it attacks something, and a later assertion then passes for the wrong
# reason.
# ---------------------------------------------------------------------------


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def acquire(connection: Any, tag: str, *, jurisdiction: str, artifact: str) -> tuple[str, int]:
    """One artifact and the manifest that carried it."""
    sha = digest(f"{tag}/{artifact}")
    execute(
        connection,
        "INSERT INTO bronze.artifact(sha256,locator,byte_count,media_type) "
        "VALUES (%s,%s,10,'application/zip') ON CONFLICT (sha256) DO NOTHING",
        sha,
        f"s3://fixture/{sha}.zip",
    )
    manifest_id = scalar(
        connection,
        "INSERT INTO bronze.release_manifest"
        "(jurisdiction_code,artifact_sha256,acquired_at,source_url,response_status,"
        "manifest_version) VALUES (%s,%s,now(),'https://example.invalid/a.zip',200,1) "
        "RETURNING manifest_id",
        jurisdiction,
        sha,
    )
    return sha, int(manifest_id)


def run_for(
    connection: Any,
    *,
    manifest_id: int,
    jurisdiction: str,
    release: str,
    tax_year: int,
    release_kind: str,
    accepted: bool = True,
) -> int:
    """A processing run over one partition, with an outcome unless asked otherwise."""
    execute(
        connection,
        "INSERT INTO bronze.release_partition(manifest_id,jurisdiction_code,tax_year,release_kind)"
        " VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        manifest_id,
        jurisdiction,
        tax_year,
        release_kind,
    )
    run_id = int(
        scalar(
            connection,
            "INSERT INTO ingestion.run"
            "(jurisdiction_code,release_identifier,manifest_id,tax_year,release_kind) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING run_id",
            jurisdiction,
            release,
            manifest_id,
            tax_year,
            release_kind,
        )
    )
    if accepted:
        execute(
            connection,
            "INSERT INTO ingestion.release_outcome"
            "(run_id,disposition,boundary_contract_version,staged_record_count,"
            "committed_record_count) VALUES (%s,'accepted',1,1,1)",
            run_id,
        )
    return run_id


def canonical_release(
    connection: Any, *, jurisdiction: str, release: str, tax_year: int, release_kind: str
) -> int:
    return int(
        scalar(
            connection,
            "INSERT INTO canonical.release"
            "(jurisdiction_code,tax_year,release_kind,release_identifier) "
            "VALUES (%s,%s,%s,%s) RETURNING release_key",
            jurisdiction,
            tax_year,
            release_kind,
            release,
        )
    )


def build(
    connection: Any,
    tag: str,
    *,
    jurisdiction: str = "tx-collin",
    tax_year: int = 2025,
    release_kind: str = "certified",
    artifacts: tuple[str, ...] = ("a",),
) -> dict[str, Any]:
    """One canonical release, one load per artifact, and a snapshot under each.

    Two artifacts model the divergence case the promoted capability preserves:
    one account, one release, two acquisitions, two loads, two snapshots at one
    grain that must not collapse into each other.
    """
    release = f"{tag}-REL"
    release_key = canonical_release(
        connection,
        jurisdiction=jurisdiction,
        release=release,
        tax_year=tax_year,
        release_kind=release_kind,
    )
    loads: list[dict[str, Any]] = []
    for artifact in artifacts:
        sha, manifest_id = acquire(connection, tag, jurisdiction=jurisdiction, artifact=artifact)
        run_id = run_for(
            connection,
            manifest_id=manifest_id,
            jurisdiction=jurisdiction,
            release=release,
            tax_year=tax_year,
            release_kind=release_kind,
        )
        execute(
            connection,
            "INSERT INTO canonical.artifact_release_binding(artifact_sha256,release_key) "
            "VALUES (%s,%s) ON CONFLICT DO NOTHING",
            sha,
            release_key,
        )
        load_key = int(
            scalar(
                connection,
                "INSERT INTO canonical.release_load"
                "(release_key,run_id,manifest_id,artifact_sha256,jurisdiction_code,tax_year,"
                "release_kind,release_identifier) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "RETURNING load_key",
                release_key,
                run_id,
                manifest_id,
                sha,
                jurisdiction,
                tax_year,
                release_kind,
                release,
            )
        )
        provenance_key = int(
            scalar(
                connection,
                "INSERT INTO canonical.provenance"
                "(load_key,release_key,jurisdiction_code,artifact_sha256,source_member_name,"
                "parser_contract_version,source_row_number) VALUES (%s,%s,%s,%s,'PROP.TXT',1,1) "
                "RETURNING provenance_key",
                load_key,
                release_key,
                jurisdiction,
                sha,
            )
        )
        loads.append(
            {
                "artifact": sha,
                "manifest_id": manifest_id,
                "run_id": run_id,
                "load_key": load_key,
                "provenance_key": provenance_key,
            }
        )

    account_key = int(
        scalar(
            connection,
            "INSERT INTO canonical.account(jurisdiction_code,source_account_id) "
            "VALUES (%s,%s) RETURNING account_key",
            jurisdiction,
            f"{tag}-ACCT",
        )
    )
    for load in loads:
        load["snapshot_key"] = int(
            scalar(
                connection,
                "INSERT INTO canonical.account_snapshot"
                "(account_key,load_key,release_key,provenance_key,jurisdiction_code) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING snapshot_key",
                account_key,
                load["load_key"],
                release_key,
                load["provenance_key"],
                jurisdiction,
            )
        )
    return {
        "jurisdiction": jurisdiction,
        "release": release,
        "release_key": release_key,
        "tax_year": tax_year,
        "release_kind": release_kind,
        "account_key": account_key,
        "loads": loads,
    }


def child_columns(load: dict[str, Any]) -> str:
    """The shared lineage values every parented insert repeats."""
    return (
        f"{load['snapshot_key']},{load['load_key']},"
        f"(SELECT release_key FROM canonical.release_load WHERE load_key={load['load_key']}),"
        f"{load['provenance_key']}"
    )


WRITABLE = (
    "release",
    "artifact_release_binding",
    "release_load",
    "provenance",
    "account",
    "account_snapshot",
    "owner_observation",
    "owner_association",
    "owner_value_allocation",
    "appraisal_value_observation",
    "taxing_unit_observation",
    "taxable_value_observation",
    "exemption_observation",
    "land_observation",
    "improvement_observation",
    "geometry_observation",
)

#: Every relation in the schema, writable or not.
RELATIONS = ("jurisdiction", *WRITABLE)

#: The one non-internal trigger the accepted design declares.
DECLARED_TRIGGERS = {("release_load", "release_load_rests_on_an_accepted_run")}

PERMISSION_WORDS = (
    "publication",
    "publish",
    "visibility",
    "visible",
    "permission",
    "permitted",
    "sensitiv",
    "suppress",
    "redact",
    "allowed",
)


@contextmanager
def as_role(connection: Any, role: str) -> Any:
    """Judge a privilege as the role that holds it.

    The owner can see everything, which is exactly why checking as the owner
    proves nothing about a grant.
    """
    execute(connection, f"SET ROLE {role}")
    try:
        yield
    finally:
        connection.rollback()
        execute(connection, "RESET ROLE")


def test_the_loading_role_may_insert_and_select(connection: Any) -> None:
    build(connection, "PRIVSETUP")

    with as_role(connection, "property_tax_ingestion"):
        execute(
            connection,
            "INSERT INTO canonical.account(jurisdiction_code,source_account_id) "
            "VALUES ('tx-collin','PRIV-1')",
        )
        assert scalar(connection, "SELECT count(*) FROM canonical.account") >= 1


def test_the_loading_role_cannot_overwrite_or_remove(connection: Any) -> None:
    """The D4 guarantee enforced by privilege as well as by shape: a merge that
    tried to overwrite divergent evidence fails rather than succeeding quietly."""

    refused = {}
    with as_role(connection, "property_tax_ingestion"):
        for label, statement in (
            ("update", "UPDATE canonical.account SET source_account_id='X'"),
            ("delete", "DELETE FROM canonical.account"),
            (
                "upsert",
                "INSERT INTO canonical.account(jurisdiction_code,source_account_id) "
                "VALUES ('tx-collin','PRIV-2') "
                "ON CONFLICT (jurisdiction_code,source_account_id) DO UPDATE "
                "SET source_account_id='X'",
            ),
        ):
            refused[label] = refuses(connection, statement)

    assert all("permission denied" in message for message in refused.values()), refused


def test_the_loading_role_may_resolve_a_conflict_by_doing_nothing(connection: Any) -> None:
    """Which is the shape task 3.5's retry needs, and the only one available."""

    with as_role(connection, "property_tax_ingestion"):
        execute(
            connection,
            "INSERT INTO canonical.account(jurisdiction_code,source_account_id) "
            "VALUES ('tx-collin','PRIV-3') ON CONFLICT DO NOTHING",
        )
        execute(
            connection,
            "INSERT INTO canonical.account(jurisdiction_code,source_account_id) "
            "VALUES ('tx-collin','PRIV-3') ON CONFLICT DO NOTHING",
        )
        assert (
            scalar(
                connection,
                "SELECT count(*) FROM canonical.account WHERE source_account_id='PRIV-3'",
            )
            == 1
        )


def test_no_canonical_relation_grants_the_loading_role_update_or_delete(
    connection: Any,
) -> None:
    granted = [
        (relation, privilege)
        for relation in RELATIONS
        for privilege in ("UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
        if scalar(
            connection,
            "SELECT has_table_privilege('property_tax_ingestion', %s, %s)",
            f"canonical.{relation}",
            privilege,
        )
    ]

    assert granted == []


def test_the_registry_is_read_only_to_the_loading_role(connection: Any) -> None:
    """0006's default privileges grant INSERT to every relation the migrator creates
    in this schema, so 0007 revokes it explicitly rather than relying on omission."""

    assert scalar(
        connection,
        "SELECT has_table_privilege('property_tax_ingestion', %s, 'SELECT')",
        "canonical.jurisdiction",
    )
    assert not scalar(
        connection,
        "SELECT has_table_privilege('property_tax_ingestion', %s, 'INSERT')",
        "canonical.jurisdiction",
    )

    with as_role(connection, "property_tax_ingestion"):
        message = refuses(
            connection,
            "INSERT INTO canonical.jurisdiction(jurisdiction_code,county_fips) "
            "VALUES ('tx-newton','48001')",
        )

    assert "permission denied" in message


def test_the_reading_role_has_nothing_in_the_canonical_schema(connection: Any) -> None:
    """Not even schema usage, so a table grant added by mistake is still unreachable."""

    assert not scalar(
        connection, "SELECT has_schema_privilege('property_tax_api','canonical','USAGE')"
    )
    granted = [
        (relation, privilege)
        for relation in RELATIONS
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
        if scalar(
            connection,
            "SELECT has_table_privilege('property_tax_api', %s, %s)",
            f"canonical.{relation}",
            privilege,
        )
    ]

    assert granted == []


def test_the_reading_role_is_refused_by_the_schema(connection: Any) -> None:
    """The refusal arrives before any table grant is consulted."""

    with as_role(connection, "property_tax_api"):
        message = refuses(connection, "SELECT count(*) FROM canonical.account_snapshot")

    assert "permission denied for schema" in message


def test_the_schema_default_privileges_grant_exactly_select_and_insert(
    connection: Any,
) -> None:
    """A relation added by a later migration must be reachable without a further
    grant, and must not inherit the ability to overwrite."""

    acl = scalar(
        connection,
        "SELECT array_to_string(defaclacl, ',') FROM pg_default_acl AS default_acl "
        "  JOIN pg_namespace AS namespace ON namespace.oid = default_acl.defaclnamespace "
        " WHERE namespace.nspname='canonical' AND default_acl.defaclobjtype='r'",
    )

    assert acl is not None
    assert "property_tax_ingestion=ar/" in acl
    assert "property_tax_api" not in acl


def test_a_relation_created_later_by_the_migrator_inherits_those_two(
    connection: Any,
) -> None:
    """Asserted behaviourally as well, because pg_default_acl is a declaration and
    the question is what a future relation actually gets."""

    execute(connection, "GRANT CREATE ON SCHEMA canonical TO property_tax_migrator")
    try:
        execute(connection, "SET ROLE property_tax_migrator")
        execute(connection, "CREATE TABLE canonical.inherited_probe (probe_key bigint)")
        execute(connection, "RESET ROLE")
        granted = {
            privilege: scalar(
                connection,
                "SELECT has_table_privilege('property_tax_ingestion', %s, %s)",
                "canonical.inherited_probe",
                privilege,
            )
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
        }
    finally:
        execute(connection, "RESET ROLE")
        execute(connection, "DROP TABLE IF EXISTS canonical.inherited_probe")
        execute(connection, "REVOKE CREATE ON SCHEMA canonical FROM property_tax_migrator")

    assert granted == {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False}


def test_no_canonical_column_confers_publication_permission(connection: Any) -> None:
    """Representing an owner name is not permission to publish it."""

    offenders = fetch(
        connection,
        "SELECT table_name, column_name FROM information_schema.columns "
        " WHERE table_schema='canonical' AND ("
        + " OR ".join(f"column_name LIKE '%{word}%'" for word in PERMISSION_WORDS)
        + ")",
    )

    assert offenders == []


def test_no_canonical_column_is_a_general_purpose_destination(connection: Any) -> None:
    """No document, array, or arbitrary-value column: an unmapped source-native value
    has nowhere to go here, which is what keeps it at adapter grain."""

    offenders = fetch(
        connection,
        "SELECT table_name, column_name, data_type, udt_name "
        "  FROM information_schema.columns "
        " WHERE table_schema='canonical' "
        "   AND (data_type IN ('json','jsonb','ARRAY','USER-DEFINED') "
        "        OR udt_name IN ('json','jsonb','hstore') "
        "        OR column_name IN ('payload','detail','extra','metadata','attributes','extras'))",
    )

    assert offenders == []


def test_the_canonical_schema_holds_no_generated_column_or_view(connection: Any) -> None:
    """An account total assembled from owner allocations has no mechanism here."""

    generated = fetch(
        connection,
        "SELECT class.relname, attribute.attname FROM pg_attribute AS attribute "
        "  JOIN pg_class AS class ON class.oid = attribute.attrelid "
        "  JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
        " WHERE namespace.nspname='canonical' AND attribute.attgenerated <> ''",
    )
    views = fetch(
        connection,
        "SELECT class.relname FROM pg_class AS class "
        "  JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
        " WHERE namespace.nspname='canonical' AND class.relkind IN ('v','m')",
    )

    assert generated == []
    assert views == []


def test_the_canonical_schema_holds_exactly_the_declared_triggers(connection: Any) -> None:
    """A trigger nobody declared is a place a total could be assembled."""

    triggers = {
        (relation, name)
        for relation, name in fetch(
            connection,
            "SELECT class.relname, trigger.tgname FROM pg_trigger AS trigger "
            "  JOIN pg_class AS class ON class.oid = trigger.tgrelid "
            "  JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
            " WHERE namespace.nspname='canonical' AND NOT trigger.tgisinternal",
        )
    }

    assert triggers == DECLARED_TRIGGERS


def test_no_column_holds_an_account_level_total(connection: Any) -> None:
    offenders = fetch(
        connection,
        "SELECT table_name, column_name FROM information_schema.columns "
        " WHERE table_schema='canonical' "
        "   AND (column_name LIKE '%total%' OR column_name LIKE '%sum%' "
        "        OR column_name LIKE '%rollup%' OR column_name LIKE '%aggregate%')",
    )

    assert offenders == []
