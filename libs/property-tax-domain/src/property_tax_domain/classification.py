"""Published identity classifications for canonical appraisal records."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from property_tax_domain.account import AccountIdentity, AccountSnapshot
from property_tax_domain.exemption import ExemptionObservation
from property_tax_domain.geometry import GeometryObservation
from property_tax_domain.improvement import ImprovementObservation
from property_tax_domain.land import LandObservation
from property_tax_domain.owner import OwnerAssociation, OwnerObservation, OwnerValueAllocation
from property_tax_domain.taxing_unit import TaxingUnitObservation
from property_tax_domain.value import AppraisalValueObservation, TaxableValueObservation

__all__ = ["RECORD_CLASSIFICATIONS", "RecordClassification"]


class RecordClassification(StrEnum):
    """The closed grain classification for canonical appraisal records."""

    STABLE_IDENTITY = "stable_identity"
    RELEASE_SNAPSHOT = "release_snapshot"
    CHILD_OBSERVATION = "child_observation"
    ASSOCIATION = "association"
    ENRICHMENT = "enrichment"


RECORD_CLASSIFICATIONS: Mapping[type[object], RecordClassification] = MappingProxyType(
    {
        AccountIdentity: RecordClassification.STABLE_IDENTITY,
        AccountSnapshot: RecordClassification.RELEASE_SNAPSHOT,
        OwnerObservation: RecordClassification.CHILD_OBSERVATION,
        OwnerAssociation: RecordClassification.ASSOCIATION,
        OwnerValueAllocation: RecordClassification.ASSOCIATION,
        AppraisalValueObservation: RecordClassification.CHILD_OBSERVATION,
        TaxingUnitObservation: RecordClassification.CHILD_OBSERVATION,
        TaxableValueObservation: RecordClassification.CHILD_OBSERVATION,
        ExemptionObservation: RecordClassification.CHILD_OBSERVATION,
        LandObservation: RecordClassification.CHILD_OBSERVATION,
        ImprovementObservation: RecordClassification.CHILD_OBSERVATION,
        GeometryObservation: RecordClassification.ENRICHMENT,
    }
)
