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

The gate checker tells you what is not complete.
Run it after each section of this page.
Do the sections in the order of this page.

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
6. Put the same login in `CODEOWNERS` after `@`. Put it on each rule.
7. Set `toolchain.language` to the language id, or `undecided`.
8. Set `toolchain.pin_file` to the pin path, or `null`.

Set the name, the full name, the repository, and the owner login in one change.
The checker fails when only some of them are set.
Set the identity before you set a language, a scanner, a report, or a forbidden construct.
The checker rejects those values while the identity is a placeholder.

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
7. Put that same name on the workflow job and in `.github/rulesets/main.json`.
8. Set `ci.required_checks` and `ci.check_commands`.
9. Copy each command into `.github/workflows/ci.yml`.
10. Keep `pull_request` in the workflow `on` block.
11. Keep the checkout step as it is. It checks out the head SHA with the full history.
12. Pin each new action to a full commit SHA.

Keep the patterns that protect the gate documents, the workflows, the project file, `CODEOWNERS`, and `tools/gatecheck/`.
The checker fails when one of them is not protected.
The pin file in `toolchain.pin_file` is also a protected path.
You can add the dependency manifest and the lock file to the protected patterns.
A new dependency is then a gatekeeper packet. A worker packet cannot add it.
Add each ignore rule of the product to `.gitignore`.
A file that Git ignores does not count as a top-level name.

## Add the product checks

The template has no product test. Add the checks when the first test exists.
A change to the workflow or to the project file is a gatekeeper packet.

1. Add one check for the product tests to `ci.required_checks` and `ci.check_commands`.
2. Add each lint check and each type check in the same way.
3. Set `ci.test_check` to the check that runs the product tests.
4. Make the test command write a JUnit XML report and a coverage report.
5. Set `ci.evidence.test_report` and `ci.evidence.coverage_report` to those files.
6. Add the check `python3 tools/gatecheck/gatecheck.py --evidence` after the test step.
7. Add the report directory to `.gitignore`.
8. Run the tests with the network off. Use the means of your stack or of your CI host.
9. Add each skip marker of your test tool to `policy.forbidden_constructs`.
10. Add a lint check that fails above `policy.max_cyclomatic_complexity` when your stack has one.

The evidence check fails on a failed test and on an ignored test.
It fails when the coverage is below `policy.coverage_floor_percent`.
The coverage report can be Cobertura XML, JaCoCo XML, or LCOV.
The template cannot turn the network off for you. That step depends on the stack.

## Set the forbidden constructs

`policy.forbidden_constructs` is empty in the template.
Each entry has an id, a pattern, a list of paths, and a reason.
The checker reads each line of each file under those paths.
A line that matches the pattern fails the gate.
An example is in `.governance/README.md`.

## Set the architecture

1. Replace each bracket in `docs/design/ARCHITECTURE.md`.
2. Put the same use cases in `docs/design/fixtures/use-cases.json`.
3. Put the same state machines in `docs/design/fixtures/state-machines.json`.
4. Set `architecture.layers` to your directory paths.
5. Keep one regression test name on each constraint.
6. Keep one regression test name on each transition and on each forbidden transition.
7. An edit to those architecture files is its own packet.
8. Set `architecture_change` true on that packet.
9. Set the worker role to OWNER.
10. Do not mix feature files into that packet.

The schemas of the two fixtures are `use-cases.schema.json` and `state-machines.schema.json`.
An unknown key in a fixture is an error.
A packet cites a state machine by its `entity` name.
A machine can also have an `id` such as `SM-01` and a `title`.
Set `linear` to false for a machine with a branch or a loop.
A transition can have an `event` and a `guard`.
List each move that the machine must reject in `forbidden_transitions`.
A test name has letters, digits, and `_`. The parts can be joined with `.` or `:`.

The issue form layer list is in `.github/ISSUE_TEMPLATE/work-packet.yml`.
Change that list when you rename a layer.

The examples in `docs/governance/examples/` have their own catalog.
Your catalog does not change them. Do not edit them for your product.

## Set the import rules

1. Read the default map in `architecture.import_rules.allowed`.
2. Change the map only when your layers differ. The map must not contain a cycle.
3. Add one scanner for each source language to `import_rules.scanners`.
4. Use the `python` parser for Python files.
5. Use the `regex` parser for each other language. Write its patterns.
6. List each file suffix in a layer that holds no import in `non_source_extensions`.
7. Add the test directory of a layer to the path list of that layer.
8. Put the file that connects the layers in `layer_exempt_prefixes`.
9. Put each file at the repository root that a packet edits in `layer_exempt_prefixes`.
10. Use `import_rules.forbidden` to keep a network module or a framework out of a layer.

Run the gate checker with the Python version of the product code when you use the `python` parser.
A file in a layer with no scanner fails the gate.
A source file outside every layer fails the gate.
The notes and an example of each parser are in `.governance/README.md`.

## Plan one layer for each packet

A packet has one `layer`.
Each allowed file is under that layer, or on an exempt path.
A feature that needs two layers is two packets.
Link them with `depends_on_packets`. The lower layer goes first.
A packet that changes the workflow, the project file, or the pin file sets `gatekeeper_packet` true.
A packet that edits a file of another packet names that packet in `depends_on_packets`.

## Set the host

The owner does the steps in `OWNER_SETUP.md`.
Those steps import the ruleset, create the labels, and limit the workflows.
The checker cannot do them. The checker cannot see if they are done.

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
Do not edit `tools/gatecheck/testdata/template_repo.json`. The tests of the checker use it.
Do not store `issue_number` in a packet file.
Do not store `base_sha` in a packet file.
Record both on the issue or the pull request.

## Prove the copy

1. Run `python3 tools/gatecheck/gatecheck.py`.
2. Run `python3 -m unittest discover -s tools/gatecheck -v`.
3. Run `python3 tools/gatecheck/architecture.py`.
4. Run `git fetch origin main`. Then run `python3 tools/gatecheck/gatecheck.py --pr`.
5. Open a pull request on the first push.
6. Wait for the check named by `ci.job_name`.

The report must end with `0 failed`.
The line `project identity is set` shows that the checker reads your project.
