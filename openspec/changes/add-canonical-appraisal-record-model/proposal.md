# Give the appraisal roll a canonical shape at its real grain

## Why

Task 2.1 settled who published a fact, which release it belongs to, and which
bytes carried it. It said nothing about what the fact *is*. There is no canonical
statement of what an account is, what a snapshot of one is, or at what grain its
owners, values, exemptions, land, and improvements live.

Task 3.4 cannot proceed without that, and it is the reason 3.4 is deliberately
unchecked. A schema written first answers those questions in table definitions,
and a primary key becomes domain semantics nobody decided. The accepted
normalization contract already forbids the shortcuts — no flattening one-to-many
facts into an account row, no deduplicating owner allocations, no manufacturing
an account total from them — but a rule stated in prose is enforced by whoever
remembers it. A rule stated in a shape is enforced by the shape.

## What changes

`property_tax_domain` gains the canonical appraisal vocabulary: an account
identity distinct from an account snapshot, owner associations at their own
grain, value observations that keep market, appraised, and assessed apart from
taxable, and child observations for exemptions, taxing units, land,
improvements, and geometry. Every record type is classified — stable identity,
release-scoped snapshot, child observation, association, or enrichment — and the
classification is asserted by a test rather than described in a comment.

Two of those shapes do real work beyond naming things.

**A taxable value cannot exist without the taxing unit it applies to.** Dallas
publishes several jurisdiction-specific taxable values, and its accepted
contract requires that each retain its jurisdiction and that no arbitrary one
become a property-wide taxable value. Making taxable a fourth member of a
value-kind enum on the account snapshot would make that forbidden value the
easiest thing to write. It is a separate record at taxing-unit grain instead, so
the property-wide taxable value has nowhere to live.

**An owner-scoped allocation cannot be an account total.** Denton and Ellis both
require ownership percentages and owner-scoped value and exemption allocations
preserved without roll-up. Those allocations hang off the owner association, not
the snapshot, so summing them into an account figure is not a rule to remember
but a value with no field to occupy.

## What this change does not do

No production code — this is the planning change for task 2.2. No PostgreSQL
migration, no Silver schema, no port or use case, no adapter change, no
orchestration, no publication behaviour. No new runtime dependency: these types
must be constructible without boto3, psycopg, Airflow, or a geospatial library,
and an architecture test proves it.

## Conservative where the evidence is not in yet

Four open issues own semantics this model must not settle by convenience.

**#58** — Dallas `TOT_VAL` and its components stay source-native. A canonical
`ValueKind` existing is not permission to map into it, and the model provides no
route from an unmapped source label to a canonical kind.

**#92** — no Dallas child natural keys, no PACS undivided-interest roll-up, no
account totals derived from owner allocations, and no publication permission for
owner, mailing, or situs fields. Representing a field is not permission to
publish it; `silver.field_publication_policy` stays default-deny.

**#59** — Collin's contract forbids approving `prop_id` as account identity until
duplicate groups are measured. So an account identity is constructible only where
a county contract approved a key, and a county without one keeps source-row grain
rather than being handed a fabricated identity.

**#60** — Dallas parent and child records stay representable with provenance
without inventing the child identity #92 owns.

No canonical exemption vocabulary is proposed, because no accepted contract
establishes one. Exemption classification stays source-native rather than
becoming an open string that looks canonical.
