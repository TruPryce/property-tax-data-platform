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

A refused batch SHALL contribute nothing to the load. Records are invisible before completion either way, which is exactly why this needs saying rather than assuming: an implementation that stages rows as they arrive and validates them afterwards would otherwise carry a rejected batch's rows to the same completion as the accepted ones, and no caller could tell until the load was already wrong. Whatever was staged for a refused batch — its rows, the parent mappings resolved for it, anything derived from it — SHALL leave no trace in the completed load, and SHALL NOT be resurrected by a later batch or by completion.

A session SHALL have exactly one terminal operation, and SHALL refuse every operation offered after it: a write, an adoption, a second completion, an abort following a completion, or a completion following an abort. Refusing SHALL be explicit rather than silent, because a caller extending a load it has already ended is a caller whose records would otherwise vanish without a word. Retrying the load itself is a separate session and is governed by the retry key.

Completion SHALL be refused while an account is still open. A batch naming an account as continuing promises a batch that continues it, and completing instead would persist a truncated account under a promise the caller never kept — a truncation nothing downstream could distinguish from a small account. The caller SHALL close it exactly as it closes every other account, with a final batch that does not name it as continuing; that batch MAY carry no entries and no deltas at all, because completion releases every value of that account still live. Closing SHALL NOT require the caller to enumerate what is live: a release delta is bounded by the maximum and the live set is not, which is the same arithmetic that ruled out a full per-batch declaration, and a closure that demanded the list would be unsatisfiable for exactly the accounts the deltas exist to serve. Aborting SHALL be permitted at any point, an open account included, because it persists nothing.

#### Scenario: A session is used after it ends
- **WHEN** a caller writes, adopts, completes, or aborts a session it has already completed or aborted
- **THEN** the operation is refused, rather than silently ignored or applied to a load that has ended

#### Scenario: A completion is attempted with an account still open
- **WHEN** a caller completes a session whose last batch named an account as continuing
- **THEN** it is refused, because that batch promised a batch continuing the account and nothing downstream could tell the truncation from a small account

#### Scenario: An account is closed by a batch carrying nothing
- **WHEN** a caller closes the last continuing account with a batch that carries no entries, no deltas, and names no account as continuing
- **THEN** it is accepted and completion releases what was live, so closing requires neither inventing a record nor enumerating a live set the maximum could not hold

#### Scenario: A closing batch would have to list an unbounded live set
- **WHEN** the account being closed has more live values than one batch's maximum could carry
- **THEN** it still closes, because closure releases nothing by name and completion sweeps the account

#### Scenario: An abort leaves an open account behind
- **WHEN** a caller aborts while an account is still continuing
- **THEN** it is permitted and zero canonical records exist for that load

#### Scenario: A release is loaded in batches
- **WHEN** a caller writes several bounded batches and then completes the session
- **THEN** the records become durable together at completion and not before

#### Scenario: A refused batch is followed by a completion
- **WHEN** a batch is refused and the caller corrects it, writes it again, and completes the session
- **THEN** the load holds the records of the accepted batches and none from the refused attempt, whatever an implementation staged before refusing it

#### Scenario: A load is abandoned partway
- **WHEN** a caller aborts after writing several batches
- **THEN** zero canonical records exist for that load

#### Scenario: A whole release is not materialised
- **WHEN** the session contract is examined
- **THEN** no operation requires a complete release as a single in-memory collection

### Requirement: Parent linkage is resolved by bounded, account-scoped correlation
The canonical persistence boundary SHALL allow one account's records to span more than one bounded batch, and SHALL provide a correlation mechanism by which a record names a parent written in an earlier batch.

That correlation SHALL be carried by the batch rather than by the canonical records, which hold their parents directly and SHALL NOT gain a correlation field. A batch entry SHALL pair one canonical record with the correlation value it can later be named by, where it may be a parent, and with the correlation value of its parent. A parent SHALL be named the same way whether it appears in the same batch or an earlier one, so there is one linkage mechanism rather than two.

Each batch SHALL carry **bounded deltas** to the set of correlation values that must remain resolvable: the values it newly requires to survive beyond it, and the values it no longer requires. The live set SHALL be the accumulation of those deltas across the session, and a batch SHALL NOT be required to re-declare it in full.

