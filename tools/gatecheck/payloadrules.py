#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Rules on a packet or a gate payload that a schema cannot state.

The schema checks the shape. These rules read the project file.
Each function returns failure lines. An empty list is success.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import architecture
import projectfile

VERDICT_GATES = ("G1_PLANNING", "G2_CODING", "G3_QA_MERGE")
PRIVILEGED_ROLES = {"GATEKEEPER": "gatekeeper", "OWNER": "owner"}
TEST_COUNTERS = ("total_tests", "failed_tests", "ignored_tests")


def extra_errors(payload: dict, project: dict, root: Path | None = None) -> list[str]:
    """Return the failure lines for one payload that already matches its schema."""
    errors = _identity_errors(payload, project)
    errors.extend(_string_errors(payload, project))
    errors.extend(_lane_errors(payload, project))
    errors.extend(_provenance_errors(payload, project))
    errors.extend(_scope_errors(payload, project))
    errors.extend(_definition_path_errors(payload))
    if payload.get("gate") == "G2_CODING":
        errors.extend(_gate2_errors(payload, project))
    if payload.get("gate") == "G3_QA_MERGE":
        errors.extend(_gate3_errors(payload, project))
    errors.extend(_toolchain_errors(payload, project))
    errors.extend(architecture.payload_errors(payload, project, root))
    return errors


def paths_overlap(left: str, right: str) -> bool:
    """True when two scope entries name the same path or a directory child."""
    if left == right:
        return True
    if left.endswith("/") and right.startswith(left):
        return True
    if right.endswith("/") and left.startswith(right):
        return True
    return False


def path_is_normal(path: str) -> bool:
    """False for an empty segment, a . segment, and a .. segment."""
    parts = path.split("/")
    if len(parts) > 1 and parts[-1] == "":
        parts = parts[:-1]
    return all(part not in ("", ".", "..") for part in parts)


