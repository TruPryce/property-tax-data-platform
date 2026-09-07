## ADDED Requirements

<!-- Owns: `CanonicalReleaseRepository`, `ReleaseLoadSession`,
     `CanonicalRecordBatch`, `CorrelatedRecord`, `CorrelationHandle`,
     adoption of a persisted snapshot, `ReleaseLoadCompletion`, the retry key,
     the no-natural-key rule, and the outcome-and-load unit of work.
     Cites: `processing-run` for `ProcessingRunRef` and
     `ReleaseProcessingOutcome`; `source-registry-and-discovery` for the
     promoted `ReleaseIdentity`; the accepted `canonical-appraisal-records`
     spec for the record types; the accepted `canonical-silver-persistence`
     spec for the snapshot grain, one-to-many children, cross-load lineage, and
     release-scoped retry. -->

### Requirement: A canonical load is a bounded session with release-atomic completion
The canonical persistence boundary SHALL expose one logical release load as a session accepting successive bounded batches of canonical records, followed by exactly one completion or one abort. It SHALL NOT require a complete release to be held in memory, and it SHALL NOT make any batch durable before completion.

A session that aborts, or whose completion fails, SHALL leave zero canonical records for that load.

#### Scenario: A release is loaded in batches
- **WHEN** a caller writes several bounded batches and then completes the session
- **THEN** the records become durable together at completion and not before

#### Scenario: A load is abandoned partway
- **WHEN** a caller aborts after writing several batches
- **THEN** zero canonical records exist for that load

#### Scenario: A whole release is not materialised
- **WHEN** the session contract is examined
- **THEN** no operation requires a complete release as a single in-memory collection

### Requirement: Parent linkage is resolved by bounded, account-scoped correlation
The canonical persistence boundary SHALL allow one account's records to span more than one bounded batch, and SHALL provide a correlation mechanism by which a record names a parent written in an earlier batch.

That correlation SHALL be carried by the batch rather than by the canonical records, which hold their parents directly and SHALL NOT gain a correlation field. A batch entry SHALL pair one canonical record with the correlation value it can later be named by, where it may be a parent, and with the correlation value of its parent. A parent SHALL be named the same way whether it appears in the same batch or an earlier one, so there is one linkage mechanism rather than two.

Each batch SHALL declare which correlation values must remain resolvable after it, and an implementation MAY release every mapping not so declared. Live mappings SHALL therefore be bounded by what the most recent batch declared, and that declaration SHALL be bounded because the batch is. Without this the bound fails inside a single account: an account carrying an unbounded number of owner associations whose allocations arrive in later batches would keep every association's mapping live until the account completed, so allowing only one continuing account SHALL NOT be claimed to bound correlation on its own.

A correlation value SHALL be unique within one load session, and SHALL NOT be reused once its account is complete. Because the session releases the mapping for a completed account, uniqueness SHALL be enforced by requiring values to increase strictly over the session and by retaining the highest value yet introduced: any value not exceeding it SHALL be refused unless it is currently live. That state is a single value, so the bound is unaffected, and a late record naming a released value SHALL be refused rather than silently retargeted at a later account.

A correlation value SHALL be neither domain identity nor persistence identity, SHALL carry no meaning outside the session, and SHALL NOT appear in any persisted record as a business value. An implementation SHALL retain a parent mapping only for values still needed as parents, releasing those whose account is complete.

Validation authority SHALL be split according to what each party can know. A batch is an immutable value and knows only itself, so it SHALL validate its own shape alone: well-formed entries, no value introduced twice within it, parents named within it resolving within it, and at most one account named as continuing. Everything requiring session history SHALL be validated by the session on write and on account completion — whether a value duplicates one already live, whether a named parent was ever introduced, whether its account has since completed, and whether the continuing-account state is consistent with the previous batch.

A resolved correlation value SHALL denote the very parent the canonical record already holds. Resolving is not sufficient: a record whose embedded parent is one observation SHALL NOT be accepted paired with a correlation value denoting a different one, because the record would then be persisted under a parent its own domain value does not name. Where the parent appears in the same batch, the batch SHALL enforce this; where it was introduced earlier, the session SHALL, since it already retains what each live value denotes. A batch SHALL NOT be required to know handles opened by earlier batches or accounts already completed, because it cannot.

