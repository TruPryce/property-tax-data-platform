"""The package root is the vocabulary, and its shape is deliberate.

The enumeration below is written out rather than read from the implementation.
Reading it from `property_tax_domain.__all__` would make this test agree with
whatever the package happens to export, including after someone removed a name
seven county adapters import.
"""

from __future__ import annotations

import importlib

import pytest

EXPECTED_EXPORTS = frozenset(
    {
        "ARTIFACT_IDENTITY_HEX_LENGTH",
        "RECORD_CLASSIFICATIONS",
        "AccountIdentity",
        "AccountSnapshot",
        "AppraisalValueObservation",
        "ArtifactIdentity",
        "ArtifactReleaseBinding",
        "County",
        "CountySlug",
        "DomainProvenance",
        "ExemptionObservation",
        "ExemptionScope",
        "GeometryEncoding",
        "GeometryObservation",
        "INITIAL_COUNTIES",
        "ImprovementObservation",
        "Jurisdiction",
        "LandObservation",
        "LegalDescription",
        "MailingAddress",
        "OwnerAssociation",
        "OwnerObservation",
        "OwnerValueAllocation",
        "RecordClassification",
        "ReleaseIdentity",
        "ReleaseKind",
        "SitusAddress",
        "TaxableValueObservation",
        "TaxingUnitObservation",
        "ValueKind",
        "county_by_slug",
    }
)

#: Imported from the package root by the county adapters today. Dropping one is
#: not a refactor, it is seven broken modules.
PRE_EXISTING = frozenset({"County", "CountySlug", "INITIAL_COUNTIES", "county_by_slug"})


def test_the_export_set_matches_the_enumeration() -> None:
    package = importlib.import_module("property_tax_domain")

    assert set(package.__all__) == EXPECTED_EXPORTS


def test_the_pre_existing_api_is_retained() -> None:
    package = importlib.import_module("property_tax_domain")

    assert PRE_EXISTING <= set(package.__all__)
    for name in PRE_EXISTING:
        assert hasattr(package, name)


def test_every_exported_name_resolves() -> None:
    package = importlib.import_module("property_tax_domain")

    for name in sorted(EXPECTED_EXPORTS):
        assert hasattr(package, name), name


def test_a_consumer_needs_no_submodule_import() -> None:
    """Available from the root, so moving a file is not a breaking change.

    The root necessarily imports the submodules internally; what is asserted is
    that a *consumer* does not have to.
    """

    namespace: dict[str, object] = {}
    exec("from property_tax_domain import " + ", ".join(sorted(EXPECTED_EXPORTS)), namespace)  # noqa: S102

    for name in EXPECTED_EXPORTS:
        assert name in namespace


def test_serialization_operations_are_not_root_exports() -> None:
    """Operations on the vocabulary, not part of it."""

    package = importlib.import_module("property_tax_domain")

    for name in ("to_json", "release_document", "parse_compact_release", "serialization"):
        assert name not in package.__all__
    assert importlib.import_module("property_tax_domain.serialization") is not None


def test_the_root_re_exports_no_private_helper() -> None:
    package = importlib.import_module("property_tax_domain")

    assert not any(name.startswith("_") for name in package.__all__)
    for helper in ("require_identifier", "require_hex_digest"):
        assert helper not in package.__all__


@pytest.mark.parametrize("name", sorted(EXPECTED_EXPORTS))
def test_each_expected_name_is_declared_not_merely_reachable(name: str) -> None:
    """A name reachable by accident is not a published one."""

    package = importlib.import_module("property_tax_domain")

    assert name in package.__all__
