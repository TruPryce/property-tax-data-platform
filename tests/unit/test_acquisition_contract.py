"""The acquisition port: what a policy admits and what a carrier may hold.

These are the rules an adapter cannot weaken, so they are tested against the
port rather than through any transport.
"""

from __future__ import annotations

import pytest
from property_tax_application.acquisition import (
    ACQUISITION_CONTRACT_VERSION,
    MAX_LOCATOR_CHARS,
    SANITIZED_HEADERS,
    AcquiredArtifact,
    AcquisitionError,
    AcquisitionFailure,
    AcquisitionPolicy,
    ArtifactSink,
    RedirectHop,
    ResponseMetadata,
    sanitize_headers,
    sanitize_url,
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
            "locator": "s3://bronze/tx-dallas/roll.zip",
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


# --------------------------------------------------------------------------
# Provenance may not carry a credential
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://user:pw@cad.example.gov/roll.zip",  # pragma: allowlist secret
            "https://cad.example.gov/roll.zip",
        ),
        ("https://cad.example.gov/roll.zip?token=SECRET", "https://cad.example.gov/roll.zip"),
        ("https://cad.example.gov/roll.zip#part", "https://cad.example.gov/roll.zip"),
        ("HTTPS://CAD.Example.GOV/roll.zip", "https://cad.example.gov/roll.zip"),
        ("https://cad.example.gov:8443/a/b.zip?k=v", "https://cad.example.gov:8443/a/b.zip"),
    ],
    ids=["userinfo", "query", "fragment", "case", "port-kept"],
)
def test_a_provenance_url_keeps_only_where_it_came_from(raw: str, expected: str) -> None:
    assert sanitize_url(raw) == expected


@pytest.mark.parametrize(
    "hostile",
    [
        "https://user:s3cr3t@cad.example.gov/roll.zip",  # pragma: allowlist secret
        "https://cad.example.gov/roll.zip?signature=SECRET-TOKEN",
        "https://cad.example.gov/roll.zip#SECRET",
    ],
    ids=["userinfo", "signed-query", "fragment"],
)
def test_a_carrier_refuses_an_unsanitized_url(hostile: str) -> None:
    """Enforced on the carrier, since the carrier is what task 3.2 persists."""

    with pytest.raises(ValueError, match="must be sanitized"):
        artifact(final_url=hostile)

    with pytest.raises(ValueError, match="must be sanitized"):
        RedirectHop(from_url=hostile, to_url="https://b.example/y", status=302)

    with pytest.raises(ValueError, match="must be sanitized"):
        RedirectHop(from_url="https://a.example/x", to_url=hostile, status=302)


def test_no_secret_survives_into_a_complete_artifact() -> None:
    # Each raw URL carries something a manifest may not: userinfo, a signed
    # query, or both.  They are synthetic, and the assertion is that none of it
    # survives sanitization into the carrier.
    raw_final = "https://user:s3cr3t@cad.example.gov/roll.zip?token=SECRET-TOKEN"  # noqa: E501, S105  # pragma: allowlist secret
    raw_start = "https://u:p@start.example.gov/go?key=SECRET-KEY"  # pragma: allowlist secret
    complete = artifact(
        final_url=sanitize_url(raw_final),
        redirects=(
            RedirectHop(
                from_url=sanitize_url(raw_start),
                to_url=sanitize_url("https://cad.example.gov/roll.zip?sig=SECRET-SIG"),
                status=302,
            ),
        ),
    )

    rendered = repr(complete)
    for secret in ("s3cr3t", "SECRET-TOKEN", "SECRET-KEY", "SECRET-SIG", "token=", "sig="):
        assert secret not in rendered, f"{secret} survived into the artifact"


# --------------------------------------------------------------------------
# The durable locator
# --------------------------------------------------------------------------


def test_an_artifact_must_say_where_its_bytes_landed() -> None:
    """The manifest task consumes this; without it the commit is unfindable."""

    assert artifact().locator == "s3://bronze/tx-dallas/roll.zip"

    for missing in ("", "   "):
        with pytest.raises(ValueError, match="locator must be"):
            artifact(locator=missing)

    with pytest.raises(ValueError, match="locator must be"):
        artifact(locator=None)


def test_the_locator_and_the_provenance_url_are_different_facts() -> None:
    """One says where it came from, the other where it went; neither substitutes."""

    complete = artifact(
        final_url="https://cad.example.gov/roll.zip", locator="s3://bronze/2026/roll.zip"
    )

    assert complete.final_url != complete.locator
    assert {"final_url", "locator"} <= set(AcquiredArtifact.__dataclass_fields__)


# --------------------------------------------------------------------------
# Frozen means frozen
# --------------------------------------------------------------------------


