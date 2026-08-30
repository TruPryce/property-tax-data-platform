# Design

## Context

Two capabilities are promoted and neither has storage. `canonical-identity-and-provenance` fixes
jurisdiction, artifact, and logical-release identity and bounded provenance;
`canonical-appraisal-records` fixes twelve record types, three composed value objects, their grain,
their cardinality, and what they must make unrepresentable. `docs/engineering/canonical-appraisal-records.md`
records the implemented shapes and ends by saying that no DDL is selected there.

Five migrations exist. They persist the bytes that arrived, the runs that processed them, one row per
physical source row under its exact source names, the verdicts, the quality results, and the
publication pointer. None of that is the canonical model, and `infra/postgres/README.md` says so.

Everything below was measured against PostgreSQL 16.11 — the pinned runtime image — in a throwaway
container, not reasoned about. The measurements are recorded where they decide something.

## Decisions

### D1 — Forward migration topology

Ten forward migrations, `0006` through `0015`, one logical concern each, in this dependency order.
Nothing on `main` claims `0006` or beyond.

| # | file | creates | references a possibly-populated relation |
| --- | --- | --- | --- |
| 0006 | `0006_canonical_schema.sql` | `CREATE SCHEMA canonical`; the lexical helper functions; schema grants and `ALTER DEFAULT PRIVILEGES` | no |
| 0007 | `0007_canonical_release_identity.sql` | `canonical.release`, `canonical.artifact_release_binding` | `bronze.artifact` |
| 0008 | `0008_canonical_release_load.sql` | `canonical.release_load` and the deferred accepted-outcome gate | `ingestion.run`, `ingestion.release_outcome` |
| 0009 | `0009_canonical_provenance.sql` | `canonical.provenance` | `bronze.artifact` |
| 0010 | `0010_canonical_accounts.sql` | `canonical.account`, `canonical.account_snapshot`, the grain index | canonical relations |
| 0011 | `0011_canonical_owners.sql` | `canonical.owner_observation`, `owner_association`, `owner_value_allocation` | canonical relations |
| 0012 | `0012_canonical_values.sql` | `canonical.appraisal_value_observation`, `taxing_unit_observation`, `taxable_value_observation` | canonical relations |
| 0013 | `0013_canonical_exemptions.sql` | `canonical.exemption_observation` | canonical relations |
| 0014 | `0014_canonical_land_and_improvements.sql` | `canonical.land_observation`, `improvement_observation` | canonical relations |
| 0015 | `0015_canonical_geometry.sql` | `canonical.geometry_observation` | canonical relations |

**Privileges are not a slice.** `infra/postgres/AGENTS.md` requires the grants in the same migration
that creates the object, because a relation created without them is invisible to the role that needs
it and the omission surfaces in production. `ALTER DEFAULT PRIVILEGES` for the schema is set once in
`0006`, before any relation exists, which is the only ordering where it can cover all of them.

**Constraints and indexes are not a slice either.** A table created without its constraints is a
window during which the wrong rows can land, and this whole design is constraints.

**No diagnostic, quality, or publication migration is included**, because the audit in D15 found the
existing objects sufficient. The one genuinely missing object is the release-atomicity gate in `0008`.

Every migration sets `lock_timeout` and `statement_timeout`. `0007`, `0008`, and `0009` reference
relations that may be live; from `0010` onward each references canonical relations that may hold rows
by the time it is applied. Measured: adding a foreign key takes `ShareRowExclusiveLock` on the
**referenced** table, which blocks writes to it for the duration.

*Rejected — one migration for the whole canonical schema.* It is the same file whether it fails on
line 40 or line 900, and the half that succeeded is the half nobody can name afterwards.

*Rejected — a separate privileges migration.* It contradicts the repository rule and reintroduces the
exact failure mode that rule exists to prevent.

### D2 — Canonical `ReleaseIdentity` versus the existing Bronze model

Canonical `ReleaseIdentity` is `Jurisdiction + tax_year + ReleaseKind + release_identifier`. Audited
against what exists:

| existing object | carries | verdict |
| --- | --- | --- |
| `bronze.artifact` | SHA-256 only | Exactly `ArtifactIdentity`. Unchanged, and referenced. |
| `bronze.release_manifest` | jurisdiction, artifact, acquisition metadata | An acquisition event. Carries no `release_identifier`. Unchanged. |
| `bronze.release_partition` | `(manifest_id, jurisdiction_code, tax_year, release_kind)` | Three of the four components and **no `release_identifier`**. It is the artifact-partition fact, not a canonical release. Unchanged, and deliberately not read as one. |
| `ingestion.run` | all four components plus the manifest, with `UNIQUE (run_id, jurisdiction_code, release_identifier, tax_year, release_kind)` | The only place all four components already appear together. `release_identifier` is constrained only to "not blank" and `release_kind` to the open identifier grammar. |
| `ArtifactReleaseBinding` | the domain association | No persistence at all. Added. |

`canonical.release` holds the identity, enforcing the canonical rules the older columns do not: the
identifier grammar `^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$`, and the closed four-value kind vocabulary.
`canonical.release_load` binds one canonical release to one `ingestion.run` through **two composite
foreign keys that share the same four component columns**:

```
FOREIGN KEY (release_key, jurisdiction_code, tax_year, release_kind, release_identifier)
    REFERENCES canonical.release (release_key, jurisdiction_code, tax_year, release_kind, release_identifier)
FOREIGN KEY (run_id, jurisdiction_code, release_identifier, tax_year, release_kind)
    REFERENCES ingestion.run (run_id, jurisdiction_code, release_identifier, tax_year, release_kind)
```

Because both keys read the same columns, the canonical release a run loads **is** the release that run
processed. A Collin run cannot register a Dallas canonical release, and a run that processed the
certified partition cannot register the proposed one. Measured: a composite foreign key onto a
`UNIQUE` that includes an identity column refuses the mismatched pair.

