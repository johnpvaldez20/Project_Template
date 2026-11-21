#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Validate work packets, gate payloads, headers, and repository shape.

The project values live in .governance/project.json. This tool reads that
file. It does not name a product or a product language. It also checks the architecture catalog from that file.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import schema_validate
import architecture

SCHEMAS_DIR = "docs/governance/schemas"
VALID_DIR = "docs/governance/examples/valid"
INVALID_DIR = "docs/governance/examples/invalid"
PACKETS_DIR = "docs/design/packets"
CONFIG_PATH = ".governance/project.json"

GATE_FILES = {
    "PACKET": "packet.schema.json",
    "G1_PLANNING": "gate1-planning-handoff.schema.json",
    "G2_CODING": "gate2-coding-handoff.schema.json",
    "G3_QA_MERGE": "gate3-qa-merge-handoff.schema.json",
}

TEMPLATE_DIRS = ("docs/governance", ".github", "tools/gatecheck")


def _banned_patterns() -> tuple[re.Pattern[str], ...]:
    """Build the denylist without placing those words in this file."""
    parts = (
        ("ka", "te"),
        ("ktext", "editor"),
        (r"\b", "kd", "e", r"\b"),
        ("mac", "os"),
        ("mac", "book"),
        ("ap", "fs"),
        ("met", "al"),
        ("upstream", "/"),
        ("clip", "py"),
        (r"\b", "car", "go", r"\b"),
        ("rust-", "toolchain"),
        ("rust", "fmt"),
        ("owner_", "mac", "book"),
    )
    return tuple(re.compile("".join(item), re.IGNORECASE) for item in parts)

REQUIRED_PATHS = (
    "project.name",
    "project.repository",
    "project.owner_login",
    "packet.id_prefix",
    "spdx.license_id",
    "spdx.copyright_line",
    "spdx.extensions",
    "scope.allowed_top_level",
    "scope.protected_path_patterns",
    "scope.amendment_path_patterns",
    "verification.command_prefixes",
    "lane.local_only_requires",
    "hosts.local_kinds",
    "hosts.cloud_kinds",
    "hosts.ci_kinds",
    "ci.workflow_file",
    "ci.job_name",
    "ci.required_checks",
    "ci.test_check",
    "ci.check_commands",
    "toolchain.language",
    "toolchain.pin_file",
    "policy.max_cyclomatic_complexity",
    "policy.coverage_floor_percent",
    "policy.forbidden_constructs",
    "gatekeeper.persona_id",
    "gatekeeper.agent_id_pattern",
)


class Report:
    """Collected check lines. An empty failure list is success."""

    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failures: list[str] = []

    def is_clean(self) -> bool:
        return not self.failures

    def pass_(self, message: str) -> None:
        self.passed.append(message)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def __str__(self) -> str:
        lines = [f"ok    {line}" for line in self.passed]
        lines.extend(f"FAIL  {line}" for line in self.failures)
        lines.append(f"{len(self.passed)} passed, {len(self.failures)} failed")
        return "\n".join(lines) + "\n"


def paths_overlap(left: str, right: str) -> bool:
    """True when two scope entries name the same path or a directory child."""
    if left == right:
        return True
    if left.endswith("/") and right.startswith(left):
        return True
    if right.endswith("/") and left.startswith(right):
        return True
    return False


def expand_placeholders(value: Any, project: dict) -> Any:
    """Replace repository and packet-id tokens. Examples stay free of a slug."""
    repository = project["project"]["repository"]
    base = f"https://github.com/{repository}"
    prefix = project["packet"]["id_prefix"]

    def one(text: str) -> str:
        text = text.replace("{{repository}}", repository).replace("{{github_base}}", base)
        return re.sub(
            r"\{\{packet:([0-9]{4,})\}\}",
            lambda match: f"{prefix}-{match.group(1)}",
            text,
        )

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return one(node)
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, dict):
            return {key: walk(item) for key, item in node.items()}
        return node

    return walk(value)