Every account a batch introduces SHALL be complete at the end of that batch, except at most one, which the batch SHALL name as continuing into the next. An implementation SHALL therefore retain, beyond a single bounded batch, only the correlation values of one continuing account, and only for records actually named as parents. Correlation SHALL NOT require memory proportional to the release, to the number of accounts in it, or to a continuing account's complete descent.

A correlation value that duplicates one already live, that names a parent never introduced, or that names one whose account is complete, SHALL be refused by the session.

#### Scenario: A record is paired with its correlation
- **WHEN** a batch entry is examined
- **THEN** it pairs the canonical record with the value it may be named by and the value naming its parent, and the canonical record itself carries no correlation field

#### Scenario: One account spans several batches
- **WHEN** an account's owners are written in one batch and its allocations in a later batch of the same account
- **THEN** the later records name their parents by the values the earlier batch introduced

#### Scenario: A batch leaves two accounts incomplete
- **WHEN** a batch would leave more than one account continuing into the next
- **THEN** it is refused, so at most one account is ever open across a batch boundary

#### Scenario: A duplicate correlation value is introduced
- **WHEN** a batch introduces a correlation value already live in the session
- **THEN** the session refuses the write

#### Scenario: A batch is validated on its own
- **WHEN** a batch is constructed
- **THEN** it rejects only what it can see — a value introduced twice within it, a parent named within it that resolves nowhere in it, or more than one account named as continuing — and does not attempt to judge handles from earlier batches

#### Scenario: A correlation value denotes a parent the record does not hold
- **WHEN** a record embedding one parent is paired with a correlation value denoting a different parent of the same kind
- **THEN** the write is refused, even though the value resolves

#### Scenario: A batch names a parent from an earlier batch
- **WHEN** a batch names a parent it does not itself contain
- **THEN** the batch accepts it as well-formed, and the session decides whether that parent is live

#### Scenario: An account with very many children is loaded
- **WHEN** an account carries far more children than one batch should hold
- **THEN** it is written across several bounded batches, and neither the caller nor the implementation is required to hold the whole account

#### Scenario: A correlation value outlives its account
- **WHEN** a record names a correlation value whose account has been declared complete
- **THEN** the write is refused

#### Scenario: A completed correlation value is minted again
- **WHEN** a later batch introduces a value already used by an account that has completed
- **THEN** it is refused, because values must exceed the highest yet introduced, so a released value cannot be silently retargeted

#### Scenario: A parent is still needed several batches later
- **WHEN** a parent's children arrive in a later batch of the same account
- **THEN** every batch between them declares that parent's value as still needed, and the implementation may release everything it does not declare

#### Scenario: An account carries more parents than a batch can hold
- **WHEN** one account's parents outnumber what a bounded batch may declare as still needed
- **THEN** the port refuses nothing and names no spill: the declaration is what bounds live mappings, a durable spill belongs to the implementation, and a caller that declares more than it can hold is bounded by that account rather than by the release

#### Scenario: Correlation state is examined for growth
- **WHEN** the boundary is examined
- **THEN** nothing requires an implementation to retain correlation beyond one bounded batch except for the single continuing account, so the state grows with neither the release nor the number of accounts in it

### Requirement: A child may name a parent persisted by an earlier load
A correlation value SHALL be obtainable for an account snapshot already persisted for the release being loaded, so a child arriving from a second artifact of the same release can name its existing parent instead of resubmitting it.

**Adoption SHALL name that snapshot by an opaque locator, never by its grain.** The account identity and release are a snapshot's *grain*, and the accepted canonical contract makes that grain deliberately non-unique: two snapshots sharing an account and a release with different provenance are both retained, and the grain SHALL NOT be expressed as a uniqueness constraint. Identifying a parent by grain is therefore ambiguous exactly in the divergence case this boundary exists to preserve, and would let an enrichment attach to whichever observation a lookup happened to return.

