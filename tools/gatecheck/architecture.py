#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Architecture rules for packets, Gate 1 payloads, and source files.

Project paths, layer directories, and import rules live in
.governance/project.json. This module does not name a product.

Run this file to check the catalog, the packets, and the import direction:

    python3 tools/gatecheck/architecture.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import importscan

_UC_ID = re.compile(r"^UC-[0-9]{2,}$")
_TEST_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:[.:][A-Za-z_][A-Za-z0-9_]*)*$")
_ENTITY = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_MACHINE_ID = re.compile(r"^SM-[0-9]{2,}$")
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
        tests = machine_tests(machines[entity])
        covered = any(all(test in names for test in tests) for names in groups)
        if not covered:
            problems.append(f"state machine {entity} is not covered by a packet")
    return problems


def import_errors(root: Path, files: list[str], project: dict) -> tuple[list[str], int]:
    """Check the import direction of each source file in a layer.

    Return the failure lines and the count of files that a scanner read.
    A file in a layer must have a scanner, or its suffix must be a declared
    non-source suffix. A source file must be in a layer or on an exempt path.
    """
    arch = project["architecture"]
    rules = arch["import_rules"]
    scanners = {
        suffix.lower(): scanner for scanner in rules["scanners"] for suffix in scanner["extensions"]
    }
    non_source = {item.lower() for item in rules["non_source_extensions"]}
    exempt = arch["layer_exempt_prefixes"]
    errors: list[str] = []
    scanned = 0
    for path in files:
        if _matches_any(path, exempt):
            continue
        suffix = PurePosixPath(path).suffix.lower()
        scanner = scanners.get(suffix)
        layer = importscan.layer_of(path, arch["layers"])
        if layer is None and scanner is not None:
            errors.append(
                f"{path}: source file is outside every layer. "
                "Move it into a layer, or add it to layer_exempt_prefixes."
            )
        elif layer is not None and scanner is None and suffix not in non_source:
            errors.append(
                f"{path}: no scanner reads this file type. "
                "Add a scanner, or add the suffix to non_source_extensions."
            )
        elif layer is not None and scanner is not None:
            scanned += 1
            errors.extend(_file_import_errors(root, path, layer, scanner, arch))
    return errors, scanned


