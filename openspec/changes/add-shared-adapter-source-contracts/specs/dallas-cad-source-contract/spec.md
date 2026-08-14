## MODIFIED Requirements

### Requirement: Adapter-local Dallas and vendor-neutral records
All parser-foundation records, value wrappers, provenance types, diagnostics, and conversion types
SHALL live in `property_tax_adapters`. This change MUST NOT modify `property_tax_domain` or
`property_tax_application` and MUST NOT introduce a domain type.

`DallasAppraisalSourceRecord` SHALL provide `account_num: str`, `appraisal_year: int`,
`gis_parcel_id: str`, `tot_val: SourceNativeDecimal`, `extras: Mapping[str, str]`, and
`provenance: DallasSourceProvenance`, and SHALL remain a county-native record in the Dallas module.

The vendor-neutral `AppraisalSourceRecord`, `SourceProvenance`, and `SourceNativeValue` SHALL be
imported from `property_tax_adapters.sources.contracts` rather than defined in the Dallas module.
Those shared types permit a null `source_account_id`, a null `source_family`, and a null
`source_status` so that a county whose accepted contract approves no account key remains
representable. Dallas SHALL NOT rely on that latitude.

The Dallas converter SHALL always emit `jurisdiction_code` equal to `tx-dallas`, a non-null
`source_account_id` taken from `account_num`, and a non-null `parcel_reference` taken from
`gis_parcel_id`. A Dallas record SHALL NOT be produced with a null account identifier or a null
parcel reference, and the parser SHALL continue to reject an empty `ACCOUNT_NUM` or
`GIS_PARCEL_ID` before a record is constructed, as it does today.

`DallasSourceProvenance` SHALL remain the county-native provenance and SHALL hold a shared
`SourceProvenance` as a field rather than subclassing it. The ordered observed header vector SHALL
remain available through Dallas provenance, and the observed and normalized header vectors SHALL be
carried on the shared provenance's `observed_fields` and `normalized_fields`.

Each key of `source_native_values` SHALL be the normalized header, and each value's `source_field`
SHALL equal that same normalized header, so the mapping key and the value agree. The ordered
observed headers remain provenance rather than value keys.

`source_family` and `source_status` SHALL be `None` for Dallas, which classifies neither.

An extra column whose observed text is empty SHALL continue to produce `lexical_text` and `value`
both equal to `""`. An empty observed text SHALL NOT be converted to `None`.

#### Scenario: Convert a valid Dallas source record
- **WHEN** a valid Dallas source record is converted at the adapter boundary
- **THEN** the output uses jurisdiction `tx-dallas`, copies the account and appraisal year, preserves the distinct parcel reference, retains source-native values and provenance, and creates no domain or application object

#### Scenario: Dallas never emits a null account identifier
- **GIVEN** any Dallas source record accepted by the parser
- **WHEN** it is converted to a vendor-neutral record
- **THEN** `source_account_id` is a non-empty `str`
- **THEN** `parcel_reference` is a non-empty `str`
- **THEN** `jurisdiction_code` is `tx-dallas`

#### Scenario: Value keys agree with the normalized header
- **GIVEN** a valid row carrying a required column and an unknown extra column
- **WHEN** the record is converted
- **THEN** every `source_native_values` key is the normalized header
- **THEN** every value's `source_field` equals its mapping key
- **THEN** the ordered observed headers are still available through provenance

#### Scenario: Keep TOT_VAL source-native
- **WHEN** a valid row contains `TOT_VAL`
- **THEN** the exact lexical text and parsed `Decimal` are retained under `source_native_values` with a source-native marker and no market, appraised, assessed, taxable, tax-amount, payment-status, delinquency, penalty, or interest field is populated or implied

#### Scenario: An empty extra column stays an empty text
- **GIVEN** a valid row whose unknown extra column is empty
- **WHEN** the record is converted
- **THEN** that column's `lexical_text` is `""`
- **THEN** that column's `value` is `""`