The boundary SHALL therefore expose the snapshots persisted for an account and release as candidates, each pairing an opaque locator with **the account snapshot value it locates**, so a caller selects on the whole observation. That locator SHALL carry the same terms as every other locator here: comparable for equality, carrying no ordering, freshness, or precedence meaning, and never canonical identity.

**Adoption SHALL accept the candidate, not the locator alone.** A record naming an in-batch parent is checked against the very object the canonical value holds, compared by identity rather than by value, because two legitimate parents can be equal. An adopted parent SHALL be held to that same check, and a locator alone does not permit it: the session would have a handle bound to a reference and no object to compare a child's parent against, so the one class of parent reached across loads would be the one nothing verified. Taking the candidate — which already carries both the locator and the snapshot it locates — binds the handle to that exact object, and a child naming the handle SHALL be refused unless the snapshot it holds is that same object.

A caller SHALL therefore construct children against the snapshot the candidate carried, rather than an equal value built elsewhere.

**Adoption SHALL verify that the candidate's two halves agree.** A candidate is an ordinary value a caller can construct, so nothing prevents pairing a valid locator with a snapshot it does not locate — and a boundary that trusted the pair would bind the handle to an object the locator never named, which is the original defect reintroduced through the fix for it. Adoption SHALL resolve the locator and SHALL refuse with a named error unless the snapshot it locates equals the snapshot the candidate carries. The verified pair is what makes the handle trustworthy; a candidate obtained from the boundary's own candidate access SHALL always satisfy it.

The candidate SHALL carry the snapshot rather than its provenance alone. Provenance does not distinguish them: the accepted persistence contract retains two snapshots **sharing one load, account, release, and provenance** that differ only in a composed situs address or legal description, and refuses any uniqueness over load, account, and provenance that would collapse them. A candidate offering only provenance would present those two as one, which is the ambiguity this requirement exists to remove, moved one field along. Where two candidates are equal as domain values they are indistinguishable by construction, and either is a correct parent.

The number of candidates for one account and release SHALL NOT be assumed bounded. One acquisition may persist several snapshots at one grain, so a per-acquisition bound is not one the accepted contract supports.

Candidate access SHALL therefore be **lazy and expressed as one**: the operation SHALL return an iterator of candidates rather than a materialised collection, so an implementation yields them as they are drawn and a caller may stop at the one it wants. "Paged or streamed" as an adjective is not a contract — an implementation satisfies it by returning a list and calling the list a page — so the port SHALL state the shape that makes laziness observable, and an implementation SHALL NOT draw every candidate before the caller consumes the first.

#### Scenario: A caller stops at the first candidate it wants
- **WHEN** a caller iterates the candidates for an account and release and stops after the one it adopts
- **THEN** the implementation has not drawn the remainder, which is what distinguishes the iterator from a collection wearing its name

Adopting a parent SHALL create no observation and SHALL leave the existing snapshot unchanged, and the child SHALL retain its own load and artifact lineage rather than being attached to its parent's.

Where the locator resolves to no persisted snapshot for the release being loaded, adoption SHALL fail with a named error rather than creating one, and SHALL fail the same way for a locator belonging to another release.

A parent that is not an account snapshot SHALL NOT be adoptable, because the canonical model gives those observations no identity to name them by, and inventing one would be the natural key this boundary forbids. A child of such a parent SHALL therefore be written in the same session as that parent.

#### Scenario: A geometry enrichment arrives from a second artifact
- **WHEN** a child carrying provenance from a second load and artifact names an account snapshot already persisted for the same release
- **THEN** it is retained with its own artifact lineage, its parent is the existing snapshot, and no second snapshot is created

#### Scenario: An account has two snapshots at one grain and one is enriched
- **WHEN** an account has two persisted snapshots for one release differing in provenance, and a child from a third artifact must name one of them
- **THEN** the candidates are offered as locator-and-snapshot pairs, the caller adopts one candidate, and the child attaches to exactly that observation rather than to whichever the grain would have matched

#### Scenario: Two candidates share a provenance and differ only in a composed value
- **WHEN** an account has two persisted snapshots sharing one load, release, and provenance that differ only in a situs address or a legal description
- **THEN** both are offered as distinct candidates carrying their own snapshot values, and adopting one candidate attaches the child to that observation and not the other