**Fail closed, and nothing is derived.** A run whose `release_kind` is Denton `preliminary`, or whose
`release_identifier` carries a space or exceeds 128 characters, has no possible `canonical.release`
row — the check constraints refuse it. Without that row there is no `release_load`, and without a
`release_load` there are no canonical records. The evidence stays in Bronze and in adapter-grain
Silver with its lineage, exactly as `canonical-identity-and-provenance` requires under "Unresolved
release discrimination is blocked". No `release_identifier` is ever constructed from a filename, an
artifact digest, a tax year, a release kind, row order, an acquisition time, or any other field.

*Rejected — adding `release_identifier` to `bronze.release_partition`.* It edits history in spirit if
not in file, it would need a value for every existing partition, and the only values available are the
ones the promoted capability forbids inventing.

*Rejected — treating `ingestion.run` as the canonical release relation.* A run is a processing event;
several runs process one release, and a release exists before any run succeeds. Making the run the
identity would make re-running a release create a second release.

### D3 — `AccountIdentity` storage

`canonical.account` is `(jurisdiction_code, source_account_id)` with `UNIQUE (jurisdiction_code,
source_account_id)`. That constraint **is** the business identity. `account_key` is
`GENERATED ALWAYS AS IDENTITY` and is a persistence locator: it is documented as one in a
`COMMENT ON COLUMN`, and a hostile test reads `pg_index` to assert that no unique index covers
`source_account_id` alone.

Two counties publishing the same source account identifier are two rows and two accounts, because the
jurisdiction leads the key. No `county_fips` column exists: FIPS is validated registry metadata that
must not become a second, independent county identity, and `Jurisdiction` excludes it from equality.

### D4 — Account snapshot grain versus evidence divergence

The grain is `(AccountIdentity, ReleaseIdentity)`. Two snapshots may share that grain and carry
different artifacts, and the promoted capability requires both to remain expressible: *"the two
snapshots share a published grain, are not equal, and each retains its own lineage."*

**Chosen: one relation, one row per snapshot observation, with a non-unique grain index.**

```
canonical.account_snapshot (
    snapshot_key   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,   -- locator
    account_key, release_key, provenance_key, load_key, jurisdiction_code, ...
    UNIQUE (load_key, account_key, provenance_key)      -- one row per evidence, per load
)
CREATE INDEX account_snapshot_grain ON canonical.account_snapshot (account_key, release_key);
```

The grain is an **index**, not a constraint. Two observations of one account in one release from two
artifacts have two provenance rows and therefore two snapshot rows; neither excludes the other.
A `UNIQUE (account_key, release_key)` would collapse exactly the divergence the capability preserves,
and its absence is asserted by a catalog test rather than by intention.

Overwriting is prevented by privilege as well as by shape. `property_tax_ingestion` is granted
`SELECT, INSERT` and **not** `UPDATE` or `DELETE`. Measured: under that grant
`INSERT ... ON CONFLICT DO NOTHING` succeeds and `INSERT ... ON CONFLICT ... DO UPDATE` is refused
with `permission denied`, as are `UPDATE` and `DELETE`. A merge in task 3.5 that tried to overwrite
divergent evidence fails loudly instead of destroying it.

*Rejected — a normalized `snapshot_grain` relation with `snapshot_observation` children.* It invents a
grain entity the domain does not have, and it forces every child to choose a parent: hang children off
the grain row and an observation from artifact A acquires children from artifact B, which is the
cross-wiring this design exists to prevent. The domain has one `AccountSnapshot` type; the schema has
one relation.

*Rejected — `UNIQUE (account_key, release_key)` with a "latest wins" update.* It is the defect.

### D5 — `DomainProvenance` persistence

**Normalized behind a foreign key.** `canonical.provenance` holds `release_key`, `jurisdiction_code`,
`artifact_sha256`, `source_member_name`, `parser_contract_version`, `source_row_number`, and
`layout_fingerprint`. Every snapshot, observation, association, allocation, and enrichment carries
`provenance_key`, so the complete lineage — jurisdiction, tax year, release kind, release identifier,
artifact digest, member, row, parser contract version, layout fingerprint — is recoverable from any
record without its parent, by joining that one key.

Normalizing rather than inlining puts the anti-cross-wiring rule in **one** place instead of eleven.
Records derived from one source row share equal provenance values, which is what the capability says
they carry; equal values are one row.

**One release authority.** `canonical.provenance.release_key` is the only place a canonical record's
release is stated. No record relation carries a release identifier, tax year, or kind of its own.
Records do carry `release_key`, and it is not a second authority: it is pinned to the provenance's own
by `FOREIGN KEY (provenance_key, release_key) REFERENCES canonical.provenance (provenance_key,
release_key)`, so it cannot name a different release — the same technique `0001` uses when it says a
partition's county is the county of the artifact it partitions. `jurisdiction_code` on provenance is
pinned the same way, to `canonical.release`.

That pinned `release_key` is what makes child agreement structural. A child carries
`(snapshot_key, release_key)` and `(provenance_key, release_key)` as two composite foreign keys over
one shared column, so a child's provenance release equals its parent snapshot's release without a
trigger.

**Anti-cross-wiring, stated as the three keys that enforce it:**

| forbidden | refused by |
| --- | --- |
| provenance naming release R while its artifact belongs to another county | provenance's `(release_key, jurisdiction_code)` key into `canonical.release` |
| a child whose provenance names a different release than its parent | the shared `release_key` across the child's two composite keys |
| an account from one county under another county's release | the snapshot's two `(…, jurisdiction_code)` keys, into `canonical.account` and `canonical.provenance` |

*Rejected — six provenance columns inlined on every relation.* Sixty-six columns, eleven copies of the
anti-cross-wiring rule, and eleven places for one of them to be omitted.

*Rejected — provenance as JSONB.* It is the escape hatch the capability forbids, and no key can
constrain it.

### D6 — Surrogate keys and one-to-many cardinality

Every canonical relation has a `*_key bigint GENERATED ALWAYS AS IDENTITY` primary key. Each is a
**persistence locator only**, carries a `COMMENT ON COLUMN` saying so, and is never the relation's only
uniqueness where a business identity exists (`canonical.release` and `canonical.account` each also
carry the natural key as a `UNIQUE`).

