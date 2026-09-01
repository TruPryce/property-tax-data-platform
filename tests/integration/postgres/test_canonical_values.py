"""Scalar rules, closed vocabularies, carried labels, and geometry.

Task 2.3 of the accepted change. The lexical and numeric cases are driven from a
table of every column carrying each kind, and a completeness test asserts no
canonical column escapes classification: a bound omitted from one column would
otherwise satisfy a suite that only exercised another.

These need a database. Set `PTDP_TEST_DATABASE_URL` and they run; leave it unset
and they skip. See `infra/postgres/README.md` for the container command.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from collections.abc import Iterator
from decimal import Decimal
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


#: Every canonical column that carries a D8 kind, and which kind it carries.
#:
#: Driven from this table rather than from one representative column per kind,
#: because a bound omitted from `basis` or `year_built` alone would satisfy a
#: suite that only ever exercised `owner_name`. The completeness test below then
#: asserts that no canonical column escapes classification, so adding one without
#: a rule fails here rather than in a county release.
KINDS: dict[str, list[tuple[str, str]]] = {
    "identifier": [
        ("release", "release_identifier"),
        ("release_load", "release_identifier"),
        ("account", "source_account_id"),
        ("provenance", "source_member_name"),
        ("owner_association", "source_discriminator"),
        ("taxing_unit_observation", "unit_code"),
        ("land_observation", "source_discriminator"),
        ("improvement_observation", "source_discriminator"),
    ],
    "label": [
        ("account_snapshot", "legal_text"),
        ("owner_observation", "owner_name"),
        ("taxing_unit_observation", "unit_name"),
        ("taxable_value_observation", "basis"),
        ("exemption_observation", "classification"),
        ("land_observation", "classification"),
        ("land_observation", "area_unit"),
        ("improvement_observation", "classification"),
        ("improvement_observation", "area_unit"),
    ],
    "address": [
        ("account_snapshot", "situs_street_address"),
        ("account_snapshot", "situs_unit"),
        ("account_snapshot", "situs_city"),
        ("account_snapshot", "situs_state_code"),
        ("account_snapshot", "situs_postal_code"),
        ("account_snapshot", "legal_subdivision"),
        ("account_snapshot", "legal_block"),
        ("account_snapshot", "legal_lot"),
        ("owner_observation", "mailing_addressee"),
        ("owner_observation", "mailing_street_address"),
        ("owner_observation", "mailing_unit"),
        ("owner_observation", "mailing_city"),
        ("owner_observation", "mailing_state_code"),
        ("owner_observation", "mailing_postal_code"),
        ("owner_observation", "mailing_country_code"),
    ],
    "crs": [("geometry_observation", "crs")],
    "amount": [
        ("appraisal_value_observation", "amount"),
        ("taxable_value_observation", "amount"),
        ("owner_value_allocation", "amount"),
        ("exemption_observation", "amount"),
    ],
    "magnitude": [("land_observation", "area"), ("improvement_observation", "area")],
    "percentage": [("owner_association", "ownership_percentage")],
    "year": [("improvement_observation", "year_built")],
    "tax_year": [("release", "tax_year"), ("release_load", "tax_year")],
    "instant": [
        ("release", "first_recorded_at"),
        ("account", "first_recorded_at"),
        ("artifact_release_binding", "first_recorded_at"),
        ("release_load", "loaded_at"),
        ("account_snapshot", "source_as_of"),
    ],
}

#: Locators, lineage references, closed vocabularies, and opaque payloads. These
#: carry no D8 kind, and each is constrained by something the other tests assert.
UNCLASSIFIED = {
    ("jurisdiction", "jurisdiction_code"),
    ("jurisdiction", "county_fips"),
    ("release", "release_key"),
    ("release", "jurisdiction_code"),
    ("release", "release_kind"),
    ("artifact_release_binding", "artifact_sha256"),
    ("artifact_release_binding", "release_key"),
    ("release_load", "load_key"),
    ("release_load", "release_key"),
    ("release_load", "run_id"),
    ("release_load", "manifest_id"),
    ("release_load", "artifact_sha256"),
    ("release_load", "jurisdiction_code"),
    ("release_load", "release_kind"),
    ("provenance", "provenance_key"),
    ("provenance", "load_key"),
    ("provenance", "release_key"),
    ("provenance", "jurisdiction_code"),
    ("provenance", "artifact_sha256"),
    ("provenance", "parser_contract_version"),
    ("provenance", "source_row_number"),
    ("provenance", "layout_fingerprint"),
    ("account", "account_key"),
    ("account", "jurisdiction_code"),
    ("account_snapshot", "snapshot_key"),
    ("account_snapshot", "account_key"),
    ("account_snapshot", "load_key"),
    ("account_snapshot", "release_key"),
    ("account_snapshot", "provenance_key"),
    ("account_snapshot", "jurisdiction_code"),
    ("owner_observation", "owner_key"),
    ("owner_association", "association_key"),
    ("owner_association", "owner_key"),
    ("owner_value_allocation", "allocation_key"),
    ("owner_value_allocation", "association_key"),
    ("owner_value_allocation", "kind"),
    ("appraisal_value_observation", "value_key"),
    ("appraisal_value_observation", "kind"),
    ("taxing_unit_observation", "taxing_unit_key"),
    ("taxable_value_observation", "taxable_key"),
    ("taxable_value_observation", "taxing_unit_key"),
    ("exemption_observation", "exemption_key"),
    ("exemption_observation", "scope"),
    ("exemption_observation", "association_key"),
    ("land_observation", "land_key"),
    ("improvement_observation", "improvement_key"),
    ("improvement_observation", "year_built"),
    ("geometry_observation", "geometry_key"),
    ("geometry_observation", "encoding"),
    ("geometry_observation", "payload_bytes"),
    ("geometry_observation", "payload_text"),
} | {
    (relation, column)
    for relation in (
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
    for column in ("snapshot_key", "release_key", "load_key", "provenance_key")
}

CONTROL = next(
    character for code in range(1, 0x100) if unicodedata.category(character := chr(code)) == "Cc"
)

#: One value outside each kind's rule. Every one must be refused by every column
#: carrying that kind.
OUTSIDE: dict[str, list[Any]] = {
    "identifier": ["has space", ".leading", "-leading", "x" * 129, "sla/sh"],
    "label": ["x" * 257, CONTROL, "   "],
    "address": ["x" * 129, CONTROL, "   "],
    "crs": ["x" * 65, CONTROL, "   "],
    "amount": ["NaN", "Infinity", "-Infinity"],
    "magnitude": ["NaN", "Infinity", -1],
    "percentage": ["NaN", -1, "100.01"],
    "year": [1599, 2201],
    "tax_year": [1899, 2201],
}


@pytest.fixture(scope="module")
def rows(connection: Any) -> dict[str, dict[str, int]]:
    """One valid row in every canonical relation, to attack column by column.

    A column check is exercised by updating a valid row rather than by composing a
    fresh insert per case: the update reaches exactly one constraint, so a refusal
    names the rule under test instead of whichever NOT NULL happened to fire first.
    """
    fixture = build(connection, "SCALAR")
    load = fixture["loads"][0]
    keys = (load["snapshot_key"], fixture["release_key"], load["load_key"], load["provenance_key"])
    owner = int(
        scalar(
            connection,
            "INSERT INTO canonical.owner_observation"
            "(snapshot_key,release_key,load_key,provenance_key,owner_name) "
            "VALUES (%s,%s,%s,%s,'OWNER') RETURNING owner_key",
            *keys,
        )
    )
    association = int(
        scalar(
            connection,
            "INSERT INTO canonical.owner_association"
            "(snapshot_key,release_key,load_key,provenance_key,owner_key,ownership_percentage,"
            "source_discriminator) VALUES (%s,%s,%s,%s,%s,50,'SEQ-1') RETURNING association_key",
            *keys,
            owner,
        )
    )
    unit = int(
        scalar(
            connection,
            "INSERT INTO canonical.taxing_unit_observation"
            "(snapshot_key,release_key,load_key,provenance_key,unit_code,unit_name) "
            "VALUES (%s,%s,%s,%s,'UNIT-1','Collin ISD') RETURNING taxing_unit_key",
            *keys,
        )
    )
    execute(
        connection,
        "INSERT INTO canonical.owner_value_allocation"
        "(association_key,release_key,load_key,provenance_key,kind,amount) "
        "VALUES (%s,%s,%s,%s,'market',1)",
        association,
        fixture["release_key"],
        load["load_key"],
        load["provenance_key"],
    )
    execute(
        connection,
        "INSERT INTO canonical.appraisal_value_observation"
        "(snapshot_key,release_key,load_key,provenance_key,kind,amount) "
        "VALUES (%s,%s,%s,%s,'market',1)",
        *keys,
    )
    execute(
        connection,
        "INSERT INTO canonical.taxable_value_observation"
        "(snapshot_key,release_key,load_key,provenance_key,taxing_unit_key,amount,basis) "
        "VALUES (%s,%s,%s,%s,%s,1,'net taxable')",
        *keys,
        unit,
    )
    execute(
        connection,
        "INSERT INTO canonical.exemption_observation"
        "(snapshot_key,release_key,load_key,provenance_key,classification,scope,amount) "
        "VALUES (%s,%s,%s,%s,'HS','account',1)",
        *keys,
    )
    for relation in ("land_observation", "improvement_observation"):
        execute(
            connection,
            f"INSERT INTO canonical.{relation}"
            "(snapshot_key,release_key,load_key,provenance_key,source_discriminator,"
            "classification,area,area_unit) VALUES (%s,%s,%s,%s,'SEQ-1','CLS',1,'acres')",
            *keys,
        )
    execute(
        connection,
        "INSERT INTO canonical.improvement_observation"
        "(snapshot_key,release_key,load_key,provenance_key,year_built) VALUES (%s,%s,%s,%s,1990)",
        *keys,
    )
    execute(
        connection,
        "INSERT INTO canonical.geometry_observation"
        "(snapshot_key,release_key,load_key,provenance_key,encoding,payload_text,crs) "
        "VALUES (%s,%s,%s,%s,'wkt','POINT(0 0)','EPSG:4326')",
        *keys,
    )
    execute(
        connection,
        "UPDATE canonical.account_snapshot SET situs_street_address='1 MAIN ST',"
        "legal_text='LOT 1',legal_subdivision='SUB',legal_block='B',legal_lot='L',"
        "situs_unit='A',situs_city='PLANO',situs_state_code='TX',situs_postal_code='75024',"
        "source_as_of=now() WHERE snapshot_key=%s",
        load["snapshot_key"],
    )
    execute(
        connection,
        "UPDATE canonical.owner_observation SET mailing_addressee='A',"
        "mailing_street_address='B',mailing_unit='C',mailing_city='D',mailing_state_code='E',"
        "mailing_postal_code='F',mailing_country_code='US' WHERE owner_key=%s",
        owner,
    )
    return {"fixture": fixture, "load": load}


def test_every_canonical_column_carries_a_classified_rule(connection: Any) -> None:
    """A column nobody classified is a column nobody bounded."""

    classified = {pair for pairs in KINDS.values() for pair in pairs}
    present = {
        (relation, column)
        for relation, column in fetch(
            connection,
            "SELECT table_name, column_name FROM information_schema.columns "
            " WHERE table_schema='canonical'",
        )
    }

    assert present - classified - UNCLASSIFIED == set()


@pytest.mark.parametrize("kind", sorted(OUTSIDE))
def test_every_column_of_a_kind_refuses_a_value_outside_it(
    connection: Any, rows: dict[str, Any], kind: str
) -> None:
    """Table-driven over every column, not one representative of each."""

    accepted: list[str] = []
    for relation, column in KINDS[kind]:
        for value in OUTSIDE[kind]:
            message = refuses(
                connection,
                f"UPDATE canonical.{relation} SET {column} = %s",
                value,
            )
            if "violates check constraint" not in message:
                accepted.append(f"{relation}.{column} = {value!r}: {message.splitlines()[0]}")

    assert accepted == []


def test_a_magnitude_accepts_zero_and_refuses_a_negative(connection: Any, rows: Any) -> None:
    """A measured extent has no negative value, where a monetary adjustment does."""

    execute(connection, "UPDATE canonical.land_observation SET area = 0")
    assert scalar(connection, "SELECT min(area) FROM canonical.land_observation") == 0
    assert "violates check constraint" in refuses(
        connection, "UPDATE canonical.land_observation SET area = -1"
    )


def test_an_amount_accepts_zero_and_a_negative(connection: Any, rows: Any) -> None:
    """Counties publish zero, and some rolls carry negative adjustments."""

    for value in (0, -5.25):
        execute(
            connection,
            "UPDATE canonical.appraisal_value_observation SET amount = %s",
            value,
        )
    assert scalar(connection, "SELECT min(amount) FROM canonical.appraisal_value_observation") < 0


def test_an_exact_decimal_round_trips_with_its_scale(connection: Any, rows: Any) -> None:
    """Unconstrained numeric, because no accepted contract fixes a precision or scale
    and NUMERIC(p,s) would silently round a county value to fit."""

    for value in (Decimal("12345678901234567890.123456789012345"), Decimal("0.10")):
        execute(
            connection,
            "UPDATE canonical.appraisal_value_observation SET amount = %s",
            value,
        )
        assert scalar(connection, "SELECT amount FROM canonical.appraisal_value_observation") == (
            value
        )
        assert str(
            scalar(connection, "SELECT amount::text FROM canonical.appraisal_value_observation")
        ) == str(value)


def test_no_canonical_column_is_floating_point_or_bounded_numeric(connection: Any) -> None:
    offenders = fetch(
        connection,
        "SELECT table_name, column_name, data_type, numeric_precision, numeric_scale "
        "  FROM information_schema.columns "
        " WHERE table_schema='canonical' "
        "   AND (data_type IN ('real','double precision') "
        "        OR (data_type='numeric' AND numeric_precision IS NOT NULL))",
    )

    assert offenders == []


def test_every_instant_column_is_timezone_aware_and_none_is_wall_clock(
    connection: Any,
) -> None:
    """What SQL can guarantee, stated as that.

    PostgreSQL accepts a value with no offset into a timestamptz column and reads
    it in the session zone, so refusing a naive value is the domain constructor's
    obligation and is proved in tests/unit/property_tax_domain/test_account.py.
    """

    types = {
        (relation, column): data_type
        for relation, column, data_type in fetch(
            connection,
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            " WHERE table_schema='canonical' AND data_type LIKE 'timestamp%'",
        )
    }

    assert set(types) == set(KINDS["instant"])
    assert set(types.values()) == {"timestamp with time zone"}


def test_an_instant_denotes_the_same_moment_under_any_session_zone(
    connection: Any, rows: Any
) -> None:
    execute(connection, "SET TIME ZONE 'UTC'")
    execute(
        connection,
        "UPDATE canonical.account_snapshot SET source_as_of = '2026-08-30 12:34:56+00'",
    )
    utc = scalar(connection, "SELECT max(source_as_of) FROM canonical.account_snapshot")
    execute(connection, "SET TIME ZONE 'America/Chicago'")
    chicago = scalar(connection, "SELECT max(source_as_of) FROM canonical.account_snapshot")
    execute(connection, "RESET TIME ZONE")

    assert utc == chicago


VOCABULARIES = {
    ("release", "release_kind"): {"proposed", "certified", "supplemental", "current"},
    ("release_load", "release_kind"): {"proposed", "certified", "supplemental", "current"},
    ("appraisal_value_observation", "kind"): {"market", "appraised", "assessed"},
    ("owner_value_allocation", "kind"): {"market", "appraised", "assessed"},
    ("exemption_observation", "scope"): {"account", "owner_association"},
    ("geometry_observation", "encoding"): {"wkb", "wkt"},
}


def admitted_members(connection: Any, relation: str, column: str) -> set[str]:
    """The members a closed-vocabulary constraint actually admits.

    Parsed from the constraint rather than tested for membership: a set that
    contains every expected value *and one more* passes a membership check and is
    exactly the defect this has to catch. PostgreSQL renders `IN (...)` as
    `= ANY (ARRAY['a'::text, ...])`, so the literals are the admitted set.
    """
    definitions = [
        definition
        for (definition,) in fetch(
            connection,
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            " WHERE conrelid = %s::regclass AND contype='c' "
            "   AND pg_get_constraintdef(oid) LIKE %s",
            relation,
            f"%{column}%",
        )
        if "= ANY (ARRAY[" in definition
    ]
    assert len(definitions) == 1, f"{relation}.{column} has {len(definitions)} vocabularies"
    body = definitions[0].split("= ANY (ARRAY[", 1)[1].split("]", 1)[0]
    return set(re.findall(r"'([^']*)'::text", body))


def test_each_closed_vocabulary_admits_exactly_its_accepted_members(
    connection: Any,
) -> None:
    """Read from the catalog and compared as a set, so widening one needs a
    migration someone reviews rather than passing unnoticed."""

    actual = {
        (relation, column): admitted_members(connection, f"canonical.{relation}", column)
        for relation, column in VOCABULARIES
    }

    assert actual == VOCABULARIES


def test_the_vocabulary_check_notices_an_extra_member(connection: Any) -> None:
    """Mutation, because a test that only ever sees the correct schema cannot say
    whether it would notice the wrong one.

    `taxable` is the plausible widening: it is the member the promoted capability
    deliberately excludes, and the one a reader who has not read it would add.
    """

    execute(
        connection,
        "CREATE TEMP TABLE widened_vocabulary "
        "(kind text CHECK (kind IN ('market','appraised','assessed','taxable')))",
    )
    try:
        widened = admitted_members(connection, "widened_vocabulary", "kind")
    finally:
        execute(connection, "DROP TABLE IF EXISTS widened_vocabulary")

    assert widened == {"market", "appraised", "assessed", "taxable"}
    assert widened != VOCABULARIES[("appraisal_value_observation", "kind")]


def test_a_value_outside_a_closed_vocabulary_is_refused(connection: Any, rows: Any) -> None:
    for (relation, column), members in VOCABULARIES.items():
        if relation in {"release", "release_load"}:
            continue
        for value in ("taxable", "TAXABLE", "", "other"):
            assert value in members or "violates check constraint" in refuses(
                connection, f"UPDATE canonical.{relation} SET {column} = %s", value
            )


#: The six labels a canonical observation is defined to carry source-native. A
#: vocabulary added to any one of them is the same defect whichever one it is.
CARRIED = (
    ("exemption_observation", "classification"),
    ("taxing_unit_observation", "unit_code"),
    ("taxing_unit_observation", "unit_name"),
    ("taxable_value_observation", "basis"),
    ("land_observation", "classification"),
    ("improvement_observation", "classification"),
)


def test_every_carried_source_native_label_stays_open(connection: Any, rows: Any) -> None:
    """A previously unseen county value is stored exactly as the county wrote it."""

    for index, (relation, column) in enumerate(CARRIED):
        # Within the identifier alphabet for unit_code, which is an identifier
        # rather than a label; the point is that neither is a member of a set.
        value = f"UNSEEN-{index}" if column == "unit_code" else f"Unseen County Label {index}"
        execute(connection, f"UPDATE canonical.{relation} SET {column} = %s", value)

        assert scalar(connection, f"SELECT {column} FROM canonical.{relation} LIMIT 1") == value


def test_no_carried_source_native_label_carries_a_vocabulary(connection: Any) -> None:
    constrained = [
        (relation, column)
        for relation, column in CARRIED
        if any(
            " IN (" in definition or " = ANY (" in definition
            for (definition,) in fetch(
                connection,
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                " WHERE conrelid = %s::regclass AND contype='c' "
                "   AND pg_get_constraintdef(oid) LIKE %s",
                f"canonical.{relation}",
                f"%{column}%",
            )
        )
    ]

    assert constrained == []


def test_a_geometry_payload_must_agree_with_its_encoding(connection: Any, rows: Any) -> None:
    fixture, load = rows["fixture"], rows["load"]
    keys = (load["snapshot_key"], fixture["release_key"], load["load_key"], load["provenance_key"])
    columns = (
        "INSERT INTO canonical.geometry_observation"
        "(snapshot_key,release_key,load_key,provenance_key,encoding,payload_bytes,payload_text,crs)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,'EPSG:4326')"
    )

    disagreements = [
        ("wkb", None, "POINT(0 0)"),
        ("wkt", b"\\x01", None),
        ("wkb", b"\\x01", "POINT(0 0)"),
        ("wkt", b"\\x01", "POINT(0 0)"),
    ]
    for encoding, payload_bytes, payload_text in disagreements:
        message = refuses(connection, columns, *keys, encoding, payload_bytes, payload_text)
        assert "violates check constraint" in message


def test_a_geometry_payload_sits_at_and_past_its_bound(connection: Any, rows: Any) -> None:
    """8 MiB, and the text case measured as UTF-8 bytes rather than characters."""

    fixture, load = rows["fixture"], rows["load"]
    keys = (load["snapshot_key"], fixture["release_key"], load["load_key"], load["provenance_key"])
    limit = 8 * 1024 * 1024
    statement = (
        "INSERT INTO canonical.geometry_observation"
        "(snapshot_key,release_key,load_key,provenance_key,encoding,payload_text,crs) "
        "VALUES (%s,%s,%s,%s,'wkt',%s,'EPSG:4326')"
    )

    execute(connection, statement, *keys, "x" * limit)
    assert "violates check constraint" in refuses(connection, statement, *keys, "x" * (limit + 1))
    # Two-byte characters, so the count is bytes and not characters.
    assert "violates check constraint" in refuses(
        connection, statement, *keys, "\u00e9" * ((limit // 2) + 1)
    )


def test_geometry_requires_a_coordinate_reference(connection: Any, rows: Any) -> None:
    fixture, load = rows["fixture"], rows["load"]
    keys = (load["snapshot_key"], fixture["release_key"], load["load_key"], load["provenance_key"])
    statement = (
        "INSERT INTO canonical.geometry_observation"
        "(snapshot_key,release_key,load_key,provenance_key,encoding,payload_text,crs) "
        "VALUES (%s,%s,%s,%s,'wkt','POINT(0 0)',%s)"
    )

    assert "not-null" in refuses(connection, statement, *keys, None)
    assert "violates check constraint" in refuses(connection, statement, *keys, "   ")


def test_no_geospatial_dependency_is_installed(connection: Any) -> None:
    extensions = {name for (name,) in fetch(connection, "SELECT extname FROM pg_extension")}
    spatial_columns = fetch(
        connection,
        "SELECT table_name, column_name, udt_name FROM information_schema.columns "
        " WHERE table_schema='canonical' "
        "   AND udt_name IN ('geometry','geography','box2d','box3d','raster')",
    )

    assert not (extensions & {"postgis", "postgis_topology", "postgis_raster"})
    assert spatial_columns == []


def test_a_legal_part_without_its_text_is_refused(connection: Any, rows: Any) -> None:
    """A legal description has one required field, so its parts alone are not one."""

    execute(
        connection,
        "UPDATE canonical.account_snapshot SET legal_text = NULL, "
        "legal_subdivision = NULL, legal_block = NULL, legal_lot = NULL",
    )

    assert "violates check constraint" in refuses(
        connection, "UPDATE canonical.account_snapshot SET legal_block = 'B'"
    )


def test_an_area_and_its_unit_arrive_together(connection: Any, rows: Any) -> None:
    assert "violates check constraint" in refuses(
        connection, "UPDATE canonical.land_observation SET area_unit = NULL"
    )
    assert "violates check constraint" in refuses(
        connection, "UPDATE canonical.land_observation SET area = NULL"
    )


def test_the_control_character_rule_matches_the_python_category(connection: Any) -> None:
    """Enumerated from Python and asserted against the database, so the two
    definitions cannot drift the way a hand-copied character class does."""

    category = [chr(code) for code in list(range(0x00, 0x20)) + list(range(0x7F, 0xA0))]
    accepted = [
        character
        for character in category
        if character != "\x00"
        and scalar(connection, "SELECT canonical.is_bounded_text(%s, 256)", f"a{character}b")
    ]

    assert accepted == []
    assert all(
        unicodedata.category(character) == "Cc" for character in category if character != "\x00"
    )
