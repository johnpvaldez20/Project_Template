#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Architecture catalog checks for packets and Gate 1 payloads.

Project paths and layer directories live in .governance/project.json.
This module does not name a product.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_UC_ID = re.compile(r"^UC-[0-9]{2,}$")
_TEST_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:[.:][A-Za-z_][A-Za-z0-9_]*)*$")
_ENTITY = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_LAYER = re.compile(r"^[a-z][a-z0-9-]*$")


def payload_errors(payload: dict, project: dict, root: Path | None) -> list[str]:
    """Return architecture errors for one packet or Gate 1 payload."""
    arch = project.get("architecture")
    if not isinstance(arch, dict):
        return []
    gate = payload.get("gate")
    if gate not in {"PACKET", "G1_PLANNING"}:
        return []
    catalog, machines, load_problems = load_catalog(root, arch)
    if load_problems:
        return load_problems
    strict = _strict(payload)
    errors: list[str] = []
    errors.extend(_use_case_errors(payload, catalog, strict))
    errors.extend(_layer_errors(payload, arch, strict))
    errors.extend(_transition_errors(payload, machines, strict))
    errors.extend(_change_errors(payload, arch))
    return errors


def coverage_errors(
    packets: list[tuple[Path, dict]], project: dict, root: Path
) -> list[str]:
    """Return errors when the catalog is not covered by the packet set."""
    arch = project.get("architecture")
    if not isinstance(arch, dict):
        return []
    catalog, machines, load_problems = load_catalog(root, arch)
    if load_problems:
        return load_problems
    cited: set[str] = set()
    declared: dict[str, list[set[str]]] = {}
    for _path, payload in packets:
        if not isinstance(payload, dict):
            continue
        for use_case in _string_list(payload.get("use_cases")):
            cited.add(use_case)
        names = _regression_names(payload)
        for entity in _string_list(payload.get("state_machines")):
            declared.setdefault(entity, []).append(names)
    problems: list[str] = []
    for use_case in sorted(catalog):
        if use_case not in cited:
            problems.append(f"use case {use_case} is not cited by a packet")
    for entity in sorted(machines):
        groups = declared.get(entity, [])
        tests = [edge["test"] for edge in machines[entity]["transitions"]]
        covered = any(all(test in names for test in tests) for names in groups)
        if not covered:
            problems.append(f"state machine {entity} is not covered by a packet")
    return problems


def load_catalog(root: Path | None, arch: dict) -> tuple[dict[str, dict], dict[str, dict], list[str]]:
    """Load and check the use-case catalog and the state machines."""
    if root is None:
        return {}, {}, ["architecture catalog root is missing"]
    errors: list[str] = []
    document = arch.get("document")
    if not isinstance(document, str) or not (root / document).is_file():
        errors.append("architecture.document is missing")
    if not isinstance(arch.get("layers"), dict) or not arch.get("layers"):
        errors.append("architecture.layers is missing")
    change_paths = arch.get("change_paths")
    if not isinstance(change_paths, list) or not change_paths:
        errors.append("architecture.change_paths is missing")
    use_cases = _read_json(root, arch.get("use_case_catalog"), errors)
    machines_doc = _read_json(root, arch.get("state_machines"), errors)
    if errors:
        return {}, {}, errors
    catalog, use_case_errors = _parse_use_cases(use_cases)
    machine_map, machine_errors = _parse_machines(machines_doc)
    return catalog, machine_map, use_case_errors + machine_errors


def linear_errors(machine: dict) -> list[str]:
    """Return errors when a linear machine skips or reverses a state."""
    if machine.get("linear") is not True:
        return []
    states = machine.get("states")
    entity = machine.get("entity", "machine")
    if not isinstance(states, list) or len(states) < 2:
        return [f"{entity} linear machine needs at least two states"]
    index = {name: position for position, name in enumerate(states) if isinstance(name, str)}
    errors: list[str] = []
    if machine.get("initial") != states[0]:
        errors.append(f"{entity} initial state is not the first state")
    seen: set[tuple[str, str]] = set()
    transitions = machine.get("transitions")
    if not isinstance(transitions, list):
        return errors + [f"{entity} transitions must be a list"]
    for edge in transitions:
        if not isinstance(edge, dict):
            continue
        source = edge.get("from")
        target = edge.get("to")
        if source not in index or target not in index:
            errors.append(f"{entity} transition {source} -> {target} leaves the state list")
            continue
        if index[target] != index[source] + 1:
            errors.append(f"{entity} transition {source} -> {target} skips or reverses a state")
        seen.add((source, target))
    for position in range(len(states) - 1):
        pair = (states[position], states[position + 1])
        if pair not in seen:
            errors.append(f"{entity} linear machine is missing transition {pair[0]} -> {pair[1]}")
    return errors