**No relation carries a `UNIQUE` derived from its payload or its kind.** Nothing in the promoted
capability establishes that one snapshot has at most one market value, at most one owner, at most one
improvement, or at most one geometry, so no constraint says it. The only uniqueness on a parented
relation is its per-load evidence identity from D17, which is composed of locators and never of
observed values. Deduplicating by resemblance has no representation here rather than being merely
discouraged.

The falsification suite inserts two of each — owner observations, owner associations, allocations,
land records, improvements, geometries — under one snapshot and asserts all survive, and separately
reads `pg_index` and asserts no unique index over a parented relation includes an observed value.

`UNIQUE` constraints that *do* exist on parented relations exist only as composite foreign-key targets
that keep a reference inside its own snapshot — `(owner_key, snapshot_key)`,
`(association_key, snapshot_key)`, `(association_key, release_key)`, `(taxing_unit_key, snapshot_key)`.
Each includes the relation's own locator, so it constrains nothing about how many rows exist.

### D7 — Record-to-relation mapping

Shared by every canonical relation unless stated: `<x>_key bigint GENERATED ALWAYS AS IDENTITY
PRIMARY KEY` (locator); `snapshot_key`, `release_key`, `provenance_key`, `load_key` all `bigint NOT
NULL`; the three composite foreign keys
`(snapshot_key, release_key) -> canonical.account_snapshot`,
`(provenance_key, release_key) -> canonical.provenance`,
`(load_key, release_key) -> canonical.release_load`;
write role `property_tax_ingestion` with `SELECT, INSERT` and no `UPDATE` or `DELETE`; read role
**none** — `property_tax_api` is granted nothing, including schema usage.

Lexical kinds are named, not restated: **identifier**, **label**, **address component**, **amount**,
**magnitude**, **percentage**, **instant**, **year**, exactly as D8 fixes them.

#### Identity and lineage relations

| relation | columns | null | domain grain | PK | UNIQUE | checks |
| --- | --- | --- | --- | --- | --- | --- |
| `canonical.release` | `release_key`; `jurisdiction_code`; `tax_year`; `release_kind`; `release_identifier`; `first_recorded_at` | all NOT NULL | `ReleaseIdentity` | `release_key` (locator) | `(jurisdiction_code, tax_year, release_kind, release_identifier)` **business identity**; `(release_key, jurisdiction_code)`; `(release_key, jurisdiction_code, tax_year, release_kind, release_identifier)` | jurisdiction code grammar; `tax_year` 1900–2200; kind in the closed four; identifier is an **identifier** |
| `canonical.artifact_release_binding` | `artifact_sha256`; `release_key`; `first_recorded_at` | all NOT NULL | `ArtifactReleaseBinding` | `(artifact_sha256, release_key)` | — | FK to `bronze.artifact` and `canonical.release`; many-to-many both ways |
| `canonical.release_load` | `load_key`; `release_key`; `run_id`; `jurisdiction_code`; `tax_year`; `release_kind`; `release_identifier`; `loaded_at` | all NOT NULL | none — a load event | `load_key` (locator) | `(release_key, run_id)` **retry anchor**; `(load_key, release_key)` | the two composite FKs of D2; deferred accepted-outcome gate |
| `canonical.provenance` | `provenance_key`; `release_key`; `jurisdiction_code`; `artifact_sha256`; `source_member_name`; `parser_contract_version`; `source_row_number`; `layout_fingerprint` | last two nullable, rest NOT NULL | `DomainProvenance` | `provenance_key` (locator) | `NULLS NOT DISTINCT (release_key, artifact_sha256, source_member_name, parser_contract_version, source_row_number, layout_fingerprint)`; `(provenance_key, release_key)`; `(provenance_key, jurisdiction_code)` | member name is an **identifier**; version `>= 1`; row number `>= 1`; fingerprint 64 lowercase hex |

#### Record relations