def test_a_policy_cannot_be_widened_after_construction() -> None:
    """A frozen dataclass holding a caller's mutable set is not frozen."""

    hosts = {"cad.example.gov"}
    schemes = {"https"}
    settled = AcquisitionPolicy(allowed_hosts=hosts, allowed_schemes=schemes)  # type: ignore[arg-type]

    hosts.add("evil.example.com")
    schemes.add("http")

    assert isinstance(settled.allowed_hosts, frozenset)
    with pytest.raises(AcquisitionError) as host_refusal:
        settled.permits("https", "evil.example.com")
    assert host_refusal.value.failure is AcquisitionFailure.UNAPPROVED_HOST

    with pytest.raises(AcquisitionError) as scheme_refusal:
        settled.permits("http", "cad.example.gov")
    assert scheme_refusal.value.failure is AcquisitionFailure.UNAPPROVED_SCHEME


def test_response_headers_cannot_be_changed_after_the_allowlist_check() -> None:
    """Otherwise the check runs on one mapping and the carrier holds another."""

    supplied = {"content-length": "10"}
    metadata = ResponseMetadata(status=200, headers=supplied)
    complete = artifact(byte_count=10, response=metadata)

    supplied["content-length"] = "999"
    supplied["set-cookie"] = "session=SECRET"

    assert metadata.declared_length == 10, "a verified agreement was invalidated afterwards"
    assert "set-cookie" not in metadata.headers, "an unsanitized header was injected"
    assert complete.response.declared_length == complete.byte_count

    with pytest.raises(TypeError):
        metadata.headers["etag"] = "injected"  # type: ignore[index]


# --------------------------------------------------------------------------
# A carrier built by hand obeys the same rules as one built by the adapter
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("x" * 513, "exceeds 512 characters"),
        ("text/csv\r\nInjected: yes", "control character"),
        ("text/csv\x00", "control character"),
        ("  text/csv  ", "surrounding whitespace"),
    ],
    ids=["unbounded", "crlf-injection", "null-byte", "untrimmed"],
)
def test_a_header_value_built_by_hand_obeys_the_sanitizer(value: str, message: str) -> None:
    """The allowlist bounded which headers survive, not what they may contain.

    `sanitize_headers` normalizes; a caller constructing the carrier directly
    bypassed it entirely, so a value could carry five kilobytes or a CRLF that
    splits a log line into a forged second record.
    """

    with pytest.raises(ValueError, match=message):
        ResponseMetadata(status=200, headers={"content-type": value})


def test_a_sanitized_header_passes_the_carrier_unchanged() -> None:
    """The two rules agree: what the sanitizer emits, the carrier accepts."""

    cleaned = sanitize_headers(
        {"ETag": '"' + "a" * 5_000 + '"', "Content-Type": "text/csv\r\nX: y", "Content-Length": "9"}
    )

    metadata = ResponseMetadata(status=200, headers=cleaned)

    assert metadata.headers == cleaned


@pytest.mark.parametrize(
    ("locator", "message"),
    [
        ("https://bronze.example/r.zip?X-Amz-Signature=SECRET", "query string"),
        ("s3://key:SECRET@bucket/r.zip", "userinfo"),  # pragma: allowlist secret
        ("https://bronze.example/r.zip#SECRET", "fragment"),
        ("bronze/r.zip", "must name a scheme"),
        ("   ", "non-blank"),
    ],
    ids=["signed-query", "userinfo", "fragment", "no-scheme", "blank"],
)
def test_a_locator_may_not_carry_access(locator: str, message: str) -> None:
    """Where the bytes landed, not who may fetch them.

    An object-store URL with a signature is a bearer credential, and task 3.2
    persists this field into a manifest that outlives the signature's validity.
    """

    with pytest.raises(ValueError, match=message):
        artifact(locator=locator)


def test_a_plain_object_locator_is_accepted_unrewritten() -> None:
    """Refused rather than rewritten: an object key is case-sensitive.

    Lowercasing an authority the way a provenance URL is lowercased would name
    a different object, so the dangerous parts are rejected and nothing else is
    touched.
    """

    for good in (
        "s3://bronze-tx/2026/Roll_CURRENT.zip",
        "https://bronze.example/tx-dallas/roll.zip",
        "file:///var/bronze/roll.zip",
    ):
        assert artifact(locator=good).locator == good


@pytest.mark.parametrize(
    ("locator", "message"),
    [
        ("s3://bucket/" + "k" * 3_000, "exceeds 2048 characters"),
        ("s3://bucket/key\r\ninjected: yes", "control character"),
        ("s3://bucket/key\x00", "control character"),
        ("  s3://bucket/key  ", "surrounding whitespace"),
    ],
    ids=["unbounded", "crlf-injection", "null-byte", "untrimmed"],
)
def test_a_locator_is_bounded_and_clean(locator: str, message: str) -> None:
    """The same rules a header value obeys, against a different party.

    The sink is trusted code, but a manifest field is a manifest field: an
    unbounded one makes the record unbounded, and a control character forges a
    line break wherever the record is later rendered.
    """

    with pytest.raises(ValueError, match=message):
        artifact(locator=locator)


def test_a_locator_at_the_bound_is_still_accepted() -> None:
    at_limit = "s3://b/" + "k" * (MAX_LOCATOR_CHARS - len("s3://b/"))

    assert len(artifact(locator=at_limit).locator) == MAX_LOCATOR_CHARS