def materialize_payload(payload: dict, project: dict) -> dict:
    """Fill config-owned CI checks so examples follow the project file."""
    evidence = payload.get("ci_evidence")
    if isinstance(evidence, dict) and evidence.get("checks") == "{{required_checks}}":
        evidence["checks"] = _checks_from_config(project)
    return payload


def _checks_from_config(project: dict) -> dict:
    test_name = project["ci"]["test_check"]
    checks: dict[str, dict] = {}
    for name, command in project["ci"]["check_commands"].items():
        if name not in project["ci"]["required_checks"]:
            continue
        if name == test_name:
            checks[name] = {
                "command": command,
                "exit_code": 0,
                "total_tests": 1,
                "failed_tests": 0,
                "ignored_tests": 0,
            }
        else:
            checks[name] = {"command": command, "exit_code": 0}
    return checks


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


def path_is_protected(path: str, project: dict) -> bool:
    return _matches_any(path, project["scope"]["protected_path_patterns"])


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, path) for pattern in patterns)


def _dig(document: dict, dotted: str) -> tuple[bool, Any]:
    current: Any = document
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json_dir(directory: Path) -> list[tuple[Path, Any]]:
    if not directory.is_dir():
        return []
    found: list[tuple[Path, Any]] = []
    for path in sorted(directory.glob("*.json")):
        found.append((path, _load_json(path)))
    return found


def payload_extra_errors(payload: dict, project: dict, root: Path | None = None) -> list[str]:
    """Rules that depend on project config, or that a schema cannot express."""
    errors: list[str] = []
    gate = payload.get("gate")
    if gate == "PACKET":
        for key in forbidden_packet_keys(payload):
            errors.append(
                f"design packet must not contain {key}; record it on the issue or pull request"
            )
    if isinstance(payload.get("packet_id"), str) and not packet_id_ok(payload["packet_id"], project):
        errors.append(f"packet_id {payload['packet_id']} does not use the configured prefix")

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

    lane = payload.get("lane")
    if isinstance(lane, dict):
        requires = lane.get("requires")
        runtime = lane.get("runtime")
        if isinstance(requires, list) and isinstance(runtime, str):
            if lane_conflicts(project, runtime, requires):
                errors.append("lane runtime is not LOCAL but requires a local-only capability")

    provenance = payload.get("provenance")
    if isinstance(provenance, dict):
        for label in ("author", "worker"):
            agent = provenance.get(label)
            if isinstance(agent, dict):
                errors.extend(_agent_errors(agent, project, label))

    scope = payload.get("subsystem_scope")
    if isinstance(scope, dict) and isinstance(scope.get("allowed_files"), list):
        gatekeeper = payload.get("gatekeeper_packet") is True
        worker_role = _worker_role(payload)
        for raw in scope["allowed_files"]:
            if not isinstance(raw, str):
                continue
            top = raw.strip("/").split("/", 1)[0]
            if top not in project["scope"]["allowed_top_level"]:
                errors.append(f"allowed file {raw} is outside allowed top-level paths")
            protected = path_is_protected(raw, project)
            if protected and gate == "PACKET" and not gatekeeper:
                errors.append(f"protected path {raw} requires gatekeeper_packet true")
            if protected and gate != "PACKET" and worker_role not in {"GATEKEEPER", "OWNER"}:
                errors.append(f"protected path {raw} requires a gatekeeper or owner worker")
            if gate == "PACKET" and _amendment_blocked(raw, payload, project):
                errors.append(f"packet amendment path {raw} requires gatekeeper_packet true")

    if gate == "G3_QA_MERGE":
        errors.extend(_gate3_errors(payload, project))
    if gate == "G2_CODING" and payload.get("verdict") == "PASS":
        errors.extend(_gate2_errors(payload, project))
    toolchain = payload.get("toolchain")
    if isinstance(toolchain, dict) and "language" in toolchain:
        expected = project["toolchain"]["language"]
        if toolchain.get("language") != expected:
            errors.append(f"toolchain language does not match the project config {expected}")
    errors.extend(architecture.payload_errors(payload, project, root))
    return errors