| record | relation | columns beyond the shared set | null | SQL type | parent FK | domain grain | allowed UNIQUE | checks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `AccountIdentity` | `canonical.account` | `account_key` as a locator, plus `jurisdiction_code`, `source_account_id`, and `first_recorded_at`; no snapshot, provenance, or load columns | NOT NULL | `bigint`, `text`, `text`, `timestamptz` | none | `(Jurisdiction, source_account_id)` | `(jurisdiction_code, source_account_id)` **identity**; `(account_key, jurisdiction_code)` | jurisdiction grammar; account id is an **identifier** |
| `AccountSnapshot` | `canonical.account_snapshot` | `account_key` as the account reference, then `jurisdiction_code`; `source_as_of`; `situs_street_address`, `situs_unit`, `situs_city`, `situs_state_code`, `situs_postal_code`; `legal_text`, `legal_subdivision`, `legal_block`, `legal_lot`; **no `snapshot_key` in the shared sense — it is this relation's own PK** | `source_as_of` and all situs/legal nullable | `bigint`, `text`, `timestamptz`, `text` | `(account_key, jurisdiction_code) -> canonical.account`; `(provenance_key, jurisdiction_code) -> canonical.provenance` | `(AccountIdentity, ReleaseIdentity)`, as a **non-unique** index on `(account_key, release_key)` | `(load_key, account_key, provenance_key)`; `(snapshot_key, release_key)` | `source_as_of` is an **instant**; situs components are **address components**; `legal_text` is a **label**, its parts **address components**; a legal part without `legal_text` is refused |
| `OwnerObservation` | `canonical.owner_observation` | `owner_name`; `mailing_addressee`, `mailing_street_address`, `mailing_unit`, `mailing_city`, `mailing_state_code`, `mailing_postal_code`, `mailing_country_code` | name NOT NULL, mailing all nullable | `text` | shared | none — an observation | `(owner_key, snapshot_key)` (FK target) | name is a **label**; mailing fields are **address components** |
| `OwnerAssociation` | `canonical.owner_association` | `owner_key`; `ownership_percentage`; `source_discriminator` | last two nullable | `bigint`, `numeric`, `text` | shared, plus `(owner_key, snapshot_key) -> canonical.owner_observation` | none | `(association_key, snapshot_key)`; `(association_key, release_key)` (FK targets) | percentage is a **percentage**; discriminator is an **identifier** |
| `OwnerValueAllocation` | `canonical.owner_value_allocation` | `association_key`; `kind`; `amount` — and **no `snapshot_key`**, because its parent is the association | NOT NULL | `bigint`, `text`, `numeric` | `(association_key, release_key) -> canonical.owner_association`; provenance and load as shared | none | none | kind in the closed three; amount is an **amount** |
| `AppraisalValueObservation` | `canonical.appraisal_value_observation` | `kind`; `amount` | NOT NULL | `text`, `numeric` | shared | none | none | kind in the closed three; amount is an **amount** |
| `TaxingUnitObservation` | `canonical.taxing_unit_observation` | `unit_code`; `unit_name` | name nullable | `text` | shared | none | `(taxing_unit_key, snapshot_key)` (FK target) | code is an **identifier**; name is a **label**; both source-native |
| `TaxableValueObservation` | `canonical.taxable_value_observation` | `taxing_unit_key`; `amount`; `basis` | **all NOT NULL** | `bigint`, `numeric`, `text` | shared, plus `(taxing_unit_key, snapshot_key) -> canonical.taxing_unit_observation` | none | none | amount is an **amount**; `basis` is a source-native **label**; the NOT NULL unit is what makes a property-wide taxable value unrepresentable |
| `ExemptionObservation` | `canonical.exemption_observation` | `classification`; `scope`; `amount`; `association_key` | last two nullable | `text`, `text`, `numeric`, `bigint` | shared, plus `(association_key, snapshot_key) -> canonical.owner_association` | none | none | classification is a source-native **label**; scope in `account`/`owner_association`; `(scope = 'owner_association') = (association_key IS NOT NULL)`; amount is an **amount** |
| `LandObservation` | `canonical.land_observation` | `source_discriminator`; `classification`; `area`; `area_unit` | all nullable | `text`, `text`, `numeric`, `text` | shared | none | none | discriminator is an **identifier**; classification is a source-native **label**; area is a **magnitude**; `(area IS NULL) = (area_unit IS NULL)` |
| `ImprovementObservation` | `canonical.improvement_observation` | the four above plus `year_built` | all nullable | as above plus `integer` | shared | none | none | as above, plus `year_built` is a **year** |
| `GeometryObservation` | `canonical.geometry_observation` | `encoding`; `payload_bytes`; `payload_text`; `crs` | payload columns individually nullable; `encoding` and `crs` NOT NULL | `text`, `bytea`, `text`, `text` | shared | none | none | see D10 |

#### Composed value objects

They have no independent grain and are not records, so they get no relation and no key. Each composes
into its owning relation as **named, prefixed, individually constrained columns**:

| value object | composes onto | columns |
| --- | --- | --- |
| `SitusAddress` | `canonical.account_snapshot` | `situs_street_address`, `situs_unit`, `situs_city`, `situs_state_code`, `situs_postal_code` |
| `LegalDescription` | `canonical.account_snapshot` | `legal_text` (required **label** when the object is present), `legal_subdivision`, `legal_block`, `legal_lot` |
| `MailingAddress` | `canonical.owner_observation` | `mailing_addressee`, `mailing_street_address`, `mailing_unit`, `mailing_city`, `mailing_state_code`, `mailing_postal_code`, `mailing_country_code` |

All-columns-absent means the object is absent, which is the optional case the capability allows; there
is therefore no way to record a present object whose every field is absent, which is the state it
rejects. `LegalDescription` alone has a required field, so
`legal_text IS NOT NULL OR (legal_subdivision IS NULL AND legal_block IS NULL AND legal_lot IS NULL)`
is a real constraint and is stated.

*Rejected — a relation per value object.* It would give a value object a surrogate key and an
independent grain, which is exactly what "they are not records" denies.

*Rejected — JSONB.* It is the escape hatch the capability names, and no column-level check reaches
inside it.

### D8 — Scalar mappings

| kind | SQL | rule, enforced as a check |
| --- | --- | --- |
| identifier | `text` | `^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$` — the same regular expression `0001` already uses for `release_kind`, and the exact behaviour of the domain's `require_identifier` |
| label | `text` | 1–256 characters, no control character, at least one non-whitespace character |
| address component | `text` | as label, bounded at 128 |
| amount | `numeric` — **no precision, no scale** | finite: rejects `NaN`, `Infinity`, `-Infinity`. No sign constraint, because the capability imposes none and some rolls carry negative adjustments. `0` is a value |
| magnitude | `numeric` — no precision, no scale | finite and `>= 0` |
| percentage | `numeric` — no precision, no scale | finite and `BETWEEN 0 AND 100` |
| instant | `timestamptz` | timezone-aware by the type itself; a naive value has no representation |
| year | `integer` | `BETWEEN 1600 AND 2200`. Distinct from `tax_year`, which is 1900–2200 |

**No floating point anywhere.** No `real`, `double precision`, or `float8` column exists in the
canonical schema, and a catalog test asserts it.

**Unconstrained `numeric` is chosen deliberately.** No accepted contract establishes a precision or a
scale, and `NUMERIC(p,s)` would silently round a county value to fit — the coercion the capability
forbids. Measured on 16.11: an unconstrained `numeric` stores
`12345678901234567890.123456789012345`, `0.000000000000000000001`, and `-0.5` exactly, and returns
`0.10` as `0.10` rather than `0.1`, so a `Decimal` round-trips with its scale intact.

Measured: `'NaN'::numeric = 'NaN'::numeric` is **true** in PostgreSQL, so the finite check is written
as three inequalities — `v <> 'NaN' AND v <> 'Infinity' AND v <> '-Infinity'` — which rejects all
three and admits `0` and `-5.25`. Written once as `canonical.is_finite(numeric)` rather than copied to
every column, for the same reason `platform.is_named` exists.

Control characters are written as the explicit range `[\u0000-\u001F\u007F-\u009F]`, which is
exactly Python's `unicodedata.category(c) == 'Cc'`. Measured: on 16.11 under UTF-8 the POSIX
`[[:cntrl:]]` class agrees on U+0085 and U+007F and correctly excludes U+00A0 — but its membership is
locale-dependent and the explicit range is not, and a hand-copied class is the drift `platform.is_named`
already exists to prevent. A test enumerates the `Cc` set from Python and asserts the database
refuses every member.

