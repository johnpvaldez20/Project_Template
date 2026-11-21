<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Project file

`.governance/project.json` holds the values that change from one repository to the next.
The schemas do not store those values.
The gate checker reads this file.
JSON has no comments. This page explains each field.

Replace the placeholder strings before you use the repository for a product.
`LicenseRef-UNSET` is not a license. Read `docs/governance/ADOPTING.md`.

## Identity

| Field | Placeholder | Meaning |
|---|---|---|
| `schema_version` | `2.0.0` | Schema set version. Bump it when an old valid payload becomes invalid. |
| `project.name` | `PROJECT-NAME` | Short name. The checker does not compare prose to this field. |
| `project.full_name` | `Replace with the full project name` | Display name. The checker does not read it. |
| `project.version` | `0.0.0` | Version string. The checker does not read it. |
| `project.repository` | `replace-me/project` | `owner/name`. Payload URLs must stay inside this repository. |
| `project.owner_login` | `replace-me` | Login that `CODEOWNERS` must cite after `@`. |
| `packet.id_prefix` | `PKT` | Packet id prefix. Example files use `{{packet:0003}}` and expand with this prefix. |

## License headers

| Field | Placeholder | Meaning |
|---|---|---|
| `spdx.license_id` | `LicenseRef-UNSET` | SPDX id. This marker grants no rights. You choose the real id. |
| `spdx.copyright_line` | `SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER` | Exact line the checker expects in a header. |
| `spdx.extensions` | `.py`, `.yml`, `.yaml`, `.md` | File suffixes that must carry the two SPDX lines. |
| `spdx.basenames` | `CODEOWNERS`, `.gitignore` | Extra file names that must carry the two SPDX lines. |
| `spdx.exempt_basenames` | `LICENSE` | File names the checker skips. |

## Scope

| Field | Meaning |
|---|---|
| `scope.allowed_top_level` | Top-level names that may exist in the repository. |
| `scope.protected_path_patterns` | Paths that need `gatekeeper_packet` true, or a gatekeeper or owner worker on a verdict. |
| `scope.amendment_path_patterns` | Packet files. A worker may name only its own packet file. |
| `verification.command_prefixes` | Allowed starts of a verification command. |
| `lane.local_only_requires` | Capabilities that force lane runtime `LOCAL`. |

## Hosts and CI

| Field | Meaning |
|---|---|
| `hosts.local_kinds` | Host kinds allowed when runtime is `LOCAL`. |
| `hosts.cloud_kinds` | Host kinds allowed when runtime is `CLOUD`. |
| `hosts.ci_kinds` | Host kinds allowed when runtime is `GITHUB_ACTIONS`. |
| `ci.workflow_file` | Workflow file name under `.github/workflows/`. |
| `ci.job_name` | Required status check name. The workflow job uses this name. |
| `ci.required_checks` | Step names that a Gate 3 approval must include. |
| `ci.test_check` | The step that reports test counts. |
| `ci.check_commands` | Command text for each required step. The workflow must contain each command. |

## Toolchain, policy, and gatekeeper

| Field | Meaning |
|---|---|
| `toolchain.language` | Language id recorded on a Gate 2 payload. `undecided` is allowed. |
| `toolchain.pin_file` | Pin file path, or `null` when no pin exists. |
| `policy.max_cyclomatic_complexity` | Gate 2 PASS fails above this number. |
| `policy.coverage_floor_percent` | Gate 3 approval fails below this number unless a waiver is granted. |
| `policy.forbidden_constructs` | Names of constructs the project forbids. The checker counts additions on Gate 2. |
| `gatekeeper.persona_id` | Id of the gatekeeper persona in the contract. |
| `gatekeeper.agent_id_pattern` | Regular expression for a gatekeeper `agent_id`. |

## Architecture

| Field | Meaning |
|---|---|
| `architecture.document` | Human architecture page. Keep it aligned with the fixtures. |
| `architecture.use_case_catalog` | JSON list of use cases. Each row has `id`, `trigger`, `flow`, `constraint`, and `constraint_test`. |
| `architecture.state_machines` | JSON list of machines. A linear machine moves only to the next state. |
| `architecture.change_paths` | Files that require `architecture_change` true and worker role `OWNER`. |
| `architecture.layers` | Map from layer name to directory prefixes. Allowed files must match the packet layer. |
| `architecture.layer_exempt_prefixes` | Process paths that are not product layers. Imports are still a reviewer check. |

The filled example use case is `UC-01`.
The filled example machine is `Item`.
The example packet is `docs/design/packets/PKT-0001.json`.
