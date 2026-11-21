<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Governance package

| File | What it is |
|---|---|
| `GOVERNANCE_LINUS.md` | The contract. Laws, roles, three gates, lanes, CI, architecture, and amendments. |
| `ADOPTING.md` | How to copy this template into another repository. |
| `schemas/common.schema.json` | Shared definitions. |
| `schemas/packet.schema.json` | Work packet plan. No issue number. No base SHA. |
| `schemas/gate1-planning-handoff.schema.json` | Gate 1 verdict. |
| `schemas/gate2-coding-handoff.schema.json` | Gate 2 verdict. |
| `schemas/gate3-qa-merge-handoff.schema.json` | Gate 3 verdict. |
| `examples/valid/` | Payloads that must validate. |
| `examples/invalid/` | Payloads that must be rejected. |

Schemas use JSON Schema 2020-12.
Project values live in `.governance/project.json`.
`python3 tools/gatecheck/gatecheck.py` checks schemas, examples, packets, headers, paths, and the architecture catalog.

Schema version is 2.0.0.
This is the generic template.
It is not a continuation of a product-specific schema.