Absence is `NULL` everywhere. Nothing is trimmed, case-folded, padded, or coerced to fit; a value
outside its rule is refused.

### D9 — Closed vocabularies

`ValueKind`, `ExemptionScope`, `GeometryEncoding`, and the canonical `ReleaseKind` are **constrained
textual columns**, not PostgreSQL enum types.

| vocabulary | column | admitted values |
| --- | --- | --- |
| `ReleaseKind` | `canonical.release.release_kind`, `canonical.release_load.release_kind` | `proposed`, `certified`, `supplemental`, `current` |
| `ValueKind` | `appraisal_value_observation.kind`, `owner_value_allocation.kind` | `market`, `appraised`, `assessed` |
| `ExemptionScope` | `exemption_observation.scope` | `account`, `owner_association` |
| `GeometryEncoding` | `geometry_observation.encoding` | `wkb`, `wkt` |

Three reasons, in order of weight:

1. **The bridge needs it.** `canonical.release_load`'s composite key reaches `ingestion.run.release_kind`,
   which is `text`. An enum on one side makes that key uncreatable, and the alternative — an enum plus
   a redundant text column — is two facts that must agree.
2. **The repository already decided this.** `0003` enumerates twelve diagnostic codes as a `CHECK`
   with the reasoning "enumerated as a constraint rather than left open so a new failure mode has to be
   named in a migration someone reviews." `0004` and `0005` do the same for severity, rule family,
   product, and publication state. A canonical enum type would be the only closed set in the database
   expressed differently.
3. **The upgrade consequence is better.** Widening a `CHECK` is
   `DROP CONSTRAINT` then `ADD CONSTRAINT ... NOT VALID` and `VALIDATE CONSTRAINT`, which takes a
   `SHARE UPDATE EXCLUSIVE` lock rather than rewriting the table, and *narrowing* fails loudly against
   any row that violates it. `ALTER TYPE ... ADD VALUE` is irreversible — a value added to an enum
   cannot be removed — and the sort order is fixed at creation. A vocabulary that can only ever grow,
   silently, is the wrong shape for a closed one.

Both mechanisms are exact; the check is the falsifiable one, because a test reads
`pg_constraint.consrc` equivalent through `pg_get_constraintdef` and asserts the admitted set, and a
separate test inserts every value outside it and asserts each is refused.

**No canonical exemption vocabulary and no canonical taxing-unit registry are defined**, because no
accepted contract establishes either. `exemption_observation.classification`,
`taxing_unit_observation.unit_code` and `unit_name`, `taxable_value_observation.basis`, and the land
and improvement classifications are source-native **label** or **identifier** columns carrying what
the county said, verbatim.

### D10 — Geometry without PostGIS

No PostGIS, no `postgis` extension, no spatial type, no spatial index. A catalog test asserts the
installed extension set contains nothing geospatial and that no canonical column has a spatial type.

```
encoding      text  NOT NULL   CHECK (encoding IN ('wkb', 'wkt'))
payload_bytes bytea            -- WKB
payload_text  text             -- WKT
crs           text  NOT NULL
CHECK ((encoding = 'wkb') = (payload_bytes IS NOT NULL))
CHECK ((encoding = 'wkt') = (payload_text  IS NOT NULL))
CHECK (payload_bytes IS NULL OR octet_length(payload_bytes) BETWEEN 1 AND 8388608)
CHECK (payload_text  IS NULL OR octet_length(convert_to(payload_text, 'UTF8')) BETWEEN 1 AND 8388608)
```

**Two payload columns, one domain field.** SQL has no union type, and a single `bytea` column holding
UTF-8-encoded WKT would make the encoding a claim about bytes rather than a typed fact. The two
columns are joined by the two mutual-exclusion checks, which make exactly one populated and make it the
one the encoding names; the invariant that exposes them as the single domain `payload` is stated in a
`COMMENT ON TABLE` and asserted by tests that offer `wkb` with text and `wkt` with bytes and require
both to be refused.

`8388608` is 8 MiB, and the text bound is measured as UTF-8 bytes rather than characters — the
capability's own rule. Measured: `convert_to(text, 'UTF8')` is accepted inside a `CHECK` constraint on
16.11, and stating the encoding explicitly rather than relying on `octet_length(text)` removes the
dependency on the server encoding being UTF-8.

`crs` is required and bounded to 1–64 characters with no control character and at least one
non-whitespace character, stated as the source stated it. Nothing converts WKT to WKB, reprojects,
validates topology, or infers a coordinate reference.

**Multiplicity is preserved**: no unique constraint mentions `snapshot_key` on this relation, and a
test inserts two geometries under one snapshot and asserts both survive.

### D11 — Taxable values and taxing units

`canonical.taxable_value_observation.taxing_unit_key` is `NOT NULL` with
`FOREIGN KEY (taxing_unit_key, snapshot_key) REFERENCES canonical.taxing_unit_observation
(taxing_unit_key, snapshot_key)`. A taxable value without a taxing unit is not refused by a check — it
has no representable form. The composite key additionally requires the unit to belong to the same
snapshot.

There is no `taxable` member in any `ValueKind` check, no property-wide taxable relation, no default
taxing unit, and no column where `Jurisdiction` could stand in for a taxing unit. Several taxing units
on one account are several rows, each keeping its own unit and `basis`, and nothing selects one to
represent the account.

### D12 — Owner associations and allocations

`canonical.owner_observation` is an observation. It has no cross-release identity, no natural key over
`owner_name` or the mailing columns, and no unique constraint that would make two observations one
owner. `canonical.owner_association` is its own relation, and `canonical.owner_value_allocation` is
parented by the association — it carries `association_key` and, deliberately, **no `snapshot_key`**,
matching the domain exactly.

