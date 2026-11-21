<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Governance contract

**Persona id:** `overseer-linus-v1`
**Role:** Gatekeeper for planning, coding, and QA workers
**Schema version:** 2.0.0 (`docs/governance/schemas/`)
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
   CI compares the diff of a packet branch with the packet file.
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
   CI checks out that SHA. CI does not cancel a run.
   A verdict copies its numbers from that run. It does not estimate them.
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
The author is the agent that wrote the payload.
The worker is the agent whose work the payload judges.
Each actor has `agent_id`, `role`, `runtime`, `host`, `model`, and `tool`.
The checker rejects an OLLAMA model that claims runtime CLOUD.
The checker rejects a host kind that the project file does not allow for that runtime.
The checker rejects a GATEKEEPER id that misses `gatekeeper.agent_id_pattern`.
The checker rejects an OWNER id that misses `owner.agent_id_pattern`.

A worker does not sign its own gate.
On a Gate 1, Gate 2, or Gate 3 payload, the author has the role GATEKEEPER or OWNER.
The author is not the worker.
The merger on a Gate 3 payload is not the worker.
The checker rejects a payload that breaks one of these rules.
The Gate 3 worker is not the Gate 2 worker.
The checker applies that rule when it gets the two payloads together.

On a gatekeeper packet, the gatekeeper is the worker. The owner signs those verdicts.
On an architecture packet, the owner is the worker. The gatekeeper signs those verdicts.

A payload states who wrote it.
The host records which account posted it.
The gatekeeper account posts each verdict.
A verdict that the worker account posted is not a verdict.
The checker cannot see the host account.
The gatekeeper compares the account with the payload before it accepts a verdict.
Section 12 states the host rules that make two accounts necessary.

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

Check a payload before you post it and after you read it.
Save the payload, or the comment text, in a file.
Run `python3 tools/gatecheck/gatecheck.py --payload <file>`.
Give the payloads of one packet together. The checker compares them.
A real payload contains no `{{` token.

A worker does not write a gate verdict.
A worker reports in the pull request body.
The body follows `.github/PULL_REQUEST_TEMPLATE.md`.

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
   A path has no empty segment, no `.` segment, and no `..` segment.
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

CI reads the packet file, not the Gate 1 comment.
A Gate 1 PASS states the same scope as the packet file.
The allowed files, the use cases, the layer, the state machines, and the test names are equal.
The `--payload` check compares them.
When they differ, amend the packet file first.

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
   The project file lists each construct with a pattern and its paths.
   CI fails when a line in those paths matches.
7. `merge_base_is_main_head` false cannot be PASS.
   The verdict is `REJECT_STALE_BASE`.
   Rebase, push, and run CI again.
8. Complexity, special cases, and swallowed errors must meet the PASS rules.
   The limit is `policy.max_cyclomatic_complexity`.
9. CI checks the import direction of each layer.
   The reviewer checks the items in section 16 that CI cannot read.
10. A modified protected path sets `touches_protected_paths` true.
    The checker compares `files_modified` with the protected patterns.
    Each file in `out_of_scope_files` is also in `files_modified`.
11. Copy the head SHA, the base result, and the file list from the `scope` check of the CI run.

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
An approval records each of the three counters.
A counter that is absent is not zero.
`ci_evidence.run_url` ends with `ci_evidence.run_id`.
`local_runs[]` stays advisory.
The schema fixes `advisory` to true.

A project with tests sets `ci.evidence` in the project file.
The `--evidence` check then reads the test report and the coverage report in CI.
It fails on a failed test, on an ignored test, and below the coverage floor.
A skipped test and an expected failure are ignored tests.
Copy the counters and the coverage from that check.

### 7.2 Regression test

A behavior packet has one named test.
The packet verification plan names that test.
The red run fails on a commit without the change.
The green run passes on `head_sha`.
Both runs are CI URLs.
The red run and the green run are two runs on two commits.
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
When `ci.evidence` names a coverage report, CI fails below the floor.
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
A dependency through a third packet also orders two packets.
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
The checker treats the pin file as a protected path.
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

