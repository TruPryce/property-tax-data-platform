"""Canonical identity, the registry, snapshot grain, and evidence divergence.

Task 2.1 of the accepted change. Every assertion reads the catalog or attacks the
database; none greps a migration, because a constraint that was written and never
took effect passes a grep and fails a load.

These need a database. Set `PTDP_TEST_DATABASE_URL` and they run; leave it unset
and they skip:

    export PGPASSWORD="$(openssl rand -hex 16)"
    docker run -d --name ptdp-test -p 5433:5432 \\
        -e POSTGRES_PASSWORD="$PGPASSWORD" -e POSTGRES_DB=ptdp postgres:16.11-bookworm

    PTDP_TEST_DATABASE_URL=postgresql://postgres@localhost:5433/ptdp \\
        uv run pytest tests/integration/postgres
"""

from __future__ import annotations

import hashlib
import os
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


RECORD_RELATIONS = (
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


def unique_indexes(connection: Any, relation: str) -> list[tuple[str, list[str]]]:
    """Every unique index on a relation, as (name, ordered column names)."""
    return [
        (name, list(columns))
        for name, columns in fetch(
            connection,
            "SELECT index_class.relname, "
            "       array_agg(attribute.attname ORDER BY key.ordinality) "
            "  FROM pg_index AS index_row "
            "  JOIN pg_class AS index_class ON index_class.oid = index_row.indexrelid "
            "  JOIN LATERAL unnest(index_row.indkey) WITH ORDINALITY AS key(attnum, ordinality) "
            "       ON true "
            "  JOIN pg_attribute AS attribute "
            "       ON attribute.attrelid = index_row.indrelid AND attribute.attnum = key.attnum "
            " WHERE index_row.indrelid = %s::regclass AND index_row.indisunique "
            " GROUP BY index_class.relname",
            f"canonical.{relation}",
        )
    ]


def test_one_source_account_identifier_in_two_counties_is_two_accounts(connection: Any) -> None:
    """County-qualified, so a shared county identifier is not a shared account."""

    collin = scalar(
        connection,
        "INSERT INTO canonical.account(jurisdiction_code,source_account_id) "
        "VALUES ('tx-collin','SHARED-1') RETURNING account_key",
    )
    dallas = scalar(
        connection,
        "INSERT INTO canonical.account(jurisdiction_code,source_account_id) "
        "VALUES ('tx-dallas','SHARED-1') RETURNING account_key",
    )

    assert collin != dallas
    assert (
        scalar(
            connection,
            "SELECT count(*) FROM canonical.account WHERE source_account_id='SHARED-1'",
        )
        == 2
    )


def test_no_constraint_makes_a_source_account_identifier_unique_on_its_own(
    connection: Any,
) -> None:
    """The jurisdiction leads the key, and nothing narrower exists beside it."""

    columns = [columns for _, columns in unique_indexes(connection, "account")]

    assert ["source_account_id"] not in columns
    assert ["jurisdiction_code", "source_account_id"] in columns


def test_a_well_formed_but_unregistered_county_is_unrepresentable(connection: Any) -> None:
    """`tx-madeup` matches the grammar and no domain Jurisdiction can be built for it."""

    release = refuses(
        connection,
        "INSERT INTO canonical.release"
        "(jurisdiction_code,tax_year,release_kind,release_identifier) "
        "VALUES ('tx-madeup',2025,'certified','MADEUP-1')",
    )
    account = refuses(
        connection,
        "INSERT INTO canonical.account(jurisdiction_code,source_account_id) "
        "VALUES ('tx-madeup','R1')",
    )

    assert "jurisdiction" in release
    assert "jurisdiction" in account


def test_the_seeded_registry_is_the_version_controlled_registry(connection: Any) -> None:
    """Two copies of one fact, asserted equal rather than assumed.

    Onboarding a seventh county without the migration that adds it fails here,
    which is the whole reason the registry is persisted rather than checked.
    """

    from property_tax_domain import INITIAL_COUNTIES

    expected = {
        (f"{county.state_code.lower()}-{county.slug.value}", county.fips)
        for county in INITIAL_COUNTIES
    }
    persisted = set(
        fetch(connection, "SELECT jurisdiction_code, county_fips FROM canonical.jurisdiction")
    )

    assert persisted == expected


def test_county_fips_lives_only_in_the_registry(connection: Any) -> None:
    """Metadata keyed by the identity, never a second independent county identity."""

    carriers = fetch(
        connection,
        "SELECT table_name, column_name FROM information_schema.columns "
        " WHERE table_schema='canonical' AND column_name LIKE '%fips%'",
    )

    assert carriers == [("jurisdiction", "county_fips")]


def test_two_snapshots_at_one_grain_with_different_provenance_both_persist(
    connection: Any,
) -> None:
    """One account, one release, two artifacts. The divergence case."""

    fixture = build(connection, "GRAIN", artifacts=("a", "b"))

    at_grain = scalar(
        connection,
        "SELECT count(*) FROM canonical.account_snapshot  WHERE account_key=%s AND release_key=%s",
        fixture["account_key"],
        fixture["release_key"],
    )

    assert at_grain == 2
    assert len({load["provenance_key"] for load in fixture["loads"]}) == 2


def test_the_grain_is_an_index_and_not_a_constraint(connection: Any) -> None:
    """A UNIQUE over the grain would collapse exactly what the capability preserves."""

    unique = [columns for _, columns in unique_indexes(connection, "account_snapshot")]
    grain = fetch(
        connection,
        "SELECT indisunique FROM pg_index "
        " WHERE indexrelid = 'canonical.account_snapshot_grain'::regclass",
    )

    assert ["account_key", "release_key"] not in unique
    assert grain == [(False,)]


def test_two_snapshots_differing_only_in_situs_both_persist(connection: Any) -> None:
    """Unequal domain values at one grain: equality is structural over every field
    except the source as-of value, so a differing situs makes two snapshots."""

    fixture = build(connection, "SITUS")
    load = fixture["loads"][0]
    for street in ("100 MAIN ST", "102 MAIN ST"):
        execute(
            connection,
            "INSERT INTO canonical.account_snapshot"
            "(account_key,load_key,release_key,provenance_key,jurisdiction_code,"
            "situs_street_address) VALUES (%s,%s,%s,%s,%s,%s)",
            fixture["account_key"],
            load["load_key"],
            fixture["release_key"],
            load["provenance_key"],
            fixture["jurisdiction"],
            street,
        )

    assert (
        scalar(
            connection,
            "SELECT count(*) FROM canonical.account_snapshot "
            " WHERE account_key=%s AND provenance_key=%s",
            fixture["account_key"],
            load["provenance_key"],
        )
        == 3
    )


def test_two_snapshots_differing_only_in_legal_description_both_persist(
    connection: Any,
) -> None:
    fixture = build(connection, "LEGAL")
    load = fixture["loads"][0]
    for text in ("LOT 1 BLK A", "LOT 2 BLK A"):
        execute(
            connection,
            "INSERT INTO canonical.account_snapshot"
            "(account_key,load_key,release_key,provenance_key,jurisdiction_code,legal_text) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            fixture["account_key"],
            load["load_key"],
            fixture["release_key"],
            load["provenance_key"],
            fixture["jurisdiction"],
            text,
        )

    assert (
        scalar(
            connection,
            "SELECT count(*) FROM canonical.account_snapshot WHERE account_key=%s",
            fixture["account_key"],
        )
        == 3
    )


def test_the_snapshot_has_no_invented_evidence_uniqueness(connection: Any) -> None:
    """No UNIQUE over load, account, and provenance, nor any subset that refuses them."""

    unique = [set(columns) for _, columns in unique_indexes(connection, "account_snapshot")]
    invented = {"load_key", "account_key", "provenance_key"}

    assert not any(columns <= invented for columns in unique)
    assert sorted(unique, key=len) == [{"snapshot_key"}, {"snapshot_key", "release_key"}]


def test_an_account_cannot_be_observed_under_another_countys_release(connection: Any) -> None:
    """The root invariant, refused at the root rather than agreed with by every child."""

    fixture = build(connection, "ROOT")
    load = fixture["loads"][0]
    dallas = scalar(
        connection,
        "INSERT INTO canonical.account(jurisdiction_code,source_account_id) "
        "VALUES ('tx-dallas','ROOT-1') RETURNING account_key",
    )

    message = refuses(
        connection,
        "INSERT INTO canonical.account_snapshot"
        "(account_key,load_key,release_key,provenance_key,jurisdiction_code) "
        "VALUES (%s,%s,%s,%s,'tx-dallas')",
        dallas,
        load["load_key"],
        fixture["release_key"],
        load["provenance_key"],
    )

    assert "provenance_is_of_its_county" in message


def test_every_generated_key_is_documented_as_a_locator(connection: Any) -> None:
    """A surrogate a reader could mistake for business identity is one they will."""

    undocumented = [
        (relation, column)
        for relation, column, comment in fetch(
            connection,
            "SELECT class.relname, attribute.attname, "
            "       col_description(class.oid, attribute.attnum) "
            "  FROM pg_attribute AS attribute "
            "  JOIN pg_class AS class ON class.oid = attribute.attrelid "
            "  JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
            " WHERE namespace.nspname='canonical' AND class.relkind='r' "
            "   AND attribute.attidentity <> ''",
        )
        if comment is None or "locator" not in comment
    ]

    assert undocumented == []


def test_relations_with_a_business_identity_carry_it_as_a_constraint(connection: Any) -> None:
    """The surrogate is never the only uniqueness where a natural key exists."""

    assert ["jurisdiction_code", "tax_year", "release_kind", "release_identifier"] in [
        columns for _, columns in unique_indexes(connection, "release")
    ]
    assert ["jurisdiction_code", "source_account_id"] in [
        columns for _, columns in unique_indexes(connection, "account")
    ]


def test_the_two_natural_key_relations_carry_no_surrogate(connection: Any) -> None:
    """A generated key on either would be a second way to name one fact."""

    generated = fetch(
        connection,
        "SELECT class.relname, attribute.attname FROM pg_attribute AS attribute "
        "  JOIN pg_class AS class ON class.oid = attribute.attrelid "
        "  JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
        " WHERE namespace.nspname='canonical' AND attribute.attidentity <> '' "
        "   AND class.relname IN ('jurisdiction','artifact_release_binding')",
    )

    assert generated == []