def _strict(payload: dict) -> bool:
    if payload.get("gate") == "PACKET":
        return payload.get("status") == "READY"
    if payload.get("gate") == "G1_PLANNING":
        return payload.get("verdict") == "PASS"
    return False


def _use_case_errors(payload: dict, catalog: dict[str, dict], strict: bool) -> list[str]:
    if "use_cases" not in payload:
        if strict:
            return ["packet cites no use case"]
        return []
    raw = payload.get("use_cases")
    if not isinstance(raw, list):
        return ["use_cases must be a list"]
    errors: list[str] = []
    if strict and len(raw) == 0:
        errors.append("packet cites no use case")
    names = _regression_names(payload)
    for use_case in raw:
        if not isinstance(use_case, str) or use_case not in catalog:
            errors.append(f"unknown use case {use_case}")
            continue
        test_name = catalog[use_case]["constraint_test"]
        if strict and test_name not in names:
            errors.append(
                f"verification plan is missing constraint test {test_name} for {use_case}"
            )
    return errors


def _layer_errors(payload: dict, arch: dict, strict: bool) -> list[str]:
    layers = arch.get("layers")
    if not isinstance(layers, dict):
        return ["architecture.layers is missing"]
    layer = payload.get("layer")
    if not isinstance(layer, str) or layer not in layers or _LAYER.fullmatch(layer) is None:
        if strict:
            return ["layer is missing or unknown"]
        if layer is not None:
            return [f"unknown layer {layer}"]
        return []
    prefixes = layers[layer]
    if not isinstance(prefixes, list) or not prefixes:
        return [f"layer {layer} has no paths"]
    exempt = arch.get("layer_exempt_prefixes", [])
    if not isinstance(exempt, list):
        exempt = []
    errors: list[str] = []
    for path in _allowed(payload):
        if _own_packet(path, payload):
            continue
        if any(isinstance(prefix, str) and _under(path, prefix) for prefix in exempt):
            continue
        if not any(isinstance(prefix, str) and _under(path, prefix) for prefix in prefixes):
            errors.append(f"allowed file {path} is outside layer {layer}")
    return errors


def _transition_errors(payload: dict, machines: dict[str, dict], strict: bool) -> list[str]:
    raw = payload.get("state_machines", [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        return ["state_machines must be a list"]
    if not strict:
        errors: list[str] = []
        for entity in raw:
            if not isinstance(entity, str) or entity not in machines:
                errors.append(f"unknown state machine {entity}")
        return errors
    names = _regression_names(payload)
    errors = []
    for entity in raw:
        if not isinstance(entity, str) or entity not in machines:
            errors.append(f"unknown state machine {entity}")
            continue
        for edge in machines[entity]["transitions"]:
            if edge["test"] not in names:
                errors.append(
                    f"verification plan is missing transition test {edge['test']} for {entity}"
                )
    return errors


def _change_errors(payload: dict, arch: dict) -> list[str]:
    change_paths = arch.get("change_paths")
    if not isinstance(change_paths, list):
        return ["architecture.change_paths is missing"]
    allowed = _allowed(payload)
    touches = [path for path in allowed if _matches_any(path, change_paths)]
    flagged = payload.get("architecture_change") is True
    if touches and not flagged:
        return ["edits to architecture paths need architecture_change true on their own packet"]
    if not flagged:
        return []
    errors: list[str] = []
    if _worker_role(payload) != "OWNER":
        errors.append("an architecture change packet requires worker role OWNER")
    if not touches:
        errors.append("architecture_change is true but allowed files do not include an architecture path")
    for path in allowed:
        if _own_packet(path, payload):
            continue
        if not _matches_any(path, change_paths):
            errors.append(f"architecture change packet must not also list {path}")
    return errors


def _parse_use_cases(document: Any) -> tuple[dict[str, dict], list[str]]:
    errors: list[str] = []
    if not isinstance(document, dict) or not isinstance(document.get("use_cases"), list):
        return {}, ["use-case catalog needs a use_cases list"]
    rows = document["use_cases"]
    if not rows:
        return {}, ["use-case catalog needs at least one use case"]
    catalog: dict[str, dict] = {}
    required = ("id", "title", "trigger", "flow", "constraint", "constraint_test")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"use case {index} is not an object")
            continue
        missing = [key for key in required if not isinstance(row.get(key), str) or not row.get(key)]
        if missing:
            errors.append(f"use case {index} is missing {', '.join(missing)}")
            continue
        use_id = row["id"]
        if _UC_ID.fullmatch(use_id) is None:
            errors.append(f"use case id {use_id} does not match UC-N")
            continue
        if _TEST_NAME.fullmatch(row["constraint_test"]) is None:
            errors.append(f"use case {use_id} constraint_test is not a test name")
            continue
        if use_id in catalog:
            errors.append(f"duplicate use case {use_id}")
            continue
        catalog[use_id] = row
    return catalog, errors


def _parse_machines(document: Any) -> tuple[dict[str, dict], list[str]]:
    errors: list[str] = []
    if not isinstance(document, dict) or not isinstance(document.get("machines"), list):
        return {}, ["state-machine catalog needs a machines list"]
    rows = document["machines"]
    if not rows:
        return {}, ["state-machine catalog needs at least one machine"]
    machines: dict[str, dict] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"state machine {index} is not an object")
            continue
        entity = row.get("entity")
        if not isinstance(entity, str) or _ENTITY.fullmatch(entity) is None:
            errors.append(f"state machine {index} entity is invalid")
            continue
        if entity in machines:
            errors.append(f"duplicate state machine {entity}")
            continue
        states = row.get("states")
        transitions = row.get("transitions")
        if not isinstance(row.get("linear"), bool):
            errors.append(f"{entity} linear must be a boolean")
            continue
        if not isinstance(states, list) or not all(isinstance(item, str) and item for item in states):
            errors.append(f"{entity} states must be a list of names")
            continue
        if len(states) != len(set(states)):
            errors.append(f"{entity} states are not unique")
            continue
        if row.get("initial") not in states:
            errors.append(f"{entity} initial state is not in the state list")
            continue
        if not isinstance(transitions, list) or not transitions:
            errors.append(f"{entity} needs at least one transition")
            continue
        edge_errors, edges = _parse_edges(entity, states, transitions)
        errors.extend(edge_errors)
        if edge_errors:
            continue
        machine = dict(row)
        machine["transitions"] = edges
        linear_problems = linear_errors(machine)
        errors.extend(linear_problems)
        if not linear_problems:
            machines[entity] = machine
    return machines, errors


