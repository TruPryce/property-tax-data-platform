"""Domain types for the Property Tax Data Platform.

The package root is the vocabulary. Consumers import these names from here
rather than from the module each happens to live in, so moving a file is not a
breaking change. Serialization functions are operations on this vocabulary
rather than part of it, and stay reachable through
`property_tax_domain.serialization`.
"""

from property_tax_domain.account import AccountIdentity, AccountSnapshot
from property_tax_domain.address import LegalDescription, MailingAddress, SitusAddress
from property_tax_domain.artifact import ARTIFACT_IDENTITY_HEX_LENGTH, ArtifactIdentity
from property_tax_domain.classification import RECORD_CLASSIFICATIONS, RecordClassification
from property_tax_domain.counties import INITIAL_COUNTIES, County, CountySlug, county_by_slug
from property_tax_domain.exemption import ExemptionObservation, ExemptionScope
from property_tax_domain.geometry import GeometryEncoding, GeometryObservation
from property_tax_domain.improvement import ImprovementObservation
from property_tax_domain.jurisdiction import Jurisdiction
from property_tax_domain.land import LandObservation
from property_tax_domain.owner import OwnerAssociation, OwnerObservation, OwnerValueAllocation
from property_tax_domain.provenance import DomainProvenance
from property_tax_domain.release import ArtifactReleaseBinding, ReleaseIdentity
from property_tax_domain.release_kind import ReleaseKind
from property_tax_domain.taxing_unit import TaxingUnitObservation
from property_tax_domain.value import AppraisalValueObservation, TaxableValueObservation, ValueKind

__all__ = [
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
]
