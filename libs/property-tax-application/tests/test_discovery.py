"""Task-local falsification for bounded discovery and identity promotion."""

from __future__ import annotations

import inspect
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest
from property_tax_application.acquisition import MAX_LOCATOR_CHARS, ResponseMetadata
from property_tax_application.discovery import (
    IncompleteReleaseIdentity,
    LogicalReleaseEvidence,
    PageEvidence,
    ReleaseDiscovery,
    SourceCandidate,
    UnchangedRelease,
    promote,
)
from property_tax_application.runs import MAX_FIELD_CHARS
from property_tax_domain import ArtifactIdentity, Jurisdiction, ReleaseIdentity, ReleaseKind

OBSERVED_AT = datetime(2026, 8, 19, 12, 30, tzinfo=UTC)
PAGE_URL = "https://example.gov/releases"
SOURCE_URL = "https://example.gov/releases/current.zip"


def jurisdiction() -> Jurisdiction:
    return Jurisdiction(state_code="tx", county_slug="dallas", county_fips="48113")


def page(**changes: object) -> PageEvidence:
    values: dict[str, object] = {
        "observed_at": OBSERVED_AT,
        "page_url": PAGE_URL,
        "rendered": False,
        "link_label": "Certified data",
    }
    values.update(changes)
    return PageEvidence(**values)  # type: ignore[arg-type]


def logical(**changes: object) -> LogicalReleaseEvidence:
    values: dict[str, object] = {
        "jurisdiction": jurisdiction(),
        "tax_year": 2026,
        "release_kind": ReleaseKind.CERTIFIED,
        "release_identifier": "certified-2026",
        "source_as_of": None,
    }
    values.update(changes)
    return LogicalReleaseEvidence(**values)  # type: ignore[arg-type]


def candidate(**changes: object) -> SourceCandidate:
    values: dict[str, object] = {
        "jurisdiction": jurisdiction(),
        "source_locator": SOURCE_URL,
        "remote_metadata": ResponseMetadata(
            status=200,
            headers={"content-type": "application/zip", "etag": '"one"'},
        ),
        "source_as_of": None,
        "page_evidence": page(),
        "logical_releases": (),
    }
    values.update(changes)
    return SourceCandidate(**values)  # type: ignore[arg-type]


def test_page_evidence_requires_an_aware_observation_instant() -> None:
    assert page().observed_at == OBSERVED_AT

    with pytest.raises(ValueError, match="timezone-aware"):
        page(observed_at=OBSERVED_AT.replace(tzinfo=None))


@pytest.mark.parametrize(
    ("field_name", "maximum", "prefix"),
    [
        ("page_url", MAX_LOCATOR_CHARS, "https://example.gov/"),
        ("section_heading", MAX_FIELD_CHARS, ""),
        ("link_label", MAX_FIELD_CHARS, ""),
        ("directory_path", MAX_FIELD_CHARS, ""),
        ("published_label", MAX_FIELD_CHARS, ""),
    ],
)
def test_each_page_text_field_accepts_its_exact_maximum(
    field_name: str,
    maximum: int,
    prefix: str,
) -> None:
    value = prefix + "a" * (maximum - len(prefix))

    evidence = page(**{field_name: value})

    assert getattr(evidence, field_name) == value


@pytest.mark.parametrize(
    ("field_name", "maximum", "prefix"),
    [
        ("page_url", MAX_LOCATOR_CHARS, "https://example.gov/"),
        ("section_heading", MAX_FIELD_CHARS, ""),
        ("link_label", MAX_FIELD_CHARS, ""),
        ("directory_path", MAX_FIELD_CHARS, ""),
        ("published_label", MAX_FIELD_CHARS, ""),
    ],
)
def test_each_page_text_field_refuses_maximum_plus_one_without_truncating(
    field_name: str,
    maximum: int,
    prefix: str,
) -> None:
    value = prefix + "a" * (maximum + 1 - len(prefix))

    with pytest.raises(ValueError, match="at most"):
        page(**{field_name: value})


def test_page_evidence_with_no_locating_fact_is_refused() -> None:
    with pytest.raises(ValueError, match="locating fact"):
        PageEvidence(observed_at=OBSERVED_AT, page_url=PAGE_URL, rendered=False)


def test_directory_evidence_leaves_unrelated_facts_absent() -> None:
    evidence = PageEvidence(
        observed_at=OBSERVED_AT,
        page_url=PAGE_URL,
        rendered=False,
        directory_path="2026/CertifiedDataAllProperty/",
    )

    assert evidence.directory_path == "2026/CertifiedDataAllProperty/"
    assert evidence.section_heading is None
    assert evidence.link_label is None
    assert evidence.published_label is None


def test_rendered_is_explicit_and_published_label_stays_text() -> None:
    fetched = page(rendered=False, published_label="August 19, 2026")
    rendered = page(rendered=True, published_label="August 19, 2026")

    assert fetched != rendered
    assert fetched.rendered is False
    assert rendered.rendered is True
    assert rendered.published_label == "August 19, 2026"
    assert isinstance(rendered.published_label, str)


