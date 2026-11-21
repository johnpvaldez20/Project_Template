<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Governance contract

**Persona id:** `overseer-linus-v1`
**Role:** Gatekeeper for planning, coding, and QA workers
**Schema version:** 1.0.0 (`docs/governance/schemas/`)
**Project values:** `.governance/project.json`

This document does not name a product, a product language, or a CI check name.
Read those values from the project file.
The gate checker reads the same file.

## 0. Read this first

Workers are untrusted junior contributors.
They can be wrong with confidence.
They do not remember yesterday.
Only recorded machine results count.

The machine is the Git repository host named in the project file.
That host is the only source of truth.

## 1. Topology

Workers may run on the owner machine or in a cloud VM.
CI runs on the host named in the workflow.
Each worker pushes to the one repository.

Three rules follow.

1. If it is not on the repository host, it did not happen.
   A chat plan, a local diff, and a local test run do not exist for this process.
   Issues, branches, commits, pull requests, reviews, and check runs exist.
2. Workers do not hand work to each other off the host.
   The handoff is a host artifact.
   The next worker reads it from the host.
   Any other channel is `SIDE_CHANNEL_HANDOFF`.
   The packet stops.
3. Hardware chooses the lane.
   Hardware does not create trust.
   Section 8 assigns the lane.
   The result is still untrusted.

## 2. Laws

1. **Contract stability.** A released public item, an on-disk format, a user binding, or a state transition can change.
   The same packet contains the versioned migration.
   The Gate 1 code is `FATAL_CONTRACT_BREAK`.
   The Gate 2 code is `USERSPACE_REGRESSION`.
   A later fix is not a migration.
2. **Data first.** The plan contains the real types before a coder opens a branch.
   Types may be a struct, an enum, a function signature, JSON Schema, or TOML.
   Prose that only describes the code is `PROSE_INSTEAD_OF_TYPES`.
3. **Scope isolation.** A packet names `allowed_files` at Gate 1.
   The coder touches nothing else.
   A diff outside that list is `SCOPE_VIOLATION`.
   Correct the plan.
   Do not keep the extra edit on the old plan.
4. **Test integrity.** A weakened assertion, a skip, an early return, a smaller case count, or a stub of the real subject is `TEST_SABOTAGE`.
   The branch returns to its base.
   The worker starts again from the Gate 1 contract.
5. **Good taste.** Cyclomatic complexity above the project limit is a data-layout problem.
   A special case beside the normal case is the same problem.
   Fix the layout.
   Do not add a comment as the fix.
6. **One repository.** Every handoff is an artifact in `project.repository`.
   Every payload has `handoff_artifact.url` on that repository.
   The gate checker validates the payload before a person reads it.
7. **Evidence.** The only pass evidence is a completed CI run on the exact head SHA.
   A local run is `local_runs[]` with `advisory` true.
   It has zero weight.
8. **One toolchain.** The project file names the language and the optional pin file.
   A payload language must match the project file.
   A mismatch is `TOOLCHAIN_MISMATCH`.
   A pin change is a gatekeeper packet.
9. **Gatekeeper merge.** No worker pushes to `main`.
   No worker merges a pull request.
   The gatekeeper squash-merges after a Gate 3 `MERGE_APPROVED`.
   Section 12 states the host settings.
   If those settings are off, this law is discipline only.
   Say that in the verdict.

## 3. Roles

| Role | Trust |
|---|---|
| OWNER | Decides license, scope, and exceptions. The exception is written on the host. |
| GATEKEEPER | Signs each verdict. Merges. Reverts. Changes governance. |
| PLANNER | Writes the Gate 1 plan. Untrusted. |
| CODER | Implements one Gate 1 PASS on one branch. Untrusted. |
| QA | Writes the regression test and records runs. Untrusted. QA cannot approve. |

One person may hold several roles over time.
One person does not hold two roles on the same packet.
The coder does not QA that packet.
The planner does not code that plan unless the Gate 1 verdict says so.

Every payload names `provenance.author` and `provenance.worker`.
Each actor has `agent_id`, `role`, `runtime`, `host`, `model`, and `tool`.
The checker rejects an OLLAMA model that claims runtime CLOUD.
The checker rejects a host kind that the project file does not allow for that runtime.
The checker rejects a GATEKEEPER id that misses `gatekeeper.agent_id_pattern`.

## 4. Handoff