def _file_import_errors(
    root: Path, path: str, layer: str, scanner: dict, arch: dict
) -> list[str]:
    try:
        source = (root / path).read_text(encoding="utf-8-sig")
        found = importscan.scan(source, path, scanner, arch["layers"])
    except UnicodeDecodeError:
        return [f"{path}: cannot read the file as UTF-8"]
    except SyntaxError as exc:
        return [f"{path}: cannot parse the file: line {exc.lineno}: {exc.msg}"]
    rules = arch["import_rules"]
    allowed = set(rules["allowed"].get(layer, [])) | {layer}
    forbidden = rules["forbidden"].get(layer, [])
    errors: list[str] = []
    reported: set[tuple[int, str]] = set()
    for item in found:
        for target in item.layers:
            if target not in allowed and (item.line, target) not in reported:
                reported.add((item.line, target))
                errors.append(
                    f"{path}:{item.line}: layer {layer} must not import layer {target} ({item.text})"
                )
        if any(re.search(pattern, item.text) for pattern in forbidden):
            errors.append(f"{path}:{item.line}: layer {layer} must not import {item.text}")
    return errors


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
        for test in machine_tests(machines[entity]):
            if test not in names:
                errors.append(
                    f"verification plan is missing transition test {test} for {entity}"
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


def machine_tests(machine: dict) -> list[str]:
    """Return the test names of each transition and each forbidden transition."""
    edges = machine["transitions"] + machine.get("forbidden_transitions", [])
    return [edge["test"] for edge in edges]


def _parse_machines(document: Any) -> tuple[dict[str, dict], list[str]]:
    if not isinstance(document, dict) or not isinstance(document.get("machines"), list):
        return {}, ["state-machine catalog needs a machines list"]
    rows = document["machines"]
    if not rows:
        return {}, ["state-machine catalog needs at least one machine"]
    machines: dict[str, dict] = {}
    errors: list[str] = []
    ids: set[str] = set()
    for index, row in enumerate(rows):
        machine, problems = _parse_machine(index, row)
        errors.extend(problems)
        if machine is None:
            continue
        entity = machine["entity"]
        machine_id = machine.get("id")
        if entity in machines:
            errors.append(f"duplicate state machine {entity}")
        elif machine_id is not None and machine_id in ids:
            errors.append(f"duplicate state machine id {machine_id}")
        else:
            machines[entity] = machine
            ids.add(machine_id)
    return machines, errors


def _parse_machine(index: int, row: Any) -> tuple[dict | None, list[str]]:
    if not isinstance(row, dict):
        return None, [f"state machine {index} is not an object"]
    entity = row.get("entity")
    if not isinstance(entity, str) or _ENTITY.fullmatch(entity) is None:
        return None, [f"state machine {index} entity is invalid"]
    shape = _machine_shape_errors(entity, row)
    if shape:
        return None, shape
    edge_errors, edges = _parse_edges(entity, row["states"], row["transitions"])
    forbidden_errors, forbidden = _parse_forbidden(
        entity, row["states"], edges, row.get("forbidden_transitions", [])
    )
    machine = dict(row)
    machine["transitions"] = edges
    machine["forbidden_transitions"] = forbidden
    errors = edge_errors + forbidden_errors
    if not errors:
        errors = linear_errors(machine) + _reach_errors(machine) + _test_name_errors(machine)
    return (None if errors else machine), errors


def _machine_shape_errors(entity: str, row: dict) -> list[str]:
    states = row.get("states")
    machine_id = row.get("id")
    if machine_id is not None and (
        not isinstance(machine_id, str) or _MACHINE_ID.fullmatch(machine_id) is None
    ):
        return [f"{entity} id does not match SM-N"]
    if not isinstance(row.get("linear"), bool):
        return [f"{entity} linear must be a boolean"]
    if not isinstance(states, list) or not all(isinstance(item, str) and item for item in states):
        return [f"{entity} states must be a list of names"]
    if len(states) != len(set(states)):
        return [f"{entity} states are not unique"]
    if row.get("initial") not in states:
        return [f"{entity} initial state is not in the state list"]
    transitions = row.get("transitions")
    if not isinstance(transitions, list) or not transitions:
        return [f"{entity} needs at least one transition"]
    return []


def _parse_edges(
    entity: str, states: list[str], transitions: list[Any]
) -> tuple[list[str], list[dict[str, str]]]:
    errors: list[str] = []
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in transitions:
        problem, edge = _parse_edge(entity, states, row)
        if edge is None:
            errors.append(problem)
            continue
        key = (edge["from"], edge["to"], edge.get("event", ""))
        if key in seen:
            errors.append(f"{entity} transition {edge['from']} -> {edge['to']} is in the list twice")
            continue
        seen.add(key)
        edges.append(edge)
    return errors, edges


def _parse_edge(entity: str, states: list[str], row: Any) -> tuple[str, dict[str, str] | None]:
    """Return the problem text, or the edge when the row is correct."""
    if not isinstance(row, dict):
        return f"{entity} transition is not an object", None
    source = row.get("from")
    target = row.get("to")
    test_name = row.get("test")
    if not isinstance(source, str) or source not in states:
        return f"{entity} transition leaves from an unknown state", None
    if not isinstance(target, str) or target not in states:
        return f"{entity} transition arrives at an unknown state", None
    if source == target:
        return f"{entity} transition {source} -> {target} does not move", None
    if not isinstance(test_name, str) or _TEST_NAME.fullmatch(test_name) is None:
        return f"{entity} transition {source} -> {target} test name is invalid", None
    edge = {"from": source, "to": target, "test": test_name}
    for key in ("event", "guard"):
        if isinstance(row.get(key), str):
            edge[key] = row[key]
    return "", edge


def _parse_forbidden(
    entity: str, states: list[str], edges: list[dict[str, str]], rows: Any
) -> tuple[list[str], list[dict[str, str]]]:
    """A forbidden transition names a move that the machine must reject."""
    if not isinstance(rows, list):
        return [f"{entity} forbidden_transitions must be a list"], []
    declared = {(edge["from"], edge["to"]) for edge in edges}
    errors: list[str] = []
    forbidden: list[dict[str, str]] = []
    for row in rows:
        problem, edge = _parse_edge(entity, states, row)
        if edge is None:
            errors.append(problem.replace(" transition ", " forbidden transition ", 1))
            continue
        pair = (edge["from"], edge["to"])
        if pair in declared:
            errors.append(f"{entity} forbidden transition {pair[0]} -> {pair[1]} is also a transition")
            continue
        if pair in {(item["from"], item["to"]) for item in forbidden}:
            errors.append(f"{entity} forbidden transition {pair[0]} -> {pair[1]} is in the list twice")
            continue
        forbidden.append({"from": edge["from"], "to": edge["to"], "test": edge["test"]})
    return errors, forbidden


def _reach_errors(machine: dict) -> list[str]:
    """Each state must be on a path from the initial state."""
    reached = {machine["initial"]}
    frontier = [machine["initial"]]
    while frontier:
        state = frontier.pop()
        for edge in machine["transitions"]:
            if edge["from"] == state and edge["to"] not in reached:
                reached.add(edge["to"])
                frontier.append(edge["to"])
    return [
        f"{machine['entity']} state {state} cannot be reached from the initial state"
        for state in machine["states"]
        if state not in reached
    ]


def _test_name_errors(machine: dict) -> list[str]:
    """One test proves one transition. A test name must not repeat."""
    tests = machine_tests(machine)
    repeated = sorted({name for name in tests if tests.count(name) > 1})
    return [f"{machine['entity']} test name {name} is on two transitions" for name in repeated]


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


def main(argv: list[str] | None = None) -> int:
    """Run the architecture checks of the gate checker."""
    import gatecheck

    args = list(sys.argv[1:] if argv is None else argv)
    return gatecheck.main(["--architecture", *args])


if __name__ == "__main__":
    sys.exit(main())