No column, generated column, view, materialized view, trigger, or default anywhere in the canonical
schema produces an account-level total from allocations. Enforced negatively and checked by catalog:
`pg_attribute.attgenerated` is empty for every canonical column, the set of views in `canonical` is
empty, and the set of non-internal triggers is exactly the one declared in D15.

`source_discriminator` is nullable on the association, on land, and on improvement, because a county
whose contract approves none must stay representable and no constraint may demand evidence a contract
has not established.

### D13 — Source-native values and labels

The D12 handoff from the canonical-appraisal planning work is preserved exactly, and the schema is
where it becomes structural rather than documentary.

**Unmapped source-native _value fields_ have nowhere to go in `canonical`.** There is no generic
value column, no `jsonb`, `json`, or `hstore` column, no array column, and no column named for a
source field. Dallas `TOT_VAL` and its components, Tarrant values without an accepted equivalence, a
property-wide taxable value, an account total assembled from allocations, and a canonical account for
a county whose source key is unapproved all remain in `silver.source_native_value` at adapter grain
with their lineage. A catalog test asserts the absence of every escape-hatch type and of any column
whose name matches a source-native vocabulary.

**Source-native _labels_ a canonical observation is defined to carry do enter, verbatim**, as bounded
**label** or **identifier** columns: `exemption_observation.classification`,
`taxing_unit_observation.unit_code` and `unit_name`, `taxable_value_observation.basis`,
`land_observation.classification`, and `improvement_observation.classification`. Carrying a county's
label is not canonicalizing it, and none of these columns is constrained to a vocabulary.

The existence of a SQL column is not permission to map an unresolved source field into it. That rule
cannot be enforced by the schema, which is why it is stated in the capability and tested at the
adapter boundary rather than claimed here.

### D14 — Publication permission remains separate

No canonical relation carries `publication_allowed`, `visibility`, `permission`, `redaction`,
`redaction_override`, `sensitive`, `suppressed`, or any equivalent. A catalog test queries
`information_schema.columns` for schema `canonical` and asserts the result set is empty for each.

`silver.field_publication_policy` **remains authoritative** for source-field publication, unchanged,
and **task 3.4 needs no forward migration to it.** It is keyed by `(jurisdiction_code, source_field)`
— by *source* field — so it does not describe canonical columns, and extending it to do so is work the
Gold projection boundary owns, not this one.

That gap has no consequence here because of the privilege decision: **`property_tax_api` is granted
nothing in the canonical schema, including `USAGE`.** The raw canonical schema holds owner names,
mailing addresses, situs addresses, and legal descriptions, and the reasoning `0002` already recorded
applies unchanged — no view, row policy, or privilege applies the field policy, so a `SELECT` would
return every value including those the policy denies. Measured: with schema usage withheld, a
`SELECT` by that role fails with `permission denied for schema` before any table grant is consulted.

Any future API read access must be justified against the Gold/publication boundary and its
default-deny policy, and is out of scope here.

### D15 — Existing diagnostics, quality, and publication objects

| migration | verdict | reasoning |
| --- | --- | --- |
| `0003` `ingestion.*` | **Satisfies 3.4 as-is** | Issue #43's bounded diagnostic contract is already implemented: twelve codes and no thirteenth, four columns and no fifth, an outcome sealed against its retained evidence by deferred constraint triggers, and constraints mirroring `ReleaseOutcome.__post_init__`. A canonical-grain diagnostic model would be a parallel replacement of a contract that is already correct. |
| `0004` `quality.*` | **Satisfies 3.4 as-is** | Rules are rows with configurable thresholds in eight families that already cover canonical-grain checks — required-key completeness, logical uniqueness, child relationship, value validity. Evaluations bind to `run_id`, and a canonical load binds to a run, so canonical data is evaluated through the existing model without a new relation. |
| `0005` `publication.*` | **Satisfies 3.4 as-is** | Publication binds to a run through a composite key, and the same run now reaches canonical rows through `canonical.release_load`. The known point-in-time admission gap stays task 6.2's, unchanged and unclaimed. |
| `0002` `silver.field_publication_policy` | **Satisfies 3.4 as-is** | See D14. |

**One object is genuinely missing, and it is the release-atomicity gate.** `0008` adds a deferred
constraint trigger on `canonical.release_load` requiring, at `COMMIT`, that the named run has an
`ingestion.release_outcome` with `disposition = 'accepted'`. Because the entire canonical load for a
release is one transaction and every canonical record references a `release_load`, this makes
*"a rejected release commits zero accepted records"* structural rather than a loader's promise —
which is precisely what issue #43 handed to task 3.4 and did not itself implement.

Deferred rather than immediate, mirroring `0003`'s own seal, because the loader may legitimately write
canonical rows before the outcome row exists within the same transaction; the judgement belongs at
`COMMIT`, when both halves exist. Measured: a deferred cross-schema constraint trigger fires at
`COMMIT` and aborts the transaction when the gate is not open, and admits it when the gate is opened
earlier in the same transaction.

Issue #43's diagnostics remain bounded, structured, release-atomic, and free of complete rows,
arbitrary values, addresses, credentials, and paths, because this change adds no diagnostic column
anywhere and does not touch `0003`.

### D16 — Upgrade path from `0001`–`0005`

Every one of `0006`–`0015` creates **new** relations in a **new** schema. Not one adds a column, a
`NOT NULL`, a `CHECK`, or a unique index to a relation that existed before. The only contact with
pre-existing relations is as a foreign-key *target* — `bronze.artifact` and `ingestion.run` — which
validates nothing against their existing rows because the referencing relations are empty.

Both states must therefore behave identically, and both are tested:

1. **Empty database.** `init` → `0001` → … → `0015`.
2. **Existing database.** `0001`–`0005` applied, with rows in `bronze.artifact`,
   `bronze.release_manifest`, `bronze.release_partition`, `ingestion.run`, `ingestion.release_outcome`,
   `silver.source_record` and its children → apply only `0006`–`0015`.

A structural comparison of the two resulting catalogs — relations, columns and types, constraints,
indexes, triggers, and privileges in schema `canonical` — must be identical, and a test asserts it.