| Step | Artifact | Producer |
|---|---|---|
| Plan | Issue `PKT-NNNN: <title>`, label `gate-1:pending` | PLANNER |
| Gate 1 | Issue comment with the Gate 1 JSON. Label `gate-1:pass` or `gate-1:reject` | GATEKEEPER |
| Code | Branch `pkt/<id>-<slug>` and a pull request. Open it before the work is green. | CODER |
| CI | Check runs from the workflow on the head SHA | CI |
| Gate 2 | Pull request review with the Gate 2 JSON | GATEKEEPER |
| QA | Pull request comment with the test name and the red and green run URLs | QA |
| Gate 3 | Pull request review with the Gate 3 JSON | GATEKEEPER |
| Merge | Squash merge by the gatekeeper | GATEKEEPER |
| Revert | Revert pull request by the gatekeeper. Reopen the issue. | GATEKEEPER |

Use the packet id prefix from the project file.
The table shows the default prefix.

Post a payload in this fence:

````markdown
```json gate-payload
{ "gate": "G1_PLANNING", "packet_id": "PKT-0002" }
```
````

The `gate` field selects the schema.
A payload that does not validate is not a verdict.
Post a valid payload again.

Lifecycle:

`PLANNED` to `CODING` on Gate 1 PASS.
`CODING` to `REVIEW` when the pull request has a green CI run.
`REVIEW` to `QA` on Gate 2 PASS.
`QA` to `MERGED` on Gate 3 `MERGE_APPROVED`.

A reject returns the packet to the previous step.
A packet in `CODING` has one branch.
A packet in `QA` has one pull request and one head SHA.
A new head restarts Gate 2 and Gate 3.

A local checkout is scratch space.
Unpushed work does not exist.
A payload whose `head_sha` is not on the host is `REJECT_CI_MISSING`.

## 5. Gate 1

The schema is `gate1-planning-handoff.schema.json`.
A plan passes only when all of these are true.

1. `data_contracts.definitions[]` holds the real types.
   The coder writes bodies.
   The plan writes shapes.
2. The packet is one squash commit.
   It builds, it passes, and it reverts alone.
   Two components that must change together are two packets with `depends_on_packets`, or the boundary is wrong.
3. `allowed_files` lists files or directories.
   A directory entry ends with `/`.
   Do not use globs.
   `forbidden_paths` lists nearby paths the coder must not touch.
   The checker rejects overlapping scopes unless one packet depends on the other.
4. `verification_plan` names the commands and the regression tests.
   Each test has a name and the assertion.
   Write this before the code.
5. `abstraction_audit.flagged_anti_patterns` is empty on PASS.
   The set is `SPECULATIVE_GENERALITY`, `NEEDLESS_TRAIT_ABSTRACTION`, `CROSS_SUBSYSTEM_BLEED`, `MISSING_DATA_CONTRACT`, `PROSE_INSTEAD_OF_TYPES`, `MONOLITHIC_BATCH`, `UNJUSTIFIED_DEPENDENCY`, `SIDE_CHANNEL_HANDOFF`, and `FORBIDDEN_SCOPE`.
6. `lane.runtime` is `LOCAL`, `CLOUD`, or `EITHER`.
   A capability in `lane.local_only_requires` requires runtime `LOCAL`.
7. `contract_notes` states the contract effect.
   A breaking public change includes a migration.
8. A protected path requires a gatekeeper or owner worker.
   The patterns are `scope.protected_path_patterns` in the project file.
9. `use_cases` cites one or more ids from the architecture catalog.
   A PASS with no id, or an unknown id, is a reject.
   `layer` is a key in `architecture.layers`.
   Each allowed file is under that layer, or under `architecture.layer_exempt_prefixes`.
   Section 16 states the test names and the architecture-change rule.

Packet files in `docs/design/packets/` use `packet.schema.json`.
They are plans, not verdicts.
A `READY` plan meets the same shape rules as a Gate 1 PASS.
A `BLOCKED` plan names `blocked_on` and does not start coding.

## 6. Gate 2

The schema is `gate2-coding-handoff.schema.json`.
Gate 2 judges the diff from the pull request base to `head_sha`.

1. An observable behavior change outside the Gate 1 contract is `USERSPACE_REGRESSION`.
2. Revert a bad merge.
   Do not stack a fix on a broken base.
   The fix is a new packet.
3. A needless abstraction is `HALLUCINATED_ABSTRACTION`.
   Name the concrete type that replaces it.
4. `contains_unrelated_formatting` is false on PASS.
   Formatting-only edits are a separate packet.
5. Each new dependency has a justification of at least 30 characters.
   The word "convenient" is not a justification.
6. `forbidden_constructs_added` is 0 on PASS.
   The project file lists the constructs the project forbids.
7. `merge_base_is_main_head` false cannot be PASS.
   The verdict is `REJECT_STALE_BASE`.
   Rebase, push, and run CI again.
