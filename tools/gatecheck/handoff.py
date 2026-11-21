#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Rules for handoff payloads that a person gives to the checker by file.

A file holds one JSON object, or text with json gate-payload blocks.
These rules compare a payload with its packet file.
They also compare the payloads of one packet with each other.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import payloadrules

PACKETS_DIR = "docs/design/packets"
GATE_ORDER = ("G1_PLANNING", "G2_CODING", "G3_QA_MERGE")

_FENCE = re.compile(
    r"^```json gate-payload[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL
)


def read_payloads(text: str) -> tuple[list[dict], list[str]]:
    """Return the payloads in one text and the errors from the read."""
    text = text.replace("\r\n", "\n")
    if text.lstrip().startswith("{"):
        blocks = [text]
    else:
        blocks = _FENCE.findall(text)
    if not blocks:
        return [], ["the file has no JSON object and no json gate-payload block"]
    payloads: list[dict] = []
    errors: list[str] = []
    for index, block in enumerate(blocks, start=1):
        try:
            value = json.loads(block)
        except json.JSONDecodeError as exc:
            errors.append(f"block {index} is not JSON: {exc}")
            continue
        if isinstance(value, dict):
            payloads.append(value)
        else:
            errors.append(f"block {index} is not a JSON object")
    return payloads, errors