A complete re-declaration is what this replaces, and the reason is arithmetic: a full declaration must itself fit inside a bounded batch, so it would cap the live set at one batch's worth, and an account whose parents exceed that could never finish however the implementation stored them. Deltas keep every declaration bounded while letting the live set be as large as the caller's own retain-and-release discipline makes it.

Releasing SHALL therefore be explicit, and completing an account SHALL release every value of that account still live, so a caller that never releases is bounded by its account rather than by the release. An account SHALL be complete at the end of the batch that touches it unless that batch names it as continuing, and completion SHALL be determined that way alone: `continuing` already carries the fact, and a second operation declaring the same thing would be one fact with two sources a caller has to reconcile. Completion SHALL release atomically with the batch that completes it, and an explicit release delta and account completion SHALL be the only ways a value leaves the live set. An implementation MAY hold the live set durably rather than in memory, which is what allows a large retained set to stay resolvable; the boundary SHALL NOT name that mechanism, and SHALL NOT require the set to fit in memory.

The deltas SHALL be governed by six rules, because an accumulating set that each batch edits is only as trustworthy as the edits:

**Bounded against a stated maximum.** The session SHALL state one maximum for what a batch may carry — its entries together with both deltas, counted as a single total — fixed when the session opens and independent of the release, the account, the number of accounts, and the data. The caller SHALL be able to read that maximum, so it can size the batches it builds rather than discover the bound by refusal, and the session SHALL refuse any batch whose total exceeds it. The maximum SHALL be an integer of at least one that is not a boolean — a boolean is an integer in Python, and `True` would otherwise pass as a maximum of one — and SHALL count the same things every time: the entries a batch carries plus the values in each of its two deltas. It SHALL NOT change while the session is open, because a caller that read it to size the batch it is building has to be able to rely on the answer. The check SHALL belong to the session and not to the batch: an immutable value that knows only itself cannot know the session's maximum. Naming no maximum anywhere and calling the deltas bounded is what this replaces — *bounded* would then describe a well-behaved caller rather than a property something checks, and the memory argument below would rest on nothing.

**Validity.** A retained value SHALL be one this batch introduces or one live at the start of it, and SHALL belong to the account the batch names as continuing, because a value of an account complete at the end of this batch cannot survive it — retaining it asks for exactly what completion undoes, and the contradiction SHALL be refused rather than settled by preferring one. A released value SHALL be one live at the start of it, so a batch SHALL NOT release a value it introduces itself; releasing a value of an account the batch completes SHALL remain valid, completion sweeping whatever the caller does not release by name. Retaining or releasing a value that is neither SHALL be refused, so a delta cannot silently create or discard state that was never there. A batch introducing a value it does not retain SHALL be well-formed: that value is live for the batch that introduced it and is released at its end, which is the common case of a parent whose children arrive beside it — and is why releasing it explicitly is redundant rather than permitted.

**No repetition, and no contradiction, and no ordering to learn.** A value SHALL appear at most once in each delta. A value repeated within one delta SHALL be refused by the batch, which sees it without any history, rather than counted twice against the maximum or quietly collapsed — the same reasoning that refuses a value introduced twice within one batch. A value named in both deltas of one batch SHALL be refused rather than resolved by applying one before the other. There is no correct order to pick — retain-then-release and release-then-retain give opposite results for the same batch — so the boundary SHALL refuse the ambiguity instead of defining a precedence a caller must remember.

**Deltas apply at the batch boundary.** The deltas SHALL take effect once every record in their batch has been validated, binding on the batch after rather than within their own. A value a batch releases SHALL therefore stay resolvable to every record in that same batch, wherever those records sit in it, and SHALL be gone for the next. A caller may name a parent for the last time and release it in one write without ordering the batch's own contents, and no record's meaning SHALL depend on its position among its siblings.

**Atomicity.** The deltas of a batch SHALL take effect only if that batch is accepted in full, and SHALL take effect together with every other change that batch makes to session correlation state: the live set, the highest value yet introduced, which account is continuing, and the completion — with its releases — of every account the batch does not carry onward. A refused batch SHALL leave all of them exactly as they were, and SHALL leave no record of its own anywhere in the load, so a corrected retry is not refused for reusing values its own rejected attempt pushed the highest-yet past, is not judged against a continuing account it never established, and does not find an account closed by a batch that was never accepted. Adoption SHALL sit outside this, being its own accepted operation rather than part of a batch: a batch refused after an adoption SHALL leave the handle that adoption minted live, and the caller SHALL NOT be required to adopt again to retry.

