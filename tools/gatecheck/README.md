<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Gate checker

This tool is Python 3 from the standard library.
It does not install a third-party package.
A product language is not required to run the gates.

The project file is `.governance/project.json`.
Change that file to adopt the template.
Read `docs/governance/ADOPTING.md`.

## Run

```text
python3 tools/gatecheck/gatecheck.py
python3 -m unittest discover -s tools/gatecheck -v
python3 tools/gatecheck/gatecheck.py --spdx-only
```

Exit code 0 means the report has no failures.
The CI job name is `ci.job_name` in the project file.

## What it checks

1. Each schema file is a JSON document with `$schema` and `$id`.
2. Valid examples and packet files match the schema for their `gate` value.
3. Invalid examples fail the schema or a project rule.
4. Packet ids match file names and the configured prefix.
5. Dependencies exist and do not cycle.
6. Scopes overlap only when a dependency is declared.
7. A packet file has no `issue_number` and no `base_sha`.
8. CI evidence for Gate 3 matches the head SHA and the configured checks.
9. SPDX headers match the project file where the format allows a header.
10. Top-level names, `CODEOWNERS`, and the workflow match the project file.
11. A READY packet and a Gate 1 PASS cite known use cases.
12. Allowed files sit under the declared layer, except exempt process paths.
13. Each cited constraint and each declared transition names a regression test.
14. An architecture edit is its own packet and the worker role is OWNER.

CI checks paths. CI does not parse imports.
The reviewer checks imports. The list is in `GOVERNANCE_LINUS.md` section 16.
