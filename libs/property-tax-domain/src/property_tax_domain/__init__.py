"""Domain types for the Property Tax Data Platform.

The package root is the vocabulary. Consumers import these names from here
rather than from the module each happens to live in, so moving a file is not a
breaking change. Serialization functions are operations on this vocabulary
rather than part of it, and stay reachable through
`property_tax_domain.serialization`.
"""

from property_tax_domain.artifact import ARTIFACT_IDENTITY_HEX_LENGTH, ArtifactIdentity
from property_tax_domain.counties import INITIAL_COUNTIES, County, CountySlug, county_by_slug
from property_tax_domain.jurisdiction import Jurisdiction
from property_tax_domain.provenance import DomainProvenance
from property_tax_domain.release import ArtifactReleaseBinding, ReleaseIdentity
from property_tax_domain.release_kind import ReleaseKind

__all__ = [
    "ARTIFACT_IDENTITY_HEX_LENGTH",
    "ArtifactIdentity",
    "ArtifactReleaseBinding",
    "County",
    "CountySlug",
    "DomainProvenance",
    "INITIAL_COUNTIES",
    "Jurisdiction",
    "ReleaseIdentity",
    "ReleaseKind",
    "county_by_slug",
]