**Account ownership.** The accounts a batch may edit SHALL be the accounts open in it: those it introduces, and the one account continuing into it, whether a previous batch left it open or an adoption opened it — which is what lets the batch that finally completes an account release values an earlier batch introduced. Retaining or releasing a value belonging to any other account SHALL be refused: correlation is account-scoped, and one account editing another's live set is the retargeting that strictly increasing values exist to prevent, arriving through the delta instead of through the handle.

Without deltas the bound fails inside a single account: an account carrying an unbounded number of owner associations whose allocations arrive in later batches would keep every association's mapping live until the account completed, so allowing only one continuing account SHALL NOT be claimed to bound correlation on its own.

A correlation value SHALL be an integer of at least one that is not a boolean, for the reason the maximum is: `True` is an integer in Python and would otherwise be a usable handle equal to one. It SHALL be unique within one load session, and SHALL NOT be reused once its account is complete. Because the session releases the mapping for a completed account, uniqueness SHALL be enforced by requiring values to increase strictly over the session and by retaining the highest value yet introduced: any value not exceeding it SHALL be refused unless it is currently live. That state is a single value, so the bound is unaffected, and a late record naming a released value SHALL be refused rather than silently retargeted at a later account.

A correlation value SHALL be neither domain identity nor persistence identity, SHALL carry no meaning outside the session, and SHALL NOT appear in any persisted record as a business value. An implementation SHALL retain a parent mapping only for values still needed as parents, releasing those whose account is complete.

Validation authority SHALL be split according to what each party can know. A batch is an immutable value and knows only itself, so it SHALL validate its own shape alone: well-formed entries, no value introduced twice within it, parents named within it resolving within it, at most one account named as continuing, no value in both deltas, and no release of a value it introduces itself. Everything requiring knowledge the batch does not have SHALL be validated by the session on write — the maximum a batch may carry, which is the session's and not the batch's; whether a value duplicates one already live; whether a released or retained value is live; whose account each value belongs to and whether that account is open; whether a named parent was ever introduced; whether its account has since completed; and whether the continuing-account state is consistent with the previous batch. Atomicity SHALL be the session's too, because only the session holds the state a refusal must leave unmoved.

A resolved correlation value SHALL denote the very parent the canonical record already holds. Resolving is not sufficient: a record whose embedded parent is one observation SHALL NOT be accepted paired with a correlation value denoting a different one, because the record would then be persisted under a parent its own domain value does not name. Where the parent appears in the same batch, the batch SHALL enforce this; where it was introduced earlier, the session SHALL, since it already retains what each live value denotes. A batch SHALL NOT be required to know handles opened by earlier batches or accounts already completed, because it cannot.

Every account a batch introduces SHALL be complete at the end of that batch, except at most one, which the batch SHALL name as continuing into the next. An account continuing into a batch — left open by the previous batch or opened by an adoption since it — SHALL be either completed by that batch or named as continuing again by it, so exactly one account is open across any batch boundary and every batch knows which account it inherited — which is what makes the accounts open in a batch a set the boundary can name. An implementation SHALL therefore retain, beyond a single bounded batch, only the correlation values of one continuing account, and only those retained and not yet released. Correlation SHALL NOT require memory proportional to the release, to the number of accounts in it, or to a continuing account's complete descent — and where one continuing account's retained set is itself large, an implementation MAY hold it durably rather than in memory, which is the case a bounded per-batch declaration could not express.

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

#### Scenario: A batch drops the account continuing into it
- **WHEN** a batch neither completes the account that continued into it nor names it as continuing again
- **THEN** it is refused, because an account cannot be left open with no batch carrying it

#### Scenario: A correlation value is a boolean
- **WHEN** a batch introduces a correlation value that is a boolean
- **THEN** it is refused, because a boolean is an integer in Python and `True` would otherwise be a handle equal to one

#### Scenario: A duplicate correlation value is introduced
- **WHEN** a batch introduces a correlation value already live in the session
- **THEN** the session refuses the write

#### Scenario: A batch is validated on its own
- **WHEN** a batch is constructed
- **THEN** it rejects only what it can see — a value introduced twice within it, a value repeated within one delta, a value in both of its deltas, a parent named within it that resolves nowhere in it, more than one account named as continuing, or a release of a value it introduces itself — and judges neither handles from earlier batches nor its own size against the session's maximum, knowing neither

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
- **THEN** the batch that introduced the parent retained its value once, no batch between them re-declares it, and it stays resolvable until a batch releases it or its account completes

