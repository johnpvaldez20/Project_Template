<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Adopt this gate template

Edit `.governance/project.json` for a new repository.
Do not edit the schemas for a project name, a license id, or a CI check name.
The gate checker reads the project file.
Field notes are in `.governance/README.md`.
JSON has no comments, so the notes live in that file.

## Keep these defaults

Keep the packet prefix `PKT` when you can.
Keep the CI check names when you can.
Keep the host kinds when you can.
The examples then stay valid.

## Set the project identity

1. Set `project.name` to the product name.
2. Set `project.full_name` to the full name.
3. Set `project.version` to the version string.
4. Set `project.repository` to `owner/name`.
5. Set `project.owner_login` to the GitHub login.
6. Put the same login in `CODEOWNERS` after `@`.
7. Set `toolchain.language` to the language id, or `undecided`.
8. Set `toolchain.pin_file` to the pin path, or `null`.

## Set the license

This template does not choose a license.
`LicenseRef-UNSET` is a marker. It is not a license. It grants no rights.
You choose the SPDX id. Put the text in `LICENSES/`.

1. Choose an SPDX license identifier.
2. Set `spdx.license_id` to that identifier.
3. Set `spdx.copyright_line` to the copyright notice.
4. Put both SPDX lines in each text file that allows a header.
5. Change every header when you change the license id.
6. Leave JSON files without a header. JSON has no comments.
7. Put the license text in `LICENSES/`.
8. Apply that license to the workflow and to the process documents.

## Set paths and checks

1. List allowed top-level names in `scope.allowed_top_level`.
2. List protected path patterns in `scope.protected_path_patterns`.
3. List packet-amendment patterns in `scope.amendment_path_patterns`.
4. List command prefixes in `verification.command_prefixes`.
5. List local-only lane capabilities in `lane.local_only_requires`.
6. Set `ci.job_name` to the required check name.
7. Put that same name on the workflow job.
8. Set `ci.required_checks` and `ci.check_commands`.
9. Copy each command into `.github/workflows/ci.yml`.
10. Keep `pull_request` in the workflow `on` block.

## Set the architecture

1. Replace each bracket in `docs/design/ARCHITECTURE.md`.
2. Put the same use cases in `docs/design/fixtures/use-cases.json`.
3. Put the same state machines in `docs/design/fixtures/state-machines.json`.
4. Set `architecture.layers` to your directory paths.
5. Keep one regression test name on each constraint.
6. Keep one regression test name on each transition.
7. An edit to those architecture files is its own packet.
8. Set `architecture_change` true on that packet.
9. Set the worker role to OWNER.
10. Do not mix feature files into that packet.

The issue form layer list is in `.github/ISSUE_TEMPLATE/work-packet.yml`.
Change that list when you rename a layer.

## Packet ids in examples

Example files use `{{packet:0003}}`.
The checker expands that token with `packet.id_prefix`.
A prefix change does not require an example edit.
Packet files under `docs/design/packets/` use real ids.
Rename those files when you change the prefix.
The file name must equal `packet_id`.

## CI checks in examples

The valid Gate 3 merge example sets `checks` to `{{required_checks}}`.
The checker builds those checks from `ci.check_commands`.
A check-name change does not require that example edit.
Invalid examples that spell a check name may need a matching edit.
Run the gate checker after the change.

## What you do not edit

Do not put the product name in `docs/governance/`.
Do not put the product name in the schemas.
Do not put the product name in `.github/` templates.
Do not put the product name in `tools/gatecheck/`.
Do not store `issue_number` in a packet file.
Do not store `base_sha` in a packet file.
Record both on the issue or the pull request.

## Prove the copy

1. Run `python3 tools/gatecheck/gatecheck.py`.
2. Run `python3 -m unittest discover -s tools/gatecheck -v`.
3. Open a pull request on the first push.
4. Wait for the check named by `ci.job_name`.
