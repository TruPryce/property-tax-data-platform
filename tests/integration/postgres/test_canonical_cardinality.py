"""One-to-many stays one-to-many, and lineage cannot be cross-wired.

Task 2.2 of the accepted change. Parent agreement is at release grain: a child
from a second artifact of the same release must attach, and a child that crosses
a release must not.

These need a database. Set `PTDP_TEST_DATABASE_URL` and they run; leave it unset
and they skip. See `infra/postgres/README.md` for the container command.
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


PARENTED = (
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

#: Columns that hold something a county said, rather than a locator or a lineage
#: reference. A unique index over any of these would be deduplication by
#: resemblance, whatever it was named.
OBSERVED = frozenset(
    {
        "owner_name",
        "mailing_addressee",
        "mailing_street_address",
        "mailing_unit",
        "mailing_city",
        "mailing_state_code",
        "mailing_postal_code",
        "mailing_country_code",
        "ownership_percentage",
        "source_discriminator",
        "kind",
        "amount",
        "unit_code",
        "unit_name",
        "basis",
        "classification",
        "scope",
        "area",
        "area_unit",
        "year_built",
        "encoding",
        "payload_bytes",
        "payload_text",
        "crs",
        "situs_street_address",
        "legal_text",
    }
)


def lineage(fixture: dict[str, Any], load: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        load["snapshot_key"],
        fixture["release_key"],
        load["load_key"],
        load["provenance_key"],
    )


def add_owner(connection: Any, fixture: dict[str, Any], load: dict[str, Any], name: str) -> int:
    return int(
        scalar(
            connection,
            "INSERT INTO canonical.owner_observation"
            "(snapshot_key,release_key,load_key,provenance_key,owner_name) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING owner_key",
            *lineage(fixture, load),
            name,
        )
    )


def add_association(
    connection: Any, fixture: dict[str, Any], load: dict[str, Any], owner_key: int
) -> int:
    return int(
        scalar(
            connection,
            "INSERT INTO canonical.owner_association"
            "(snapshot_key,release_key,load_key,provenance_key,owner_key) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING association_key",
            *lineage(fixture, load),
            owner_key,
        )
    )


def add_taxing_unit(
    connection: Any, fixture: dict[str, Any], load: dict[str, Any], code: str
) -> int:
    return int(
        scalar(
            connection,
            "INSERT INTO canonical.taxing_unit_observation"
            "(snapshot_key,release_key,load_key,provenance_key,unit_code) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING taxing_unit_key",
            *lineage(fixture, load),
            code,
        )
    )


def populate(connection: Any, fixture: dict[str, Any], load: dict[str, Any]) -> None:
    """Two of every parented record under one snapshot."""
    keys = lineage(fixture, load)
    for index in (1, 2):
        owner = add_owner(connection, fixture, load, f"OWNER {index}")
        association = add_association(connection, fixture, load, owner)
        execute(
            connection,
            "INSERT INTO canonical.owner_value_allocation"
            "(association_key,release_key,load_key,provenance_key,kind,amount) "
            "VALUES (%s,%s,%s,%s,'market',%s)",
            association,
            fixture["release_key"],
            load["load_key"],
            load["provenance_key"],
            index * 1000,
        )
        execute(
            connection,
            "INSERT INTO canonical.appraisal_value_observation"
            "(snapshot_key,release_key,load_key,provenance_key,kind,amount) "
            "VALUES (%s,%s,%s,%s,'market',%s)",
            *keys,
            index * 100,
        )
        unit = add_taxing_unit(connection, fixture, load, f"UNIT-{index}")
        execute(
            connection,
            "INSERT INTO canonical.taxable_value_observation"
            "(snapshot_key,release_key,load_key,provenance_key,taxing_unit_key,amount,basis) "
            "VALUES (%s,%s,%s,%s,%s,%s,'net taxable')",
            *keys,
            unit,
            index * 10,
        )
        execute(
            connection,
            "INSERT INTO canonical.exemption_observation"
            "(snapshot_key,release_key,load_key,provenance_key,classification,scope) "
            "VALUES (%s,%s,%s,%s,%s,'account')",
            *keys,
            f"HOMESTEAD {index}",
        )
        execute(
            connection,
            "INSERT INTO canonical.land_observation"
            "(snapshot_key,release_key,load_key,provenance_key,classification) "
            "VALUES (%s,%s,%s,%s,%s)",
            *keys,
            f"LAND {index}",
        )
        execute(
            connection,
            "INSERT INTO canonical.improvement_observation"
            "(snapshot_key,release_key,load_key,provenance_key,classification) "
            "VALUES (%s,%s,%s,%s,%s)",
            *keys,
            f"IMP {index}",
        )
        execute(
            connection,
            "INSERT INTO canonical.geometry_observation"
            "(snapshot_key,release_key,load_key,provenance_key,encoding,payload_text,crs) "
            "VALUES (%s,%s,%s,%s,'wkt',%s,'EPSG:4326')",
            *keys,
            f"POINT({index} {index})",
        )


def test_two_of_every_parented_record_survive_under_one_snapshot(connection: Any) -> None:
    """One-to-many means one-to-many. Nothing here is one-per-kind or one-per-parent."""

    fixture = build(connection, "MANY")
    load = fixture["loads"][0]
    populate(connection, fixture, load)

    counted = {
        relation: scalar(
            connection,
            f"SELECT count(*) FROM canonical.{relation} WHERE snapshot_key=%s",
            load["snapshot_key"],
        )
        for relation in PARENTED
        if relation != "owner_value_allocation"
    }
    counted["owner_value_allocation"] = scalar(
        connection,
        "SELECT count(*) FROM canonical.owner_value_allocation allocation "
        "  JOIN canonical.owner_association association USING (association_key) "
        " WHERE association.snapshot_key=%s",
        load["snapshot_key"],
    )

    assert counted == dict.fromkeys(PARENTED, 2)


def test_two_geometries_for_one_snapshot_both_survive(connection: Any) -> None:
    """No accepted contract establishes that a county publishes only one."""

    fixture = build(connection, "GEOM")
    load = fixture["loads"][0]
    keys = lineage(fixture, load)
    execute(
        connection,
        "INSERT INTO canonical.geometry_observation"
        "(snapshot_key,release_key,load_key,provenance_key,encoding,payload_text,crs) "
        "VALUES (%s,%s,%s,%s,'wkt','POINT(0 0)','EPSG:4326')",
        *keys,
    )
    execute(
        connection,
        "INSERT INTO canonical.geometry_observation"
        "(snapshot_key,release_key,load_key,provenance_key,encoding,payload_bytes,crs) "
        "VALUES (%s,%s,%s,%s,'wkb','\\x0101'::bytea,'EPSG:4326')",
        *keys,
    )

    assert (
        scalar(
            connection,
            "SELECT count(*) FROM canonical.geometry_observation WHERE snapshot_key=%s",
            load["snapshot_key"],
        )
        == 2
    )


def test_no_unique_index_on_a_parented_relation_holds_an_observed_value(
    connection: Any,
) -> None:
    """Uniqueness composed of locators is a key target; uniqueness composed of what a
    county said is deduplication by resemblance."""

    offending = fetch(
        connection,
        "SELECT class.relname, attribute.attname "
        "  FROM pg_index AS index_row "
        "  JOIN pg_class AS class ON class.oid = index_row.indrelid "
        "  JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
        "  JOIN pg_attribute AS attribute "
        "       ON attribute.attrelid = index_row.indrelid "
        "      AND attribute.attnum = ANY (index_row.indkey) "
        " WHERE namespace.nspname='canonical' AND index_row.indisunique "
        "   AND attribute.attname = ANY (%s)",
        list(OBSERVED),
    )

    assert offending == []


def test_a_child_may_come_from_a_second_artifact_of_the_same_release(
    connection: Any,
) -> None:
    """Parent agreement is at release grain, not load grain.

    The promoted capability permits two snapshots at one grain with different
    artifact lineage and permits geometry from a partial GIS source. Requiring a
    child's load to equal its parent's would silently strengthen that and make a
    same-release enrichment from a second artifact unrepresentable.
    """

    fixture = build(connection, "CROSSART", artifacts=("a", "b"))
    parent, other = fixture["loads"]

    execute(
        connection,
        "INSERT INTO canonical.geometry_observation"
        "(snapshot_key,release_key,load_key,provenance_key,encoding,payload_text,crs) "
        "VALUES (%s,%s,%s,%s,'wkt','POINT(9 9)','EPSG:4326')",
        parent["snapshot_key"],
        fixture["release_key"],
        other["load_key"],
        other["provenance_key"],
    )

    assert (
        scalar(
            connection,
            "SELECT count(*) FROM canonical.geometry_observation "
            " WHERE snapshot_key=%s AND load_key=%s",
            parent["snapshot_key"],
            other["load_key"],
        )
        == 1
    )


def test_a_record_cannot_claim_provenance_from_another_load(connection: Any) -> None:
    """Keeping its own load while naming another's provenance is the escape this closes."""

    fixture = build(connection, "MIXLOAD", artifacts=("a", "b"))
    parent, other = fixture["loads"]

    message = refuses(
        connection,
        "INSERT INTO canonical.geometry_observation"
        "(snapshot_key,release_key,load_key,provenance_key,encoding,payload_text,crs) "
        "VALUES (%s,%s,%s,%s,'wkt','POINT(8 8)','EPSG:4326')",
        parent["snapshot_key"],
        fixture["release_key"],
        parent["load_key"],
        other["provenance_key"],
    )

    assert "lineage_is_its_provenance" in message


