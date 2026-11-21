<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

<!--
One packet, one branch, one pull request.
Read docs/governance/GOVERNANCE_LINUS.md.
Open this pull request when the branch is first pushed.
The first CI run can be the red run.
The branch name is pkt/<packet id>-<slug>.
The title starts with the packet id.
-->

## Packet

- **Packet:** <id from the project prefix>
- **Packet file:** `docs/design/packets/<id>.json`
- **Use cases:** <UC ids from the catalog>
- **Layer:** <presentation, application, domain, or infrastructure>
- **Gate 1 PASS:** <link to the issue comment that holds the Gate 1 payload>
- **Tracking issue:** <link recorded here, not inside the packet JSON>
- **Pull request base:** the host records the base. Do not copy a stale base SHA into the packet file.

## Worker provenance

```json
{
  "agent_id": "",
  "role": "CODER",
  "runtime": "LOCAL or CLOUD",
  "host": { "kind": "", "name": "" },
  "model": { "provider": "", "name": "", "settings": {} },
  "tool": { "name": "" }
}
```

## Scope

- [ ] The `scope` check is green on this head. It measures the base, the file list, and the planned tests.
- [ ] Every modified file is in the Gate 1 `allowed_files`.
- [ ] Every allowed file is under the declared layer, or it is on an exempt path.
- [ ] The import check is green. Each layer imports only the layers in `architecture.import_rules`.
- [ ] No import has a computed name.
- [ ] Infrastructure does not own a use-case rule.
- [ ] The packet cites each use case it serves. Each cited id is in the catalog.
- [ ] The verification plan names the constraint test for each cited use case.
- [ ] The verification plan names one test for each transition and each forbidden transition of each declared state machine.
- [ ] An edit to `docs/design/ARCHITECTURE.md` or `docs/design/fixtures/` is its own packet with worker role OWNER.
- [ ] No protected path was touched, unless this is a gatekeeper packet.
- [ ] No unrelated formatting. Every new dependency has a justification below.

## Tests

- [ ] Each planned regression test is in the tree by its name.
- [ ] No test uses the network, the wall clock, or the home directory.
- [ ] No test is skipped. No test is an expected failure.
- [ ] No assertion of an old test is weaker.
- [ ] The coverage in CI is at or above `policy.coverage_floor_percent`.

## Secrets

- [ ] The diff has no token, no key, and no environment file.

## Dependencies added

| name | version | why the current tree is not enough |
|---|---|---|
| — | — | — |

## Regression test

- **Name:**
- **Red run (fails without the change):** <CI URL>
- **Green run (passes on this head):** <CI URL>

## Local runs (advisory, zero weight)

```
command    ->
exit code  ->
```

<!--
Gate 2 and Gate 3 verdicts are pull request reviews with a json gate-payload block.
The gatekeeper writes them. Do not write a verdict for your own work.
Do not approve this pull request. Do not merge this pull request.
-->
