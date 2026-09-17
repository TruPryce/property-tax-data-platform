"""Attacks on the processing-run values, one per case in the falsification matrix.

These values are enforced twice — once here and once by a database constraint —
so what the suite proves is that the two agree. A value this boundary accepts has
to be a value that can be recorded, and the seal is the sharpest example: an
outcome that satisfies every field-level rule and fails the seal would abort the
canonical transaction at COMMIT, after the records were written.

This suite may import both packages, where the application may not import
either: proving the disposition mapping is total means enumerating both
vocabularies rather than asserting the sentence.
"""

from __future__ import annotations

import pytest
from property_tax_adapters.release import outcome as adapters
from property_tax_application.runs import (
    BOUNDARY_CONTRACT_VERSION,
    DIAGNOSTIC_CODES,
    DIAGNOSTIC_RETENTION_LIMIT,
    ProcessingRunRef,
    ReleaseDiagnosticRecord,
    ReleaseDisposition,
    ReleaseNoticeRecord,
    ReleaseProcessingOutcome,
)

FINGERPRINT = "layout-a"


def diagnostic(**kwargs: object) -> ReleaseDiagnosticRecord:
    return ReleaseDiagnosticRecord(kwargs.pop("code", "record_rejected"), **kwargs)  # type: ignore[arg-type]


def rejected(**kwargs: object) -> ReleaseProcessingOutcome:
    """A minimally valid rejected outcome, which every seal attack perturbs."""

    fields: dict[str, object] = {
        "diagnostics": (diagnostic(),),
        "total_diagnostic_count": 1,
        "rejected_row_count": 1,
    }
    fields.update(kwargs)
    return ReleaseProcessingOutcome(ReleaseDisposition.REJECTED, **fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# ProcessingRunRef: an opaque locator a caller never invents
# --------------------------------------------------------------------------


def test_the_reference_compares_by_equality_and_hashes() -> None:
    first, same, other = ProcessingRunRef(7), ProcessingRunRef(7), ProcessingRunRef(8)

    assert first == same and first != other
    assert hash(first) == hash(same)
    assert len({first, same, other}) == 2
    assert {first: "run"}[same] == "run"


def test_every_ordering_comparison_raises_rather_than_being_absent() -> None:
    first, second = ProcessingRunRef(7), ProcessingRunRef(8)

    for compare in (
        lambda: first < second,
        lambda: first <= second,
        lambda: first > second,
        lambda: first >= second,
    ):
        with pytest.raises(TypeError, match="no ordering"):
            compare()

    with pytest.raises(TypeError):
        sorted([second, first])


def test_the_reference_refuses_a_mutable_or_unhashable_value() -> None:
    for rejected_value in ([], {}, set(), ["run-1"]):
        with pytest.raises(ValueError, match="str, an int, or a tuple"):
            ProcessingRunRef(rejected_value)

    with pytest.raises(ValueError, match="must not be None"):
        ProcessingRunRef(None)


def test_the_reference_refuses_a_hashable_but_mutable_value() -> None:
    """The regression: `hash()` succeeding is one observation, not immutability.

    An object whose `__hash__` reads a mutable attribute passes the probe, then
    moves — and the mapping entry filed under it becomes unreachable with
    nothing raising. Constraining the payload by type is what rules that out.
    """

    class Sneaky:
        def __init__(self, key: int) -> None:
            self.key = key

        def __hash__(self) -> int:
            return hash(self.key)

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Sneaky) and other.key == self.key

    payload = Sneaky(1)
    assert hash(payload) == hash(Sneaky(1)), "it passes the probe the old guard used"

    with pytest.raises(ValueError, match="a hashable object is not an immutable one"):
        ProcessingRunRef(payload)


def test_the_reference_admits_what_a_database_hands_back() -> None:
    for value in (7, "run-1", (2026, "run-1")):
        assert ProcessingRunRef(value).value == value

    # `True == 1` in Python, so a bool would otherwise be a reference to run 1.
    with pytest.raises(ValueError, match="str, an int, or a tuple"):
        ProcessingRunRef(True)
    with pytest.raises(ValueError, match="str, an int, or a tuple"):
        ProcessingRunRef((1, []))


def test_the_reference_is_frozen() -> None:
    reference = ProcessingRunRef(7)

    with pytest.raises(AttributeError):
        reference.value = 8  # type: ignore[misc]