**No backfill.** Pre-existing releases, runs, and source records gain no canonical counterpart. A
canonical row exists only where a loader creates it from evidence. Where an old row's
`release_identifier` or `release_kind` falls outside the canonical contract, no canonical release is
constructible for it and none is invented — the fail-closed answer from D2. No staged migration is
needed, because no new constraint is ever established over pre-existing rows.

### D17 — Idempotency target for task 3.5

Four concepts, kept apart:

| concept | what it is | where it lives |
| --- | --- | --- |
| **domain grain** | `(AccountIdentity, ReleaseIdentity)` for a snapshot; a parented record has none of its own | the non-unique index `account_snapshot (account_key, release_key)` |
| **evidence identity** | which release, artifact, member, row, parser contract, and layout produced this fact | `canonical.provenance` and its `NULLS NOT DISTINCT` natural key |
| **persistence surrogate** | a locator for foreign-key mechanics | every `*_key` identity column, commented as such |
| **retry / idempotency key** | has this release already been loaded by this run? | `canonical.release_load (release_key, run_id)` |

None is the others, and no relation collapses them into one "primary key" concept.

**The contract task 3.5 codes against.** A canonical load is one transaction. It begins with

```
INSERT INTO canonical.release_load (...) VALUES (...)
ON CONFLICT (release_key, run_id) DO NOTHING
RETURNING load_key
```

If a `load_key` comes back, this run has not loaded this release and the load proceeds under that key,
with every canonical row referencing it. If nothing comes back, the load already happened and the
transaction ends having done nothing. A retry is therefore safe by construction rather than by
comparing rows: it loses no divergent evidence, because it writes nothing; it deduplicates no
legitimate child row, because it inspects none; and it manufactures no natural key, because it uses
none.

`ON CONFLICT DO NOTHING` is available to `property_tax_ingestion`; `ON CONFLICT ... DO UPDATE` is not,
measured, because `UPDATE` is not granted. The unsafe form of the merge is unavailable rather than
discouraged.

**The consequence, stated rather than hidden.** Two *different* runs of one release produce two loads
and two complete record sets. That is divergence kept, not a defect — it is the same answer
`bronze.diverged_release` already gives, and the same reason `property_tax_ingestion` may not overwrite
a snapshot. Which load a consumer reads is chosen the way `publication.publication` already chooses:
by `run_id`, through `release_load`. Silver keeps every observation; selecting among them is the Gold
boundary's decision and task 6.2's to seal.

*Rejected — `UNIQUE (release_key)` on the load.* It reads well until a parser is corrected and the
release must be reprocessed, at which point the only way forward is to delete evidence.

*Rejected — a natural key per child relation over its observed values.* It is deduplication by
resemblance under another name, and D6 forbids it.

### D18 — Privileges

Migrations run as `property_tax_migrator`. Nothing here needs superuser.

| grantee | schema `canonical` | relations |
| --- | --- | --- |
| `property_tax_ingestion` | `USAGE` | `SELECT, INSERT` on every relation. **No `UPDATE`. No `DELETE`.** |
| `property_tax_api` | **nothing, not even `USAGE`** | nothing |

`ALTER DEFAULT PRIVILEGES FOR ROLE property_tax_migrator IN SCHEMA canonical GRANT SELECT, INSERT ON
TABLES TO property_tax_ingestion` is set in `0006`, before any relation exists, so a relation added by
a later migration is reachable without anyone remembering to come back — and it grants exactly the two
privileges, so a later relation cannot silently inherit `UPDATE`.

That last point is why the canonical relations live in a **new schema** rather than in `silver`.
`0002` set `ALTER DEFAULT PRIVILEGES … IN SCHEMA silver GRANT SELECT, INSERT, UPDATE`, and a canonical
relation created there would inherit `UPDATE` silently — the one privilege that would let a retry
overwrite divergent evidence. That default cannot be narrowed without either editing `0002` or
changing the rule for the adapter-grain relations too. A separate schema makes the distinction the
`README` already draws in prose — "`silver` here … is **not** the canonical Silver model" — structural,
and gives the canonical relations a privilege slate set once and set correctly.

No sequence grants are needed: every generated key is `GENERATED ALWAYS AS IDENTITY`, whose implicit
sequence is covered by `INSERT` on the relation.

Withdrawing a load is a `property_tax_migrator` operation, deliberately, for the same reason the
ingestion role may not rewrite an outcome in `0003`.

*Rejected — canonical relations in schema `silver` with an explicit `REVOKE UPDATE` per relation.*
It fights a default instead of not setting it, and the next relation someone adds inherits `UPDATE`
again unless they remember the revoke.

### D19 — Operational migration contract

Every one of `0006`–`0015`:

- is **forward-only**; there is no down migration and none is written;
- carries **one logical concern**;
- refuses to run without `-v file_sha256=…`, raising an exception rather than `\quit`, so the exit
  status is 3 and an operator's `&&` sees the failure;
- **refuses on reapply** — `RAISE EXCEPTION 'migration NNNN is already applied'`;
- **refuses when its prerequisite is missing** — `RAISE EXCEPTION 'migration NNNN-1 must be applied first'`;
- is **one transaction**, `BEGIN` to `COMMIT`, with its own ledger insert inside it;
- sets **`lock_timeout` and `statement_timeout`**, because each references a relation that may hold
  rows and adding a foreign key takes `ShareRowExclusiveLock` on the referenced one;
- records itself in `platform.schema_migration` with the operator-supplied file SHA-256;
- is **safe against an already-populated cluster**, by D16.

No statement in this set requires running outside a transaction, so none declares an exception.

`infra/postgres/README.md` must be updated in the same work: its apply loop enumerates `0001_*` through
`0005_*` literally, its "what each migration creates" table stops at `0005`, and its "What these are
not" section states that task 3.4 is incomplete.

### D20 — Scope boundary

This planning change does not modify `0001`–`0005`, add `0006`+ SQL, modify production Python,
implement the task-2.3 ports or the task-2.4 use cases, implement task-3.5 parsing or loading, apply
a migration to any shared or production database, resolve a county semantic question by inference,
enable sensitive publication, or check bootstrap task 3.4.

## The falsification plan

