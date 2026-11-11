"""Task-local falsification for the processing-run lifecycle port."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from property_tax_application.bronze import ManifestRef
from property_tax_application.runs import (
    ProcessingRunHeldError,
    ProcessingRunRef,
    ProcessingRunRepository,
    ProcessingRunStart,
    ReleaseDisposition,
    ReleaseProcessingOutcome,
    UnknownProcessingRunError,
)
from property_tax_domain import Jurisdiction, ReleaseIdentity, ReleaseKind


@dataclass
class RunState:
    release: ReleaseIdentity
    manifest: ManifestRef
    finished: bool = False


class InMemoryProcessingRunRepository:
    """A serial contract fake, not a claim about persistence concurrency."""

    def __init__(self) -> None:
        self._runs: dict[ProcessingRunRef, RunState] = {}
        self._held: set[ProcessingRunRef] = set()

    def start(self, release: ReleaseIdentity, manifest: ManifestRef) -> ProcessingRunStart:
        unfinished = next(
            (
                reference
                for reference, state in reversed(tuple(self._runs.items()))
                if state.release == release and not state.finished
            ),
            None,
        )
        if unfinished is not None:
            if unfinished in self._held:
                raise ProcessingRunHeldError(release.rendered)
            self._held.add(unfinished)
            return ProcessingRunStart(reference=unfinished, resumed=True)

        reference = ProcessingRunRef(len(self._runs) + 1)
        self._runs[reference] = RunState(release=release, manifest=manifest)
        self._held.add(reference)
        return ProcessingRunStart(reference=reference, resumed=False)

    def finish(self, reference: ProcessingRunRef, outcome: ReleaseProcessingOutcome) -> None:
        state = self._runs.get(reference)
        if state is None:
            raise UnknownProcessingRunError(reference)
        state.finished = True
        self._held.discard(reference)

    def abandon(self, reference: ProcessingRunRef) -> None:
        if reference not in self._runs:
            raise UnknownProcessingRunError(reference)
        self._held.discard(reference)

    def manifest_for(self, reference: ProcessingRunRef) -> ManifestRef:
        return self._runs[reference].manifest


def release() -> ReleaseIdentity:
    return ReleaseIdentity(
        jurisdiction=Jurisdiction(state_code="tx", county_slug="dallas", county_fips="48113"),
        tax_year=2026,
        release_kind=ReleaseKind.CERTIFIED,
        release_identifier="release-1",
    )


def accepted_outcome() -> ReleaseProcessingOutcome:
    return ReleaseProcessingOutcome(disposition=ReleaseDisposition.ACCEPTED)


def test_a_fresh_start_records_and_returns_a_new_run() -> None:
    repository = InMemoryProcessingRunRepository()
    manifest = ManifestRef(10)

    started = repository.start(release(), manifest)

    assert started.resumed is False
    assert repository.manifest_for(started.reference) == manifest
    assert isinstance(repository, ProcessingRunRepository)


def test_a_live_holder_is_refused_by_name() -> None:
    repository = InMemoryProcessingRunRepository()
    repository.start(release(), ManifestRef(10))

    with pytest.raises(ProcessingRunHeldError):
        repository.start(release(), ManifestRef(10))


def test_an_abandoned_run_resumes_with_the_original_reference() -> None:
    repository = InMemoryProcessingRunRepository()
    original = repository.start(release(), ManifestRef(10))
    repository.abandon(original.reference)

    resumed = repository.start(release(), ManifestRef(10))

    assert resumed.resumed is True
    assert resumed.reference == original.reference


def test_a_finished_run_allows_a_new_run() -> None:
    repository = InMemoryProcessingRunRepository()
    first = repository.start(release(), ManifestRef(10))
    repository.finish(first.reference, accepted_outcome())

    second = repository.start(release(), ManifestRef(10))

    assert second.resumed is False
    assert second.reference != first.reference


def test_two_conceptual_retries_cannot_both_hold_an_abandoned_run() -> None:
    repository = InMemoryProcessingRunRepository()
    original = repository.start(release(), ManifestRef(10))
    repository.abandon(original.reference)

    winner = repository.start(release(), ManifestRef(10))
    with pytest.raises(ProcessingRunHeldError):
        repository.start(release(), ManifestRef(10))

    assert winner.reference == original.reference
    assert winner.resumed is True


def test_finishing_an_unknown_reference_refuses_instead_of_creating_a_run() -> None:
    repository = InMemoryProcessingRunRepository()

    with pytest.raises(UnknownProcessingRunError):
        repository.finish(ProcessingRunRef(999), accepted_outcome())

    fresh = repository.start(release(), ManifestRef(10))
    assert fresh.reference == ProcessingRunRef(1)