def _worker_role(payload: dict) -> str | None:
    worker = payload.get("provenance", {})
    if isinstance(worker, dict):
        agent = worker.get("worker")
        if isinstance(agent, dict):
            role = agent.get("role")
            if isinstance(role, str):
                return role
    return None


def _amendment_blocked(path: str, payload: dict, project: dict) -> bool:
    if payload.get("gatekeeper_packet") is True:
        return False
    if not _matches_any(path, project["scope"]["amendment_path_patterns"]):
        return False
    packet_id = payload.get("packet_id")
    own = f"docs/design/packets/{packet_id}.json"
    return path.rstrip("/") != own


def _agent_errors(agent: dict, project: dict, label: str) -> list[str]:
    errors: list[str] = []
    runtime = agent.get("runtime")
    host = agent.get("host") if isinstance(agent.get("host"), dict) else {}
    kind = host.get("kind")
    expected = {
        "LOCAL": project["hosts"]["local_kinds"],
        "CLOUD": project["hosts"]["cloud_kinds"],
        "GITHUB_ACTIONS": project["hosts"]["ci_kinds"],
    }.get(runtime)
    if expected is not None and kind not in expected:
        errors.append(f"{label} host kind {kind} does not match runtime {runtime}")
    model = agent.get("model") if isinstance(agent.get("model"), dict) else {}
    if model.get("provider") == "OLLAMA" and runtime != "LOCAL":
        errors.append(f"{label} claims an OLLAMA model outside LOCAL runtime")
    if agent.get("role") == "GATEKEEPER":
        pattern = project["gatekeeper"]["agent_id_pattern"]
        agent_id = agent.get("agent_id")
        if not isinstance(agent_id, str) or re.fullmatch(pattern, agent_id) is None:
            errors.append(f"{label} gatekeeper agent_id does not match the configured pattern")
    return errors


def _gate3_errors(payload: dict, project: dict) -> list[str]:
    errors: list[str] = []
    github = payload.get("github") if isinstance(payload.get("github"), dict) else {}
    evidence = payload.get("ci_evidence") if isinstance(payload.get("ci_evidence"), dict) else {}
    head = github.get("head_sha")
    ci_head = evidence.get("head_sha")
    if isinstance(head, str) and isinstance(ci_head, str) and head != ci_head:
        errors.append(f"ci_evidence.head_sha {ci_head} does not match github.head_sha {head}")
    if payload.get("verdict") != "MERGE_APPROVED":
        return errors
    checks = evidence.get("checks") if isinstance(evidence.get("checks"), dict) else {}
    for name in project["ci"]["required_checks"]:
        step = checks.get(name)
        if not isinstance(step, dict):
            errors.append(f"MERGE_APPROVED is missing required check {name}")
            continue
        if step.get("exit_code") != 0:
            errors.append(f"required check {name} exit_code is not 0")
    test_name = project["ci"]["test_check"]
    test_step = checks.get(test_name)
    if isinstance(test_step, dict):
        if test_step.get("failed_tests", 0) != 0:
            errors.append(f"{test_name} failed_tests is not 0")
        if test_step.get("ignored_tests", 0) != 0:
            errors.append(f"{test_name} ignored_tests is not 0")
        total = test_step.get("total_tests", 0)
        if not isinstance(total, int) or isinstance(total, bool) or total < 1:
            errors.append(f"{test_name} total_tests is below 1")
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    waiver = coverage.get("waiver") if isinstance(coverage.get("waiver"), dict) else {}
    percent = coverage.get("line_percentage")
    floor = project["policy"]["coverage_floor_percent"]
    granted = waiver.get("granted") is True
    if not granted and (not isinstance(percent, (int, float)) or isinstance(percent, bool) or percent < floor):
        errors.append(f"coverage {percent} is below the configured floor {floor}")
    audit = payload.get("test_integrity_audit")
    if isinstance(audit, dict) and isinstance(audit.get("regression_test"), dict):
        regression = audit["regression_test"]
        green = regression.get("green_run") if isinstance(regression.get("green_run"), dict) else {}
        if regression.get("required") is True and green.get("head_sha") != head:
            errors.append("green_run.head_sha does not match github.head_sha")
    return errors


