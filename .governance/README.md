<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Project file

`.governance/project.json` holds the values that change from one repository to the next.
The gate schemas do not store those values.
The gate checker reads this file.
JSON has no comments. This page explains each field.

The schema of this file is `docs/governance/schemas/project.schema.json`.
The gate checker applies that schema first.
An unknown key is an error. A missing key is an error.

Replace the placeholder strings before you use the repository for a product.
`LicenseRef-UNSET` is not a license. Read `docs/governance/ADOPTING.md`.

Set the four identity fields in one change.
The checker fails when only some of them are set.
While the identity is a placeholder, the repository is a template.
A template has no language, no pin file, no scanner, no report, and no forbidden construct.

## Identity

| Field | Placeholder | Meaning |
|---|---|---|
| `schema_version` | `2.0.0` | Schema set version. It equals the constant in `common.schema.json`. Bump both when an old valid payload becomes invalid. |
| `project.name` | `PROJECT-NAME` | Short name. The checker does not compare prose to this field. |
| `project.full_name` | `Replace with the full project name` | Display name. |
| `project.version` | `0.0.0` | Version string. The checker does not read it. |
| `project.repository` | `replace-me/project` | `owner/name`. Payload URLs must stay inside this repository. |
| `project.owner_login` | `replace-me` | Login that each `CODEOWNERS` rule must cite after `@`. |
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
| `scope.allowed_top_level` | Top-level names that may exist in the repository. A file that Git ignores does not count. |
| `scope.protected_path_patterns` | Paths that need `gatekeeper_packet` true, or a gatekeeper or owner worker on a verdict. The patterns must cover the gate documents, the schemas, the examples, the workflows, the project file, `CODEOWNERS`, and `tools/gatecheck/`. |
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
| `ci.job_name` | Required status check name. The workflow job and the ruleset file use this name. |
| `ci.required_checks` | Step names that a Gate 3 approval must include. |
| `ci.test_check` | The step that reports test counts. It is one of the required checks. |
| `ci.check_commands` | Command text for each required step. The workflow must contain each command. Each command starts with an allowed prefix. |
| `ci.evidence.test_report` | JUnit XML file that the product test command writes, or `null`. |
| `ci.evidence.coverage_report` | Cobertura XML, JaCoCo XML, or LCOV file, or `null`. Set both reports or no report. |

The `scope` check is `python3 tools/gatecheck/gatecheck.py --pr`.
It measures the head SHA, the base, and the diff of a pull request.
The `--evidence` option reads the two reports. Add it as a check when the project has tests.

## Toolchain, policy, and gatekeeper

| Field | Meaning |
|---|---|
| `toolchain.language` | Language id recorded on a Gate 2 payload. `undecided` is allowed. |
| `toolchain.pin_file` | Pin file path, or `null` when no pin exists. The pin file is a protected path. |
| `policy.max_cyclomatic_complexity` | Gate 2 PASS fails above this number. |
| `policy.coverage_floor_percent` | Gate 3 approval fails below this number unless a waiver is granted. The `--evidence` check uses the same number. |
| `policy.forbidden_constructs` | Text that the project forbids. Each entry has `id`, `pattern`, `paths`, and `reason`. `extensions` is optional. The checker fails on each line that matches. |
| `gatekeeper.persona_id` | Id of the gatekeeper persona in the contract. |
| `gatekeeper.agent_id_pattern` | Regular expression for the `agent_id` of a GATEKEEPER. |
| `owner.agent_id_pattern` | Regular expression for the `agent_id` of an OWNER. |

An example of a forbidden construct:

```json
{
  "id": "NO_TODO_NOTE",
  "pattern": "\\bTODO\\b",
  "paths": ["src/"],
  "reason": "Open an issue. Do not leave a note in the code."
}
```

## Architecture

| Field | Meaning |
|---|---|
| `architecture.document` | Human architecture page. Keep it aligned with the fixtures. |
| `architecture.use_case_catalog` | JSON list of use cases. The schema is `use-cases.schema.json`. |
| `architecture.state_machines` | JSON list of machines. The schema is `state-machines.schema.json`. |
| `architecture.change_paths` | Files that require `architecture_change` true and worker role `OWNER`. |
| `architecture.layers` | Map from layer name to directory paths. Allowed files must match the packet layer. A layer can have more than one path, for example its test directory. |
| `architecture.layer_exempt_prefixes` | Paths that are not in a layer. An entry that ends with `/` is a directory. Any other entry is one file. The import rules do not apply to these paths. |
| `architecture.import_rules.allowed` | Map from each layer to the other layers that it can import. The map has no cycle. |
| `architecture.import_rules.forbidden` | Map from a layer to patterns. A file in that layer must not import a name that matches. |
| `architecture.import_rules.non_source_extensions` | File suffixes in a layer that hold no import. |
| `architecture.import_rules.scanners` | One scanner for each source language. |

## Import scanners

A scanner tells the checker how to read the imports of one file type.
A file in a layer must have a scanner, or its suffix must be in `non_source_extensions`.
A source file outside every layer must be on an exempt path.

The `python` parser reads the syntax tree of a Python file.
`roots` lists the directories that an absolute import starts from.
The empty string is the repository root.

```json
{ "parser": "python", "extensions": [".py"], "roots": ["", "src/"] }
```

The `regex` parser reads any other language.
Each import pattern has one group. The group is the imported name.
`layer_patterns` states which imported names are in each layer.

```json
{
  "parser": "regex",
  "extensions": [".ts"],
  "import_patterns": ["from\\s+['\"]([^'\"]+)['\"]"],
  "layer_patterns": {
    "presentation": ["(^|/)presentation(/|$)"],
    "application": ["(^|/)application(/|$)"],
    "domain": ["(^|/)domain(/|$)"],
    "infrastructure": ["(^|/)infrastructure(/|$)"]
  }
}
```

Give one pattern list for each layer.
An import of a layer with no pattern is not found.

The `regex` parser reads text. It can miss an import that the pattern does not describe.
The reviewer reads the imports that a pattern cannot find.

The filled example use case is `UC-01`.
The filled example machine is `Item`.
The example packet is `docs/design/packets/PKT-0001.json`.