Every defect below must make a test fail. The tests inspect PostgreSQL catalogs, constraints, and
privileges against a real server rather than searching SQL source text, because a test that greps a
migration passes for a constraint that was written and never took effect.

| defect | how it is caught |
| --- | --- |
| the same `source_account_id` in two counties collides | insert both; assert two rows and two distinct `account_key`s; assert no unique index covers `source_account_id` alone |
| the same snapshot grain with different provenance is overwritten | insert two snapshots sharing `(account_key, release_key)` with different `provenance_key`; assert both persist; assert no unique index covers exactly `(account_key, release_key)` |
| a child relation accidentally enforces at-most-one | insert two of every parented record under one snapshot; assert all survive; assert no unique index on a parented relation includes an observed value |
| two geometries for one snapshot collapse | insert two; assert both persist with their own lineage |
| owner allocations are rolled up | assert no generated column, no view, and no undeclared trigger exists in `canonical`; assert no column name matches a total/sum/aggregate vocabulary |
| a taxable value exists without its taxing unit | attempt the insert with `NULL`; assert `not_null_violation`; attempt with a unit from another snapshot; assert `foreign_key_violation` |
| an unresolved source-native value enters a canonical `ValueKind` | insert every string outside `{market, appraised, assessed}`; assert each is refused |
| a county exemption label is forced into a canonical enum | assert `exemption_observation.classification` has no vocabulary constraint and accepts an arbitrary county label verbatim |
| a parented record is linked to provenance from another release | insert a child whose `provenance_key` belongs to another release; assert `foreign_key_violation` |
| artifact or release provenance can be cross-wired | attempt provenance whose `jurisdiction_code` differs from its release's; attempt a `release_load` whose run processed another release; assert both are refused |
| a persistence surrogate is exposed as stable business identity | assert every relation with a business identity also carries it as a `UNIQUE`; assert each `*_key` column comment names it a locator |
| WKT/WKB type disagreement is accepted | insert `wkb` with `payload_text`, and `wkt` with `payload_bytes`; assert both refused; insert both payload columns at once; assert refused |
| a negative magnitude is accepted | insert a negative `area`; assert refused; insert `0` and a positive value; assert accepted |
| a float-like or lossy money representation is introduced | assert no `real`, `double precision`, or `numeric(p,s)` column exists in `canonical`; round-trip a 35-digit `Decimal` and `0.10` and assert both come back unchanged |
| canonical records acquire publication permission | assert no column in `canonical` matches the publication, visibility, permission, or redaction vocabulary |
| `property_tax_api` gains unauthorized raw-Silver access | assert `has_schema_privilege('property_tax_api', 'canonical', 'USAGE')` is false and every table privilege is false; connect as that role and assert `SELECT` fails |
| a migration succeeds out of order | apply `0007` to a database at `0005`; assert it raises "migration 0006 must be applied first" and changes nothing |
| a migration reapplication succeeds | apply each file twice; assert the second raises "already applied" and the ledger still holds one row for it |
| an upgrade from a populated `0001`–`0005` database fails | populate, then apply `0006`–`0015`; assert every one succeeds |
| a clean rebuild and an upgrade produce structurally different schemas | build both; compare relations, columns, types, constraints, indexes, triggers, and privileges in `canonical`; assert identical |
| the ingestion role can overwrite a snapshot | as `property_tax_ingestion`, attempt `UPDATE`, `DELETE`, and `ON CONFLICT DO UPDATE`; assert each is `insufficient_privilege`; assert `ON CONFLICT DO NOTHING` succeeds |
| a rejected release leaves canonical rows | write a load for a run whose outcome is `rejected`; assert the transaction aborts at `COMMIT` |

## Risks

| risk | mitigation |
| --- | --- |
| Two runs of one release write two full canonical record sets, and nothing in Silver says which is current. | Stated as a consequence rather than hidden. Reads select through `release_load` by `run_id`, exactly as `publication.publication` already binds. Sealing which release is current stays task 6.2's. |
| The governed CountyForge implementation runner cannot author these files. Measured: `infra/` is outside `allowed_write_roots`, and `migrations/` matches `_HIGHER_RISK`, which raises unconditionally. | The implementation runs in the direct lane, like the archival lane that cannot write under `openspec`. Task 0.1 records this rather than discovering it at dispatch. |
| Adding a foreign key takes `ShareRowExclusiveLock` on `ingestion.run` and `bronze.artifact`, blocking writes while it is held. | `lock_timeout` in every migration, so the migration yields rather than queueing production behind it. |
| Geometry payloads of 8 MiB will TOAST and can grow the relation quickly. | Bounded per row by check, and geometry is an enrichment: nothing requires it to be loaded for a release to be accepted. |
| `canonical.provenance`'s natural key is six columns including a 64-character fingerprint, so its index is wide. | It is the only relation with a wide natural key, and it is written once per distinct source row rather than once per canonical fact. |
| A future canonical relation added in `silver` by mistake would inherit `UPDATE`. | Canonical relations live in their own schema, whose default privileges grant exactly `SELECT, INSERT`. A catalog test asserts no canonical relation grants `UPDATE` to the ingestion role. |

## Migration

Forward-only, `0006` through `0015`, applied in ascending order by an operator with
`-v file_sha256=…` per `infra/postgres/README.md`. There is no down migration. A disposable database
is rebuilt from empty; a real one is recovered through the ADR-0002 restore path. Existing rows are
untouched and un-backfilled.

## Unresolved decisions

None.

## Deferred to later tasks

- Extending field-level publication policy to canonical columns, and any bounded Gold projection that
  would let `property_tax_api` read canonical data. Task 4.x and 6.2.
- COPY-to-staging and set-based idempotent merges against these relations. Task 3.5.
- Continuous-integration PostgreSQL so these suites stop skipping. Task 3.6.
- Sealing quality for a published release, so `publication.current` is a maintained invariant rather
  than a check that passed once. Task 6.2, unchanged by this work.
- Dallas `TOT_VAL` semantics (#58) and the Dallas extras boundary (#78). Until they are resolved, the
  affected values stay at adapter grain, which this design requires rather than merely permits.