def load_packet(root: Path, packet_id: Any) -> dict | None:
    """Return the packet file for one id, or None when no correct file exists."""
    if not isinstance(packet_id, str) or re.fullmatch(r"[A-Z][A-Z0-9]*-[0-9]{4,}", packet_id) is None:
        return None
    path = root / PACKETS_DIR / f"{packet_id}.json"
    if not path.is_file():
        return None
    try:
        return payloadrules.json_object(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def packet_errors(payload: dict, packet: dict | None) -> list[str]:
    """Compare one verdict with the packet file that CI reads."""
    gate = payload.get("gate")
    if gate not in GATE_ORDER:
        return []
    if packet is None:
        if gate == "G1_PLANNING":
            return []
        return [f"no packet file for {payload.get('packet_id')} in {PACKETS_DIR}/"]
    if gate == "G1_PLANNING":
        return _gate1_packet_errors(payload, packet)
    if gate == "G2_CODING":
        return _gate2_packet_errors(payload, packet)
    return _gate3_packet_errors(payload, packet)


def _gate1_packet_errors(payload: dict, packet: dict) -> list[str]:
    """A PASS restates the plan. The packet file must say the same."""
    if payload.get("verdict") != "PASS":
        return []
    errors: list[str] = []
    if packet.get("status") != "READY":
        errors.append("Gate 1 PASS on a packet file that is not READY")
    pairs = {
        "allowed_files": (_allowed(payload), _allowed(packet)),
        "use_cases": (_names(payload.get("use_cases")), _names(packet.get("use_cases"))),
        "state_machines": (
            _names(payload.get("state_machines")),
            _names(packet.get("state_machines")),
        ),
        "regression test names": (_tests(payload), _tests(packet)),
        "layer": (payload.get("layer"), packet.get("layer")),
        "architecture_change": (
            payload.get("architecture_change") is True,
            packet.get("architecture_change") is True,
        ),
    }
    for label, (verdict_value, packet_value) in pairs.items():
        if verdict_value != packet_value:
            errors.append(f"Gate 1 {label} differs from the packet file")
    return errors


def _gate2_packet_errors(payload: dict, packet: dict) -> list[str]:
    """Each modified file is in the packet scope, or the verdict names it."""
    hygiene = _dict(payload.get("diff_hygiene"))
    allowed = sorted(_allowed(packet))
    outside = _names(hygiene.get("out_of_scope_files"))
    errors: list[str] = []
    for path in sorted(_names(hygiene.get("files_modified"))):
        if path in outside:
            continue
        if not any(payloadrules.paths_overlap(entry, path) for entry in allowed):
            errors.append(
                f"{path} is outside the packet allowed_files and is not in out_of_scope_files"
            )
    return errors


def _gate3_packet_errors(payload: dict, packet: dict) -> list[str]:
    if payload.get("verdict") != "MERGE_APPROVED":
        return []
    regression = _dict(_dict(payload.get("test_integrity_audit")).get("regression_test"))
    errors: list[str] = []
    if packet.get("regression_required") is True and regression.get("required") is not True:
        errors.append("the packet requires a regression test but regression_test.required is not true")
    name = regression.get("name")
    if isinstance(name, str) and name not in _tests(packet):
        errors.append(f"regression test {name} is not in the packet verification plan")
    return errors


def chain_errors(payloads: list[dict]) -> list[str]:
    """Compare the verdicts of each packet that has more than one payload."""
    by_packet: dict[str, dict[str, dict]] = {}
    errors: list[str] = []
    for payload in payloads:
        gate = payload.get("gate")
        packet_id = payload.get("packet_id")
        if gate not in GATE_ORDER or not isinstance(packet_id, str):
            continue
        gates = by_packet.setdefault(packet_id, {})
        if gate in gates:
            errors.append(f"{packet_id}: two {gate} payloads. Give one payload for each gate.")
        gates[gate] = payload
    for packet_id in sorted(by_packet):
        for message in _packet_chain_errors(by_packet[packet_id]):
            errors.append(f"{packet_id}: {message}")
    return errors


def _packet_chain_errors(gates: dict[str, dict]) -> list[str]:
    gate1 = gates.get("G1_PLANNING")
    gate2 = gates.get("G2_CODING")
    gate3 = gates.get("G3_QA_MERGE")
    errors = _branch_errors(gates)
    if gate1 is not None and gate2 is not None:
        errors.extend(_gate1_gate2_errors(gate1, gate2))
    if gate2 is not None and gate3 is not None:
        errors.extend(_gate2_gate3_errors(gate2, gate3))
    return errors


def _branch_errors(gates: dict[str, dict]) -> list[str]:
    branches = {_dict(payload.get("github")).get("branch") for payload in gates.values()}
    if len(branches) > 1:
        return ["the payloads name different branches. A packet has one branch."]
    return []


def _gate1_gate2_errors(gate1: dict, gate2: dict) -> list[str]:
    errors: list[str] = []
    if gate2.get("gate1_verdict_url") != _dict(gate1.get("handoff_artifact")).get("url"):
        errors.append("Gate 2 gate1_verdict_url is not the Gate 1 handoff_artifact.url")
    if gate2.get("verdict") == "PASS" and gate1.get("verdict") != "PASS":
        errors.append("Gate 2 PASS needs a Gate 1 PASS")
    return errors


def _gate2_gate3_errors(gate2: dict, gate3: dict) -> list[str]:
    errors: list[str] = []
    if gate3.get("gate2_verdict_url") != _dict(gate2.get("handoff_artifact")).get("url"):
        errors.append("Gate 3 gate2_verdict_url is not the Gate 2 handoff_artifact.url")
    for key in ("head_sha", "pr_number"):
        if _dict(gate3.get("github")).get(key) != _dict(gate2.get("github")).get(key):
            errors.append(f"Gate 3 {key} differs from Gate 2. A new head starts Gate 2 again.")
    if gate3.get("verdict") == "MERGE_APPROVED" and gate2.get("verdict") != "PASS":
        errors.append("Gate 3 MERGE_APPROVED needs a Gate 2 PASS")
    coder = _worker_id(gate2)
    if coder is not None and coder == _worker_id(gate3):
        errors.append("the Gate 3 worker is the Gate 2 worker. The coder does not QA that packet.")
    return errors


def _worker_id(payload: dict) -> str | None:
    agent_id = _dict(_dict(payload.get("provenance")).get("worker")).get("agent_id")
    return agent_id if isinstance(agent_id, str) else None


def _allowed(payload: dict) -> set[str]:
    return set(payloadrules.allowed_files(payload))


def _tests(payload: dict) -> set[str]:
    return payloadrules.regression_test_names(payload)


def _names(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}