def test_page_evidence_has_no_arbitrary_content_or_credential_field() -> None:
    assert tuple(field.name for field in fields(PageEvidence)) == (
        "observed_at",
        "page_url",
        "rendered",
        "section_heading",
        "link_label",
        "directory_path",
        "published_label",
    )
    with pytest.raises(TypeError):
        PageEvidence(  # type: ignore[call-arg]
            observed_at=OBSERVED_AT,
            page_url=PAGE_URL,
            rendered=False,
            link_label="release",
            html="<script>secret()</script>",
        )


class FakeDiscovery:
    def __init__(self, result: SourceCandidate | UnchangedRelease) -> None:
        self.result = result
        self.download_calls = 0

    def discover(self, requested: Jurisdiction) -> SourceCandidate | UnchangedRelease:
        assert requested == jurisdiction()
        return self.result


def test_discovery_observes_one_jurisdiction_and_has_no_cohort_operation() -> None:
    parameters = tuple(inspect.signature(ReleaseDiscovery.discover).parameters)
    discovery = FakeDiscovery(candidate())

    assert parameters == ("self", "jurisdiction")
    assert not hasattr(discovery, "discover_many")
    assert isinstance(discovery, ReleaseDiscovery)
    assert discovery.discover(jurisdiction()).jurisdiction == jurisdiction()


def test_candidate_and_unchanged_are_distinct_and_unchanged_needs_no_download() -> None:
    no_change = UnchangedRelease(
        jurisdiction=jurisdiction(),
        source_locator=SOURCE_URL,
        remote_metadata=ResponseMetadata(status=304),
        source_as_of=None,
        page_evidence=page(),
        artifact=ArtifactIdentity("a" * 64),
    )
    discovery = FakeDiscovery(no_change)

    result = discovery.discover(jurisdiction())

    assert type(result) is UnchangedRelease
    assert result.artifact == ArtifactIdentity("a" * 64)
    assert discovery.download_calls == 0


def test_a_candidate_may_carry_zero_or_several_logical_releases() -> None:
    empty = candidate()
    two = candidate(
        logical_releases=(
            logical(tax_year=2025, release_identifier="current-2025"),
            logical(tax_year=2024, release_identifier="certified-2024"),
        )
    )

    assert empty.logical_releases == ()
    assert len(two.logical_releases) == 2


def test_candidate_fields_are_bounded_and_carry_no_source_content() -> None:
    assert tuple(field.name for field in fields(SourceCandidate)) == (
        "jurisdiction",
        "source_locator",
        "remote_metadata",
        "source_as_of",
        "page_evidence",
        "logical_releases",
    )
    with pytest.raises(ValueError, match="sanitized"):
        candidate(source_locator="https://example.gov/release.zip?token=SECRET")


def test_partial_evidence_preserves_only_established_facts() -> None:
    evidence = LogicalReleaseEvidence(
        jurisdiction=jurisdiction(),
        tax_year=2026,
        release_kind=ReleaseKind.CERTIFIED,
    )

    assert evidence.release_identifier is None
    assert evidence.source_as_of is None


def test_incomplete_promotion_names_every_missing_component_without_synthesis() -> None:
    evidence = LogicalReleaseEvidence(
        jurisdiction=jurisdiction(),
        release_kind=ReleaseKind.CERTIFIED,
    )

    with pytest.raises(IncompleteReleaseIdentity) as caught:
        promote(evidence)

    assert caught.value.missing_components == ("tax_year", "release_identifier")
    assert "release_identifier" in str(caught.value)


def test_complete_page_or_parser_evidence_uses_the_same_promotion() -> None:
    page_established = logical()
    parser_established = replace(logical(), release_identifier="parsed-certified-2026")

    first = promote(page_established)
    second = promote(parser_established)

    assert first == ReleaseIdentity(
        jurisdiction=jurisdiction(),
        tax_year=2026,
        release_kind=ReleaseKind.CERTIFIED,
        release_identifier="certified-2026",
    )
    assert second.release_identifier == "parsed-certified-2026"


def test_releases_from_one_artifact_keep_distinct_content_instants() -> None:
    first_instant = OBSERVED_AT - timedelta(days=1)
    second_instant = OBSERVED_AT - timedelta(days=30)
    observed = candidate(
        logical_releases=(
            logical(release_identifier="current", source_as_of=first_instant),
            logical(release_identifier="certified", source_as_of=second_instant),
        )
    )

    assert tuple(item.source_as_of for item in observed.logical_releases) == (
        first_instant,
        second_instant,
    )


def test_page_instant_populates_each_release_and_content_overrides_only_one() -> None:
    page_instant = OBSERVED_AT - timedelta(days=2)
    content_instant = OBSERVED_AT - timedelta(days=1)
    observed = candidate(
        source_as_of=page_instant,
        logical_releases=(
            logical(release_identifier="current", source_as_of=content_instant),
            logical(release_identifier="certified"),
        ),
    )

    assert observed.logical_releases[0].source_as_of == content_instant
    assert observed.logical_releases[1].source_as_of == page_instant


def test_absent_source_as_of_remains_absent_and_never_uses_acquisition_time() -> None:
    observed = candidate(logical_releases=(logical(source_as_of=None),))

    assert observed.source_as_of is None
    assert observed.logical_releases[0].source_as_of is None
    assert "acquired_at" not in {field.name for field in fields(SourceCandidate)}