def forbidden_packet_keys(value: Any) -> list[str]:
    """Return issue_number and base_sha keys found anywhere in a packet."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if key in {"issue_number", "base_sha"}:
                    found.add(key)
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return sorted(found)


def command_allowed(command: str, project: dict) -> bool:
    prefixes = project["verification"]["command_prefixes"]
    return any(command.startswith(prefix) for prefix in prefixes)


def lane_conflicts(project: dict, runtime: str, requires: list[str]) -> bool:
    local_only = set(project["lane"]["local_only_requires"])
    return runtime != "LOCAL" and bool(local_only & set(requires))


def packet_id_ok(packet_id: str, project: dict) -> bool:
    prefix = re.escape(project["packet"]["id_prefix"])
    return re.fullmatch(rf"{prefix}-[0-9]{{4,}}", packet_id) is not None


def _identity_errors(payload: dict, project: dict) -> list[str]:
    errors: list[str] = []
    if payload.get("gate") == "PACKET":
        for key in forbidden_packet_keys(payload):
            errors.append(
                f"design packet must not contain {key}; record it on the issue or pull request"
            )
    packet_id = payload.get("packet_id")
    if isinstance(packet_id, str) and not packet_id_ok(packet_id, project):
        errors.append(f"packet_id {packet_id} does not use the configured prefix")
    return errors


def _string_errors(payload: dict, project: dict) -> list[str]:
    errors: list[str] = []
    repository = project["project"]["repository"]
    base = f"https://github.com/{repository}/"
    for value in _walk_key(payload, "repository"):
        if value != repository:
            errors.append(f"repository {value} does not match the project config")
    for value in _walk_strings(payload):
        if value.startswith("https://github.com/") and not value.startswith(base):
            errors.append(f"github url is outside the configured repository: {value}")
        if "{{" in value:
            errors.append(f"unexpanded placeholder in {value}")
    for command in _walk_commands(payload):
        if not command_allowed(command, project):
            errors.append(f"command is not allowed by the project config: {command}")
    return errors


def _lane_errors(payload: dict, project: dict) -> list[str]:
    lane = _dict(payload.get("lane"))
    requires = lane.get("requires")
    runtime = lane.get("runtime")
    if isinstance(requires, list) and isinstance(runtime, str):
        if lane_conflicts(project, runtime, requires):
            return ["lane runtime is not LOCAL but requires a local-only capability"]
    return []


def _provenance_errors(payload: dict, project: dict) -> list[str]:
    """Check each agent. On a verdict, keep the worker apart from the signer."""
    agents = _named_agents(payload)
    errors: list[str] = []
    for label, agent in agents.items():
        errors.extend(_agent_errors(agent, project, label))
    for index, run in enumerate(_list(payload.get("local_runs"))):
        agent = _dict(run).get("agent")
        if isinstance(agent, dict):
            errors.extend(_agent_errors(agent, project, f"local_runs[{index}] agent"))
    if payload.get("gate") in VERDICT_GATES:
        errors.extend(_separation_errors(agents))
    return errors


def _named_agents(payload: dict) -> dict[str, dict]:
    agents: dict[str, dict] = {}
    provenance = _dict(payload.get("provenance"))
    for label in ("author", "worker"):
        if isinstance(provenance.get(label), dict):
            agents[label] = provenance[label]
    merged_by = _dict(payload.get("merge")).get("merged_by")
    if isinstance(merged_by, dict):
        agents["merged_by"] = merged_by
    return agents


def _separation_errors(agents: dict[str, dict]) -> list[str]:
    worker_id = agents.get("worker", {}).get("agent_id")
    if not isinstance(worker_id, str):
        return []
    errors: list[str] = []
    if agents.get("author", {}).get("agent_id") == worker_id:
        errors.append("author is the worker; a worker does not sign its own gate")
    if agents.get("merged_by", {}).get("agent_id") == worker_id:
        errors.append("merged_by is the worker; a worker does not merge")
    return errors


def _agent_errors(agent: dict, project: dict, label: str) -> list[str]:
    errors: list[str] = []
    runtime = agent.get("runtime")
    kind = _dict(agent.get("host")).get("kind")
    expected = {
        "LOCAL": project["hosts"]["local_kinds"],
        "CLOUD": project["hosts"]["cloud_kinds"],
        "GITHUB_ACTIONS": project["hosts"]["ci_kinds"],
    }.get(runtime)
    if expected is not None and kind not in expected:
        errors.append(f"{label} host kind {kind} does not match runtime {runtime}")
    if _dict(agent.get("model")).get("provider") == "OLLAMA" and runtime != "LOCAL":
        errors.append(f"{label} claims an OLLAMA model outside LOCAL runtime")
    section = PRIVILEGED_ROLES.get(agent.get("role"))
    if section is not None:
        pattern = project[section]["agent_id_pattern"]
        agent_id = agent.get("agent_id")
        if not isinstance(agent_id, str) or re.fullmatch(pattern, agent_id) is None:
            errors.append(f"{label} {section} agent_id does not match {section}.agent_id_pattern")
    return errors


def _scope_errors(payload: dict, project: dict) -> list[str]:
    allowed = _dict(payload.get("subsystem_scope")).get("allowed_files")
    if not isinstance(allowed, list):
        return []
    errors: list[str] = []
    for raw in allowed:
        if isinstance(raw, str):
            errors.extend(_scope_path_errors(raw, payload, project))
    return errors


def _scope_path_errors(raw: str, payload: dict, project: dict) -> list[str]:
    if not path_is_normal(raw):
        return [f"allowed file {raw} is not a normal repository path"]
    errors: list[str] = []
    is_packet = payload.get("gate") == "PACKET"
    top = raw.strip("/").split("/", 1)[0]
    if top not in project["scope"]["allowed_top_level"]:
        errors.append(f"allowed file {raw} is outside allowed top-level paths")
    if projectfile.path_is_protected(raw, project):
        if is_packet and payload.get("gatekeeper_packet") is not True:
            errors.append(f"protected path {raw} requires gatekeeper_packet true")
        if not is_packet and _worker_role(payload) not in PRIVILEGED_ROLES:
            errors.append(f"protected path {raw} requires a gatekeeper or owner worker")
    if is_packet and _amendment_blocked(raw, payload, project):
        errors.append(f"packet amendment path {raw} requires gatekeeper_packet true")
    return errors


def _definition_path_errors(payload: dict) -> list[str]:
    definitions = _dict(payload.get("data_contracts")).get("definitions")
    errors: list[str] = []
    for item in _list(definitions):
        path = _dict(item).get("path")
        if isinstance(path, str) and not path_is_normal(path):
            errors.append(f"definition path {path} is not a normal repository path")
    return errors


def _worker_role(payload: dict) -> str | None:
    role = _dict(_dict(payload.get("provenance")).get("worker")).get("role")
    return role if isinstance(role, str) else None


def _amendment_blocked(path: str, payload: dict, project: dict) -> bool:
    if payload.get("gatekeeper_packet") is True:
        return False
    patterns = project["scope"]["amendment_path_patterns"]
    if not any(re.search(pattern, path) for pattern in patterns):
        return False
    own = f"docs/design/packets/{payload.get('packet_id')}.json"
    return path.rstrip("/") != own


def _gate2_errors(payload: dict, project: dict) -> list[str]:
    hygiene = _dict(payload.get("diff_hygiene"))
    errors = _diff_errors(hygiene, project)
    if payload.get("verdict") != "PASS":
        return errors
    complexity = _dict(payload.get("taste_metrics")).get("max_cyclomatic_complexity")
    limit = project["policy"]["max_cyclomatic_complexity"]
    if _is_int(complexity) and complexity > limit:
        errors.append(f"max_cyclomatic_complexity {complexity} is above the configured limit {limit}")
    added = hygiene.get("forbidden_constructs_added")
    if _is_int(added) and added != 0:
        errors.append("PASS records forbidden constructs")
    return errors


def _diff_errors(hygiene: dict, project: dict) -> list[str]:
    """The file lists and the protected-path flag must agree."""
    modified = _strings(hygiene.get("files_modified"))
    outside = _strings(hygiene.get("out_of_scope_files"))
    errors = [
        f"diff path {path} is not a normal repository path"
        for path in modified + outside
        if not path_is_normal(path)
    ]
    protected = [path for path in modified if projectfile.path_is_protected(path, project)]
    if protected and hygiene.get("touches_protected_paths") is not True:
        errors.append(
            f"files_modified names the protected path {protected[0]} "
            "but touches_protected_paths is not true"
        )
    for path in outside:
        if path not in modified:
            errors.append(f"out_of_scope_files names {path}, which is not in files_modified")
    return errors


def _gate3_errors(payload: dict, project: dict) -> list[str]:
    github = _dict(payload.get("github"))
    evidence = _dict(payload.get("ci_evidence"))
    regression = _dict(_dict(payload.get("test_integrity_audit")).get("regression_test"))
    errors = _evidence_errors(github, evidence)
    errors.extend(_run_pair_errors(regression))
    if payload.get("verdict") != "MERGE_APPROVED":
        return errors
    checks = _dict(evidence.get("checks"))
    errors.extend(_required_check_errors(checks, project))
    errors.extend(_test_count_errors(checks, project))
    errors.extend(_coverage_errors(_dict(payload.get("coverage")), project))
    green = _dict(regression.get("green_run"))
    if regression.get("required") is True and green.get("head_sha") != github.get("head_sha"):
        errors.append("green_run.head_sha does not match github.head_sha")
    return errors


def _evidence_errors(github: dict, evidence: dict) -> list[str]:
    errors: list[str] = []
    head = github.get("head_sha")
    ci_head = evidence.get("head_sha")
    if isinstance(head, str) and isinstance(ci_head, str) and head != ci_head:
        errors.append(f"ci_evidence.head_sha {ci_head} does not match github.head_sha {head}")
    run_id = evidence.get("run_id")
    run_url = evidence.get("run_url")
    if _is_int(run_id) and isinstance(run_url, str):
        if not run_url.endswith(f"/actions/runs/{run_id}"):
            errors.append("ci_evidence.run_url does not end with ci_evidence.run_id")
    return errors


def _run_pair_errors(regression: dict) -> list[str]:
    """The red run and the green run are two runs on two commits."""
    red = regression.get("red_run")
    green = regression.get("green_run")
    if not isinstance(red, dict) or not isinstance(green, dict):
        return []
    errors: list[str] = []
    if red.get("head_sha") == green.get("head_sha"):
        errors.append("red_run and green_run name the same commit")
    if red.get("run_url") == green.get("run_url"):
        errors.append("red_run and green_run name the same CI run")
    return errors


def _required_check_errors(checks: dict, project: dict) -> list[str]:
    errors: list[str] = []
    for name in project["ci"]["required_checks"]:
        step = checks.get(name)
        if not isinstance(step, dict):
            errors.append(f"MERGE_APPROVED is missing required check {name}")
        elif step.get("exit_code") != 0:
            errors.append(f"required check {name} exit_code is not 0")
    return errors


def _test_count_errors(checks: dict, project: dict) -> list[str]:
    """An approval records each counter. A counter that is absent is not zero."""
    name = project["ci"]["test_check"]
    step = checks.get(name)
    if not isinstance(step, dict):
        return []
    missing = [key for key in TEST_COUNTERS if not _is_int(step.get(key))]
    if missing:
        return [f"{name} must record {key}" for key in missing]
    errors: list[str] = []
    if step["failed_tests"] != 0:
        errors.append(f"{name} failed_tests is not 0")
    if step["ignored_tests"] != 0:
        errors.append(f"{name} ignored_tests is not 0")
    if step["total_tests"] < 1:
        errors.append(f"{name} total_tests is below 1")
    return errors


def _coverage_errors(coverage: dict, project: dict) -> list[str]:
    percent = coverage.get("line_percentage")
    floor = project["policy"]["coverage_floor_percent"]
    if _dict(coverage.get("waiver")).get("granted") is True:
        return []
    if not isinstance(percent, (int, float)) or isinstance(percent, bool) or percent < floor:
        return [f"coverage {percent} is below the configured floor {floor}"]
    return []


def _toolchain_errors(payload: dict, project: dict) -> list[str]:
    toolchain = payload.get("toolchain")
    if not isinstance(toolchain, dict) or "language" not in toolchain:
        return []
    expected = project["toolchain"]["language"]
    if toolchain.get("language") != expected:
        return [f"toolchain language does not match the project config {expected}"]
    return []


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    return [item for item in _list(value) if isinstance(item, str)]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _walk_key(node: Any, key: str) -> list[Any]:
    found: list[Any] = []

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            for name, value in current.items():
                if name == key:
                    found.append(value)
                walk(value)
        elif isinstance(current, list):
            for item in current:
                walk(item)

    walk(node)
    return found


def _walk_strings(node: Any) -> list[str]:
    found: list[str] = []

    def walk(current: Any) -> None:
        if isinstance(current, str):
            found.append(current)
        elif isinstance(current, dict):
            for value in current.values():
                walk(value)
        elif isinstance(current, list):
            for item in current:
                walk(item)

    walk(node)
    return found


def _walk_commands(node: Any) -> list[str]:
    found: list[str] = []

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            for key, value in current.items():
                if key == "command" and isinstance(value, str):
                    found.append(value)
                elif key == "commands" and isinstance(value, list):
                    found.extend(item for item in value if isinstance(item, str))
                else:
                    walk(value)
        elif isinstance(current, list):
            for item in current:
                walk(item)

    walk(node)
    return found