def _parse_edges(
    entity: str, states: list[str], transitions: list[Any]
) -> tuple[list[str], list[dict[str, str]]]:
    known = set(states)
    errors: list[str] = []
    edges: list[dict[str, str]] = []
    for edge in transitions:
        if not isinstance(edge, dict):
            errors.append(f"{entity} transition is not an object")
            continue
        source = edge.get("from")
        target = edge.get("to")
        test_name = edge.get("test")
        if not isinstance(source, str) or source not in known:
            errors.append(f"{entity} transition leaves from an unknown state")
            continue
        if not isinstance(target, str) or target not in known:
            errors.append(f"{entity} transition arrives at an unknown state")
            continue
        if source == target:
            errors.append(f"{entity} transition {source} -> {target} does not move")
            continue
        if not isinstance(test_name, str) or _TEST_NAME.fullmatch(test_name) is None:
            errors.append(f"{entity} transition {source} -> {target} test name is invalid")
            continue
        edges.append({"from": source, "to": target, "test": test_name})
    return errors, edges


def _read_json(root: Path, relative: Any, errors: list[str]) -> Any:
    if not isinstance(relative, str) or not relative:
        errors.append("architecture catalog path is missing")
        return None
    path = root / relative
    if not path.is_file():
        errors.append(f"missing architecture catalog {relative}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{relative}: invalid JSON: {exc}")
        return None


def _allowed(payload: dict) -> list[str]:
    scope = payload.get("subsystem_scope")
    if not isinstance(scope, dict):
        return []
    values = scope.get("allowed_files")
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str)]


def _regression_names(payload: dict) -> set[str]:
    plan = payload.get("verification_plan")
    if not isinstance(plan, dict):
        return set()
    tests = plan.get("regression_tests")
    if not isinstance(tests, list):
        return set()
    return {
        item["name"]
        for item in tests
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _worker_role(payload: dict) -> str | None:
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        return None
    worker = provenance.get("worker")
    if not isinstance(worker, dict):
        return None
    role = worker.get("role")
    if isinstance(role, str):
        return role
    return None


def _own_packet(path: str, payload: dict) -> bool:
    packet_id = payload.get("packet_id")
    if not isinstance(packet_id, str):
        return False
    return path.rstrip("/") == f"docs/design/packets/{packet_id}.json"


def _under(path: str, prefix: str) -> bool:
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix


def _matches_any(path: str, patterns: list[Any]) -> bool:
    return any(isinstance(pattern, str) and _under(path, pattern) for pattern in patterns)