def test_a_child_cannot_cross_a_release(connection: Any) -> None:
    """The other direction: a parent of one release and a record of another."""

    first = build(connection, "RELA")
    second = build(connection, "RELB")
    load = second["loads"][0]

    message = refuses(
        connection,
        "INSERT INTO canonical.land_observation"
        "(snapshot_key,release_key,load_key,provenance_key) VALUES (%s,%s,%s,%s)",
        first["loads"][0]["snapshot_key"],
        second["release_key"],
        load["load_key"],
        load["provenance_key"],
    )

    assert "parent_is_of_its_release" in message


def test_a_load_cannot_claim_an_artifact_its_run_did_not_read(connection: Any) -> None:
    """The manifest is the only relation saying which artifact an acquisition carried."""

    fixture = build(connection, "WRONGART", artifacts=("a", "b"))
    reader, other = fixture["loads"]
    third = run_for(
        connection,
        manifest_id=reader["manifest_id"],
        jurisdiction=fixture["jurisdiction"],
        release=fixture["release"],
        tax_year=fixture["tax_year"],
        release_kind=fixture["release_kind"],
    )

    message = refuses(
        connection,
        "INSERT INTO canonical.release_load"
        "(release_key,run_id,manifest_id,artifact_sha256,jurisdiction_code,tax_year,"
        "release_kind,release_identifier) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        fixture["release_key"],
        third,
        reader["manifest_id"],
        other["artifact"],
        fixture["jurisdiction"],
        fixture["tax_year"],
        fixture["release_kind"],
        fixture["release"],
    )

    assert "reads_its_manifest_artifact" in message


