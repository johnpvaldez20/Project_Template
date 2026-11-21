<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Gate checker

This tool is Python 3 from the standard library.
It does not install a third-party package.
A product language is not required to run the gates.
It uses Git to list the files and to read a pull request.

The project file is `.governance/project.json`.
Change that file to adopt the template.
Read `docs/governance/ADOPTING.md`.

## Run

```text
python3 tools/gatecheck/gatecheck.py
python3 -m unittest discover -s tools/gatecheck -v
python3 tools/gatecheck/gatecheck.py --spdx-only
python3 tools/gatecheck/gatecheck.py --pr
```

Exit code 0 means the report has no failures.
The CI job name is `ci.job_name` in the project file.

| Command | Use |
|---|---|
| `gatecheck.py` | Check the full repository. |
| `architecture.py` | Check the catalog, the packets, and the import direction only. |
| `gatecheck.py --payload FILE` | Check one or more gate payloads in files. |
| `gatecheck.py --pr` | Check the commits between the base branch and `HEAD`. |
| `gatecheck.py --evidence` | Check the test report and the coverage report in `ci.evidence`. |
| `gatecheck.py --spdx-only` | Check the SPDX headers only. |

A report line starts with `ok`, `info`, or `FAIL`.
An `info` line is a measured fact. Copy it into a verdict.

## Check a payload

Save the payload in a file. The file holds one JSON object.
The file can also hold comment text with `json gate-payload` blocks.
The name `-` reads standard input.

```text
python3 tools/gatecheck/gatecheck.py --payload gate1.json gate2.json gate3.json
```

The checker applies the schema and the project rules.
It compares each payload with the packet file in `docs/design/packets/`.
It compares the payloads of one packet with each other.
A real payload contains no `{{` token.

## Check a pull request

```text
git fetch origin main
python3 tools/gatecheck/gatecheck.py --pr
```

The base is `origin/$GITHUB_BASE_REF`, then `origin/main`. `--base` sets another ref.
The branch is `$GITHUB_HEAD_REF`, then the current branch. `--branch` sets another name.
The check prints the head SHA, the base SHA, and each modified file.
It fails when the base branch moved.
On a `pkt/<id>-<slug>` branch, it reads the packet file from the base commit.
It fails on a file outside `allowed_files`.
It fails on a protected path without a gatekeeper packet.
It fails when a planned regression test is not in the tree.

## What it checks

1. Each schema file is a JSON document with `$schema` and `$id`.
2. The project file matches `project.schema.json` and the rules in `projectfile.py`.
3. Valid examples and packet files match the schema for their `gate` value.
4. Invalid examples fail the schema or a project rule. Each one has a row in the examples page.
5. Packet ids match file names and the configured prefix.
6. Dependencies exist and do not cycle.
7. Scopes overlap only when one packet depends on the other.
8. A packet file has no `issue_number` and no `base_sha`.
9. A verdict has a gatekeeper or owner author. The author is not the worker.
10. CI evidence for Gate 3 matches the head SHA and the configured checks. Each test counter is present.
11. SPDX headers match the project file where the format allows a header.
12. Top-level names, `CODEOWNERS`, the workflows, and the ruleset file match the project file.
13. Each action is pinned to a full commit SHA. Each workflow has a `permissions` block.
14. A READY packet and a Gate 1 PASS cite known use cases.
15. Allowed files sit under the declared layer, except exempt paths.
16. Each cited constraint, each transition, and each forbidden transition names a regression test.
17. An architecture edit is its own packet and the worker role is OWNER.
18. Each source file in a layer follows `architecture.import_rules`.
19. The tree has no forbidden construct from the project file.
20. The tree has no environment file and no text with the shape of a secret.

## Modules

| File | Contents |
|---|---|
| `gatecheck.py` | Command line. Examples, packets, and the report. |
| `architecture.py` | Catalog rules, layer rules, and import rules. |
| `importscan.py` | Parsers that read the imports of one source file. |
| `payloadrules.py` | Rules on a packet or a gate payload that a schema cannot state. |
| `handoff.py` | Payloads in files. Comparison with the packet and with each other. |
| `evidence.py` | The pull request check and the report check. |
| `projectfile.py` | Rules on the project file that a schema cannot state. |
| `treecheck.py` | Headers, owners, workflows, ruleset, constructs, and secrets. |
| `repofiles.py` | The list of repository files. A file that Git ignores is not content. |
| `schema_validate.py` | The JSON Schema subset that the schemas use. |
| `repo_fixture.py` | Test support. It builds a template repository for each test. |

## Tests

The tests do not read the project of this repository.
They build a template repository from `testdata/template_repo.json`, the schemas, and the examples.
A project that adopts the template does not edit that snapshot.

In the template repository, a test fails when the snapshot differs from the files.
Write the snapshot again:

```text
python3 tools/gatecheck/repo_fixture.py
```

## Limits

The `python` parser finds each static import and each dynamic import with a literal name.
It does not find an import with a computed name.
The `regex` parser finds only the imports that its patterns describe.
The reviewer checks the rest. The list is in `GOVERNANCE_LINUS.md` section 16.

The checker reads a payload. It cannot see which host account posted the payload.
The gatekeeper checks the account. The host rules are in `docs/governance/OWNER_SETUP.md`.