def test_a_tuple_of_mutables_is_refused_though_a_tuple_is_not() -> None:
    """A tuple is admitted by what it holds, checked element by element."""

    assert ProcessingRunRef(("run", 1)).value == ("run", 1)
    with pytest.raises(ValueError, match="element must be a str, an int"):
        ProcessingRunRef(([],))


# --------------------------------------------------------------------------
# The disposition, and the total mapping
# --------------------------------------------------------------------------


def test_the_disposition_vocabulary_is_closed() -> None:
    assert [member.value for member in ReleaseDisposition] == ["accepted", "rejected"]

    with pytest.raises(ValueError):
        ReleaseDisposition("partially_accepted")


def test_the_mapping_to_the_adapters_vocabulary_is_total_in_both_directions() -> None:
    ours = {member.value for member in ReleaseDisposition}
    theirs = {member.value for member in adapters.ReleaseDisposition}

    assert ours == theirs, "neither side may carry a disposition the other cannot express"
    for member in ReleaseDisposition:
        assert adapters.ReleaseDisposition(member.value).value == member.value
    for member in adapters.ReleaseDisposition:
        assert ReleaseDisposition(member.value).value == member.value


def test_an_outcome_refuses_a_disposition_outside_the_vocabulary() -> None:
    with pytest.raises(ValueError, match="disposition"):
        ReleaseProcessingOutcome("accepted")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Two codes, two rules, deliberately not one rule
# --------------------------------------------------------------------------


def test_the_diagnostic_vocabulary_is_exactly_the_accepted_one() -> None:
    assert DIAGNOSTIC_CODES == {member.value for member in adapters.ReleaseDiagnosticCode}


def test_a_diagnostic_code_outside_the_closed_vocabulary_is_refused() -> None:
    for code in ("unknown_failure", "RECORD_REJECTED", "", "record rejected"):
        with pytest.raises(ValueError, match="closed diagnostic vocabulary"):
            ReleaseDiagnosticRecord(code)


def test_a_notice_code_outside_that_vocabulary_is_accepted_when_well_formed() -> None:
    """The notice vocabulary is open where the diagnostic vocabulary is closed.

    Checking a notice against `DIAGNOSTIC_CODES` would refuse codes the database
    accepts, which is why the two rules are deliberately different.
    """

    notice = ReleaseNoticeRecord("collin_layout_drifted")

    assert notice.code not in DIAGNOSTIC_CODES


def test_a_malformed_notice_code_is_refused() -> None:
    for code in ("Collin", "1_bad", "with space", "a" * 65, "", "trailing-"):
        with pytest.raises(ValueError, match="a-z"):
            ReleaseNoticeRecord(code)


def test_the_carriers_hold_no_source_value_and_bound_what_they_hold() -> None:
    assert set(ReleaseDiagnosticRecord.__slots__) == {
        "code",
        "field_name",
        "physical_row_number",
        "layout_fingerprint",
    }
    assert set(ReleaseNoticeRecord.__slots__) == {
        "code",
        "field_name",
        "physical_row_number",
    }
    with pytest.raises(ValueError, match="at most"):
        diagnostic(field_name="x" * 257)
    with pytest.raises(ValueError, match="one-based"):
        diagnostic(physical_row_number=0)


# --------------------------------------------------------------------------
# The evidence seal, refused in the value rather than at COMMIT
# --------------------------------------------------------------------------


def test_the_retention_limit_matches_the_one_the_database_enforces() -> None:
    assert DIAGNOSTIC_RETENTION_LIMIT == adapters.DIAGNOSTIC_RETENTION_LIMIT


def test_an_outcome_declaring_more_evidence_than_it_retains_is_refused() -> None:
    """The case that would otherwise abort the canonical transaction at COMMIT."""

    with pytest.raises(ValueError, match="entries"):
        ReleaseProcessingOutcome(
            ReleaseDisposition.REJECTED, diagnostics=(), total_diagnostic_count=1
        )


def test_an_outcome_above_the_bound_retains_exactly_the_bound() -> None:
    entries = tuple(diagnostic() for _ in range(DIAGNOSTIC_RETENTION_LIMIT))
    total = DIAGNOSTIC_RETENTION_LIMIT + 5

    accepted_outcome = rejected(
        diagnostics=entries, total_diagnostic_count=total, diagnostics_truncated=True
    )
    assert len(accepted_outcome.diagnostics) == DIAGNOSTIC_RETENTION_LIMIT

    with pytest.raises(ValueError, match="entries"):
        rejected(
            diagnostics=entries[:-1],
            total_diagnostic_count=total,
            diagnostics_truncated=True,
        )


