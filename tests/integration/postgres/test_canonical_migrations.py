"""The migration contract, and both histories it must survive.

Task 2.5 of the accepted change. A clean build from empty and an upgrade from a
populated 0005 must produce one schema: ordering bugs and missing grants only
appear on the first, and a forward extension to a pre-existing relation only
appears on the second.

These need a database and create two more beside it. Set `PTDP_TEST_DATABASE_URL`
and they run; leave it unset and they skip. See `infra/postgres/README.md`.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from collections.abc import Iterator
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


CANONICAL_MIGRATIONS = [path for path in migration_files() if int(path.name[:4]) >= 6]

#: The catalog projections compared between a clean build and an upgrade. Names,
#: types, nullability, every constraint definition, every index definition, every
#: trigger definition, and every grant -- because "the same schema" that omits any
#: of those is a claim rather than a comparison.
PROJECTIONS = {
    "relations": (
        "SELECT class.relname, class.relkind FROM pg_class AS class "
        "  JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
        " WHERE namespace.nspname='canonical' AND class.relkind IN ('r','v','m','S') "
        " ORDER BY 1,2"
    ),
    "columns": (
        "SELECT table_name, column_name, data_type, udt_name, is_nullable, "
        "       ordinal_position, is_identity "
        "  FROM information_schema.columns WHERE table_schema='canonical' ORDER BY 1,6"
    ),
    "constraints": (
        "SELECT class.relname, constraint_row.conname, "
        "       pg_get_constraintdef(constraint_row.oid) "
        "  FROM pg_constraint AS constraint_row "
        "  JOIN pg_class AS class ON class.oid = constraint_row.conrelid "
        "  JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
        " WHERE namespace.nspname='canonical' ORDER BY 1,2"
    ),
    "indexes": (
        "SELECT index_class.relname, index_row.indisunique, "
        "       pg_get_indexdef(index_row.indexrelid) "
        "  FROM pg_index AS index_row "
        "  JOIN pg_class AS index_class ON index_class.oid = index_row.indexrelid "
        "  JOIN pg_namespace AS namespace ON namespace.oid = index_class.relnamespace "
        " WHERE namespace.nspname='canonical' ORDER BY 1"
    ),
    "triggers": (
        "SELECT class.relname, trigger_row.tgname, pg_get_triggerdef(trigger_row.oid) "
        "  FROM pg_trigger AS trigger_row "
        "  JOIN pg_class AS class ON class.oid = trigger_row.tgrelid "
        "  JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
        " WHERE namespace.nspname='canonical' AND NOT trigger_row.tgisinternal ORDER BY 1,2"
    ),
    "routines": (
        "SELECT proname, pg_get_functiondef(pg_proc.oid) FROM pg_proc "
        "  JOIN pg_namespace AS namespace ON namespace.oid = pg_proc.pronamespace "
        " WHERE namespace.nspname='canonical' ORDER BY 1"
    ),
    "privileges": (
        "SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants "
        " WHERE table_schema='canonical' ORDER BY 1,2,3"
    ),
    "default_privileges": (
        "SELECT namespace.nspname, default_acl.defaclobjtype, "
        "       array_to_string(default_acl.defaclacl, ',') "
        "  FROM pg_default_acl AS default_acl "
        "  JOIN pg_namespace AS namespace ON namespace.oid = default_acl.defaclnamespace "
        " WHERE namespace.nspname='canonical' ORDER BY 1,2"
    ),
    "manifest_constraints": (
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        " WHERE conrelid='bronze.release_manifest'::regclass ORDER BY 1"
    ),
    "registry": "SELECT jurisdiction_code, county_fips FROM canonical.jurisdiction ORDER BY 1",
}


def populate_pre_canonical(handle: Any) -> None:
    """Representative rows in every relation 0001-0005 created, before 0006 runs.

    The upgrade path has to meet a database with data in it, not an empty one that
    merely stopped at 0005.
    """
    digest_value = hashlib.sha256(b"upgrade-fixture").hexdigest()
    with handle.cursor() as cursor:
        cursor.execute(
            "INSERT INTO bronze.artifact(sha256,locator,byte_count,media_type) "
            "VALUES (%s,'s3://fixture/upgrade.zip',10,'application/zip')",
            (digest_value,),
        )
        cursor.execute(
            "INSERT INTO bronze.release_manifest"
            "(jurisdiction_code,artifact_sha256,acquired_at,source_url,response_status,"
            "manifest_version) VALUES ('tx-collin',%s,now(),'https://example.invalid/a.zip',200,1)"
            " RETURNING manifest_id",
            (digest_value,),
        )
        manifest_id = int(cursor.fetchone()[0])
        cursor.execute(
            "INSERT INTO bronze.release_redirect(manifest_id,hop_index,from_url,to_url,status) "
            "VALUES (%s,0,'https://example.invalid/a','https://example.invalid/b',302)",
            (manifest_id,),
        )
        cursor.execute(
            "INSERT INTO bronze.release_partition"
            "(manifest_id,jurisdiction_code,tax_year,release_kind) "
            "VALUES (%s,'tx-collin',2025,'certified')",
            (manifest_id,),
        )
        cursor.execute(
            "INSERT INTO ingestion.run"
            "(jurisdiction_code,release_identifier,manifest_id,tax_year,release_kind) "
            "VALUES ('tx-collin','LEGACY-REL',%s,2025,'certified') RETURNING run_id",
            (manifest_id,),
        )
        run_id = int(cursor.fetchone()[0])
        cursor.execute(
            "INSERT INTO ingestion.release_outcome"
            "(run_id,disposition,boundary_contract_version,staged_record_count,"
            "committed_record_count) VALUES (%s,'accepted',1,1,1)",
            (run_id,),
        )
        cursor.execute(
            "INSERT INTO silver.source_record"
            "(jurisdiction_code,appraisal_year,source_account_id,release_identifier,"
            "source_member_name,source_row_number,parser_contract_version,layout_fingerprint,"
            "manifest_id,run_id) VALUES ('tx-collin',2025,'LEGACY-1','LEGACY-REL','PROP.TXT',1,1,"
            "%s,%s,%s) RETURNING record_id",
            (digest_value, manifest_id, run_id),
        )
        record_id = int(cursor.fetchone()[0])
        cursor.execute(
            "INSERT INTO silver.source_native_identifier"
            "(record_id,identifier_name,identifier_value) VALUES (%s,'prop_id','LEGACY-1')",
            (record_id,),
        )
        cursor.execute(
            "INSERT INTO silver.source_native_value(record_id,source_field,text_value) "
            "VALUES (%s,'TOT_VAL','123')",
            (record_id,),
        )


def catalog(handle: Any) -> dict[str, list[tuple[Any, ...]]]:
    snapshot: dict[str, list[tuple[Any, ...]]] = {}
    for name, query in PROJECTIONS.items():
        with handle.cursor() as cursor:
            cursor.execute(query)
            snapshot[name] = [tuple(row) for row in cursor.fetchall()]
    return snapshot


@pytest.fixture(scope="module")
def build_paths(connection: Any) -> Iterator[dict[str, Any]]:
    """One database built from empty, one upgraded from a populated 0005."""
    clean, upgraded = "ptdp_canonical_clean", "ptdp_canonical_upgraded"
    dsn = _dsn()
    for name in (clean, upgraded):
        execute(connection, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        execute(connection, f'CREATE DATABASE "{name}"')

    def connect(name: str) -> Any:
        base = dsn.rsplit("/", 1)[0]
        handle = psycopg.connect(f"{base}/{name}", connect_timeout=5)
        handle.autocommit = True
        return handle

    results: dict[str, Any] = {}
    clean_handle, upgraded_handle = connect(clean), connect(upgraded)
    try:
        apply_migrations(clean_handle)
        results["clean"] = catalog(clean_handle)

        apply_migrations(upgraded_handle, upto=5)
        populate_pre_canonical(upgraded_handle)
        with upgraded_handle.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM silver.source_record")
            results["legacy_rows"] = int(cursor.fetchone()[0])
        apply_migrations(upgraded_handle, start=6)
        results["upgraded"] = catalog(upgraded_handle)
        with upgraded_handle.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM canonical.account "
                "UNION ALL SELECT count(*) FROM canonical.release "
                "UNION ALL SELECT count(*) FROM canonical.account_snapshot"
            )
            results["canonicalized"] = [int(row[0]) for row in cursor.fetchall()]
            cursor.execute("SELECT count(*) FROM silver.source_record")
            results["legacy_rows_after"] = int(cursor.fetchone()[0])
        yield results
    finally:
        clean_handle.close()
        upgraded_handle.close()
        for name in (clean, upgraded):
            execute(connection, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_a_canonical_migration_refuses_to_apply_twice(connection: Any) -> None:
    """Re-running an applied file changes nothing and says why."""

    for path in CANONICAL_MIGRATIONS:
        message = refuses(connection, render(path))

        assert f"migration {path.name[:4]} is already applied" in message


def test_the_ledger_holds_one_row_for_each_migration(connection: Any) -> None:
    versions = [
        version
        for (version,) in fetch(
            connection, "SELECT version FROM platform.schema_migration ORDER BY version"
        )
    ]

    assert versions == list(range(1, len(migration_files()) + 1))


def test_every_canonical_migration_refuses_without_its_predecessor(
    connection: Any, build_paths: dict[str, Any]
) -> None:
    """The whole chain, not one example: a guard omitted from 0013 is invisible to a
    test that only ever applies 0007 to a database at 0005."""

    dsn = _dsn()
    base = dsn.rsplit("/", 1)[0]
    for path in CANONICAL_MIGRATIONS:
        version = int(path.name[:4])
        name = f"ptdp_chain_{version}"
        execute(connection, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        execute(connection, f'CREATE DATABASE "{name}"')
        handle = psycopg.connect(f"{base}/{name}", connect_timeout=5)
        handle.autocommit = True
        try:
            apply_migrations(handle, upto=version - 2)
            with pytest.raises(psycopg.Error) as raised:
                with handle.cursor() as cursor:
                    cursor.execute(render(path))
            assert f"migration {version - 1:04d} must be applied first" in str(raised.value)
        finally:
            handle.close()
            execute(connection, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.mark.skipif(shutil.which("psql") is None, reason="requires the psql client")
def test_a_canonical_migration_refuses_without_its_checksum() -> None:
    """Not \\quit: psql treats that as normal termination and exits 0, so a script
    reading the status would call a missing checksum a success."""

    dsn = _dsn()
    completed = subprocess.run(
        ["psql", "--set", "ON_ERROR_STOP=on", "-f", str(CANONICAL_MIGRATIONS[0]), dsn],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 3
    assert "file_sha256 was not supplied" in completed.stderr


def test_no_canonical_migration_writes_an_inverse_script() -> None:
    """Forward-only. A DROP SCHEMA CASCADE script is a production footgun sitting
    beside the thing it destroys."""

    assert not (MIGRATIONS / "rollback").exists()
    assert not any("DROP SCHEMA" in path.read_text() for path in CANONICAL_MIGRATIONS)


def test_every_canonical_migration_is_one_transaction() -> None:
    for path in CANONICAL_MIGRATIONS:
        text = path.read_text()

        assert text.count("\nBEGIN;") == 1, path.name
        assert text.count("\nCOMMIT;") == 1, path.name


def test_every_canonical_migration_sets_both_timeouts() -> None:
    """Adding a foreign key takes ShareRowExclusiveLock on the referenced relation,
    which may be live."""

    for path in CANONICAL_MIGRATIONS:
        text = path.read_text()

        assert "SET LOCAL lock_timeout" in text, path.name
        assert "SET LOCAL statement_timeout" in text, path.name


def test_the_upgrade_meets_a_populated_database(build_paths: dict[str, Any]) -> None:
    """0001-0005 applied with rows in them, then only 0006-0016."""

    assert build_paths["legacy_rows"] == 1
    assert build_paths["legacy_rows_after"] == 1


def test_no_pre_existing_row_is_canonicalized_by_a_migration(
    build_paths: dict[str, Any],
) -> None:
    """A canonical row exists only where a loader creates one from evidence."""

    assert build_paths["canonicalized"] == [0, 0, 0]


@pytest.mark.parametrize("projection", sorted(PROJECTIONS))
def test_the_two_build_paths_produce_one_schema(
    build_paths: dict[str, Any], projection: str
) -> None:
    """Ordering bugs and missing grants only appear on a from-scratch run, and a
    forward extension only appears on an upgrade. Both must land in one place."""

    assert build_paths["clean"][projection] == build_paths["upgraded"][projection]