#### Scenario: An account carries more parents than one batch could enumerate
- **WHEN** one account's live parents outnumber what a single bounded batch could have listed
- **THEN** the account still completes, because each batch contributed bounded retain and release deltas rather than a full declaration, and the port refuses nothing and names no mechanism for holding the accumulated set

#### Scenario: A released value is named afterwards
- **WHEN** a batch releases a correlation value and a record in a later batch names it
- **THEN** it is refused, because release is explicit and a released value is gone whatever an implementation still holds

#### Scenario: A caller never releases within an account
- **WHEN** a caller retains every value it introduces and releases none until the account completes
- **THEN** the live set is bounded by that one account and is released in full at completion, rather than growing with the release

#### Scenario: Correlation state is examined for growth
- **WHEN** the boundary is examined
- **THEN** correlation state grows with neither the release nor the number of accounts in it: only one continuing account's values outlive a batch, and that account's set is what the caller retained and has not released — which the boundary permits an implementation to hold durably rather than in memory

#### Scenario: A delta names a value that is neither live nor introduced here
- **WHEN** a batch retains or releases a correlation value it does not introduce and which is not live
- **THEN** it is refused, so a delta cannot create or discard state that was never there

#### Scenario: One batch both retains and releases one value
- **WHEN** a batch names one correlation value in both its retain and its release delta
- **THEN** it is refused rather than resolved by an ordering rule, because the two orders give opposite results and neither is more correct

#### Scenario: A refused batch leaves session correlation state alone
- **WHEN** a batch is refused for any reason after carrying retain and release deltas
- **THEN** the live set, the highest value yet introduced, and which account is continuing are each exactly what they were before, so a retry reasons about no half-applied edit

#### Scenario: A corrected batch reuses the values its rejected attempt introduced
- **WHEN** a refused batch had introduced values above the highest yet introduced, and the caller retries a corrected batch carrying those same values
- **THEN** they are accepted, because the refusal moved the highest yet introduced no more than it moved the live set

#### Scenario: A refused batch does not establish its continuing account
- **WHEN** a batch naming an account as continuing is refused, and the next batch names the account the last accepted batch left continuing
- **THEN** it is accepted, because the refused batch's continuing-account claim never took effect

#### Scenario: A batch that would complete an account is refused
- **WHEN** a batch that names an account as continuing no further is refused
- **THEN** that account is still open and every value of it still resolves, because the completion and its releases take effect only with the batch that carries them

#### Scenario: An account completes without any separate declaration
- **WHEN** a batch touches an account and does not name it as continuing
- **THEN** that account is complete at the end of the batch and every value of it still live is released, with no second operation declaring it and no way for the two to disagree

#### Scenario: A batch retains a value of an account it completes
- **WHEN** a batch retains a correlation value belonging to an account it does not name as continuing
- **THEN** it is refused, because the retain asks the value to outlive the batch and the completion releases it at that batch's end

#### Scenario: A batch releases a value of an account it completes
- **WHEN** a batch releases some of a completing account's values by name and leaves the rest
- **THEN** it is accepted and the completion sweeps the rest, so an exhaustive release is a caller's option and never its obligation

#### Scenario: A batch releases another account's value
- **WHEN** a batch releases a correlation value belonging to an account that is neither introduced by it nor continuing into it from the previous batch
- **THEN** it is refused, because correlation is account-scoped and one account editing another's live set is retargeting by another route

#### Scenario: The batch that completes a continuing account releases its values
- **WHEN** the batch completing an account that continued into it releases values an earlier batch introduced, and names that account as continuing no further
- **THEN** it is accepted, because the accounts a batch may edit are those open in it rather than only those it introduces or carries onward

#### Scenario: A value is introduced and not retained
- **WHEN** a batch introduces a correlation value, names it as a parent within that same batch, and does not retain it
- **THEN** the batch is well-formed, and the value is released at the end of it

#### Scenario: A batch carries more than the session's maximum
- **WHEN** a batch's entries and its two deltas together exceed the maximum the session states
- **THEN** the session refuses it on write, so the deltas are bounded by something that checks rather than by the caller's good behaviour