def _gate2_errors(payload: dict, project: dict) -> list[str]:
    errors: list[str] = []
    taste = payload.get("taste_metrics") if isinstance(payload.get("taste_metrics"), dict) else {}
    complexity = taste.get("max_cyclomatic_complexity")
    limit = project["policy"]["max_cyclomatic_complexity"]
    if isinstance(complexity, int) and not isinstance(complexity, bool) and complexity > limit:
        errors.append(f"max_cyclomatic_complexity {complexity} is above the configured limit {limit}")
    hygiene = payload.get("diff_hygiene") if isinstance(payload.get("diff_hygiene"), dict) else {}
    added = hygiene.get("forbidden_constructs_added")
    if isinstance(added, int) and not isinstance(added, bool) and added != 0:
        errors.append("PASS records forbidden constructs")
    return errors


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

    walk(current := node)
    return found


def _check_config(project: dict, report: Report) -> bool:
    missing = [path for path in REQUIRED_PATHS if not _dig(project, path)[0]]
    if missing:
        report.fail("project config is missing " + ", ".join(missing))
        return False
    commands = project["ci"]["check_commands"]
    if not isinstance(commands, dict):
        report.fail("ci.check_commands must be an object")
        return False
    absent = [name for name in project["ci"]["required_checks"] if name not in commands]
    if absent:
        report.fail("ci.check_commands is missing " + ", ".join(absent))
        return False
    report.pass_("project config has the required keys")
    return True


def _load_schemas(root: Path, report: Report) -> schema_validate.SchemaSet | None:
    directory = root / SCHEMAS_DIR
    documents: dict[str, Any] = {}
    if not directory.is_dir():
        report.fail(f"no schemas found in {SCHEMAS_DIR}")
        return None
    for path in sorted(directory.glob("*.json")):
        try:
            documents[path.name] = _load_json(path)
        except json.JSONDecodeError as exc:
            report.fail(f"{_rel(root, path)}: invalid JSON: {exc}")
    if not documents:
        report.fail(f"no schemas found in {SCHEMAS_DIR}")
        return None
    for name, document in documents.items():
        if not isinstance(document, dict) or "$schema" not in document or "$id" not in document:
            report.fail(f"{SCHEMAS_DIR}/{name} needs $schema and $id")
        else:
            report.pass_(f"{SCHEMAS_DIR}/{name} is a schema document")
    return schema_validate.SchemaSet(documents)


def _check_payload(
    schemas: schema_validate.SchemaSet,
    root: Path,
    path: Path,
    payload: Any,
    project: dict,
    report: Report,
    *,
    must_reject: bool,
) -> None:
    name = _rel(root, path)
    if not isinstance(payload, dict):
        report.fail(f"{name}: payload is not an object")
        return
    expanded = materialize_payload(expand_placeholders(payload, project), project)
    gate = expanded.get("gate")
    schema_name = GATE_FILES.get(gate) if isinstance(gate, str) else None
    if schema_name is None or schema_name not in schemas.documents:
        if must_reject:
            report.fail(f"{name}: invalid examples must still name a known gate")
        else:
            report.fail(f"{name}: missing or unknown gate")
        return
    ok, errors = schemas.validate_document(schema_name, expanded)
    errors = list(errors)
    errors.extend(payload_extra_errors(expanded, project, root))
    if must_reject:
        if errors:
            report.pass_(f"{name} is rejected ({len(errors)} error(s), first: {errors[0]})")
        else:
            report.fail(f"{name} was accepted but must be rejected")
        return
    if errors:
        for item in errors:
            report.fail(f"{name}: {item}")
        return
    report.pass_(f"{name} validates")


