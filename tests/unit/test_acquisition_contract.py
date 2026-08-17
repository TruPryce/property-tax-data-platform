"""The acquisition port: what a policy admits and what a carrier may hold.

These are the rules an adapter cannot weaken, so they are tested against the
port rather than through any transport.
"""

from __future__ import annotations

import pytest
from property_tax_application.acquisition import (
    ACQUISITION_CONTRACT_VERSION,
    SANITIZED_HEADERS,
    AcquiredArtifact,
    AcquisitionError,
    AcquisitionFailure,
    AcquisitionPolicy,
    ArtifactSink,
    RedirectHop,
    ResponseMetadata,
    sanitize_headers,
)


def policy(**overrides: object) -> AcquisitionPolicy:
    return AcquisitionPolicy(
        **{"allowed_hosts": frozenset({"cad.example.gov"}), **overrides}  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------


def test_the_default_posture_is_https_and_an_explicit_host_list() -> None:
    settled = policy()

    assert settled.allowed_schemes == frozenset({"https"})
    assert settled.max_redirects == 5
    assert settled.max_artifact_bytes == 8 * 1024 * 1024 * 1024


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"allowed_hosts": frozenset()}, "at least one host"),
        ({"allowed_schemes": frozenset()}, "at least one scheme"),
        ({"allowed_hosts": frozenset({"CAD.example.gov"})}, "must be lowercase"),
        ({"allowed_schemes": frozenset({"HTTPS"})}, "must be lowercase"),
        ({"max_redirects": -1}, "must not be negative"),
        ({"max_redirects": True}, "must be an int"),
        ({"chunk_bytes": 0}, "must be positive"),
        ({"max_artifact_bytes": 0}, "must be positive"),
        ({"chunk_bytes": 4096, "max_artifact_bytes": 1024}, "must not exceed"),
        ({"timeout_seconds": 0}, "must be positive"),
    ],
    ids=[
        "no-hosts",
        "no-schemes",
        "uppercase-host",
        "uppercase-scheme",
        "negative-hops",
        "bool-as-hops",
        "zero-chunk",
        "zero-ceiling",
        "chunk-over-ceiling",
        "zero-timeout",
    ],
)
def test_an_unusable_policy_is_refused_at_construction(overrides: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        policy(**overrides)


def test_a_permitted_destination_passes_and_compares_casefolded() -> None:
    settled = policy()

    settled.permits("https", "cad.example.gov")
    settled.permits("HTTPS", "CAD.EXAMPLE.GOV")


@pytest.mark.parametrize(
    ("scheme", "host", "expected"),
    [
        ("http", "cad.example.gov", AcquisitionFailure.UNAPPROVED_SCHEME),
        ("file", "cad.example.gov", AcquisitionFailure.UNAPPROVED_SCHEME),
        ("https", "evil.example.com", AcquisitionFailure.UNAPPROVED_HOST),
        ("https", "cad.example.gov.evil.com", AcquisitionFailure.UNAPPROVED_HOST),
    ],
    ids=["plain-http", "file-scheme", "other-host", "suffix-lookalike"],
)
def test_a_refused_destination_names_which_rule_refused_it(
    scheme: str, host: str, expected: AcquisitionFailure
) -> None:
    with pytest.raises(AcquisitionError) as raised:
        policy().permits(scheme, host)

    assert raised.value.failure is expected
    assert raised.value.failure.retryable is False, "a rule failure repeated is the same failure"


def test_the_retryable_partition_covers_every_code() -> None:
    """A code with no retry answer is a code an orchestrator cannot act on."""

    for failure in AcquisitionFailure:
        assert isinstance(failure.retryable, bool)

    assert AcquisitionFailure.TRUNCATED_ARTIFACT.retryable is True
    assert AcquisitionFailure.CHECKSUM_MISMATCH.retryable is False


# --------------------------------------------------------------------------
# Sanitized metadata
# --------------------------------------------------------------------------


def test_only_allowlisted_headers_survive() -> None:
    kept = sanitize_headers(
        {
            "Content-Type": "application/zip",
            "Content-Length": "1024",
            "ETag": '"abc"',
            "Set-Cookie": "session=secret",
            "Authorization": "Bearer secret",
            "Server": "nginx/1.2.3",
            "X-Amz-Request-Id": "0123456789",
        }
    )

    assert set(kept) == {"content-type", "content-length", "etag"}
    assert "secret" not in "".join(kept.values())


def test_a_header_the_server_invents_is_dropped_by_default() -> None:
    """An allowlist rather than a denylist: the unknown is excluded, not kept."""

    assert sanitize_headers({"X-Future-Tracking-Id": "person-42"}) == {}


def test_a_preserved_value_is_bounded_and_control_free() -> None:
    kept = sanitize_headers({"ETag": '"' + "a" * 5_000 + '"', "Content-Type": "text/csv\r\nX: y"})

    assert len(kept["etag"]) == 512
    assert "\r" not in kept["content-type"] and "\n" not in kept["content-type"]


def test_metadata_refuses_a_header_outside_the_allowlist() -> None:
    with pytest.raises(ValueError, match="outside the allowlist"):
        ResponseMetadata(status=200, headers={"set-cookie": "session=secret"})


@pytest.mark.parametrize("status", [99, 600, True], ids=["too-low", "too-high", "bool"])
def test_metadata_refuses_an_impossible_status(status: object) -> None:
    with pytest.raises(ValueError, match="status must"):
        ResponseMetadata(status=status)  # type: ignore[arg-type]


def test_declared_length_is_none_when_the_server_gave_nothing_usable() -> None:
    assert ResponseMetadata(status=200).declared_length is None
    assert ResponseMetadata(status=200, headers={"content-length": "nope"}).declared_length is None
    assert ResponseMetadata(status=200, headers={"content-length": "12"}).declared_length == 12


def test_the_media_type_drops_its_parameters() -> None:
    metadata = ResponseMetadata(status=200, headers={"content-type": "text/CSV; charset=utf-8"})

    assert metadata.media_type == "text/csv"


# --------------------------------------------------------------------------
# The acquired artifact
# --------------------------------------------------------------------------


def artifact(**overrides: object) -> AcquiredArtifact:
    return AcquiredArtifact(
        **{
            "sha256": "a" * 64,
            "byte_count": 12,
            "final_url": "https://cad.example.gov/roll.zip",
            "response": ResponseMetadata(status=200),
            **overrides,
        }  # type: ignore[arg-type]
    )


def test_a_complete_artifact_pins_its_contract_version() -> None:
    assert artifact().acquisition_contract_version == ACQUISITION_CONTRACT_VERSION == 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"sha256": "A" * 64}, "lowercase hexadecimal"),
        ({"sha256": "a" * 63}, "lowercase hexadecimal"),
        ({"byte_count": -1}, "must not be negative"),
        ({"byte_count": True}, "must be an int"),
        ({"response": {"status": 200}}, "must be a ResponseMetadata"),
        ({"redirects": ("not a hop",)}, "tuple of RedirectHop"),
        ({"acquisition_contract_version": 2}, "must be the int 1"),
        ({"acquisition_contract_version": True}, "must be the int 1"),
    ],
    ids=[
        "uppercase-digest",
        "short-digest",
        "negative-count",
        "bool-as-count",
        "raw-dict-response",
        "string-in-redirects",
        "wrong-version",
        "bool-as-version",
    ],
)
def test_an_incoherent_artifact_is_refused(overrides: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        artifact(**overrides)


def test_the_byte_count_may_not_contradict_the_declared_length() -> None:
    """A cross-field rule: both values are individually valid.

    Neither the count nor the header is wrong on its own, so no check of either
    one alone can catch a manifest that says the server promised one size and
    the transfer produced another.
    """

    with pytest.raises(ValueError, match="declared content length"):
        artifact(
            byte_count=12,
            response=ResponseMetadata(status=200, headers={"content-length": "99"}),
        )

    agreeing = artifact(
        byte_count=99,
        response=ResponseMetadata(status=200, headers={"content-length": "99"}),
    )
    assert agreeing.byte_count == 99


def test_a_redirect_hop_must_carry_a_redirect_status() -> None:
    with pytest.raises(ValueError, match="3xx status"):
        RedirectHop(from_url="https://a.example", to_url="https://b.example", status=200)

    with pytest.raises(ValueError, match="both of its endpoints"):
        RedirectHop(from_url="", to_url="https://b.example", status=302)


def test_the_sink_protocol_names_the_three_verbs_a_caller_needs() -> None:
    """Written, durable, and discarded are three states, so three verbs."""

    assert {"write", "commit", "abort"} <= set(dir(ArtifactSink))
    assert "content-length" in SANITIZED_HEADERS
