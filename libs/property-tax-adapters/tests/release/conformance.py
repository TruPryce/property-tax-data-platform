"""A reusable suite any stage or reader can be driven through.

The stage half asserts the atomicity guarantee.  The reader half detects
**input-proportional** accumulation, and does it structurally rather than by
watching memory: the peak-RSS target belongs to a separate change, and read-ahead
is observable without it.

The lead is pulls minus **envelopes consumed**, never records written.  Records
are the wrong denominator twice over — a row may produce zero or several, and the
processor stops writing at the first rejected row while it keeps reading, so a
conforming reader on a rejected release would show a lead climbing against a
write count that never moves again.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from property_tax_adapters.release import (
    DuplicateRecordKey,
    PreparedReader,
    ReleaseStage,
)
from property_tax_adapters.sources.contracts import AppraisalSourceRecord

#: The approved lead. A reader may buffer a fixed block; what it may not do is
#: accumulate in proportion to the release.
APPROVED_MAX_LEAD = 64

#: Two lengths far enough above the constant that a materializing reader reports
#: visibly different maxima.
SHORT_FIXTURE = 1_000
LONG_FIXTURE = 8_000


@dataclass(slots=True)
class GuardedPullSource:
    """Records every pull, so the lead can be computed against consumption."""

    rows: int
    pulls: int = 0

    def __iter__(self) -> Iterator[int]:
        for number in range(1, self.rows + 1):
            self.pulls += 1
            yield number


class LeadObserver:
    """Tracks the maximum lead over one drive of a reader."""

    __slots__ = ("consumed", "max_lead", "source")

    def __init__(self, source: GuardedPullSource) -> None:
        self.source = source
        self.consumed = 0
        self.max_lead = 0

    def consume(self) -> None:
        self.consumed += 1
        self.max_lead = max(self.max_lead, self.source.pulls - self.consumed)


ReaderFactory = Callable[[GuardedPullSource], PreparedReader]


def max_lead_for(factory: ReaderFactory, rows: int) -> int:
    """Drive a reader over `rows` and return the maximum observed lead."""

    source = GuardedPullSource(rows=rows)
    observer = LeadObserver(source)
    reader = factory(source)
    with reader as opened:
        opened.prepare()
        for _ in opened:
            observer.consume()
    return observer.max_lead


def assert_reader_is_bounded(factory: ReaderFactory) -> None:
    """A conforming reader's maximum lead is bounded and does not scale.

    Run at two materially different lengths: an implementation that materializes
    its member reports a maximum near each length and cannot produce the same
    number twice.
    """

    short = max_lead_for(factory, SHORT_FIXTURE)
    long = max_lead_for(factory, LONG_FIXTURE)
    assert short <= APPROVED_MAX_LEAD, f"lead {short} exceeds {APPROVED_MAX_LEAD}"
    assert long <= APPROVED_MAX_LEAD, f"lead {long} exceeds {APPROVED_MAX_LEAD}"
    assert short == long, (
        f"lead grew with release size: {short} at {SHORT_FIXTURE}, {long} at {LONG_FIXTURE}"
    )


StageFactory = Callable[[], ReleaseStage]


def assert_stage_is_atomic(
    factory: StageFactory,
    visible: Callable[[ReleaseStage], Sequence[AppraisalSourceRecord]],
    records: Sequence[AppraisalSourceRecord],
) -> None:
    """Nothing is visible before commit; abort exposes nothing afterwards."""

    stage = factory()
    with stage as opened:
        opened.write(records)
        assert list(visible(opened)) == [], "records were visible before commit"
        opened.finalize()
        opened.commit()
        assert len(visible(opened)) == len(records), "commit did not expose the records"

    aborted = factory()
    with aborted as opened:
        opened.write(records)
        opened.abort()
        assert list(visible(opened)) == [], "abort left records behind"


def assert_failed_commit_exposes_nothing(
    factory: StageFactory,
    visible: Callable[[ReleaseStage], Sequence[AppraisalSourceRecord]],
    records: Sequence[AppraisalSourceRecord],
    sabotage: Callable[[ReleaseStage], None],
) -> None:
    """A commit that raises exposes zero records, exactly as an abort does.

    The suite cannot break a stage it knows nothing about, so the implementation
    supplies the one way its own commit fails.  This is the case that separates
    a stage which is atomic from one which is merely ordered: writing, then
    finalizing, then failing to commit is the moment a half-visible release
    would appear if one could.
    """

    stage = factory()
    raised = False
    with stage as opened:
        opened.write(records)
        opened.finalize()
        sabotage(opened)
        try:
            opened.commit()
        except Exception:  # noqa: BLE001 - any failure, the code is the caller's
            raised = True
        assert raised, "the sabotaged commit reported success"
        assert list(visible(opened)) == [], "a failed commit exposed records"


def assert_unrelated_failure_is_not_a_duplicate(
    factory: StageFactory,
    unwritable: Sequence[AppraisalSourceRecord],
) -> None:
    """A write that fails for any other reason raises something else.

    `DuplicateRecordKey` is the one typed exception the processor reads, so a
    stage that raised it for every failure would report `duplicate_record_key`
    for a release with no duplicate in it.
    """

    stage = factory()
    with stage as opened:
        try:
            opened.write(unwritable)
        except DuplicateRecordKey:
            raise AssertionError("an unrelated failure was reported as a duplicate") from None
        except Exception:  # noqa: BLE001 - anything but the typed one
            pass
        else:
            raise AssertionError("the unwritable record was accepted")
        opened.abort()


def assert_stage_context_is_well_behaved(
    factory: StageFactory,
    records: Sequence[AppraisalSourceRecord],
) -> None:
    """`__enter__` returns the stage itself, and `__exit__` suppresses nothing.

    A stage returning something else would silently make `with stage as opened`
    address a different object than the processor holds; one that suppressed
    would turn a rejected release into an accepted one by swallowing the
    exception that rejected it.
    """

    # Entered and left by hand, and the verdict reached afterwards: a stage that
    # suppresses would swallow an assertion made inside its own `with`, and the
    # first thing this checks is a stage that may do exactly that.
    stage = factory()
    opened = stage.__enter__()
    identical = opened is stage
    stage.abort()
    stage.__exit__(None, None, None)
    assert identical, "__enter__ returned something other than the stage"

    sentinel = RuntimeError("conformance-propagation-probe")
    escaped = None
    try:
        with factory() as opened:
            opened.write(records)
            raise sentinel
    except RuntimeError as error:
        escaped = error
    assert escaped is sentinel, "__exit__ suppressed an exception raised inside the stage"


def assert_stage_reports_duplicates(
    factory: StageFactory,
    duplicate_pair: Sequence[AppraisalSourceRecord],
) -> None:
    """A repeated key raises the typed exception, from write or from finalize."""

    stage = factory()
    raised = False
    with stage as opened:
        try:
            for record in duplicate_pair:
                opened.write([record])
            opened.finalize()
        except DuplicateRecordKey:
            raised = True
        finally:
            opened.abort()
    assert raised, "a repeated key raised no DuplicateRecordKey from write or finalize"


def assert_stage_exit_is_safe(
    factory: StageFactory, records: Sequence[AppraisalSourceRecord]
) -> None:
    """Exit may not fail after either a commit or an abort."""

    committed = factory()
    with committed as opened:
        opened.write(records)
        opened.finalize()
        opened.commit()

    aborted = factory()
    with aborted as opened:
        opened.write(records)
        opened.abort()