The workflow checks out the head SHA of the pull request.
It does not test a merge commit.
The workflow does not cancel a run.
A cancelled run cannot be the red run.
The `scope` check runs `python3 tools/gatecheck/gatecheck.py --pr`.
It prints the head SHA, the base SHA, and the file list.
It fails when the base branch moved.
On a `pkt/` branch, it reads the packet file from the base commit.
It fails on a file outside `allowed_files`.
It fails on a protected path without a gatekeeper packet.
It fails when a planned regression test is not in the tree.
A branch with another name is not a packet branch.
It gets no gate verdict. Only the owner merges it.

Each action in a workflow is pinned to a full commit SHA.
Each workflow has a `permissions` block.
No workflow uses `pull_request_target`.
The checker fails when a workflow breaks one of these rules.

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

The ruleset for `main` is `.github/rulesets/main.json`.
The host does not read that file.
The owner imports it on the host. The steps are in `OWNER_SETUP.md`.
The checker fails when the file does not agree with this list.

`main` must require these settings.

- A pull request before merge.
- One approving review.
- Stale reviews dismissed on push.
- Review from the code owner in `CODEOWNERS`.
- Approval of the last push by an account that did not push it.
- The status check named by `ci.job_name`, from the CI service only.
- An up-to-date branch.
- Linear history.
- Squash merge only.
- No force push.
- No branch deletion.

`CODEOWNERS` names `@` plus `project.owner_login` on each rule.
One `CODEOWNERS` file exists. It is at the repository root.

The host does not let the author of a pull request approve it.
The worker account and the gatekeeper account must be two accounts.
When one account does both jobs, the host cannot enforce Gate 3.
The law is then discipline only.
Say that in the Gate 3 verdict.
If the host plan cannot enforce the ruleset, say that in the Gate 3 verdict also.

## 13. Amendments

This document, the schemas, the examples, the project file, the workflows, the ruleset file, and the gate checker change only by a gatekeeper pull request.
The owner approves that pull request.
`tools/gatecheck/` is a protected path.
The checker fails when the project file does not protect each of these paths.
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

| Command | Use |
|---|---|
| `python3 tools/gatecheck/gatecheck.py` | Check the full repository. |
| `python3 tools/gatecheck/architecture.py` | Check the catalog, the packets, and the import direction. |
| `python3 tools/gatecheck/gatecheck.py --payload <file>` | Check one or more gate payloads. |
| `python3 tools/gatecheck/gatecheck.py --pr` | Check the branch against its base before a push. |
| `python3 tools/gatecheck/gatecheck.py --evidence` | Check the test report and the coverage report. |

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
A packet has one layer.
A feature that needs two layers is two packets with `depends_on_packets`.
Each allowed file is under that layer path.
A path under `architecture.layer_exempt_prefixes` is exempt.
The packet file for that packet is exempt.
CI checks these paths.

`architecture.import_rules.allowed` states which layers each layer can import.
A layer can always import itself.
The map has no cycle.
The default map is this list.

- Presentation imports application and domain.
- Application imports domain.
- Domain imports no other layer.
- Infrastructure imports application and domain.

CI reads the imports of each source file in a layer.
A scanner in the project file names the parser for each file suffix.
A file in a layer must have a scanner, or its suffix must be in `non_source_extensions`.
A source file must be in a layer or on an exempt path.
Put the file that connects the layers on an exempt path.
`import_rules.forbidden` can keep a named module out of one layer.

The reviewer checks these items before Gate 2 PASS.

1. Infrastructure does not own a use-case rule.
2. An import with a computed name does not go around the import rules.
3. A project with no scanner follows the map. The reviewer reads each import.

### 16.3 State machines

A state machine lists its states.
A linear machine moves only to the next state.
A skip or a reverse step in a linear machine is a catalog error.
A machine that is not linear lists each transition that it permits.
Each state must be on a path from the initial state.
A transition can name an event and a guard.
A machine can list forbidden transitions.
A forbidden transition is a move that the machine must reject.
A packet that names a machine lists one regression test for each transition.
It also lists one regression test for each forbidden transition.
The test name is the `test` field on that transition.
One test name is on one transition only.
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
