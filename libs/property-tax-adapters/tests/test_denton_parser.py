"""Component, contract, privacy, and boundary tests for the Denton foundation.

Every expectation is authored from the accepted OpenSpec change
``add-denton-cad-pacs-parser-foundation`` rather than from the parser's output.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest
from fixtures import denton_synthetic as synthetic
from property_tax_adapters.sources.pacs import (
    PACS_COMPONENT_CONTRACT_VERSION,
    PacsField,
    PacsLayout,
)
from property_tax_adapters.sources.texas.denton import (
    DENTON_CHILD_LAYOUT,
    DENTON_CORE_CHILD_TABLES,
    DENTON_DIAGNOSTIC_RETENTION_LIMIT,
    DENTON_LEGAL_CHILD_TABLES,
    DENTON_PROPERTY_LAYOUT,
    DENTON_SENSITIVE_FIELDS,
    DENTON_SOURCE,
    DentonDiagnostic,
    DentonDiagnosticCode,
    DentonValidationReport,
    validate_child_member,
    validate_property_member,
)

IDENTITY = {
    "release_identifier": synthetic.RELEASE_IDENTIFIER,
    "source_member_name": synthetic.SOURCE_MEMBER_NAME,
    "expected_tax_year": synthetic.EXPECTED_TAX_YEAR,
}


def _validate(data: bytes | str, **overrides: object) -> DentonValidationReport:
    return validate_property_member(data, **{**IDENTITY, **overrides})  # type: ignore[arg-type]


def _codes(report: DentonValidationReport) -> list[str]:
    return [entry.code.value for entry in report.diagnostics]


# --------------------------------------------------------------------------
# The shared PACS component
# --------------------------------------------------------------------------


def test_positions_are_one_indexed_and_inclusive() -> None:
    layout = PacsLayout("t", "v1", (PacsField("a", 1, 3), PacsField("b", 4, 6)))
    sliced = layout.slice_record("ABCDEF")
    assert sliced.values == {"a": "ABC", "b": "DEF"}
    assert layout.fields[0].length == 3
    assert layout.declared_width == 6


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ((PacsField("b", 4, 6), PacsField("a", 1, 3)), "descending order"),
        ((PacsField("a", 1, 5), PacsField("b", 4, 8)), "overlap"),
        ((PacsField("a", 1, 3), PacsField("a", 4, 6)), "duplicate name"),
        ((), "no fields"),
    ],
    ids=["order", "overlap", "duplicate-name", "empty"],
)
def test_a_layout_defect_raises_rather_than_diagnosing(
    fields: tuple[PacsField, ...], reason: str
) -> None:
    """A layout is trusted repository code, so a defect in one is an authoring
    mistake rather than something a source file did."""

    del reason
    with pytest.raises(ValueError):
        PacsLayout("t", "v1", fields)


@pytest.mark.parametrize(
    ("start", "end"), [(0, 3), (-1, 3), (5, 4)], ids=["zero", "negative", "reversed"]
)
def test_an_invalid_field_position_raises(start: int, end: int) -> None:
    with pytest.raises(ValueError):
        PacsField("a", start, end)


def test_the_layout_fingerprint_matches_the_specified_document() -> None:
    """Recomputed from the spec's five keys rather than from the component."""

    fields = (PacsField("a", 1, 3), PacsField("b", 4, 6, required=False))
    payload = json.dumps(
        {
            "component_contract_version": PACS_COMPONENT_CONTRACT_VERSION,
            "field_count": 2,
            "fields": [["a", 1, 3, True], ["b", 4, 6, False]],
            "layout_id": "t",
            "layout_version": "v1",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert PacsLayout("t", "v1", fields).fingerprint == expected
    assert expected == expected.lower()
    assert len(expected) == 64


@pytest.mark.parametrize(
    "mutation",
    ["layout_id", "layout_version", "name", "start", "end", "required", "field_count"],
)
def test_every_declared_attribute_changes_the_fingerprint(mutation: str) -> None:
    base = PacsLayout("t", "v1", (PacsField("a", 1, 3), PacsField("b", 4, 6)))
    variants = {
        "layout_id": PacsLayout("u", "v1", (PacsField("a", 1, 3), PacsField("b", 4, 6))),
        "layout_version": PacsLayout("t", "v2", (PacsField("a", 1, 3), PacsField("b", 4, 6))),
        "name": PacsLayout("t", "v1", (PacsField("z", 1, 3), PacsField("b", 4, 6))),
        "start": PacsLayout("t", "v1", (PacsField("a", 2, 3), PacsField("b", 4, 6))),
        "end": PacsLayout("t", "v1", (PacsField("a", 1, 2), PacsField("b", 4, 6))),
        "required": PacsLayout(
            "t", "v1", (PacsField("a", 1, 3, required=False), PacsField("b", 4, 6))
        ),
        "field_count": PacsLayout("t", "v1", (PacsField("a", 1, 3),)),
    }
    assert variants[mutation].fingerprint != base.fingerprint


def test_a_truncated_required_field_is_never_emitted_as_a_value() -> None:
    layout = PacsLayout("t", "v1", (PacsField("a", 1, 3), PacsField("b", 4, 10)))
    sliced = layout.slice_record("ABCDE")
    assert sliced.values == {"a": "ABC"}
    assert sliced.truncated_required == ("b",)
    assert "DE" not in sliced.values.values()


def test_a_truncated_optional_field_is_absent_rather_than_partial() -> None:
    layout = PacsLayout("t", "v1", (PacsField("a", 1, 3), PacsField("b", 4, 10, required=False)))
    sliced = layout.slice_record("ABCDE")
    assert sliced.truncated_required == ()
    assert sliced.absent_optional == ("b",)
    assert "b" not in sliced.values


def test_a_trailing_region_is_fingerprinted_and_never_carried() -> None:
    layout = PacsLayout("t", "v1", (PacsField("a", 1, 3),))
    sliced = layout.slice_record("ABC" + "SECRET-TRAILING")
    assert sliced.trailing is not None
    assert sliced.trailing.byte_length == len("SECRET-TRAILING")
    assert sliced.trailing.digest == hashlib.sha256(b"SECRET-TRAILING").hexdigest()
    assert "SECRET-TRAILING" not in repr(sliced.trailing)


def test_the_component_names_no_county_in_its_code() -> None:
    """A component that knew a county field could not be bound by another.

    Read from the parsed code rather than the file text: the module docstring
    legitimately explains *why* Ellis binds rather than forks, and a naive grep
    would fail on that explanation while missing nothing real.
    """

    import ast

    from property_tax_adapters.sources import pacs

    tree = ast.parse(Path(inspect.getfile(pacs)).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value.value = ""  # drop docstrings, keeping the code shape
    code = ast.unparse(tree).casefold()

    for county in ("denton", "ellis", "tarrant", "dallas", "collin", "rockwall"):
        assert county not in code, county
    for county_field in ("prop_id", "owner_sequence", "ten_percent_cap"):
        assert county_field not in code, county_field


# --------------------------------------------------------------------------
# Denton physical layer
# --------------------------------------------------------------------------


def test_the_declared_layout_matches_the_documented_widths() -> None:
    assert DENTON_PROPERTY_LAYOUT.declared_width == synthetic.EXPECTED_PROPERTY_WIDTH
    assert DENTON_CHILD_LAYOUT.declared_width == synthetic.EXPECTED_CHILD_WIDTH
    assert len(synthetic.property_row()) == synthetic.EXPECTED_PROPERTY_WIDTH


@pytest.mark.parametrize(
    "member",
    [synthetic.VALID_LF, synthetic.VALID_CRLF, synthetic.VALID_NO_TRAILING_NEWLINE],
    ids=["lf", "crlf", "no-trailing-newline"],
)
def test_a_valid_member_is_accepted(member: bytes) -> None:
    report = _validate(member)
    assert report.release_accepted is True
    assert report.accepted_row_count == 1
    assert report.owner_row_count == 1
    assert report.diagnostics == ()
    assert report.parser_contract_version == 1


def test_text_outside_the_approved_encoding_is_refused() -> None:
    report = _validate("—" * synthetic.EXPECTED_PROPERTY_WIDTH)
    assert _codes(report) == ["invalid_encoding"]


@pytest.mark.parametrize(
    "member", [synthetic.UTF8_BOM, synthetic.UTF16_LE_BOM], ids=["utf-8", "utf-16-le"]
)
def test_a_byte_order_mark_is_refused(member: bytes) -> None:
    assert _codes(_validate(member)) == ["unexpected_bom"]


def test_records_of_disagreeing_width_are_refused() -> None:
    """Width is a member-level property: PACS records carry no delimiter, so a
    differing width is evidence the member is not the declared layout."""

    report = _validate(synthetic.WIDTH_MISMATCH)
    assert _codes(report) == ["record_width_mismatch"]
    assert report.diagnostics[0].physical_row_number == 2
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_a_uniformly_short_member_is_refused() -> None:
    """Uniformity is not enough: every required Denton field ends by position 75,
    so comparing rows only with one another accepted a 75-character member
    against a layout declaring 305."""

    report = _validate(synthetic.UNIFORMLY_SHORT)
    assert _codes(report) == ["record_width_mismatch"]
    assert report.release_accepted is False
    assert report.accepted_row_count == 0

    # And the short-by-any-amount case is refused the same way.
    assert _codes(_validate(synthetic.TRUNCATED_REQUIRED)) == ["record_width_mismatch"]


def test_an_undocumented_trailing_region_fails_closed() -> None:
    """Issue #20 requires unknown trailing bytes to be rejected.

    Treating them as a warning accepted a member carrying undocumented content
    with its unknown region merely noted. The region is still fingerprinted, so
    the rejection carries evidence of what was found without carrying it.
    """

    report = _validate(synthetic.WITH_TRAILING_REGION)
    assert _codes(report) == ["undocumented_trailing_region"]
    assert report.release_accepted is False
    assert report.accepted_row_count == 0
    assert report.trailing_region_bytes == len(synthetic.TRAILING_REGION_TEXT)
    assert synthetic.TRAILING_REGION_TEXT not in repr(report)


def test_a_bare_cr_is_not_a_record_boundary_and_does_not_pass_as_one_record() -> None:
    """A bare CR is not a boundary, so two records become one over-wide record.

    Accepting that as a valid record with a trailing region would silently read
    two records as one, so an embedded control character is refused outright.
    """

    member = (synthetic.property_row() + "\r" + synthetic.property_row()).encode("iso-8859-1")
    report = _validate(member)
    assert _codes(report) == ["invalid_source_text"]
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_an_over_wide_fixture_value_is_refused_by_the_fixture() -> None:
    """The four-character owner sequence cannot hold five digits, so the bound
    is structural. The fixture refuses rather than silently clipping."""

    with pytest.raises(ValueError):
        synthetic.property_row(owner_sequence="12345")


# --------------------------------------------------------------------------
# Lexical rules
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("prop_id", "", "blank_required_key"),
        ("owner_sequence", "", "blank_required_key"),
        ("owner_sequence", "abcd", "invalid_owner_sequence"),
        ("tax_year", "999", "invalid_tax_year"),
        ("tax_year", "1899", "invalid_tax_year"),
        ("tax_year", "2024", "tax_year_mismatch"),
        ("ownership_percentage", "101", "invalid_ownership_percentage"),
        ("ownership_percentage", "-1", "invalid_ownership_percentage"),
        ("market_value", "1,250.00", "invalid_monetary_value"),
        ("market_value", "-1", "invalid_monetary_value"),
        ("market_value", "1.234", "invalid_monetary_value"),
        ("market_value", "", "blank_required_key"),
        ("ten_percent_cap", "abc", "invalid_monetary_value"),
    ],
)
def test_an_unapproved_value_is_refused(field: str, value: str, code: str) -> None:
    report = _validate(synthetic.member(synthetic.property_row(**{field: value})))
    assert code in _codes(report), _codes(report)
    assert report.release_accepted is False


@pytest.mark.parametrize("value", ["0", "100", "50.5", "33.333333"])
def test_an_approved_ownership_percentage_is_accepted(value: str) -> None:
    report = _validate(synthetic.member(synthetic.property_row(ownership_percentage=value)))
    assert report.release_accepted is True


def test_optional_monetary_fields_may_be_blank_as_source_absence() -> None:
    report = _validate(
        synthetic.member(
            synthetic.property_row(land_value="", improvement_value="", ten_percent_cap="")
        )
    )
    assert report.release_accepted is True


def test_an_account_identifier_is_compared_as_text() -> None:
    """`000123` and `123` are two accounts, not one."""

    report = _validate(synthetic.LEADING_ZERO_ACCOUNTS)
    assert report.release_accepted is True
    assert report.accepted_row_count == 2
    assert report.owner_row_count == 2


# --------------------------------------------------------------------------
# Owner-row grain
# --------------------------------------------------------------------------


def test_an_undivided_interest_allocation_is_preserved() -> None:
    report = _validate(synthetic.OWNER_ALLOCATION)
    assert report.release_accepted is True
    assert report.accepted_row_count == 3
    assert report.owner_row_count == 3
    # No account-level total is derived from the three rows.
    assert not hasattr(report, "account_total")


def test_a_repeated_owner_row_is_refused() -> None:
    report = _validate(synthetic.DUPLICATE_OWNER_ROW)
    assert "duplicate_owner_row" in _codes(report)
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_conflicting_account_facts_are_refused() -> None:
    report = _validate(synthetic.CONFLICTING_ACCOUNT_FACTS)
    assert "conflicting_account_facts" in _codes(report)
    assert report.diagnostics[0].field_name == "market_value"
    assert report.release_accepted is False


def test_ten_percent_cap_is_carried_without_interpretation() -> None:
    report = _validate(
        synthetic.member(
            synthetic.property_row(ten_percent_cap="20000.00", market_value="250000.00")
        )
    )
    assert report.release_accepted is True
    for derived in ("capped_value", "assessed_after_cap", "taxable_value"):
        assert not hasattr(report, derived)


# --------------------------------------------------------------------------
# Child relationships
# --------------------------------------------------------------------------


@pytest.mark.parametrize("table", sorted(DENTON_CORE_CHILD_TABLES))
def test_a_core_appraisal_orphan_blocks(table: str) -> None:
    report = validate_child_member(
        synthetic.CHILD_ORPHANED,
        release_identifier=synthetic.RELEASE_IDENTIFIER,
        source_member_name=synthetic.SOURCE_MEMBER_NAME,
        child_table=table,
        accepted_account_ids=synthetic.ACCEPTED_ACCOUNT_IDS,
    )
    assert _codes(report) == ["core_child_orphaned"]
    assert report.release_accepted is False


@pytest.mark.parametrize("table", sorted(DENTON_LEGAL_CHILD_TABLES))
def test_a_legal_orphan_warns_without_blocking(table: str) -> None:
    report = validate_child_member(
        synthetic.CHILD_ORPHANED,
        release_identifier=synthetic.RELEASE_IDENTIFIER,
        source_member_name=synthetic.SOURCE_MEMBER_NAME,
        child_table=table,
        accepted_account_ids=synthetic.ACCEPTED_ACCOUNT_IDS,
    )
    assert _codes(report) == ["legal_child_orphaned"]
    assert report.release_accepted is True


def test_a_resolved_child_is_accepted() -> None:
    report = validate_child_member(
        synthetic.CHILD_RESOLVED,
        release_identifier=synthetic.RELEASE_IDENTIFIER,
        source_member_name=synthetic.SOURCE_MEMBER_NAME,
        child_table="land",
        accepted_account_ids=synthetic.ACCEPTED_ACCOUNT_IDS,
    )
    assert report.release_accepted is True
    assert report.accepted_row_count == 1


def test_an_unapproved_child_table_raises() -> None:
    with pytest.raises(ValueError):
        validate_child_member(
            synthetic.CHILD_RESOLVED,
            release_identifier=synthetic.RELEASE_IDENTIFIER,
            source_member_name=synthetic.SOURCE_MEMBER_NAME,
            child_table="not_a_table",
            accepted_account_ids=synthetic.ACCEPTED_ACCOUNT_IDS,
        )


# --------------------------------------------------------------------------
# Diagnostics, atomicity, caller identity
# --------------------------------------------------------------------------


def test_the_diagnostic_vocabulary_is_closed() -> None:
    observed = {code.value for code in DentonDiagnosticCode}
    assert len(observed) == synthetic.EXPECTED_DIAGNOSTIC_CODE_COUNT
    assert observed == {
        "invalid_encoding",
        "unexpected_bom",
        "record_width_mismatch",
        "unsupported_layout_fingerprint",
        "undocumented_trailing_region",
        "blank_required_key",
        "invalid_account_id",
        "invalid_owner_sequence",
        "invalid_monetary_value",
        "invalid_ownership_percentage",
        "invalid_tax_year",
        "tax_year_mismatch",
        "invalid_source_text",
        "duplicate_owner_row",
        "conflicting_account_facts",
        "core_child_orphaned",
        "legal_child_orphaned",
    }


def test_a_diagnostic_carries_only_the_four_permitted_fields() -> None:
    assert list(DentonDiagnostic.__dataclass_fields__) == [
        "code",
        "field_name",
        "physical_row_number",
        "layout_fingerprint",
    ]


def test_one_failing_record_among_many_returns_nothing() -> None:
    rows = [synthetic.property_row(prop_id=f"ACC-{index:04d}") for index in range(40)]
    rows[21] = synthetic.property_row(prop_id="ACC-0021", market_value="-1")
    report = _validate(synthetic.member(*rows))
    assert "invalid_monetary_value" in _codes(report)
    assert report.diagnostics[0].physical_row_number == 22
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_diagnostics_truncate_deterministically_while_preserving_the_total() -> None:
    rows = [
        synthetic.property_row(prop_id=f"ACC-{index:04d}", market_value="-1")
        for index in range(130)
    ]
    member = synthetic.member(*rows)
    report = _validate(member)
    assert len(report.diagnostics) == DENTON_DIAGNOSTIC_RETENTION_LIMIT
    assert report.total_diagnostic_count == 130
    assert report.diagnostics_truncated is True
    assert _validate(member).diagnostics == report.diagnostics


@pytest.mark.parametrize(
    "override",
    [
        {"release_identifier": ""},
        {"release_identifier": "a" * 129},
        {"source_member_name": "/var/tmp/denton.txt"},
        {"source_member_name": "../denton.txt"},
        {"expected_tax_year": 1899},
        {"expected_tax_year": True},
        {"expected_tax_year": "2025"},
        {"release_identifier": b"denton"},
    ],
    ids=["empty", "too-long", "path", "traversal", "year-low", "bool", "str-year", "bytes"],
)
def test_an_out_of_contract_caller_argument_raises(override: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _validate(synthetic.VALID_LF, **override)


# --------------------------------------------------------------------------
# Privacy and boundaries
# --------------------------------------------------------------------------


def test_owner_and_address_values_never_reach_the_report() -> None:
    report = _validate(synthetic.VALID_LF)
    rendered = repr(report)
    for placeholder in (
        synthetic.OWNER_PLACEHOLDER,
        synthetic.ADDRESS_PLACEHOLDER,
        synthetic.SITUS_PLACEHOLDER,
    ):
        assert placeholder not in rendered


def test_the_sensitive_field_inventory_matches_the_contract() -> None:
    assert DENTON_SENSITIVE_FIELDS == {"owner_name", "owner_address", "situs_address"}
    assert len(DENTON_SENSITIVE_FIELDS) == synthetic.EXPECTED_SENSITIVE_FIELD_COUNT


def test_the_report_carries_no_row_payload() -> None:
    fields = set(DentonValidationReport.__dataclass_fields__)
    assert fields == {
        "parser_contract_version",
        "release_accepted",
        "layout_fingerprint",
        "layout_version",
        "accepted_row_count",
        "owner_row_count",
        "trailing_region_bytes",
        "diagnostics",
        "total_diagnostic_count",
        "diagnostics_truncated",
    }
    assert not fields & {"rows", "records", "values", "source_records"}


def _denton_source() -> str:
    from property_tax_adapters.sources.texas import denton

    return Path(inspect.getfile(denton)).read_text(encoding="utf-8")


def test_no_county_local_shared_contract_is_defined() -> None:
    """Issue #43 owns these three; a local copy is still what this avoids.

    Before the shared module existed this also asserted that nothing referenced
    it, because waiting was the only correct behaviour.  Tasks 6.1 to 6.3 end
    the wait; they do not license a copy, so the prohibition is now expressed as
    a check on what this module *defines* rather than on what it imports.
    """

    import ast

    source = _denton_source()
    assert "from property_tax_adapters.sources.contracts import" in source

    defined = {node.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ClassDef)}
    assert not defined & {
        "SourceNativeValue",
        "SourceProvenance",
        "AppraisalSourceRecord",
        "DentonSourceNativeValue",
        "DentonAppraisalSourceRecord",
    }


def test_the_domain_and_application_packages_gain_no_parser_vocabulary() -> None:
    """`DENTON_SOURCE` legitimately imports both, so absence is not the claim."""

    source = _denton_source()
    assert "from property_tax_application import" in source
    assert "from property_tax_domain import" in source
    assert DENTON_SOURCE.parser_id == "texas.denton.pacs-fixed-width-v1"

    vocabulary = (
        "DentonDiagnostic",
        "DentonValidationReport",
        "validate_property_member",
        "PacsLayout",
        "PacsField",
        "ten_percent_cap",
        "owner_sequence",
    )
    repo_root = Path(__file__).resolve().parents[3]
    for package in ("property-tax-domain", "property-tax-application"):
        for path in (repo_root / "libs" / package / "src").rglob("*.py"):
            body = path.read_text(encoding="utf-8")
            leaked = [name for name in vocabulary if name in body]
            assert leaked == [], (path, leaked)


def test_no_acquisition_network_or_persistence_behavior_is_present() -> None:
    for source in (_denton_source(), _pacs_source()):
        for forbidden in (
            "import requests",
            "import httpx",
            "urllib",
            "socket",
            "zipfile",
            "sqlalchemy",
            "boto3",
            "open(",
        ):
            assert forbidden not in source, forbidden


def _pacs_source() -> str:
    from property_tax_adapters.sources import pacs

    return Path(inspect.getfile(pacs)).read_text(encoding="utf-8")


def test_the_foundation_adds_no_dependency_outside_the_standard_library() -> None:
    for source in (_denton_source(), _pacs_source()):
        imported = {
            line.split()[1].split(".")[0]
            for line in source.splitlines()
            if line.startswith(("import ", "from ")) and "property_tax" not in line
        }
        assert imported <= {
            "__future__",
            "hashlib",
            "json",
            "re",
            "collections",
            "dataclasses",
            "decimal",
            "enum",
            "types",
            "typing",
        }, imported


# --------------------------------------------------------------------------
# Review findings
# --------------------------------------------------------------------------


def test_the_trailing_digest_describes_source_bytes() -> None:
    """Re-encoding as UTF-8 reported four bytes for two ISO-8859-1 characters
    and digested content that never appeared in the member."""

    import hashlib

    report = _validate(synthetic.WITH_LATIN1_TRAILING)
    assert report.release_accepted is False  # trailing bytes fail closed
    expected = synthetic.LATIN1_TRAILING_TEXT.encode("iso-8859-1")
    assert len(expected) == 2
    assert report.trailing_region_bytes == 2

    sliced = DENTON_PROPERTY_LAYOUT.slice_record(
        synthetic.property_row() + synthetic.LATIN1_TRAILING_TEXT, encoding="iso-8859-1"
    )
    assert sliced.trailing is not None
    assert sliced.trailing.digest == hashlib.sha256(expected).hexdigest()


def test_a_declared_length_that_disagrees_with_positions_raises() -> None:
    """`length` was derived, so the promised disagreement could never occur."""

    from property_tax_adapters.sources.pacs import PacsField

    with pytest.raises(ValueError):
        PacsField("a", 1, 12, declared_length=11)
    assert PacsField("a", 1, 12, declared_length=12).length == 12


def test_the_expected_fingerprint_is_pinned_rather_than_derived() -> None:
    """A self-derived constant moves with the layout, so the gate cannot fail.

    Reading the literal out of the module source proves it is written down
    rather than computed from the layout it guards.
    """

    source = _denton_source()
    assert f'"{DENTON_PROPERTY_LAYOUT.fingerprint}"' in source
    assert f'"{DENTON_CHILD_LAYOUT.fingerprint}"' in source
    assert "DENTON_EXPECTED_PROPERTY_FINGERPRINT: Final = DENTON_PROPERTY_LAYOUT" not in source


def test_an_unexpected_layout_fingerprint_is_refused() -> None:
    report = _validate(synthetic.VALID_LF, expected_layout_fingerprint="0" * 64)
    assert _codes(report) == ["unsupported_layout_fingerprint"]
    assert report.release_accepted is False


def test_the_fingerprint_gate_runs_before_any_record_is_read() -> None:
    report = _validate(synthetic.WIDTH_MISMATCH, expected_layout_fingerprint="0" * 64)
    assert _codes(report) == ["unsupported_layout_fingerprint"]


def _validate_child(data: bytes, **overrides: object):
    return validate_child_member(
        data,
        **{
            "release_identifier": synthetic.RELEASE_IDENTIFIER,
            "source_member_name": synthetic.SOURCE_MEMBER_NAME,
            "child_table": "land",
            "accepted_account_ids": ("000123", "000124"),
            **overrides,
        },  # type: ignore[arg-type]
    )


def test_child_validation_applies_the_same_width_rule() -> None:
    """A uniformly short child member was accepted outright."""

    report = _validate_child(synthetic.SHORT_CHILD)
    assert _codes(report) == ["record_width_mismatch"]
    assert report.release_accepted is False


def test_child_validation_applies_the_same_control_character_rule() -> None:
    """A control character corrupted `prop_id` into a false orphan report."""

    report = _validate_child(synthetic.CONTROL_CHILD)
    assert _codes(report) == ["invalid_source_text"]
    assert "core_child_orphaned" not in _codes(report)


def test_child_validation_gates_on_its_own_fingerprint() -> None:
    report = _validate_child(synthetic.CHILD_RESOLVED, expected_layout_fingerprint="0" * 64)
    assert _codes(report) == ["unsupported_layout_fingerprint"]


def test_every_declared_denton_code_is_reachable() -> None:
    """Three codes in these PRs were declared and never emitted. Pin the rule.

    `unsupported_layout_fingerprint` and `invalid_source_text` are covered by the
    tests above; this asserts the vocabulary carries nothing that no test emits.
    """

    emitted = {
        "invalid_encoding",
        "unexpected_bom",
        "record_width_mismatch",
        "unsupported_layout_fingerprint",
        "undocumented_trailing_region",
        "blank_required_key",
        "invalid_account_id",
        "invalid_owner_sequence",
        "invalid_monetary_value",
        "invalid_ownership_percentage",
        "invalid_tax_year",
        "tax_year_mismatch",
        "invalid_source_text",
        "duplicate_owner_row",
        "conflicting_account_facts",
        "core_child_orphaned",
        "legal_child_orphaned",
    }
    assert {code.value for code in DentonDiagnosticCode} == emitted


def test_a_fingerprinted_layout_cannot_be_relabelled() -> None:
    """A settable version let a mutated layout report the old approved digest."""

    from property_tax_adapters.sources.pacs import PacsField, PacsLayout

    layout = PacsLayout("t", "v1", (PacsField("a", 1, 3),))
    before = layout.fingerprint
    # Read-only properties were not enough: the private attributes behind them
    # stayed assignable, so the public names were a formality.
    for attribute in (
        "layout_version",
        "layout_id",
        "_layout_version",
        "_layout_id",
        "_fields",
        "_fingerprint",
    ):
        with pytest.raises(AttributeError):
            setattr(layout, attribute, "mutated")
        with pytest.raises(AttributeError):
            delattr(layout, attribute)
    assert layout.fingerprint == before
    assert layout.layout_version == "v1"


# --------------------------------------------------------------------------
# Automated review findings, carried over from the Ellis binding
# --------------------------------------------------------------------------


def test_repository_drift_fails_even_when_the_caller_supplies_the_live_digest() -> None:
    """The gate compared the caller's value against the live layout digest.

    That made the pinned constant decorative: a drifted mapping moves the live
    digest with it, so a caller passing the current value passed the gate while
    the approved constant still held the old one.
    """

    from property_tax_adapters.sources.pacs import PacsLayout
    from property_tax_adapters.sources.texas.denton import (
        DENTON_EXPECTED_PROPERTY_FINGERPRINT,
        _assert_layout_approved,
    )

    drifted = PacsLayout("denton.property", "v1", tuple(DENTON_PROPERTY_LAYOUT.fields[:-1]))
    assert drifted.fingerprint != DENTON_EXPECTED_PROPERTY_FINGERPRINT
    assert not _assert_layout_approved(
        drifted, drifted.fingerprint, DENTON_EXPECTED_PROPERTY_FINGERPRINT
    )
    assert _assert_layout_approved(
        DENTON_PROPERTY_LAYOUT,
        DENTON_EXPECTED_PROPERTY_FINGERPRINT,
        DENTON_EXPECTED_PROPERTY_FINGERPRINT,
    )


def test_a_uniformly_wide_child_member_is_refused() -> None:
    """The child path ignored trailing regions the property path rejects."""

    wide = synthetic.member(
        synthetic.child_row() + "EXTRA-TRAILING",
        synthetic.child_row(prop_id="000124") + "EXTRA-TRAILING",
    )
    report = _validate_child(wide, accepted_account_ids=("000123", "000124"))
    assert _codes(report) == ["undocumented_trailing_region"]
    assert report.release_accepted is False
    assert report.trailing_region_bytes == len("EXTRA-TRAILING")


def test_every_declared_denton_code_is_actually_emitted() -> None:
    """Set equality proves the vocabulary agrees with itself, not that any input
    produces each code. This drives real inputs through the entry points."""

    emitted: set[str] = set()

    def collect(report: DentonValidationReport) -> None:
        emitted.update(entry.code.value for entry in report.diagnostics)

    row = synthetic.property_row
    collect(_validate("\u2014" * synthetic.EXPECTED_PROPERTY_WIDTH))
    collect(_validate(synthetic.UTF8_BOM))
    collect(_validate(synthetic.WIDTH_MISMATCH))
    collect(_validate(synthetic.VALID_LF, expected_layout_fingerprint="0" * 64))
    collect(_validate(synthetic.WITH_TRAILING_REGION))
    collect(_validate(synthetic.member(row(prop_id=""))))
    collect(_validate(synthetic.member(row(prop_id="a b"))))
    collect(_validate(synthetic.member(row(owner_sequence="abcd"))))
    collect(_validate(synthetic.member(row(market_value="-1"))))
    collect(_validate(synthetic.member(row(ownership_percentage="101"))))
    collect(_validate(synthetic.member(row(tax_year="1899"))))
    collect(_validate(synthetic.member(row(tax_year="2024"))))
    collect(_validate((row() + "\r" + row()).encode("iso-8859-1")))
    collect(_validate(synthetic.DUPLICATE_OWNER_ROW))
    collect(_validate(synthetic.CONFLICTING_ACCOUNT_FACTS))
    collect(_validate_child(synthetic.CHILD_ORPHANED))
    collect(_validate_child(synthetic.CHILD_ORPHANED, child_table="arb"))

    declared = {code.value for code in DentonDiagnosticCode}
    assert declared - emitted == set(), f"declared but never emitted: {sorted(declared - emitted)}"


# --------------------------------------------------------------------------
# Tasks 6.1, 6.2, 6.3: records, conversion, and typed children
# --------------------------------------------------------------------------


def _materialize(data: bytes | str = None, **overrides: object):  # type: ignore[assignment]
    from property_tax_adapters.sources.texas.denton import materialize_property_member

    payload = synthetic.VALID_LF if data is None else data
    return materialize_property_member(payload, **{**IDENTITY, **overrides})  # type: ignore[arg-type]


def _materialize_child(data: bytes | str = None, **overrides: object):  # type: ignore[assignment]
    from property_tax_adapters.sources.texas.denton import materialize_child_member

    payload = synthetic.CHILD_RESOLVED if data is None else data
    return materialize_child_member(
        payload,
        release_identifier=synthetic.RELEASE_IDENTIFIER,
        source_member_name=synthetic.SOURCE_MEMBER_NAME,
        accepted_account_ids=overrides.pop("accepted_account_ids", synthetic.ACCEPTED_ACCOUNT_IDS),
        **overrides,  # type: ignore[arg-type]
    )


# -- 6.1 --------------------------------------------------------------------


def test_materialization_reuses_validation_rather_than_repeating_it() -> None:
    """Contract: Add a row-materialization entry point that reuses the existing validation."""

    validated = _validate(synthetic.VALID_LF)
    result = _materialize(synthetic.VALID_LF)

    assert result.report == validated
    assert len(result.records) == validated.accepted_row_count


def test_the_report_stays_valid_and_record_free() -> None:
    """Contract: Keep DentonValidationReport valid and record-free."""

    from dataclasses import fields as dataclass_fields

    from property_tax_adapters.sources.texas.denton import DentonValidationReport

    declared = {field.name for field in dataclass_fields(DentonValidationReport)}
    assert not declared & {"records", "rows", "values", "source_native_values"}
    assert not hasattr(_materialize().report, "records")


def test_a_record_carries_the_owner_grain_and_its_values() -> None:
    """Contract: ...carrying prop_id, owner_sequence, the approved values as shared entries."""

    record = _materialize().records[0]

    assert record.prop_id == "000123"
    assert record.owner_sequence
    for name, value in record.source_native_values.items():
        assert value.source_field == name
        assert value.classification == "source-native"
        assert value.lexical_text == value.lexical_text.strip()


def test_ten_percent_cap_is_a_source_native_amount_and_nothing_more() -> None:
    """Contract: ...ten_percent_cap as a source-native cap amount."""

    from decimal import Decimal

    row = synthetic.property_row(ten_percent_cap="000000000250.00")
    record = _materialize(synthetic.member(row)).records[0]

    cap = record.source_native_values["ten_percent_cap"]
    assert cap.source_field == "ten_percent_cap"
    assert cap.value == Decimal("250.00")
    # A published amount, not a canonical capped value derived from anything.
    assert not hasattr(record, "capped_value")


def test_provenance_carries_the_fingerprint_version_and_field_positions() -> None:
    """Contract: ...layout fingerprint and version, field positions, and the one-based row."""

    from property_tax_adapters.sources.contracts import SourceProvenance
    from property_tax_adapters.sources.texas.denton import DENTON_PROPERTY_LAYOUT

    provenance = _materialize().records[0].provenance

    assert provenance.jurisdiction_code == "tx-denton"
    assert provenance.release_identifier == synthetic.RELEASE_IDENTIFIER
    assert provenance.source_member_name == synthetic.SOURCE_MEMBER_NAME
    assert provenance.tax_year == synthetic.EXPECTED_TAX_YEAR
    assert provenance.layout_fingerprint == DENTON_PROPERTY_LAYOUT.fingerprint
    assert provenance.layout_version == DENTON_PROPERTY_LAYOUT.layout_version
    assert provenance.physical_row_number == 1
    assert isinstance(provenance.shared, SourceProvenance)

    assert provenance.field_positions["prop_id"] == (1, 12)
    assert provenance.field_positions["ten_percent_cap"] == (121, 135)


def test_no_sensitive_field_position_or_value_reaches_a_record() -> None:
    """Contract: their values MUST NOT enter a report, a diagnostic, a
    fixture, a log, or any output."""

    record = _materialize().records[0]

    assert not set(record.source_native_values) & DENTON_SENSITIVE_FIELDS
    assert not set(record.provenance.field_positions) & DENTON_SENSITIVE_FIELDS


def test_a_rejected_release_materializes_nothing() -> None:
    """Release-level atomicity, with a valid row present to actually discard."""

    mixed = synthetic.member(
        synthetic.property_row(),
        synthetic.property_row(prop_id="000124", tax_year="1899"),
    )
    result = _materialize(mixed)

    assert result.report.release_accepted is False
    assert result.records == ()


def test_a_stored_shared_provenance_may_not_disagree_with_its_county_fields() -> None:
    from dataclasses import replace

    from property_tax_adapters.sources.texas.denton import DentonSourceProvenance

    provenance = _materialize().records[0].provenance
    with pytest.raises(ValueError, match="disagrees with Denton provenance"):
        DentonSourceProvenance(
            jurisdiction_code=provenance.jurisdiction_code,
            release_identifier=provenance.release_identifier,
            source_member_name=provenance.source_member_name,
            tax_year=provenance.tax_year,
            layout_fingerprint=provenance.layout_fingerprint,
            layout_version=provenance.layout_version,
            field_positions=provenance.field_positions,
            physical_row_number=provenance.physical_row_number,
            parser_contract_version=provenance.parser_contract_version,
            shared=replace(provenance.shared, source_row_number=99),
        )


# -- 6.2 --------------------------------------------------------------------


def test_conversion_uses_prop_id_as_the_source_account_id() -> None:
    """Contract: ...with jurisdiction tx-denton, prop_id as source account ID."""

    from property_tax_adapters.sources.texas.denton import convert_denton_record

    record = _materialize().records[0]
    shared = convert_denton_record(record)

    assert shared.jurisdiction_code == "tx-denton"
    assert shared.source_account_id == record.prop_id
    assert shared.appraisal_year == record.provenance.tax_year
    assert shared.provenance is record.provenance.shared
    for name, value in shared.source_native_values.items():
        assert value.source_field == name


def test_conversion_preserves_the_owner_grain_and_derives_no_roll_up() -> None:
    """Contract: preserve (prop_id, owner_sequence) grain in the output,
    derive no account roll-up."""

    from property_tax_adapters.sources.texas.denton import convert_denton_record

    allocation = synthetic.member(
        synthetic.property_row(owner_sequence="1"),
        synthetic.property_row(owner_sequence="2"),
    )
    records = _materialize(allocation).records
    assert len(records) == 2

    converted = [convert_denton_record(record) for record in records]
    # One owner row in, one shared record out: no account-level merge.
    assert len(converted) == 2
    assert {shared.source_account_id for shared in converted} == {"000123"}
    assert {shared.source_native_identifiers["owner_sequence"] for shared in converted} == {
        "1",
        "2",
    }


def test_conversion_populates_no_canonical_field() -> None:
    """Contract: populate no canonical market, appraised, assessed, taxable,
    tax-amount, exemption-entitlement, or capped-value field.

    The Denton *field names* are market_value and the rest, and they travel as
    source-native values keyed by the county's own name.  The prohibition is
    about the record growing a canonical attribute, so that is what is checked.
    """

    from dataclasses import fields as dataclass_fields

    from property_tax_adapters.sources.contracts import AppraisalSourceRecord
    from property_tax_adapters.sources.texas.denton import convert_denton_record

    shared = convert_denton_record(_materialize().records[0])
    declared = {field.name for field in dataclass_fields(AppraisalSourceRecord)}
    assert not declared & {
        "market_value",
        "appraised_value",
        "assessed_value",
        "taxable_value",
        "tax_amount",
        "exemption_entitlement",
        "capped_value",
    }
    assert "market_value" in shared.source_native_values


# -- 6.3 --------------------------------------------------------------------


def test_a_child_record_carries_its_measured_grain() -> None:
    """Contract: ...carrying prop_id, child_sequence, the child value as a shared entry."""

    from decimal import Decimal

    from property_tax_adapters.sources.texas.denton import DENTON_CHILD_LAYOUT

    record = _materialize_child().records[0]

    assert record.prop_id == "000123"
    assert record.child_sequence == "1"
    assert record.child_value is not None
    assert record.child_value.source_field == "child_value"
    assert record.child_value.value == Decimal("1000.00")
    assert record.provenance.child_table == "land"
    assert record.provenance.layout_fingerprint == DENTON_CHILD_LAYOUT.fingerprint
    assert record.provenance.layout_version == DENTON_CHILD_LAYOUT.layout_version
    assert record.provenance.physical_row_number == 1


def test_an_empty_child_value_is_the_only_null() -> None:
    """Contract: ...with empty text after trimming as the only null."""

    blank = synthetic.member(synthetic.child_row(prop_id="000123", value=""))
    record = _materialize_child(blank).records[0]

    assert record.child_value is None
    assert record.child_sequence == "1"


def test_children_are_not_rolled_up_to_the_parent_account() -> None:
    """Contract: Preserve each child at its measured source grain, derive no roll-up."""

    two = synthetic.member(
        synthetic.child_row(prop_id="000123", sequence="1", value="1000.00"),
        synthetic.child_row(prop_id="000123", sequence="2", value="2500.00"),
    )
    records = _materialize_child(two).records

    assert len(records) == 2
    assert {record.child_sequence for record in records} == {"1", "2"}
    # No summed total exists anywhere in the output.
    assert not any(hasattr(record, "total") for record in records)


def test_a_core_orphan_blocks_and_a_legal_orphan_warns_without_blocking() -> None:
    """Contract: keep the core-blocking and legal-warning classification intact.

    The earlier version asserted a legal orphan produced one record, which was
    this implementation's behaviour rather than the contract's.  An unresolved
    child is not an accepted row either way -- the report counts zero -- so a
    record for it would contradict the report it came with.  What differs
    between the two classes is whether the release is rejected, not whether an
    unresolved child materializes.
    """

    core = _materialize_child(synthetic.CHILD_ORPHANED)
    assert core.report.release_accepted is False
    assert _codes(core.report) == ["core_child_orphaned"]
    assert core.records == ()

    legal = _materialize_child(synthetic.CHILD_ORPHANED, child_table="arb")
    assert legal.report.release_accepted is True
    assert _codes(legal.report) == ["legal_child_orphaned"]
    assert legal.report.accepted_row_count == 0
    assert legal.records == ()


def test_a_child_record_exists_for_exactly_the_accepted_rows() -> None:
    """One traversal, so the report and the records cannot disagree."""

    mixed = synthetic.member(
        synthetic.child_row(prop_id="000123", sequence="1"),
        synthetic.child_row(prop_id="999999", sequence="2"),
    )
    result = _materialize_child(mixed, child_table="arb")

    assert result.report.release_accepted is True
    assert result.report.accepted_row_count == len(result.records) == 1
    assert result.records[0].prop_id == "000123"


@pytest.mark.parametrize(
    ("sequence", "code"),
    [
        ("", "blank_required_key"),
        ("   ", "blank_required_key"),
        ("abcd", "invalid_owner_sequence"),
        ("1.2", "invalid_owner_sequence"),
        ("-1", "invalid_owner_sequence"),
    ],
    ids=["blank", "whitespace", "letters", "decimal", "negative"],
)
def test_a_child_sequence_outside_the_d5_bounds_is_rejected(sequence: str, code: str) -> None:
    """Contract: child_sequence SHALL be required and one to four ASCII digits.

    The upper bound has no negative case here because the field is four
    characters wide: a five-digit sequence cannot be written into this layout at
    all, so the length rule is enforced by the layout before the grammar sees
    it.  The grammar still carries the rule for any layout that widens the field.
    """

    member = synthetic.member(synthetic.child_row(prop_id="000123", sequence=sequence))
    result = _materialize_child(member)

    assert _codes(result.report) == [code]
    assert result.report.release_accepted is False
    assert result.records == ()


@pytest.mark.parametrize(
    "value",
    ["-1.00", "1.000", "1,000.00", "$100", "1e5", "100.", "abc"],
    ids=["negative", "three-decimals", "grouped", "currency", "exponent", "trailing-point", "text"],
)
def test_a_child_value_outside_the_d5_grammar_is_rejected(value: str) -> None:
    """Contract: a nonblank child_value SHALL match the property monetary grammar."""

    member = synthetic.member(synthetic.child_row(prop_id="000123", value=value))
    result = _materialize_child(member)

    assert _codes(result.report) == ["invalid_monetary_value"]
    assert result.report.release_accepted is False
    assert result.records == ()


def test_a_child_value_at_the_d5_bounds_is_accepted() -> None:
    """Contract: ...and fall from zero through 10**26 - 1 inclusive."""

    from decimal import Decimal

    for text in ("0", "0.00", "1000.00"):
        member = synthetic.member(synthetic.child_row(prop_id="000123", value=text.rjust(15)))
        result = _materialize_child(member)
        assert result.report.release_accepted is True, text
        assert result.records[0].child_value is not None
        assert result.records[0].child_value.value == Decimal(text)


def test_whitespace_only_child_value_is_absence_not_a_malformed_amount() -> None:
    """Contract: empty text after trimming SHALL be the only null."""

    member = synthetic.member(synthetic.child_row(prop_id="000123", value="   "))
    result = _materialize_child(member)

    assert result.report.release_accepted is True
    assert result.records[0].child_value is None
