#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Rules on the project file that a schema cannot state.

The schema is docs/governance/schemas/project.schema.json.
The gate checker applies the schema first. Then it applies these rules.
"""

from __future__ import annotations

import re

PLACEHOLDER_IDENTITY = {
    "name": "PROJECT-NAME",
    "full_name": "Replace with the full project name",
    "repository": "replace-me/project",
    "owner_login": "replace-me",
}
UNSET_LANGUAGE = "undecided"

_LAYER_NAME = re.compile(r"^[a-z][a-z0-9-]*$")


def is_template(project: dict) -> bool:
    """True when each identity field still holds the template placeholder."""
    identity = project["project"]
    return all(identity.get(key) == value for key, value in PLACEHOLDER_IDENTITY.items())


def path_is_protected(path: str, project: dict) -> bool:
    """True for a protected path pattern and for the toolchain pin file."""
    pin = project.get("toolchain", {}).get("pin_file")
    if isinstance(pin, str) and path == pin:
        return True
    return any(re.search(pattern, path) for pattern in project["scope"]["protected_path_patterns"])


def governance_paths(project: dict) -> list[str]:
    """One path from each part of the gate process. Each must be protected."""
    return [
        ".governance/project.json",
        "docs/governance/GOVERNANCE_LINUS.md",
        "docs/governance/schemas/common.schema.json",
        "docs/governance/examples/valid/gate1-pass.json",
        f".github/workflows/{project['ci']['workflow_file']}",
        "CODEOWNERS",
        "tools/gatecheck/gatecheck.py",
    ]


def semantic_errors(project: dict) -> list[str]:
    """Return the failure lines for a project file that matches the schema."""
    errors = _pattern_errors(project)
    if errors:
        return errors
    return (
        _ci_errors(project)
        + _layer_errors(project)
        + _import_rule_errors(project)
        + _construct_errors(project)
        + _protection_errors(project)
        + _identity_errors(project)
    )


def _pattern_errors(project: dict) -> list[str]:
    groups = {
        "scope.protected_path_patterns": project["scope"]["protected_path_patterns"],
        "scope.amendment_path_patterns": project["scope"]["amendment_path_patterns"],
        "gatekeeper.agent_id_pattern": [project["gatekeeper"]["agent_id_pattern"]],
        "owner.agent_id_pattern": [project["owner"]["agent_id_pattern"]],
    }
    errors: list[str] = []
    for label, patterns in groups.items():
        errors.extend(_regex_list_errors(label, patterns))
    return errors


def regex_problem(pattern: str) -> str | None:
    """Return the compile error text, or None when the pattern compiles."""
    try:
        re.compile(pattern)
    except re.error as exc:
        return str(exc)
    return None


def _ci_errors(project: dict) -> list[str]:
    ci = project["ci"]
    errors = [
        f"ci.check_commands has no command for the required check {name}"
        for name in ci["required_checks"]
        if name not in ci["check_commands"]
    ]
    if ci["test_check"] not in ci["required_checks"]:
        errors.append("ci.test_check must be one of ci.required_checks")
    errors.extend(_command_prefix_errors(project))
    gatekeeper = project["gatekeeper"]
    if re.fullmatch(gatekeeper["agent_id_pattern"], gatekeeper["persona_id"]) is None:
        errors.append("gatekeeper.persona_id does not match gatekeeper.agent_id_pattern")
    reports = [item is None for item in ci["evidence"].values()]
    if any(reports) and not all(reports):
        errors.append("ci.evidence must name the test report and the coverage report, or no report")
    return errors


def _command_prefix_errors(project: dict) -> list[str]:
    prefixes = project["verification"]["command_prefixes"]
    return [
        f"ci.check_commands.{name} does not start with a prefix in verification.command_prefixes"
        for name, command in project["ci"]["check_commands"].items()
        if not any(command.startswith(prefix) for prefix in prefixes)
    ]


def _layer_errors(project: dict) -> list[str]:
    layers = project["architecture"]["layers"]
    errors = [
        f"architecture.layers has the invalid layer name {name!r}"
        for name in layers
        if _LAYER_NAME.fullmatch(name) is None
    ]
    owned = [(path, name) for name, paths in layers.items() for path in paths]
    for index, (path_a, name_a) in enumerate(owned):
        for path_b, name_b in owned[index + 1 :]:
            if name_a != name_b and (path_a.startswith(path_b) or path_b.startswith(path_a)):
                errors.append(f"layer paths {path_a} and {path_b} overlap")
    return errors


def _import_rule_errors(project: dict) -> list[str]:
    architecture = project["architecture"]
    rules = architecture["import_rules"]
    layers = set(architecture["layers"])
    errors = _allowed_map_errors(rules["allowed"], layers)
    for layer, patterns in rules["forbidden"].items():
        if layer not in layers:
            errors.append(f"import_rules.forbidden names the unknown layer {layer}")
        errors.extend(_regex_list_errors(f"import_rules.forbidden.{layer}", patterns))
    errors.extend(_scanner_errors(rules, layers))
    return errors


def _allowed_map_errors(allowed: dict, layers: set[str]) -> list[str]:
    errors: list[str] = []
    if set(allowed) != layers:
        errors.append("import_rules.allowed needs one key for each layer in architecture.layers")
    for layer, targets in allowed.items():
        for target in targets:
            if target == layer:
                errors.append(f"import_rules.allowed.{layer} names itself")
            elif target not in layers:
                errors.append(f"import_rules.allowed.{layer} names the unknown layer {target}")
    if not errors and _has_cycle(allowed):
        errors.append("import_rules.allowed contains a cycle. Imports must have one direction.")
    return errors


def _has_cycle(graph: dict) -> bool:
    done: set[str] = set()
    active: set[str] = set()

    def visit(node: str) -> bool:
        if node in active:
            return True
        if node in done:
            return False
        active.add(node)
        found = any(visit(target) for target in graph.get(node, []))
        active.remove(node)
        done.add(node)
        return found

    return any(visit(node) for node in graph)


def _scanner_errors(rules: dict, layers: set[str]) -> list[str]:
    errors: list[str] = []
    owner: dict[str, int] = {}
    non_source = {item.lower() for item in rules["non_source_extensions"]}
    for index, scanner in enumerate(rules["scanners"]):
        label = f"import_rules.scanners[{index}]"
        for extension in scanner["extensions"]:
            key = extension.lower()
            if key in owner:
                errors.append(f"{label} reads {extension}, which scanner {owner[key]} also reads")
            owner.setdefault(key, index)
            if key in non_source:
                errors.append(f"{label} reads {extension}, which is in non_source_extensions")
        if scanner["parser"] == "regex":
            errors.extend(_regex_scanner_errors(label, scanner, layers))
    return errors


def _regex_scanner_errors(label: str, scanner: dict, layers: set[str]) -> list[str]:
    errors = _regex_list_errors(f"{label}.import_patterns", scanner["import_patterns"])
    for pattern in scanner["import_patterns"]:
        if regex_problem(pattern) is None and re.compile(pattern).groups < 1:
            errors.append(f"{label} import pattern {pattern!r} needs one group for the imported name")
    for layer, patterns in scanner["layer_patterns"].items():
        if layer not in layers:
            errors.append(f"{label}.layer_patterns names the unknown layer {layer}")
        errors.extend(_regex_list_errors(f"{label}.layer_patterns.{layer}", patterns))
    return errors


def _regex_list_errors(label: str, patterns: list[str]) -> list[str]:
    errors: list[str] = []
    for pattern in patterns:
        problem = regex_problem(pattern)
        if problem:
            errors.append(f"{label}: {pattern!r} is not a regular expression: {problem}")
    return errors


def _construct_errors(project: dict) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for construct in project["policy"]["forbidden_constructs"]:
        name = construct["id"]
        if name in seen:
            errors.append(f"policy.forbidden_constructs has the id {name} twice")
        seen.add(name)
        errors.extend(_regex_list_errors(f"policy.forbidden_constructs.{name}", [construct["pattern"]]))
    return errors


def _protection_errors(project: dict) -> list[str]:
    return [
        f"{path} must match scope.protected_path_patterns"
        for path in governance_paths(project)
        if not path_is_protected(path, project)
    ]


def _identity_errors(project: dict) -> list[str]:
    identity = project["project"]
    unset = sorted(
        key for key, value in PLACEHOLDER_IDENTITY.items() if identity.get(key) == value
    )
    if not unset:
        return []
    if len(unset) < len(PLACEHOLDER_IDENTITY):
        return [f"project.{key} still holds the template placeholder" for key in unset]
    return _template_errors(project)


def _template_errors(project: dict) -> list[str]:
    """A template has no product stack. Set the identity, then choose the stack."""
    toolchain = project["toolchain"]
    errors: list[str] = []
    if toolchain["language"] != UNSET_LANGUAGE:
        errors.append("toolchain.language is set but the project identity is a placeholder")
    if toolchain["pin_file"] is not None:
        errors.append("toolchain.pin_file is set but the project identity is a placeholder")
    if project["architecture"]["import_rules"]["scanners"]:
        errors.append("import_rules.scanners is set but the project identity is a placeholder")
    if any(value is not None for value in project["ci"]["evidence"].values()):
        errors.append("ci.evidence is set but the project identity is a placeholder")
    if project["policy"]["forbidden_constructs"]:
        errors.append("policy.forbidden_constructs is set but the project identity is a placeholder")
    return errors
