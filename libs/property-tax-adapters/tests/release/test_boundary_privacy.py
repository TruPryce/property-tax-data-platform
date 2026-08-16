"""Nothing a caller learns may carry a row, a value, a path, or an exception.

Each collaborator is driven with an identifiable secret in its message, so a
leak fails a test rather than being argued about.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass

import pytest
from property_tax_adapters.release import (
    MAX_CARRIER_NOTICES,
    NoticeSet,
    PreparedRelease,
    ReleaseDiagnostic,
    ReleaseDiagnosticCode,
    ReleaseNotice,
    ReleaseProgressEvent,
    SourceRowEnvelope,
    process_release,
)

from release.support import (
    Reader,
    RecordingGuard,
    RecordingProgress,
    RecordingStage,
    envelopes,
    notice_set,
    prepared,
)

SECRETS = (
    "SECRET-ENTER",
    "SECRET-PREPARE",
    "SECRET-EXIT",
    "SECRET-ITERATION",
    "SECRET-STAGE-ENTER",
    "SECRET-CALLBACK",
    "SECRET-GUARD",
)


@pytest.mark.parametrize(
    "build",
    [
        lambda: process_release(reader=Reader([], fail_on_enter=True), stage=RecordingStage()),
        lambda: process_release(reader=Reader([], fail_on_prepare=True), stage=RecordingStage()),
        lambda: process_release(
            reader=Reader(envelopes(2), fail_on_exit=True), stage=RecordingStage()
        ),
        lambda: process_release(
            reader=Reader(envelopes(2), fail_on_iteration=True), stage=RecordingStage()
        ),
        lambda: process_release(
            reader=Reader(envelopes(2)), stage=RecordingStage(fail_on_enter=True)
        ),
        lambda: process_release(
            reader=Reader(envelopes(2)),
            stage=RecordingStage(),
            progress=RecordingProgress(raise_on_final=True),
        ),
        lambda: process_release(
            reader=Reader(envelopes(2)),
            stage=RecordingStage(),
            guard=RecordingGuard(raise_on_call=1),
        ),
    ],
    ids=["enter", "prepare", "exit", "iteration", "stage-enter", "callback", "guard"],
)
def test_no_exception_text_reaches_the_outcome(build) -> None:  # noqa: ANN001
    rendered = repr(build())

    for secret in SECRETS:
        assert secret not in rendered, secret


@pytest.mark.parametrize(
    ("cls", "permitted"),
    [
        (
            ReleaseDiagnostic,
            {"code", "field_name", "physical_row_number", "layout_fingerprint"},
        ),
        (ReleaseNotice, {"code", "field_name", "physical_row_number"}),
        (NoticeSet, {"retained", "total", "truncated"}),
        (
            ReleaseProgressEvent,
            {
                "jurisdiction_code",
                "release_identifier",
                "source_member_name",
                "parser_contract_version",
                "layout_fingerprint",
                "physical_rows_processed",
                "staged_record_count",
                "sequence_number",
                "final",
                "progress_contract_version",
            },
        ),
    ],
    ids=["diagnostic", "notice", "notice-set", "progress-event"],
)
def test_each_type_declares_exactly_its_permitted_fields(cls: type, permitted: set[str]) -> None:
    assert is_dataclass(cls)
    declared = {entry.name for entry in fields(cls)}
    assert declared == permitted
    for entry in fields(cls):
        assert "Any" not in str(entry.type), entry.name
        assert not any(
            token in entry.name.lower()
            for token in ("payload", "extras", "metadata", "owner", "address", "situs")
        ), entry.name


@pytest.mark.parametrize("cls", [ReleaseDiagnostic, ReleaseNotice, NoticeSet, ReleaseProgressEvent])
def test_each_type_refuses_assignment_after_construction(cls: type) -> None:
    instances = {
        ReleaseDiagnostic: lambda: ReleaseDiagnostic(code=ReleaseDiagnosticCode.RECORD_REJECTED),
        ReleaseNotice: lambda: ReleaseNotice(code="extra_columns_present"),
        NoticeSet: NoticeSet,
        ReleaseProgressEvent: lambda: ReleaseProgressEvent(
            jurisdiction_code="tx-dallas",
            release_identifier="rel-1",
            source_member_name="m.txt",
            parser_contract_version=1,
            layout_fingerprint="f" * 64,
            physical_rows_processed=0,
            staged_record_count=0,
            sequence_number=0,
            final=True,
        ),
    }
    instance = instances[cls]()
    with pytest.raises((AttributeError, TypeError)):
        instance.__setattr__(fields(cls)[0].name, "mutated")


def test_a_notice_set_cannot_be_reached_into() -> None:
    """The retained tuple is immutable, and the set holds no source reference."""

    observations = [ReleaseNotice(code="extra_columns_present") for _ in range(3)]
    built = NoticeSet.from_observations(iter(observations))

    assert isinstance(built.retained, tuple)
    with pytest.raises(AttributeError):
        built.retained.append(ReleaseNotice(code="another"))  # type: ignore[attr-defined]
    # No attribute anywhere on the set refers to the iterable it consumed.
    assert not any(
        getattr(built, name) is observations for name in ("retained", "total", "truncated")
    )


def test_a_release_identifier_shaped_like_a_path_is_refused() -> None:
    for hostile in ("/var/tmp/dallas-2026", "../../etc/passwd", "C:\\releases\\x"):
        with pytest.raises(ValueError, match="release_identifier"):
            prepared(release_identifier=hostile)


def test_overflowing_notices_are_truncated_and_never_fatal() -> None:
    """Dallas emits one per unknown header, with no limit in its contract."""

    overflowing = notice_set(150)
    assert len(overflowing.retained) == MAX_CARRIER_NOTICES
    assert overflowing.total == 150
    assert overflowing.truncated is True

    reader = Reader([], release=prepared(notices=overflowing))
    outcome = process_release(reader=reader, stage=RecordingStage())

    assert outcome.disposition.value == "accepted", "a warning rejected the release"
    assert outcome.total_notice_count == 150
    assert outcome.notices_truncated is True
    assert outcome.total_diagnostic_count == 0


def test_notice_retention_is_incremental_not_trim_after_the_fact() -> None:
    """A carrier that materialized first would already hold what the bound prevents."""

    produced = 0

    def observations():
        nonlocal produced
        for _ in range(10_000):
            produced += 1
            yield ReleaseNotice(code="extra_columns_present")

    built = NoticeSet.from_observations(observations())
    assert produced == 10_000, "the generator was not consumed to exhaustion"
    assert built.total == 10_000
    assert len(built.retained) == MAX_CARRIER_NOTICES


def test_a_row_notice_may_not_claim_another_row() -> None:
    with pytest.raises(ValueError, match="did not come from"):
        SourceRowEnvelope(physical_row_number=7, notices=notice_set(1, row=6))


def test_a_notice_code_cannot_carry_free_text() -> None:
    for hostile in ("Extra Columns!", "a" * 65, "", "1leading_digit"):
        with pytest.raises(ValueError, match="code must be"):
            ReleaseNotice(code=hostile)


def test_prepared_release_notices_default_to_an_empty_set() -> None:
    assert prepared().notices == NoticeSet()
    assert isinstance(PreparedRelease.__dataclass_fields__["notices"].default_factory(), NoticeSet)