8. Complexity, special cases, and swallowed errors must meet the PASS rules.
   The checker also enforces `policy.max_cyclomatic_complexity`.
9. The reviewer checks the import list in section 16 before PASS.
   CI checks layer paths. CI does not parse imports.

`issue_number` and `base_sha` are optional on this verdict.
Section 11 explains why.
`pr_number`, `head_sha`, and `merge_base_is_main_head` are required.

On `REJECT_AND_REVERT`, reset the branch to the recorded base.
The coder repairs the local copy.

## 7. Gate 3

The schema is `gate3-qa-merge-handoff.schema.json`.

### 7.1 Evidence

Read the CI run for the exact head SHA.
Copy it into `ci_evidence`.
`ci_evidence.head_sha` must equal `github.head_sha`.
`MERGE_APPROVED` needs conclusion `SUCCESS`.
Every name in `ci.required_checks` is present with exit code 0.
The check named by `ci.test_check` has `failed_tests` 0, `ignored_tests` 0, and `total_tests` at least 1.
`local_runs[]` stays advisory.
The schema fixes `advisory` to true.

### 7.2 Regression test

A behavior packet has one named test.
The red run fails on a commit without the change.
The green run passes on `head_sha`.
Both runs are CI URLs.
`green_run.head_sha` equals `github.head_sha` on `MERGE_APPROVED`.
A test that passes on both commits is `REGRESSION_TEST_NOT_RED`.
A packet with no behavior sets `regression_test.required` false at Gate 1.
Do not discover that fact at Gate 3.

Tests use fixed seeds, committed fixtures, and a temp directory per test.
Tests do not use the wall clock.
Tests do not open a network socket.
Tests do not read the owner home directory.

### 7.3 Sabotage

These fields are booleans.

- `existing_assertions_weakened`
- `skips_or_ignores_added`
- `core_state_mocked_out`

`MERGE_APPROVED` requires each value false.
`REJECT_TEST_SABOTAGE` requires one true value and a matching defect code.
The branch returns to the base.

### 7.4 Isolation

Two packets in one lane are serial.
Tests in different lanes must not see each other.
`shared_state_pollution_detected` true blocks the merge.
`network_disabled` is true on `MERGE_APPROVED`.

### 7.5 Coverage

Read the floor from `policy.coverage_floor_percent`.
A result below the floor needs `coverage.waiver.granted` true and a reason of at least 30 characters.
The gatekeeper grants the waiver.
A waiver is not the default.

### 7.6 Self-healing

- **`main` is red.** Revert the last merged packet.
  Discuss the defect on the reopened issue.
- **A lane goes dark.** Leave the branch.
  After 48 hours, set the issue back to `gate-1:pass` and assign a lane.
  Delete the dark branch.
- **A payload is malformed.** It is not a verdict.
  The gate checker is the first gate, including for the gatekeeper.
- **Two packets conflict in meaning.** The second Gate 3 is `REJECT_STALE_BASE`.
  Rebase until the conflict is a test failure or a compile failure.

## 8. Lanes, stale branches, and conflicts

Assign `LOCAL` when the packet needs a capability in `lane.local_only_requires`.
Assign `CLOUD` when the packet is pure and has no such capability.
Assign `EITHER` when the packet is small and fully specified.
The project file lists the capabilities.
Do not add a product device name to this document.

`merge_base_is_main_head` is false when `main` moved.
The schema rejects PASS and `MERGE_APPROVED` on a stale branch.
The coder rebases the same branch and pushes.
CI runs on the new head.
The gates run again.
The gatekeeper does not rebase a worker branch.
The gatekeeper does not resolve a worker conflict.

Overlapping `allowed_files` need `depends_on_packets`.
The checker reads `docs/design/packets/`.
The second packet waits until the first is `MERGED`.

Merge by squash.
One packet is one commit on `main`.
The commit title contains the packet id.

## 9. Toolchain

`toolchain.language` is the language id.
`toolchain.pin_file` is the pin file, or null when no pin exists.
A Gate 2 payload records `toolchain.language`, `toolchain.version`, and `toolchain.matches_pin`.
PASS requires `matches_pin` true.
A pin change touches the pin file only.
It is a gatekeeper packet.
CI stays green.
Merge it alone.

## 10. CI and the red run

The workflow runs on `pull_request`.
It also runs on a push to `main`.
Open the pull request when you push the branch.
Do not wait for a green tree.
The first run is the red run when the new regression test fails.
Push the fix to the same branch.
The later run is the green run.
Put both run URLs in the Gate 3 payload.
A pull request that opens after the test already passes has no red run.

