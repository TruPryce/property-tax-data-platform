"""Acquisition against a synthetic local server: hops, bounds, and cleanup.

Every response is scripted in-process. No county endpoint is contacted and no
county bytes exist here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from property_tax_adapters.acquisition import acquire_artifact
from property_tax_application.acquisition import (
    AcquisitionError,
    AcquisitionFailure,
    AcquisitionPolicy,
)

from acquisition.fixture_server import FileSink, Route, base_url, serving

BODY = b"account|value\n" + b"".join(f"{n:08d}|{n * 7}\n".encode() for n in range(4_000))
DIGEST = hashlib.sha256(BODY).hexdigest()


def local_policy(**overrides: object) -> AcquisitionPolicy:
    """The production posture, widened only to reach the loopback fixture."""

    return AcquisitionPolicy(
        **{
            "allowed_hosts": frozenset({"127.0.0.1"}),
            "allowed_schemes": frozenset({"http"}),
            "chunk_bytes": 4_096,
            "timeout_seconds": 10.0,
            **overrides,
        }  # type: ignore[arg-type]
    )


def sink_at(tmp_path: Path) -> FileSink:
    return FileSink(tmp_path / "artifact.txt")


# --------------------------------------------------------------------------
# The complete path
# --------------------------------------------------------------------------


def test_a_complete_download_is_hashed_and_committed(tmp_path: Path) -> None:
    with serving({"/roll.txt": Route(body=BODY, headers={"Content-Type": "text/plain"})}) as server:
        sink = sink_at(tmp_path)
        artifact = acquire_artifact(
            url=f"{base_url(server)}/roll.txt", sink=sink, policy=local_policy()
        )

    assert artifact.sha256 == DIGEST
    assert artifact.byte_count == len(BODY)
    assert artifact.media_type == "text/plain"
    assert sink.committed is True and sink.aborted is False
    assert sink.destination.read_bytes() == BODY
    assert not sink.partial.exists(), "the partial neighbour outlived the commit"


def test_the_checksum_is_incremental_not_computed_from_a_buffer(tmp_path: Path) -> None:
    """Peak memory is the chunk size, whatever the artifact size.

    The sink records the largest chunk it was handed; a reader that buffered the
    response and wrote it once would show a chunk the size of the body.
    """

    seen: list[int] = []

    class Watching(FileSink):
        def write(self, chunk: bytes) -> None:
            seen.append(len(chunk))
            super().write(chunk)

    with serving({"/roll.txt": Route(body=BODY)}) as server:
        sink = Watching(tmp_path / "artifact.txt")
        artifact = acquire_artifact(
            url=f"{base_url(server)}/roll.txt", sink=sink, policy=local_policy(chunk_bytes=4_096)
        )

    assert artifact.sha256 == DIGEST
    assert len(seen) > 1, "the body arrived in one piece; it was not streamed"
    assert max(seen) <= 4_096, f"a chunk of {max(seen)} exceeded the bound"


def test_an_expected_checksum_that_matches_is_accepted(tmp_path: Path) -> None:
    with serving({"/roll.txt": Route(body=BODY)}) as server:
        artifact = acquire_artifact(
            url=f"{base_url(server)}/roll.txt",
            sink=sink_at(tmp_path),
            policy=local_policy(),
            expected_sha256=DIGEST,
        )

    assert artifact.sha256 == DIGEST


def test_an_empty_artifact_is_still_a_complete_one(tmp_path: Path) -> None:
    with serving({"/empty.txt": Route(body=b"")}) as server:
        artifact = acquire_artifact(
            url=f"{base_url(server)}/empty.txt", sink=sink_at(tmp_path), policy=local_policy()
        )

    assert artifact.byte_count == 0
    assert artifact.sha256 == hashlib.sha256(b"").hexdigest()


# --------------------------------------------------------------------------
# Redirects: validated before contact
# --------------------------------------------------------------------------


def test_an_approved_redirect_chain_is_followed_and_recorded(tmp_path: Path) -> None:
    routes = {
        "/start": Route(status=302, location="/middle"),
        "/middle": Route(status=302, location="/roll.txt"),
        "/roll.txt": Route(body=BODY),
    }
    with serving(routes) as server:
        artifact = acquire_artifact(
            url=f"{base_url(server)}/start", sink=sink_at(tmp_path), policy=local_policy()
        )

    assert [hop.status for hop in artifact.redirects] == [302, 302]
    assert artifact.redirects[-1].to_url.endswith("/roll.txt")
    assert artifact.final_url.endswith("/roll.txt")


def test_an_unapproved_host_is_never_contacted(tmp_path: Path) -> None:
    """The refusal is the point: the destination must receive no request."""

    reached: list[str] = []

    with serving({"/elsewhere": Route(body=b"never")}) as decoy:
        decoy_url = f"{base_url(decoy)}/elsewhere".replace("127.0.0.1", "localhost")
        with serving({"/start": Route(status=302, location=decoy_url)}) as server:
            sink = sink_at(tmp_path)
            with pytest.raises(AcquisitionError) as raised:
                acquire_artifact(url=f"{base_url(server)}/start", sink=sink, policy=local_policy())
        reached = list(decoy.requested)

    assert raised.value.failure is AcquisitionFailure.UNAPPROVED_HOST
    assert reached == [], "the unapproved destination received a request"
    assert sink.aborted is True and not sink.destination.exists()


def test_an_unapproved_scheme_is_refused_before_connecting(tmp_path: Path) -> None:
    sink = sink_at(tmp_path)
    with pytest.raises(AcquisitionError) as raised:
        acquire_artifact(
            url="ftp://127.0.0.1/roll.txt",
            sink=sink,
            policy=local_policy(),
        )

    assert raised.value.failure is AcquisitionFailure.UNAPPROVED_SCHEME
    assert raised.value.failure.retryable is False
    assert sink.aborted is True


def test_the_initial_url_is_validated_as_strictly_as_a_redirect(tmp_path: Path) -> None:
    """A first request to an unapproved host is the same defect as a hop to one."""

    with pytest.raises(AcquisitionError) as raised:
        acquire_artifact(
            url="http://example.invalid/roll.txt",
            sink=sink_at(tmp_path),
            policy=local_policy(),
        )

    assert raised.value.failure is AcquisitionFailure.UNAPPROVED_HOST


def test_a_hop_limit_stops_a_redirect_loop(tmp_path: Path) -> None:
    routes = {"/loop": Route(status=302, location="/loop")}
    with serving(routes) as server:
        sink = sink_at(tmp_path)
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(
                url=f"{base_url(server)}/loop", sink=sink, policy=local_policy(max_redirects=3)
            )
        attempts = len(server.requested)

    assert raised.value.failure is AcquisitionFailure.TOO_MANY_REDIRECTS
    assert attempts == 4, f"the limit admitted {attempts} requests"
    assert sink.aborted is True


def test_a_redirect_without_a_destination_is_a_named_failure(tmp_path: Path) -> None:
    with serving({"/start": Route(status=302)}) as server:
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(
                url=f"{base_url(server)}/start", sink=sink_at(tmp_path), policy=local_policy()
            )

    assert raised.value.failure is AcquisitionFailure.MISSING_REDIRECT_TARGET


def test_a_relative_redirect_resolves_against_the_url_that_sent_it(tmp_path: Path) -> None:
    routes = {"/a/start": Route(status=307, location="../roll.txt"), "/roll.txt": Route(body=BODY)}
    with serving(routes) as server:
        artifact = acquire_artifact(
            url=f"{base_url(server)}/a/start", sink=sink_at(tmp_path), policy=local_policy()
        )

    assert artifact.sha256 == DIGEST


# --------------------------------------------------------------------------
# Bounds and cleanup
# --------------------------------------------------------------------------


def test_a_declared_length_over_the_ceiling_is_refused_before_reading(tmp_path: Path) -> None:
    route = Route(body=BODY, declared_length=len(BODY))
    with serving({"/roll.txt": route}) as server:
        sink = sink_at(tmp_path)
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(
                url=f"{base_url(server)}/roll.txt",
                sink=sink,
                policy=local_policy(max_artifact_bytes=1_000, chunk_bytes=512),
            )

    assert raised.value.failure is AcquisitionFailure.ARTIFACT_TOO_LARGE
    assert sink.aborted is True
    assert not sink.destination.exists() and not sink.partial.exists()


def test_an_unframed_body_is_stopped_at_the_ceiling(tmp_path: Path) -> None:
    """The case a declared length cannot catch: the server declares nothing.

    Without `Content-Length` the body ends at connection close, so nothing but
    the running count bounds what arrives. This is the only shape in which more
    bytes can reach the process than any declaration promised.
    """

    with serving({"/roll.txt": Route(body=BODY, omit_length=True)}) as server:
        sink = sink_at(tmp_path)
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(
                url=f"{base_url(server)}/roll.txt",
                sink=sink,
                policy=local_policy(max_artifact_bytes=2_000, chunk_bytes=512),
            )

    assert raised.value.failure is AcquisitionFailure.ARTIFACT_TOO_LARGE
    assert sink.aborted is True
    assert not sink.destination.exists() and not sink.partial.exists()


def test_an_unframed_body_within_the_ceiling_still_completes(tmp_path: Path) -> None:
    """A missing Content-Length is not itself a failure, only an unbounded one."""

    with serving({"/roll.txt": Route(body=BODY, omit_length=True)}) as server:
        artifact = acquire_artifact(
            url=f"{base_url(server)}/roll.txt", sink=sink_at(tmp_path), policy=local_policy()
        )

    assert artifact.sha256 == DIGEST
    assert artifact.response.declared_length is None


def test_a_server_declaring_fewer_bytes_than_it_sends_frames_the_artifact(
    tmp_path: Path,
) -> None:
    """Content-Length frames the message, so the surplus is never part of it.

    Worth stating rather than discovering: the checksum covers what the
    framing admitted, so an under-declaring server yields a short artifact with
    an honest checksum of those bytes rather than a silent mixture.
    """

    with serving({"/roll.txt": Route(body=BODY, declared_length=64)}) as server:
        artifact = acquire_artifact(
            url=f"{base_url(server)}/roll.txt", sink=sink_at(tmp_path), policy=local_policy()
        )

    assert artifact.byte_count == 64
    assert artifact.sha256 == hashlib.sha256(BODY[:64]).hexdigest()


def test_a_truncated_transfer_leaves_nothing_behind(tmp_path: Path) -> None:
    route = Route(body=BODY, declared_length=len(BODY), send_bytes=len(BODY) // 3)
    with serving({"/roll.txt": route}) as server:
        sink = sink_at(tmp_path)
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink, policy=local_policy())

    assert raised.value.failure is AcquisitionFailure.TRUNCATED_ARTIFACT
    assert raised.value.failure.retryable is True
    assert sink.aborted is True
    assert not sink.destination.exists(), "a truncated artifact was left as a source object"
    assert not sink.partial.exists()


def test_a_checksum_mismatch_discards_the_object(tmp_path: Path) -> None:
    with serving({"/roll.txt": Route(body=BODY)}) as server:
        sink = sink_at(tmp_path)
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(
                url=f"{base_url(server)}/roll.txt",
                sink=sink,
                policy=local_policy(),
                expected_sha256="0" * 64,
            )

    assert raised.value.failure is AcquisitionFailure.CHECKSUM_MISMATCH
    assert sink.committed is False and sink.aborted is True
    assert not sink.destination.exists()


def test_an_interruption_aborts_as_surely_as_a_failure(tmp_path: Path) -> None:
    """KeyboardInterrupt is not an Exception, and leaves the same partial object."""

    class Interrupting(FileSink):
        def write(self, chunk: bytes) -> None:
            super().write(chunk)
            raise KeyboardInterrupt

    with serving({"/roll.txt": Route(body=BODY)}) as server:
        sink = Interrupting(tmp_path / "artifact.txt")
        with pytest.raises(KeyboardInterrupt):
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink, policy=local_policy())

    assert sink.aborted is True
    assert not sink.destination.exists() and not sink.partial.exists()


def test_a_failing_sink_is_named_and_cleaned_up(tmp_path: Path) -> None:
    with serving({"/roll.txt": Route(body=BODY)}) as server:
        sink = FileSink(tmp_path / "artifact.txt", fail_on_write=True)
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink, policy=local_policy())

    assert raised.value.failure is AcquisitionFailure.SINK_FAILED
    assert sink.aborted is True


def test_a_failing_commit_does_not_leave_a_committed_object(tmp_path: Path) -> None:
    with serving({"/roll.txt": Route(body=BODY)}) as server:
        sink = FileSink(tmp_path / "artifact.txt", fail_on_commit=True)
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink, policy=local_policy())

    assert raised.value.failure is AcquisitionFailure.SINK_FAILED
    assert sink.committed is False and sink.aborted is True
    assert not sink.destination.exists()


@pytest.mark.parametrize(
    ("status", "expected", "retryable"),
    [
        (503, AcquisitionFailure.TRANSIENT_STATUS, True),
        (429, AcquisitionFailure.TRANSIENT_STATUS, True),
        (408, AcquisitionFailure.TRANSIENT_STATUS, True),
        (500, AcquisitionFailure.TRANSIENT_STATUS, True),
        (404, AcquisitionFailure.UNSUPPORTED_STATUS, False),
        (403, AcquisitionFailure.UNSUPPORTED_STATUS, False),
        (204, AcquisitionFailure.UNSUPPORTED_STATUS, False),
    ],
    ids=["503", "429", "408", "500", "404", "403", "204"],
)
def test_an_error_status_is_classified_for_retry(
    tmp_path: Path, status: int, expected: AcquisitionFailure, retryable: bool
) -> None:
    """A transient status and an unsupported one are different facts.

    Retrying a 503 may succeed; retrying a 404 repeats it. Collapsing both into
    one code would make an orchestrator either give up on an overloaded server
    or hammer a missing file.
    """

    with serving({"/roll.txt": Route(status=status, body=b"not content")}) as server:
        sink = sink_at(tmp_path)
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink, policy=local_policy())

    assert raised.value.failure is expected
    assert raised.value.failure.retryable is retryable
    assert sink.aborted is True
    assert not sink.destination.exists()


def test_no_sink_failure_text_reaches_the_error(tmp_path: Path) -> None:
    with serving({"/roll.txt": Route(body=BODY)}) as server:
        sink = FileSink(tmp_path / "artifact.txt", fail_on_write=True)
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink, policy=local_policy())

    assert "SECRET-SINK-WRITE" not in str(raised.value)
    assert "SECRET-SINK-WRITE" not in repr(raised.value.detail)


# --------------------------------------------------------------------------
# The sink lifecycle, including the entry that fails
# --------------------------------------------------------------------------


def test_a_sink_that_fails_to_enter_is_still_aborted(tmp_path: Path) -> None:
    """`with` would skip cleanup, because the block was never entered.

    An entry that created its partial object and then failed has left exactly
    what a mid-transfer failure leaves, so the same cleanup is owed.
    """

    class FailingEntry(FileSink):
        def __enter__(self) -> FailingEntry:
            super().__enter__()
            raise OSError("SECRET-SINK-ENTER")

    sink = FailingEntry(tmp_path / "artifact.txt")
    with serving({"/roll.txt": Route(body=BODY)}) as server:
        with pytest.raises(OSError, match="SECRET-SINK-ENTER"):
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink, policy=local_policy())

    assert sink.aborted is True, "a failed entry skipped cleanup"
    assert not sink.partial.exists() and not sink.destination.exists()


def test_a_failed_cleanup_is_reported_beside_the_original_failure(tmp_path: Path) -> None:
    """Two facts, and a caller that cannot tell them apart assumes a clean sink.

    The abort raises *before* removing anything, so the partial object really
    does survive — a test whose abort cleans up first and then raises proves
    nothing about the case that matters.
    """

    class UnabortableSink(FileSink):
        def abort(self) -> None:
            raise OSError("SECRET-ABORT-FAILED")

    sink = UnabortableSink(tmp_path / "artifact.txt")
    with serving({"/roll.txt": Route(status=404)}) as server:
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink, policy=local_policy())

    # The cause survives...
    assert raised.value.failure is AcquisitionFailure.UNSUPPORTED_STATUS
    # ...and so does the news that cleanup did not happen.
    assert raised.value.cleanup_failed is True
    assert any("partial artifact may remain" in note for note in raised.value.__notes__)
    assert sink.partial.exists(), "the premise failed: nothing was actually left behind"
    assert "SECRET-ABORT-FAILED" not in str(raised.value)
    assert not any("SECRET-ABORT-FAILED" in note for note in raised.value.__notes__)


def test_a_successful_cleanup_reports_no_cleanup_failure(tmp_path: Path) -> None:
    with serving({"/roll.txt": Route(status=404)}) as server:
        sink = sink_at(tmp_path)
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink, policy=local_policy())

    assert raised.value.cleanup_failed is False
    assert not sink.partial.exists()


def test_a_failed_cleanup_after_an_interruption_is_still_noted(tmp_path: Path) -> None:
    """The note reaches a BaseException too, which carries no failure code."""

    class Interrupting(FileSink):
        def write(self, chunk: bytes) -> None:
            super().write(chunk)
            raise KeyboardInterrupt

        def abort(self) -> None:
            raise OSError("SECRET-ABORT-FAILED")

    with serving({"/roll.txt": Route(body=BODY)}) as server:
        with pytest.raises(KeyboardInterrupt) as raised:
            acquire_artifact(
                url=f"{base_url(server)}/roll.txt",
                sink=Interrupting(tmp_path / "artifact.txt"),
                policy=local_policy(),
            )

    assert any("partial artifact may remain" in note for note in raised.value.__notes__)


def test_the_sink_is_left_exactly_once_on_the_happy_path(tmp_path: Path) -> None:
    exits: list[int] = []

    class Counting(FileSink):
        def __exit__(self, *args: object) -> None:
            exits.append(1)
            super().__exit__(*args)  # type: ignore[arg-type]

    with serving({"/roll.txt": Route(body=BODY)}) as server:
        acquire_artifact(
            url=f"{base_url(server)}/roll.txt",
            sink=Counting(tmp_path / "artifact.txt"),
            policy=local_policy(),
        )

    assert sum(exits) == 1


# --------------------------------------------------------------------------
# The locator, and provenance that carries no credential
# --------------------------------------------------------------------------


def test_the_committed_locator_reaches_the_artifact(tmp_path: Path) -> None:
    """Task 3.2 builds the manifest from this; discarding it strands the object."""

    with serving({"/roll.txt": Route(body=BODY)}) as server:
        sink = sink_at(tmp_path)
        acquired = acquire_artifact(
            url=f"{base_url(server)}/roll.txt", sink=sink, policy=local_policy()
        )

    assert acquired.locator == sink.destination.as_uri()
    assert acquired.locator != acquired.final_url


def test_a_sink_committing_without_a_locator_is_a_named_failure(tmp_path: Path) -> None:
    class SilentCommit(FileSink):
        def commit(self) -> str:
            super().commit()
            return ""

    with serving({"/roll.txt": Route(body=BODY)}) as server:
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(
                url=f"{base_url(server)}/roll.txt",
                sink=SilentCommit(tmp_path / "artifact.txt"),
                policy=local_policy(),
            )

    assert raised.value.failure is AcquisitionFailure.SINK_FAILED


def test_a_signed_request_url_does_not_reach_the_provenance(tmp_path: Path) -> None:
    """The request carries the token; the manifest must not."""

    routes = {
        "/start": Route(status=302, location="/roll.txt?signature=SECRET-SIGNATURE"),
        "/roll.txt": Route(body=BODY),
    }
    with serving(routes) as server:
        acquired = acquire_artifact(
            url=f"{base_url(server)}/start?token=SECRET-TOKEN",
            sink=sink_at(tmp_path),
            policy=local_policy(),
        )

    rendered = repr(acquired)
    for secret in ("SECRET-TOKEN", "SECRET-SIGNATURE", "signature=", "token="):
        assert secret not in rendered, f"{secret} survived into the artifact"
    assert acquired.final_url.endswith("/roll.txt")
    assert acquired.redirects[0].to_url.endswith("/roll.txt")
