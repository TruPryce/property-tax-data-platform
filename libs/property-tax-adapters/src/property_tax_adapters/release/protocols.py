"""What a county and a caller must supply, stated as structural types.

These are `Protocol` classes rather than base classes because a county adapter
already owns its parsing.  Requiring inheritance would invert that and make the
boundary a framework a county must join; structural typing also lets a test
stage conform without importing anything county-specific.

Every callable declares an exact signature.  Two implementations that each
satisfied a prose description could still be incompatible, which is the thing a
protocol exists to prevent.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from types import TracebackType
from typing import Protocol, runtime_checkable

from property_tax_adapters.release.progress import ReleaseProgressEvent
from property_tax_adapters.release.records import PreparedRelease, SourceRowEnvelope
from property_tax_adapters.sources.contracts import AppraisalSourceRecord

__all__ = ["PreparedReader", "ProgressCallback", "ReleaseStage", "ResourceGuard"]


@runtime_checkable
class PreparedReader(Protocol):
    """A single-pass, context-managed source of one logical release.

    `prepare()` is a named method rather than an implicit phase because the
    diagnostic table assigns `source_open_failed` to entry and `layout_rejected`
    to preparation.  Without a call to attribute each failure to, an
    implementation could only guess which applied by inspecting where inside
    `__enter__` an exception arose.
    """

    def __enter__(self) -> PreparedReader:
        """Open the immutable source and return this reader."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the source.

        Annotated as returning `None` rather than `bool`: a `None` return is
        always falsy, so the prohibition on suppressing an exception is carried
        by the signature rather than by prose an implementation could overlook.
        A suppressed failure is one the processor cannot map to a code.
        """

    def prepare(self) -> PreparedRelease:
        """Validate the complete layout and return the release identity.

        Called exactly once, after `__enter__` and before the first iteration.
        Reads no record, so an empty release still has a complete identity.
        """

    def __iter__(self) -> Iterator[SourceRowEnvelope]:
        """Yield one envelope per physical row.

        A reader signals an invalid row by marking the envelope rejected, never
        by raising: raising ends iteration at the first bad row, which would
        report one defect for a member with many and make the retention cap
        unreachable.
        """


@runtime_checkable
class ReleaseStage(Protocol):
    """A caller-supplied atomic destination.

    The contract is the atomicity guarantee: nothing written is visible until
    `commit` returns, and `abort` or a failed `commit` exposes zero accepted
    records.
    """

    def __enter__(self) -> ReleaseStage:
        """Open the stage and return it."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release the stage.

        May not fail after either a successful commit or an abort, which is what
        makes it safe to run after the only step that changes visibility.  A
        stage that raises here regardless is a defect in trusted code and
        propagates, exactly as a malformed layout raises rather than diagnosing.
        """

    def write(self, records: Sequence[AppraisalSourceRecord]) -> None:
        """Stage one physical row's records, all or nothing.

        A row is the unit accepted or rejected, so splitting it across calls
        would let a stage hold half a refused row.  If this raises, none of the
        call's records are staged — not the prefix written before the failure,
        which would leave the staged count describing neither what was attempted
        nor what is present.

        Raises `DuplicateRecordKey` for a repeated key where the index is eager.
        """

    def finalize(self) -> None:
        """Run release-wide checks.

        Raises `DuplicateRecordKey` for a repeated key where the index is
        deferred, so a bulk-loaded stage is as conforming as an eager one.
        """

    def abort(self) -> None:
        """Discard everything staged, exposing zero accepted records."""

    def commit(self) -> None:
        """Make the staged records visible, exactly once."""


@runtime_checkable
class ProgressCallback(Protocol):
    """A synchronous observer of release progress.

    A callback that raises rejects the release.  Progress is part of the
    contract rather than a best-effort notification, because a DAG that silently
    loses progress cannot tell a stalled release from a slow one.
    """

    def __call__(self, event: ReleaseProgressEvent) -> None: ...


@runtime_checkable
class ResourceGuard(Protocol):
    """A caller-supplied bound, asked at checkpoints the boundary fixes.

    The protocol says *what is passed* and *when it is asked*, and never what is
    measured, in what units, or by what probe.  A guard that measures nothing
    and never raises conforms, and is what a caller supplying none gets.
    """

    def check(self, physical_rows_processed: int, staged_record_count: int) -> None:
        """Raise to reject the release with `resource_limit_exceeded`."""
