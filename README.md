<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Development project template

This repository is a gate process for a new software project.
It does not contain a product.
Copy it when you start a repository.
Then set the project file and the architecture page.

The gatekeeper reviews plans, code, and test evidence.
A worker does not merge.

## Workflow

1. Write one packet under `docs/design/packets/`.
2. Cite the use case ids that the packet serves.
3. Ask the gatekeeper for a Gate 1 review.
4. Open the coder pull request on the first push.
5. Keep the red CI run URL and the green CI run URL.
6. Ask the gatekeeper for a Gate 2 review and a Gate 3 review.
7. The gatekeeper squash-merges after `MERGE_APPROVED`.

Open the pull request before the tree is green.
The first CI run can be the red run.
A later push on the same pull request can be the green run.
Put both run URLs in the Gate 3 payload.

## Start a new project

1. Copy this repository into a new repository.
2. Set `project.name` in `.governance/project.json`.
3. Set `project.full_name` and `project.version`.
4. Set `project.repository` to `owner/name`.
5. Set `project.owner_login` to the owner login.
6. Put that login after `@` in `CODEOWNERS`.
7. Choose a license by the steps in `docs/governance/ADOPTING.md`.
8. Replace each bracket in `docs/design/ARCHITECTURE.md`.
9. Update the use-case fixture and the state-machine fixture.
10. Set `architecture.layers` when your directories differ.
11. Run the gate commands in this file.
12. Open a pull request on the first push.

This template does not choose a license.
`LicenseRef-UNSET` is a marker. It grants no rights.
Field notes for the project file are in `.governance/README.md`.
JSON has no comments, so the notes live beside the file.

## Example

`PKT-0001` cites `UC-01` and the `Item` state machine.
The filled use case is `docs/design/fixtures/use-cases.json`.
The filled state machine is `docs/design/fixtures/state-machines.json`.
`docs/design/ARCHITECTURE.md` keeps brackets until you fill them.

## Read next

| Path | Contents |
|---|---|
| `docs/governance/GOVERNANCE_LINUS.md` | Gate contract |
| `docs/governance/ADOPTING.md` | Steps to set identity, license, and paths |
| `.governance/README.md` | Meaning of each project file field |
| `.governance/project.json` | Name, license marker, layers, and CI checks |
| `docs/design/ARCHITECTURE.md` | Architecture template with brackets |
| `docs/design/packets/PKT-0001.json` | Example packet that the gate checks |

## Gate commands

```text
python3 tools/gatecheck/gatecheck.py
python3 -m unittest discover -s tools/gatecheck -v
```

CI runs those commands on pull requests and on pushes to `main`.
The required check name is `gate`.