def _packet_graph(root: Path, packets: list[tuple[Path, dict]], report: Report) -> None:
    known = [
        payload.get("packet_id")
        for _, payload in packets
        if isinstance(payload.get("packet_id"), str)
    ]
    for path, payload in packets:
        stem = path.stem
        packet_id = payload.get("packet_id")
        if stem == packet_id:
            report.pass_(f"{_rel(root, path)} packet_id matches file name")
        else:
            report.fail(f"{_rel(root, path)}: packet_id {packet_id!r} does not match file name {stem!r}")
        for dep in _depends(payload):
            if dep == packet_id:
                report.fail(f"{_rel(root, path)}: depends on itself")
            elif dep not in known:
                report.fail(f"{_rel(root, path)}: depends_on_packets names unknown packet {dep}")
    _cycles(root, packets, report)
    conflicts = 0
    for index, (path_a, left) in enumerate(packets):
        for path_b, right in packets[index + 1 :]:
            id_a = left.get("packet_id")
            id_b = right.get("packet_id")
            if not isinstance(id_a, str) or not isinstance(id_b, str):
                continue
            if id_b in _depends(left) or id_a in _depends(right):
                continue
            for file_a in _allowed(left):
                for file_b in _allowed(right):
                    if paths_overlap(file_a, file_b):
                        conflicts += 1
                        report.fail(
                            f"{_rel(root, path_a)} and {_rel(root, path_b)} "
                            f"both claim {file_a!r} / {file_b!r} without a declared dependency"
                        )
    if conflicts == 0 and len(packets) > 1:
        report.pass_(f"{len(packets)} packets have disjoint or dependency-ordered scopes")


def _depends(payload: dict) -> list[str]:
    scope = payload.get("subsystem_scope")
    if not isinstance(scope, dict):
        return []
    values = scope.get("depends_on_packets")
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str)]


def _allowed(payload: dict) -> list[str]:
    scope = payload.get("subsystem_scope")
    if not isinstance(scope, dict):
        return []
    values = scope.get("allowed_files")
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str)]


def _cycles(root: Path, packets: list[tuple[Path, dict]], report: Report) -> None:
    graph = {
        payload.get("packet_id"): _depends(payload)
        for _, payload in packets
        if isinstance(payload.get("packet_id"), str)
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(node: str) -> None:
        if node in visiting:
            report.fail(f"packet dependency cycle includes {node}")
            return
        if node in visited:
            return
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep in graph:
                walk(dep)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(key for key in graph if isinstance(key, str)):
        walk(node)


def _check_top_level(root: Path, project: dict, report: Report) -> None:
    allowed = set(project["scope"]["allowed_top_level"])
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if child.name in {".git", "__pycache__"}:
            continue
        if child.name not in allowed:
            report.fail(f"top-level path {child.name} is not in the project config")
    report.pass_("top-level paths match the project config")


def _check_codeowners(root: Path, project: dict, report: Report) -> None:
    path = root / "CODEOWNERS"
    if not path.is_file():
        return
    login = project["project"]["owner_login"]
    text = path.read_text(encoding="utf-8")
    if f"@{login}" not in text:
        report.fail(f"CODEOWNERS does not name @{login} from the project config")
    else:
        report.pass_("CODEOWNERS matches project.owner_login")


def _check_workflow(root: Path, project: dict, report: Report) -> None:
    workflow = root / ".github" / "workflows" / project["ci"]["workflow_file"]
    if not workflow.is_file():
        if (root / ".github").exists():
            report.fail(f"missing {workflow.relative_to(root).as_posix()}")
        return
    text = workflow.read_text(encoding="utf-8")
    job = project["ci"]["job_name"]
    ok = True
    if f"\n  {job}:\n" not in text or f"\n    name: {job}\n" not in text:
        report.fail(f"workflow job name must be {job}")
        ok = False
    if "pull_request:" not in text:
        report.fail("workflow must run on pull_request")
        ok = False
    for command in project["ci"]["check_commands"].values():
        if command not in text:
            report.fail(f"workflow is missing command: {command}")
            ok = False
    if ok:
        report.pass_("workflow matches the project CI config")


def _check_spdx(root: Path, project: dict, report: Report) -> None:
    extensions = {item.lower() for item in project["spdx"]["extensions"]}
    basenames = set(project["spdx"].get("basenames", []))
    exempt = set(project["spdx"].get("exempt_basenames", []))
    copyright_line = project["spdx"]["copyright_line"]
    license_line = f"SPDX-License-Identifier: {project['spdx']['license_id']}"
    checked = 0
    for path in _iter_files(root):
        name = path.name
        if name in exempt:
            continue
        if name not in basenames and path.suffix.lower() not in extensions:
            continue
        checked += 1
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:12])
        rel = _rel(root, path)
        if copyright_line not in head:
            report.fail(f"{rel}: missing {copyright_line}")
        if license_line not in head:
            report.fail(f"{rel}: missing {license_line}")
    if checked == 0:
        report.fail("no files were checked for SPDX headers")
    else:
        report.pass_(f"checked SPDX headers on {checked} files")