#### Scenario: A caller sizes its batches before building them
- **WHEN** a caller asks the session what a batch may carry
- **THEN** it reads one integer of at least one, fixed for the session, counting the entries a batch carries plus the values in each of its two deltas, and does not have to find the bound by being refused

#### Scenario: A maximum that is not a usable count
- **WHEN** a session states a maximum that is zero, negative, not an integer, or a boolean
- **THEN** it is refused as a session no caller can use, the boolean named because it is an integer in Python and `True` would otherwise pass as a maximum of one

#### Scenario: The maximum changes while the session is open
- **WHEN** a session states one maximum and later states a different one
- **THEN** it breaks the contract, because a caller sized the batch it is building against the first answer

#### Scenario: A delta names one value twice
- **WHEN** a batch repeats a correlation value within its retain delta or within its release delta
- **THEN** the batch refuses it on its own, rather than counting it twice against the maximum or quietly collapsing it

#### Scenario: A batch releases a value it introduced itself
- **WHEN** a batch names a correlation value in both the entries it introduces and its release delta
- **THEN** it is refused as redundant, because an introduced value the batch does not retain is released at the end of it anyway

#### Scenario: A parent is named and released in one batch
- **WHEN** a batch names a live correlation value as the parent of records it carries and also releases that value
- **THEN** every record in that batch resolves it and the batch after does not, because deltas take effect at the batch boundary rather than between the records of a batch

#### Scenario: A released parent is named by an earlier record of the same batch
- **WHEN** a batch releases a correlation value and a record positioned before the release in that same batch names it
- **THEN** it resolves, because no record's meaning depends on where it sits among its siblings

### Requirement: A child may name a parent persisted by an earlier load
A correlation value SHALL be obtainable for an account snapshot already persisted for the release being loaded, so a child arriving from a second artifact of the same release can name its existing parent instead of resubmitting it.

**Adoption SHALL name that snapshot by an opaque locator, never by its grain.** The account identity and release are a snapshot's *grain*, and the accepted canonical contract makes that grain deliberately non-unique: two snapshots sharing an account and a release with different provenance are both retained, and the grain SHALL NOT be expressed as a uniqueness constraint. Identifying a parent by grain is therefore ambiguous exactly in the divergence case this boundary exists to preserve, and would let an enrichment attach to whichever observation a lookup happened to return.

The boundary SHALL therefore expose the snapshots persisted for an account and release as candidates, each pairing an opaque locator with **the account snapshot value it locates**, so a caller selects on the whole observation. That locator SHALL carry the same terms as every other locator here: comparable for equality, carrying no ordering, freshness, or precedence meaning, and never canonical identity.

**Adoption SHALL accept the candidate, not the locator alone.** A record naming an in-batch parent is checked against the very object the canonical value holds, compared by identity rather than by value, because two legitimate parents can be equal. An adopted parent SHALL be held to that same check, and a locator alone does not permit it: the session would have a handle bound to a reference and no object to compare a child's parent against, so the one class of parent reached across loads would be the one nothing verified. Taking the candidate — which already carries both the locator and the snapshot it locates — binds the handle to that exact object, and a child naming the handle SHALL be refused unless the snapshot it holds is that same object.

A caller SHALL therefore construct children against the snapshot the candidate carried, rather than an equal value built elsewhere.

**Adoption SHALL verify that the candidate's two halves agree.** A candidate is an ordinary value a caller can construct, so nothing prevents pairing a valid locator with a snapshot it does not locate — and a boundary that trusted the pair would bind the handle to an object the locator never named, which is the original defect reintroduced through the fix for it. Adoption SHALL resolve the locator and SHALL refuse with a **declared, named exception distinct from the one raised for a locator that resolves to nothing** unless the snapshot it locates equals the snapshot the candidate carries. The two failures are different facts — one says the locator names no snapshot of this release, the other says the candidate disagrees with itself — and a caller that cannot tell them apart cannot tell a stale locator from an assembly mistake. The verified pair is what makes the handle trustworthy; a candidate obtained from the boundary's own candidate access SHALL always satisfy it.

The candidate SHALL carry the snapshot rather than its provenance alone. Provenance does not distinguish them: the accepted persistence contract retains two snapshots **sharing one load, account, release, and provenance** that differ only in a composed situs address or legal description, and refuses any uniqueness over load, account, and provenance that would collapse them. A candidate offering only provenance would present those two as one, which is the ambiguity this requirement exists to remove, moved one field along. Where two candidates are equal as domain values they are indistinguishable by construction, and either is a correct parent.