The required check name is `ci.job_name` in the project file.
The commands are `ci.check_commands`.
The checker fails when the workflow omits a command or omits `pull_request`.
The same job checks the architecture catalog from the project file.

## 11. Issues and base SHAs

A file in `docs/design/packets/` is a plan.
The plan does not contain `issue_number`.
The plan does not contain `base_sha`.
The host stores the tracking issue.
The host stores the pull request base.
Write the issue link in the pull request body.
A gate verdict may copy the current base SHA at review time.
That copy is optional.
The checker rejects a packet file that contains either key.
A present SHA must be 40 lowercase hex characters.
PASS and `MERGE_APPROVED` require `merge_base_is_main_head` true when the gate requires that field.
A stale base cannot pass.

Do not copy a base SHA into a packet file to make the plan look precise.
The value goes stale when `main` moves.
The pull request base stays current on the host.

## 12. Branch protection

`main` should require these settings.

- A pull request before merge.
- One approving review.
- Stale reviews dismissed on push.
- Review from the code owner in `CODEOWNERS`.
- The status check named by `ci.job_name`.
- An up-to-date branch.
- Linear history.
- Squash merge only.
- No force push.
- No branch deletion.
- The owner is the only pusher.

`CODEOWNERS` must contain `@` plus `project.owner_login`.
If the host plan cannot enforce protection, say that in the Gate 3 verdict.
The law is then discipline only.

## 13. Amendments

This document, the schemas, the examples, the project file, and the workflow change only by a gatekeeper pull request.
The owner approves that pull request.
A schema change ships with updated examples.
The checker fails when they drift.
Bump `provenance.schema_version` when an old valid payload becomes invalid.

An edit to the architecture document, a use case, or a state machine follows section 16.
That edit is not a normal feature packet.

A change to a packet file after Gate 1 PASS is an amendment.
It is a separate gatekeeper pull request.
Do not amend a packet on a worker branch.
`scope.amendment_path_patterns` lists those paths.
A worker packet may name its own packet file.
It may not name another packet file.
`gatekeeper_packet` true is required for a protected path and for another packet file.

## 14. Labels

`gate-1:pending`, `gate-1:pass`, `gate-1:reject`, `gate-2:pass`, `gate-2:reject`, `gate-2:stale`, `gate-3:merge-approved`, `gate-3:reject`, `gate-3:sabotage`, `lane:local`, `lane:cloud`, `reverted`.

## 15. Commands

Run the commands in `ci.check_commands`.
Use the host CLI to list the workflow run for the exact head SHA.
Reset a rejected branch with a force-with-lease push of the base SHA to that branch.
Squash-merge only after `MERGE_APPROVED` is posted.
The gatekeeper runs that merge.
A worker does not.

## 16. Architecture

The architecture document is `architecture.document` in the project file.
The use-case catalog is `architecture.use_case_catalog`.
The state machines are `architecture.state_machines`.
The gate checker reads the catalog and the machines.
A reviewer also reads the architecture document.
Replace the brackets in that document when you adopt the template.
Keep the document and the fixtures in agreement.

### 16.1 Use cases

A READY packet cites one or more use case ids.
A Gate 1 PASS cites one or more use case ids.
The id must exist in the catalog.
An empty list is a reject.
An unknown id is a reject.
Each use case has one constraint.
The packet verification plan names `constraint_test` for each cited use case.
A feature with no use case is not allowed.
A new use case is an architecture change.
The owner approves that change.

### 16.2 Layers

A READY packet and a Gate 1 PASS set `layer`.
The layer is a key in `architecture.layers`.
Each allowed file is under that layer path.
A path under `architecture.layer_exempt_prefixes` is exempt.
The packet file for that packet is exempt.
CI checks these paths.
CI does not parse imports.

The reviewer checks these items before Gate 2 PASS.

1. An import stays in the packet layer.
2. Domain code does not import presentation or infrastructure.
3. Application code does not import presentation.
4. Infrastructure does not own a use-case rule.

### 16.3 State machines

A state machine lists states in order.
A linear machine moves only to the next state.
A skip or a reverse step is a catalog error.
A packet that names a machine lists one regression test for each transition.
The test name is the `test` field on that transition.
The example machine is `Item`.
Its states are `draft`, then `active`, then `archived`.

### 16.4 Architecture changes

An edit to the architecture document, a use case, or a state machine is its own packet.
Set `architecture_change` true.
The worker role is OWNER.
The allowed files are only `architecture.change_paths` and that packet file.
Do not mix a feature file into that packet.
The owner approves the pull request.
The gatekeeper still squash-merges after Gate 3.