def _check_neutrality(root: Path, report: Report) -> None:
    for relative in TEMPLATE_DIRS:
        directory = root / relative
        if not directory.exists():
            continue
        paths = [directory] if directory.is_file() else _iter_files(directory)
        for path in paths:
            if path.suffix.lower() in {".png", ".jpg"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pattern in _banned_patterns():
                match = pattern.search(text)
                if match:
                    report.fail(
                        f"{_rel(root, path)} contains non-neutral text {match.group(0)!r}"
                    )
                    break
    report.pass_("template paths do not name a product stack")


def _iter_files(root: Path) -> list[Path]:
    skip = {".git", "__pycache__", ".pytest_cache"}
    found: list[Path] = []
    if not root.exists():
        return found
    for path in root.rglob("*"):
        if any(part in skip for part in path.parts):
            continue
        if path.is_file():
            found.append(path)
    found.sort()
    return found


def run(root: Path) -> Report:
    """Run every check against the repository at root."""
    report = Report()
    config_path = root / CONFIG_PATH
    if not config_path.is_file():
        report.fail(f"missing {CONFIG_PATH}")
        return report
    try:
        project = _load_json(config_path)
    except json.JSONDecodeError as exc:
        report.fail(f"{CONFIG_PATH}: invalid JSON: {exc}")
        return report
    if not isinstance(project, dict) or not _check_config(project, report):
        return report

    schemas = _load_schemas(root, report)
    if schemas is None:
        return report

    for relative, must_exist in ((VALID_DIR, True), (INVALID_DIR, True), (PACKETS_DIR, True)):
        directory = root / relative
        rows = _load_json_dir(directory)
        if must_exist and not rows:
            report.fail(f"no payloads found in {relative}")
        for path, payload in rows:
            _check_payload(
                schemas,
                root,
                path,
                payload,
                project,
                report,
                must_reject=relative == INVALID_DIR,
            )

    packets: list[tuple[Path, dict]] = []
    for path, payload in _load_json_dir(root / PACKETS_DIR):
        if isinstance(payload, dict):
            packets.append((path, expand_placeholders(payload, project)))
    if packets:
        _packet_graph(root, packets, report)
    coverage_problems = architecture.coverage_errors(packets, project, root)
    for message in coverage_problems:
        report.fail(message)
    if isinstance(project.get("architecture"), dict) and not coverage_problems:
        report.pass_("architecture catalog is covered by packets")

    _check_top_level(root, project, report)
    _check_codeowners(root, project, report)
    _check_workflow(root, project, report)
    _check_spdx(root, project, report)
    _check_neutrality(root, report)
    return report


def default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    spdx_only = "--spdx-only" in args
    args = [arg for arg in args if arg != "--spdx-only"]
    root = Path(args[0]) if args else default_root()
    if spdx_only:
        report = _spdx_only(root)
    else:
        report = run(root)
    sys.stdout.write(str(report))
    return 0 if report.is_clean() else 1


def _spdx_only(root: Path) -> Report:
    report = Report()
    config_path = root / CONFIG_PATH
    try:
        project = _load_json(config_path)
    except (OSError, json.JSONDecodeError) as exc:
        report.fail(f"{CONFIG_PATH}: {exc}")
        return report
    if not isinstance(project, dict) or not _check_config(project, report):
        return report
    _check_spdx(root, project, report)
    return report


if __name__ == "__main__":
    sys.exit(main())
