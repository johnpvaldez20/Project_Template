<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Gate payload examples

`valid/` must validate.
`invalid/` must be rejected.
The gate checker runs both sets.
It also checks every file in `docs/design/packets/`.

Invalid files are valid files with one defect.
The file name names the defect.
A schema change that accepts an invalid file has opened a hole.

Example strings may contain `{{repository}}`, `{{github_base}}`, and `{{packet:0003}}`.
The checker expands them from the project file.
The valid Gate 3 merge file sets `checks` to `{{required_checks}}`.
The checker fills that value from `ci.check_commands`.

| Invalid file | The defect |
|---|---|
| `gate1-pass-without-definitions` | PASS with no type definitions |
| `gate1-pass-with-flagged-anti-pattern` | PASS with a flagged anti-pattern |
| `gate1-coder-touches-protected-path` | A coder lists a protected path |
| `gate1-cloud-lane-needs-local-capability` | CLOUD lane requires a local-only capability |
| `gate1-pass-not-atomic` | PASS when `is_atomic` is false |
| `gate1-pass-without-use-case` | PASS with an empty use-case list |
| `gate1-pass-unknown-use-case` | PASS that cites an id missing from the catalog |
| `gate1-pass-file-outside-layer` | PASS whose allowed file is outside the declared layer |
| `gate1-pass-missing-constraint-test` | PASS that omits the use-case constraint test |
| `packet-hardcodes-issue-number` | A packet file contains `issue_number` |
| `packet-hardcodes-base-sha` | A packet file contains `base_sha` |
| `packet-architecture-change-by-planner` | Architecture packet whose worker is not OWNER |
| `packet-architecture-mixed-with-feature` | Architecture packet that also lists a feature file |
| `packet-missing-transition-test` | Packet omits a state-transition test |
| `gate2-pass-with-out-of-scope-files` | PASS with a file outside scope |
| `gate2-ollama-model-claims-cloud-runtime` | OLLAMA model with runtime CLOUD |
| `gate2-pass-on-stale-base` | PASS while the base is stale |
| `gate2-pass-with-forbidden-construct` | PASS with a forbidden construct |
| `gate2-dependency-without-justification` | Justification is too short |
| `gate2-abbreviated-base-sha` | Optional base SHA is not 40 hex characters |
| `gate3-merge-approved-with-failed-ci` | Approval with CI failure |
| `gate3-merge-approved-without-ci-run` | Approval with CI missing |
| `gate3-abbreviated-sha` | Short SHA |
| `gate3-ci-run-for-different-commit` | CI head differs from the pull request head |
| `gate3-merge-approved-with-ignored-tests` | Ignored tests on approval |
| `gate3-merge-approved-regression-test-not-red` | Red run exit code is 0 |
| `gate3-handoff-outside-github` | Payload URL is outside the repository |
| `gate3-merge-approved-with-network-tests` | Tests are allowed to use the network |
| `gate3-merge-approved-coverage-below-floor-no-waiver` | Coverage is below the configured floor |
| `gate3-unknown-top-level-field` | Unknown field |
| `gate3-merged-by-coder` | A coder is recorded as the merger |
| `gate3-merge-approved-missing-required-check` | A required CI check is absent |

Valid Gate 2 and Gate 3 files omit `issue_number` and `base_sha`.
Those fields stay optional on a verdict.
They are forbidden in a packet file.