def test_a_truncation_flag_that_disagrees_with_its_total_is_refused() -> None:
    with pytest.raises(ValueError, match="exactly when"):
        rejected(diagnostics_truncated=True)

    entries = tuple(diagnostic() for _ in range(DIAGNOSTIC_RETENTION_LIMIT))
    with pytest.raises(ValueError, match="exactly when"):
        rejected(
            diagnostics=entries,
            total_diagnostic_count=DIAGNOSTIC_RETENTION_LIMIT + 1,
            diagnostics_truncated=False,
        )


def test_a_retained_diagnostic_naming_another_layout_is_refused() -> None:
    with pytest.raises(ValueError, match="one release has one layout"):
        rejected(diagnostics=(diagnostic(layout_fingerprint=FINGERPRINT),))

    with pytest.raises(ValueError, match="one release has one layout"):
        rejected(
            diagnostics=(diagnostic(),),
            parser_contract_version=1,
            layout_fingerprint=FINGERPRINT,
        )


def test_the_seal_covers_notices_on_the_same_terms() -> None:
    with pytest.raises(ValueError, match="entries"):
        rejected(notices=(), total_notice_count=1)

    accepted_with_notices = ReleaseProcessingOutcome(
        ReleaseDisposition.ACCEPTED,
        notices=(ReleaseNoticeRecord("layout_drifted"),),
        total_notice_count=1,
    )
    assert accepted_with_notices.accepted is True


def test_a_tuple_of_the_right_length_holding_the_wrong_type_is_refused() -> None:
    """Counts alone would pass; the element type is what keeps free text out."""

    with pytest.raises(ValueError, match="tuple of ReleaseDiagnosticRecord"):
        rejected(diagnostics=("record_rejected",))


# --------------------------------------------------------------------------
# The paired invariants, and the mirrored constant
# --------------------------------------------------------------------------


def test_one_prepared_field_without_the_other_is_refused() -> None:
    for fields in ({"parser_contract_version": 1}, {"layout_fingerprint": FINGERPRINT}):
        with pytest.raises(ValueError, match="together or not at all"):
            rejected(**fields)


def test_acceptance_and_diagnostics_are_not_independent() -> None:
    with pytest.raises(ValueError, match="accepted exactly when"):
        ReleaseProcessingOutcome(
            ReleaseDisposition.ACCEPTED,
            diagnostics=(diagnostic(),),
            total_diagnostic_count=1,
        )
    with pytest.raises(ValueError, match="accepted exactly when"):
        ReleaseProcessingOutcome(ReleaseDisposition.REJECTED)


def test_a_rejected_release_commits_no_record_and_an_accepted_one_commits_what_it_staged() -> None:
    with pytest.raises(ValueError, match="rejected release commits no record"):
        rejected(committed_record_count=1)
    with pytest.raises(ValueError, match="commits what it staged"):
        ReleaseProcessingOutcome(
            ReleaseDisposition.ACCEPTED, staged_record_count=2, committed_record_count=1
        )
    with pytest.raises(ValueError, match="rejected no row"):
        ReleaseProcessingOutcome(ReleaseDisposition.ACCEPTED, rejected_row_count=1)


def test_the_boundary_contract_version_is_the_constant_and_mirrors_the_adapters() -> None:
    assert BOUNDARY_CONTRACT_VERSION == adapters.BOUNDARY_CONTRACT_VERSION

    with pytest.raises(ValueError, match="must be the int"):
        rejected(boundary_contract_version=BOUNDARY_CONTRACT_VERSION + 1)
    # `True == 1` in Python, so equality alone would admit a bool.
    with pytest.raises(ValueError, match="must be the int"):
        rejected(boundary_contract_version=True)


def test_counts_are_non_negative_ints_and_not_bools() -> None:
    for name in (
        "physical_rows_processed",
        "staged_record_count",
        "rejected_row_count",
    ):
        with pytest.raises(ValueError, match="non-negative int"):
            rejected(**{name: -1})
        with pytest.raises(ValueError, match="non-negative int"):
            rejected(**{name: True})


def test_the_outcome_is_frozen_and_reports_its_own_acceptance() -> None:
    outcome = ReleaseProcessingOutcome(ReleaseDisposition.ACCEPTED)

    assert outcome.accepted is True
    assert rejected().accepted is False
    with pytest.raises(AttributeError):
        outcome.disposition = ReleaseDisposition.REJECTED  # type: ignore[misc]
