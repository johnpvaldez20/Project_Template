<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Backlog

Filed packets are in `packets/`.
A READY packet can take a Gate 1 review.
Add a row when you file a packet.
Do not file a feature that has no use case.

| Packet | Status | Use cases | Layer | Depends on | Delivers |
|---|---|---|---|---|---|
| PKT-0001 | READY | UC-01 | domain | none | Item record, save constraint, and the two state transitions |

PKT-0001 is the example. Replace it when the project has a real first packet.
Keep the fixture and the packet in agreement until you replace both.

## Amendment rule

A change to a filed packet is a gatekeeper pull request.
See `docs/governance/GOVERNANCE_LINUS.md` section 13.
A change to the architecture page or the fixtures is an owner packet.
See section 16.
A worker branch does not edit another packet file.