#### Scenario: An account has more candidates than a caller wishes to hold
- **WHEN** the snapshots persisted for one account and release outnumber what a caller wants in memory
- **THEN** candidates are obtained lazily through the iterator, and neither the boundary nor the caller is required to hold all of them

#### Scenario: An adopted parent is named by a child holding an equal but different snapshot
- **WHEN** a child names an adopted handle while holding a snapshot equal in value to the adopted one but not the same object
- **THEN** it is refused, exactly as it would be for a parent introduced in the batch

#### Scenario: An adopted parent does not exist
- **WHEN** adoption is offered a candidate whose locator resolves to no snapshot persisted for the release being loaded, including one belonging to another release
- **THEN** it fails with a named error and no snapshot is created

#### Scenario: A candidate pairs a valid locator with a snapshot it does not locate
- **WHEN** adoption is offered a candidate assembled by the caller whose locator resolves to a snapshot other than the one it carries
- **THEN** it fails with a named error, because a handle bound to an object the locator never named is the ambiguity this requirement removes, arriving through the value meant to remove it

#### Scenario: Adoption is offered a grain instead of a candidate
- **WHEN** adoption is attempted by account identity and release rather than by a candidate
- **THEN** no such operation exists, because the grain does not identify one snapshot

#### Scenario: A deeper parent is offered for adoption
- **WHEN** adoption is attempted for an observation that is not an account snapshot
- **THEN** it is refused, because that observation has no declared identity to name it by

### Requirement: The processing outcome and the canonical load complete as one unit of work
The canonical load session SHALL own the relationship between the processing run, its accepted or rejected outcome with bounded diagnostics and notices, and the canonical load, such that the outcome and the load become durable together at one completion point.

The boundary SHALL NOT require an implementation to make the accepted outcome durable in one unit of work and the canonical load in another.

#### Scenario: An accepted release is completed
- **WHEN** a session carrying an accepted outcome is completed
- **THEN** the outcome and the canonical load become durable together

#### Scenario: A rejected release is completed
- **WHEN** a run's outcome is rejected
- **THEN** the outcome is recorded and zero canonical records are committed for that release

#### Scenario: The contract is examined for independent commits
- **WHEN** the boundary is examined
- **THEN** no arrangement of its operations requires the outcome and the load to be committed separately

### Requirement: Retry is scoped to one release and one processing run
The retry key SHALL be the pairing of a canonical release with the processing run that loaded it. Completing a load for a pairing that has already completed SHALL persist nothing further and SHALL return a bounded, machine-readable result stating that the load had already happened, rather than raising an error the caller must interpret.

Two distinct processing runs loading one canonical release SHALL be two loads, and the second SHALL NOT be treated as a retry of the first.

#### Scenario: A completed load is retried
- **WHEN** a load is completed again for the same release and the same run
- **THEN** the result reports that the load was already complete and nothing further is persisted

#### Scenario: A release is reprocessed by a second run
- **WHEN** a second processing run loads a release a first run already loaded
- **THEN** the result reports a new load rather than an already-complete one, and both loads are retained

#### Scenario: The retry key is inspected
- **WHEN** the retry key is examined
- **THEN** it is composed of a release and a run and of no observed value

### Requirement: The boundary defines no key over observed values
The canonical persistence boundary SHALL NOT define a natural key, a uniqueness rule, or a deduplication rule over observed canonical values. Submitting records that the canonical model admits SHALL NOT cause the boundary to discard, merge, or reject them on the basis of their values.

#### Scenario: Divergent evidence is submitted at one grain
- **WHEN** several account snapshots are submitted at one account and release grain, differing in provenance or in situs or legal description
- **THEN** all are accepted and retained, and none is treated as a duplicate of another

#### Scenario: Several children of one parent are submitted
- **WHEN** several children of an accepted one-to-many type, or several geometries, are submitted for one parent
- **THEN** all are accepted and none is collapsed

#### Scenario: Children arrive from another load of the same release
- **WHEN** children are submitted by a second load of the same logical release
- **THEN** they are retained alongside the first load's records
