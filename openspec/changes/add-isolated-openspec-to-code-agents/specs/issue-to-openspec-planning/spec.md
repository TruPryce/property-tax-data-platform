## MODIFIED Requirements

### Requirement: Human approval
The planning agent MUST NOT approve its own result. Implementation eligibility SHALL remain false until the planning change exists on the trusted default branch as the result of a planning PR merged by an authorized human maintainer. The eligibility evidence MUST bind the merged PR's merge commit SHA and immutable approving actor ID; reactions, labels, draft PRs, bot output, and issue prose alone MUST NOT count as approval.

#### Scenario: Accept only merged human planning work
- **WHEN** trusted GitHub facts show the exact planning change on the captured default-branch SHA and a merged planning PR whose actor has `admin`, `maintain`, or `write`
- **THEN** implementation eligibility may be granted

#### Scenario: Reject draft or self-approval
- **WHEN** the planning PR is open/draft, the actor is unauthorized, or approval facts are missing
- **THEN** implementation eligibility is denied before workspace or provider execution