The number of candidates for one account and release SHALL NOT be assumed bounded. One acquisition may persist several snapshots at one grain, so a per-acquisition bound is not one the accepted contract supports.

Candidate access SHALL therefore be **lazy and expressed as one**: the operation SHALL return an iterator of candidates rather than a materialised collection, so an implementation yields them as they are drawn and a caller may stop at the one it wants. "Paged or streamed" as an adjective is not a contract — an implementation satisfies it by returning a list and calling the list a page — so the port SHALL state the shape that makes laziness observable, and an implementation SHALL NOT draw every candidate before the caller consumes the first.

#### Scenario: A caller stops at the first candidate it wants
- **WHEN** a caller iterates the candidates for an account and release and stops after the one it adopts
- **THEN** the implementation has not drawn the remainder, which is what distinguishes the iterator from a collection wearing its name

Adopting a parent SHALL create no observation and SHALL leave the existing snapshot unchanged, and the child SHALL retain its own load and artifact lineage rather than being attached to its parent's.

An adopted handle SHALL take its place in the correlation model rather than beside it. It SHALL belong to the account of the snapshot it locates, SHALL be live from the moment adoption succeeds, and SHALL advance the highest value yet introduced like any other. Adopting SHALL open that account in the session, and the handle SHALL be released when that account completes.

Adoption SHALL be held to the one-open-account bound rather than exempted from it, because an operation that opens an account is an operation that can open too many. Adopting SHALL be refused unless the account it would open is the account already open in the session, or no account is open at all. A caller with parents in several accounts SHALL therefore finish one account before adopting into the next, exactly as it must finish one account before introducing another, so the number of accounts a session holds open stays one however they were opened. An account opened by adoption SHALL be that one open account and SHALL continue into the next batch: that batch may edit its values, and SHALL complete it or name it as continuing, exactly as if a previous batch had left it open. Several snapshots of one account MAY be adopted, that being one account's parents, which the deltas already bound.

An adopted handle SHALL survive beyond the first batch written after it only if that batch retains it, exactly as for a value that batch introduces, so adoption adds no second lifetime a caller must learn. The batch writing its children SHALL complete its account or name it as continuing, exactly as for an account that batch introduced.

Adoption SHALL take effect on its own rather than as part of a batch, because it is not carried by one. A batch refused after an adoption SHALL leave the adopted handle live and the highest value where adoption left it, and a caller retrying that batch SHALL NOT be required to adopt again, nor refused for naming the handle it already holds.

A failed adoption SHALL change nothing. It SHALL mint no handle, consume no correlation value, leave the highest value yet introduced where it was, and open no account — so a caller offering a stale locator, a candidate whose halves disagree, or a parent of the wrong kind corrects it and tries again against the session it already had. Adoption takes effect by succeeding, exactly as a batch takes effect by being accepted.

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

#### Scenario: Parents are adopted from two accounts at once
- **WHEN** a caller adopts a snapshot of one account and then, without completing it, adopts a snapshot of another
- **THEN** the second adoption is refused, because adoption opens an account and the session holds one open however it was opened

#### Scenario: Several parents of one account are adopted
- **WHEN** a caller adopts several snapshots belonging to the one account it has open
- **THEN** each is adopted, because those are one account's parents and the retain and release deltas already bound them

#### Scenario: An adopted handle is not retained
- **WHEN** a caller adopts a parent and the next batch names it without retaining it
- **THEN** the handle is released at the end of that batch, exactly as for a value that batch introduced

#### Scenario: An adoption fails
- **WHEN** adoption is offered a stale locator, a candidate whose halves disagree, or a parent that is not an account snapshot
- **THEN** nothing changes: no handle is minted, no correlation value is consumed, the highest value yet introduced is where it was, and no account is opened

#### Scenario: An adopted parent's account is carried like any other
- **WHEN** a batch writes children of an adopted parent
- **THEN** it completes that parent's account or names it as continuing, and the adopted handle is released when the account completes, because adoption opened the account rather than creating a handle outside every account

#### Scenario: A batch is refused after an adoption
- **WHEN** a caller adopts a parent, writes a batch naming it, and that batch is refused
- **THEN** the adopted handle is still live and the retry names it without adopting again, because adoption is its own accepted operation and not part of the batch that failed

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
