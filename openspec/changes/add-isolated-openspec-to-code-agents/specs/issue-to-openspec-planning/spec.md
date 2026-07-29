## MODIFIED Requirements

### Requirement: Human approval
The planning agent MUST NOT approve its own result. Implementation eligibility SHALL remain false until the planning change exists on the trusted default branch as the result of a planning PR merged by an authorized human maintainer. The eligibility evidence MUST bind the merged PR's merge commit SHA and immutable approving actor ID; reactions, labels, draft PRs, bot output, and issue prose alone MUST NOT count as approval.

#### Scenario: Accept only merged human planning work
- **WHEN** trusted GitHub facts show the exact planning change on the captured default-branch SHA and a merged planning PR whose actor has `admin`, `maintain`, or `write`
- **THEN** implementation eligibility may be granted

#### Scenario: Reject draft or self-approval
- **WHEN** the planning PR is open/draft, the actor is unauthorized, or approval facts are missing
- **THEN** implementation eligibility is denied before workspace or provider execution

### Requirement: Recent discussion selection
The planning adapter SHALL deduplicate issue comments whose immutable comment IDs are at or before the original plan-command comment ID and select a deterministic newest-first window of at most 16 comments using immutable comment identity and timestamps. Initial intake, initial packet preparation, and retry packet reconstruction MUST apply the same candidate cutoff and selected window. When the original triggering command comment is available, it MUST be retained in the selected window. The selected comments, including their bounded redacted bodies and identities, MUST participate in the planning context fingerprint and packet provenance; post-cutoff comments and older pre-cutoff comments outside the selected window MUST NOT participate.

#### Scenario: Freeze discussion at the plan command
- **WHEN** initial intake, initial packet preparation, or retry reconstruction observes comments whose IDs are greater than the original plan-command comment ID
- **THEN** those post-cutoff comments are excluded and every stage derives the same bounded planning-context fingerprint

#### Scenario: Selected discussion mutation changes identity
- **WHEN** an issue has more than 16 eligible pre-cutoff comments and a comment selected into the newest bounded window changes or disappears
- **THEN** packet reconstruction detects a changed planning-context fingerprint and fails closed before provider execution

#### Scenario: Unselected discussion preserves frozen identity
- **WHEN** an older pre-cutoff comment outside the selected 16-comment window or any post-cutoff comment changes
- **THEN** the frozen planning-context fingerprint remains unchanged
