<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Infrastructure

Put infrastructure code in this directory.
Infrastructure talks to the network, the database, and the clock.
It does not own a use-case rule.
It can import application and domain.
The import map is `architecture.import_rules` in `.governance/project.json`.
Read `docs/design/ARCHITECTURE.md`.