def test_provenance_cannot_claim_an_artifact_its_load_did_not_read(connection: Any) -> None:
    fixture = build(connection, "PROVART", artifacts=("a", "b"))
    first, second = fixture["loads"]

    message = refuses(
        connection,
        "INSERT INTO canonical.provenance"
        "(load_key,release_key,jurisdiction_code,artifact_sha256,source_member_name,"
        "parser_contract_version) VALUES (%s,%s,%s,%s,'OTHER.TXT',1)",
        first["load_key"],
        fixture["release_key"],
        fixture["jurisdiction"],
        second["artifact"],
    )

    assert "artifact_is_its_load_artifact" in message


def test_a_load_cannot_name_another_countys_run(connection: Any) -> None:
    collin = build(connection, "COUNTYA")
    dallas = build(connection, "COUNTYB", jurisdiction="tx-dallas")

    message = refuses(
        connection,
        "INSERT INTO canonical.release_load"
        "(release_key,run_id,manifest_id,artifact_sha256,jurisdiction_code,tax_year,"
        "release_kind,release_identifier) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        dallas["release_key"],
        collin["loads"][0]["run_id"],
        collin["loads"][0]["manifest_id"],
        collin["loads"][0]["artifact"],
        dallas["jurisdiction"],
        dallas["tax_year"],
        dallas["release_kind"],
        dallas["release"],
    )

    assert "release_load" in message


def test_an_association_cannot_reference_an_owner_of_another_snapshot(
    connection: Any,
) -> None:
    fixture = build(connection, "OWNSNAP", artifacts=("a", "b"))
    first, second = fixture["loads"]
    owner = add_owner(connection, fixture, first, "OWNER ELSEWHERE")

    message = refuses(
        connection,
        "INSERT INTO canonical.owner_association"
        "(snapshot_key,release_key,load_key,provenance_key,owner_key) "
        "VALUES (%s,%s,%s,%s,%s)",
        second["snapshot_key"],
        fixture["release_key"],
        second["load_key"],
        second["provenance_key"],
        owner,
    )

    assert "owner_is_of_its_snapshot" in message


def test_a_taxable_value_cannot_reference_a_unit_of_another_snapshot(
    connection: Any,
) -> None:
    fixture = build(connection, "UNITSNAP", artifacts=("a", "b"))
    first, second = fixture["loads"]
    unit = add_taxing_unit(connection, fixture, first, "ISD-1")

    message = refuses(
        connection,
        "INSERT INTO canonical.taxable_value_observation"
        "(snapshot_key,release_key,load_key,provenance_key,taxing_unit_key,amount,basis) "
        "VALUES (%s,%s,%s,%s,%s,1,'net taxable')",
        second["snapshot_key"],
        fixture["release_key"],
        second["load_key"],
        second["provenance_key"],
        unit,
    )

    assert "names_a_taxing_unit_of_its_snapshot" in message


def test_a_taxable_value_without_a_taxing_unit_has_no_shape(connection: Any) -> None:
    """Not refused by a check: there is nowhere to put it."""

    fixture = build(connection, "NOUNIT")
    load = fixture["loads"][0]

    message = refuses(
        connection,
        "INSERT INTO canonical.taxable_value_observation"
        "(snapshot_key,release_key,load_key,provenance_key,taxing_unit_key,amount,basis) "
        "VALUES (%s,%s,%s,%s,NULL,1,'net taxable')",
        *lineage(fixture, load),
    )

    assert "not-null" in message or "not null" in message


def test_an_owner_allocation_carries_no_snapshot_of_its_own(connection: Any) -> None:
    """Its parent is the association, and the domain gives it exactly one."""

    columns = {
        name
        for (name,) in fetch(
            connection,
            "SELECT column_name FROM information_schema.columns "
            " WHERE table_schema='canonical' AND table_name='owner_value_allocation'",
        )
    }

    assert "snapshot_key" not in columns
    assert "association_key" in columns
