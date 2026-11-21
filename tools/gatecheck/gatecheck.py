#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Validate work packets, gate payloads, headers, and repository shape.

The project values live in .governance/project.json. This tool reads that
file. It does not name a product or a product language.

With no option, the tool checks the full repository.
--architecture checks the catalog, the packets, and the import direction.
--payload checks gate payloads that are in files.
--pr checks the commits between the base branch and HEAD.
--evidence checks the test report and the coverage report from CI.
--spdx-only checks the license headers.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import architecture
import evidence
import handoff
import payloadrules
import projectfile
import repofiles
import schema_validate
import treecheck

SCHEMAS_DIR = "docs/governance/schemas"
VALID_DIR = "docs/governance/examples/valid"
INVALID_DIR = "docs/governance/examples/invalid"
EXAMPLE_ARCHITECTURE = "docs/governance/examples/architecture.json"
EXAMPLE_INDEX = "docs/governance/examples/README.md"
PACKETS_DIR = "docs/design/packets"
CONFIG_PATH = ".governance/project.json"

GATE_FILES = {
    "PACKET": "packet.schema.json",
    "G1_PLANNING": "gate1-planning-handoff.schema.json",
    "G2_CODING": "gate2-coding-handoff.schema.json",
    "G3_QA_MERGE": "gate3-qa-merge-handoff.schema.json",
}

PROJECT_SCHEMA = "project.schema.json"
ARCHITECTURE_REF = "project.schema.json#/properties/architecture"
CATALOG_SCHEMAS = {
    "use_case_catalog": "use-cases.schema.json",
    "state_machines": "state-machines.schema.json",
}


paths_overlap = payloadrules.paths_overlap
forbidden_packet_keys = payloadrules.forbidden_packet_keys
command_allowed = payloadrules.command_allowed
lane_conflicts = payloadrules.lane_conflicts
packet_id_ok = payloadrules.packet_id_ok
payload_extra_errors = payloadrules.extra_errors
path_is_protected = projectfile.path_is_protected


class Report:
    """Collected check lines. An empty failure list is success.

    An info line is a measured fact. It is not a pass and it is not a failure.
    """

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    @property
    def passed(self) -> list[str]:
        return [text for kind, text in self.lines if kind == "ok"]

    @property
    def facts(self) -> list[str]:
        return [text for kind, text in self.lines if kind == "info"]

    @property
    def failures(self) -> list[str]:
        return [text for kind, text in self.lines if kind == "FAIL"]

    def is_clean(self) -> bool:
        return not self.failures

    def pass_(self, message: str) -> None:
        self.lines.append(("ok", message))

    def info(self, message: str) -> None:
        self.lines.append(("info", message))

    def fail(self, message: str) -> None:
        self.lines.append(("FAIL", message))

    def record(self, errors: list[str], ok_message: str) -> None:
        """Add each error as a failure. Add the pass line when the list is empty."""
        if not errors:
            self.pass_(ok_message)
        for message in errors:
            self.fail(message)

    def __str__(self) -> str:
        order = {"ok": 0, "info": 0, "FAIL": 1}
        rows = sorted(self.lines, key=lambda row: order[row[0]])
        lines = [f"{kind:<4}  {text}" for kind, text in rows]
        lines.append(f"{len(self.passed)} passed, {len(self.failures)} failed")
        return "\n".join(lines) + "\n"


def expand_placeholders(value: Any, project: dict) -> Any:
    """Replace project tokens. Examples stay free of a slug and a language id."""
    repository = project["project"]["repository"]
    base = f"https://github.com/{repository}"
    prefix = project["packet"]["id_prefix"]
    language = project.get("toolchain", {}).get("language", "undecided")

    def one(text: str) -> str:
        text = text.replace("{{repository}}", repository).replace("{{github_base}}", base)
        text = text.replace("{{toolchain_language}}", language)
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
    ci_evidence = payload.get("ci_evidence")
    if isinstance(ci_evidence, dict) and ci_evidence.get("checks") == "{{required_checks}}":
        ci_evidence["checks"] = _checks_from_config(project)
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


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json_dir(root: Path, directory: Path, report: Report) -> list[tuple[Path, Any]]:
    """Load each JSON file in one directory. Report a file that is not JSON."""
    if not directory.is_dir():
        return []
    found: list[tuple[Path, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            found.append((path, _load_json(path)))
        except json.JSONDecodeError as exc:
            report.fail(f"{_rel(root, path)}: invalid JSON: {exc}")
    return found


def _check_config(
    project: dict, schemas: schema_validate.SchemaSet, report: Report
) -> bool:
    """Apply the project schema. Then apply the rules a schema cannot state."""
    if PROJECT_SCHEMA not in schemas.documents:
        report.fail(f"missing {SCHEMAS_DIR}/{PROJECT_SCHEMA}")
        return False
    _ok, errors = schemas.validate_document(PROJECT_SCHEMA, project)
    if not errors:
        errors = projectfile.semantic_errors(project) + _version_errors(project, schemas)
    report.record(
        [f"{CONFIG_PATH}: {item}" for item in errors],
        "project file matches project.schema.json",
    )
    if errors:
        return False
    if projectfile.is_template(project):
        report.pass_("project identity is the template placeholder")
    else:
        report.pass_("project identity is set")
    return True


def _version_errors(project: dict, schemas: schema_validate.SchemaSet) -> list[str]:
    """The project file and the common schema must name one schema version."""
    try:
        target, _file = schemas.resolve(
            "common.schema.json#/$defs/provenance/properties/schema_version", PROJECT_SCHEMA
        )
    except KeyError:
        return ["common.schema.json does not define provenance.schema_version"]
    expected = target.get("const") if isinstance(target, dict) else None
    if project["schema_version"] != expected:
        return [f"schema_version {project['schema_version']} is not the schema constant {expected}"]
    return []


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


def load_context(root: Path) -> tuple[schema_validate.SchemaSet, dict]:
    """Load the schemas and the project file. Raise ValueError when one fails."""
    report = Report()
    schemas = _load_schemas(root, report)
    project = _load_project(root, schemas, report) if schemas is not None else None
    if schemas is None or project is None:
        raise ValueError(str(report))
    return schemas, project


def payload_errors(
    schemas: schema_validate.SchemaSet, payload: dict, project: dict, root: Path | None
) -> list[str]:
    """Return the schema errors and the rule errors for one payload."""
    gate = payload.get("gate")
    schema_name = GATE_FILES.get(gate) if isinstance(gate, str) else None
    if schema_name is None or schema_name not in schemas.documents:
        return ["missing or unknown gate"]
    _ok, errors = schemas.validate_document(schema_name, payload)
    return list(errors) + payload_extra_errors(payload, project, root)


def check_payload_files(
    root: Path, names: list[str], stdin_text: str | None = None
) -> Report:
    """Check handoff payloads that are in files. The name - reads standard input."""
    report = Report()
    try:
        schemas, project = load_context(root)
    except ValueError:
        _context_project(root, report)
        return report
    checked: list[dict] = []
    for name in names:
        for label, payload in _read_payload_file(name, stdin_text, report):
            packet = handoff.load_packet(root, payload.get("packet_id"))
            errors = payload_errors(schemas, payload, project, root)
            errors.extend(handoff.packet_errors(payload, packet))
            note = "" if packet is not None else ". No packet file exists to compare."
            report.record(
                [f"{label}: {item}" for item in errors],
                f"{label} is a correct {payload.get('gate')} payload "
                f"for {payload.get('packet_id')}{note}",
            )
            checked.append(payload)
    if len(checked) > 1:
        report.record(handoff.chain_errors(checked), "the payloads of each packet agree")
    return report


def check_pull_request(
    root: Path, base_ref: str | None = None, branch: str | None = None, env: Any = None
) -> Report:
    """Check the commits of one pull request. Print the facts that a verdict records."""
    report = Report()
    project = _context_project(root, report)
    if project is not None:
        found = evidence.pull_request(root, project, base_ref, branch, env)
        _add_findings(report, found, "the pull request follows the base, scope, and plan rules")
    return report


def check_reports(root: Path) -> Report:
    """Check the test report and the coverage report that CI wrote."""
    report = Report()
    project = _context_project(root, report)
    if project is not None:
        found = evidence.reports(root, project)
        _add_findings(
            report, found, "the reports show no failed test, no ignored test, and the coverage floor"
        )
    return report


def _context_project(root: Path, report: Report) -> dict | None:
    try:
        _schemas, project = load_context(root)
    except ValueError:
        report.fail(
            "the schemas or the project file are not correct. "
            "Run the gate checker with no option."
        )
        return None
    return project


def _add_findings(report: Report, found: evidence.Findings, ok_message: str) -> None:
    for line in found.facts:
        report.info(line)
    report.record(found.errors, ok_message)


def _read_payload_file(
    name: str, stdin_text: str | None, report: Report
) -> list[tuple[str, dict]]:
    try:
        if name == "-":
            text = sys.stdin.read() if stdin_text is None else stdin_text
        else:
            text = Path(name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        report.fail(f"{name}: cannot read the file: {exc}")
        return []
    payloads, errors = handoff.read_payloads(text)
    for item in errors:
        report.fail(f"{name}: {item}")
    if len(payloads) == 1:
        return [(name, payloads[0])]
    return [(f"{name} block {index}", payload) for index, payload in enumerate(payloads, start=1)]


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
    errors = payload_errors(schemas, expanded, project, root)
    if errors == ["missing or unknown gate"]:
        if must_reject:
            report.fail(f"{name}: invalid examples must still name a known gate")
        else:
            report.fail(f"{name}: missing or unknown gate")
        return
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
    ordered = _ancestors(packets)
    conflicts = 0
    for index, (path_a, left) in enumerate(packets):
        for path_b, right in packets[index + 1 :]:
            id_a = left.get("packet_id")
            id_b = right.get("packet_id")
            if not isinstance(id_a, str) or not isinstance(id_b, str):
                continue
            if id_b in ordered.get(id_a, set()) or id_a in ordered.get(id_b, set()):
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


def _ancestors(packets: list[tuple[Path, dict]]) -> dict[str, set[str]]:
    """Map each packet id to every packet it depends on, direct or not."""
    graph = {
        payload.get("packet_id"): _depends(payload)
        for _, payload in packets
        if isinstance(payload.get("packet_id"), str)
    }
    closure: dict[str, set[str]] = {}
    for start in graph:
        seen: set[str] = set()
        stack = list(graph[start])
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(graph.get(node, []))
        closure[start] = seen
    return closure


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


def run(root: Path) -> Report:
    """Run every check against the repository at root."""
    report = Report()
    schemas = _load_schemas(root, report)
    if schemas is None:
        return report
    project = _load_project(root, schemas, report)
    if project is None:
        return report
    _check_examples(schemas, root, project, report)
    _check_catalog(schemas, root, project["architecture"], report)
    _check_packets(schemas, root, project, report)
    _check_tree(root, project, report)
    return report


def run_architecture(root: Path) -> Report:
    """Run the architecture checks only: catalog, packets, and import direction."""
    report = Report()
    schemas = _load_schemas(root, Report())
    if schemas is None:
        report.fail(f"no schemas found in {SCHEMAS_DIR}")
        return report
    project = _load_project(root, schemas, report)
    if project is None:
        return report
    _check_catalog(schemas, root, project["architecture"], report)
    _check_packets(schemas, root, project, report)
    _check_imports(root, repofiles.list_files(root), project, report)
    return report


def _check_catalog(
    schemas: schema_validate.SchemaSet, root: Path, arch: dict, report: Report
) -> None:
    """Check the use cases and the state machines of one architecture block."""
    errors: list[str] = []
    for key, schema_name in CATALOG_SCHEMAS.items():
        errors.extend(_catalog_file_errors(schemas, root, arch.get(key), schema_name))
    if not errors:
        _use_cases, _machines, errors = architecture.load_catalog(root, arch)
    report.record(
        errors,
        f"{arch.get('use_case_catalog')} and {arch.get('state_machines')} are correct catalogs",
    )


def _catalog_file_errors(
    schemas: schema_validate.SchemaSet, root: Path, relative: Any, schema_name: str
) -> list[str]:
    if not isinstance(relative, str) or not (root / relative).is_file():
        return [f"missing architecture catalog {relative}"]
    if schema_name not in schemas.documents:
        return [f"missing {SCHEMAS_DIR}/{schema_name}"]
    try:
        document = _load_json(root / relative)
    except json.JSONDecodeError as exc:
        return [f"{relative}: invalid JSON: {exc}"]
    _ok, found = schemas.validate_document(schema_name, document)
    return [f"{relative}: {item}" for item in found]


def _check_imports(root: Path, files: list[str], project: dict, report: Report) -> None:
    errors, scanned = architecture.import_errors(root, files, project)
    report.record(
        errors,
        f"layer imports follow architecture.import_rules ({scanned} source files)",
    )


def _load_project(
    root: Path, schemas: schema_validate.SchemaSet, report: Report
) -> dict | None:
    config_path = root / CONFIG_PATH
    if not config_path.is_file():
        report.fail(f"missing {CONFIG_PATH}")
        return None
    try:
        project = _load_json(config_path)
    except json.JSONDecodeError as exc:
        report.fail(f"{CONFIG_PATH}: invalid JSON: {exc}")
        return None
    if not _check_config(project, schemas, report):
        return None
    return project


def example_project(root: Path, project: dict, report: Report) -> dict | None:
    """Give the examples their own architecture catalog.

    A project replaces its use cases and its state machines when it adopts
    the template. The examples must stay valid after that edit.
    """
    path = root / EXAMPLE_ARCHITECTURE
    if not path.is_file():
        report.fail(f"missing {EXAMPLE_ARCHITECTURE}")
        return None
    try:
        block = _load_json(path)
    except json.JSONDecodeError as exc:
        report.fail(f"{EXAMPLE_ARCHITECTURE}: invalid JSON: {exc}")
        return None
    example = dict(project)
    example["architecture"] = block
    return example


def _check_examples(
    schemas: schema_validate.SchemaSet, root: Path, project: dict, report: Report
) -> None:
    example = example_project(root, project, report)
    if example is None:
        return
    shape = schemas.validate_ref(ARCHITECTURE_REF, example["architecture"])
    if shape:
        report.record([f"{EXAMPLE_ARCHITECTURE}: {item}" for item in shape], "")
        return
    _check_catalog(schemas, root, example["architecture"], report)
    for relative in (VALID_DIR, INVALID_DIR):
        rows = _load_json_dir(root, root / relative, report)
        if not rows:
            report.fail(f"no payloads found in {relative}")
        for path, payload in rows:
            _check_payload(
                schemas,
                root,
                path,
                payload,
                example,
                report,
                must_reject=relative == INVALID_DIR,
            )
    _check_example_index(root, report)


def _check_example_index(root: Path, report: Report) -> None:
    """Each invalid example must have a row in the examples page."""
    index = root / EXAMPLE_INDEX
    text = index.read_text(encoding="utf-8") if index.is_file() else ""
    missing = [
        f"{_rel(root, path)} has no row in {EXAMPLE_INDEX}"
        for path in sorted((root / INVALID_DIR).glob("*.json"))
        if f"`{path.stem}`" not in text
    ]
    report.record(missing, "each invalid example has a row in the examples page")


def _check_packets(
    schemas: schema_validate.SchemaSet, root: Path, project: dict, report: Report
) -> None:
    rows = _load_json_dir(root, root / PACKETS_DIR, report)
    if not rows:
        report.fail(f"no payloads found in {PACKETS_DIR}")
    for path, payload in rows:
        _check_payload(schemas, root, path, payload, project, report, must_reject=False)
    packets = [
        (path, expand_placeholders(payload, project))
        for path, payload in rows
        if isinstance(payload, dict)
    ]
    if packets:
        _packet_graph(root, packets, report)
    report.record(
        architecture.coverage_errors(packets, project, root),
        "architecture catalog is covered by packets",
    )


def _check_tree(root: Path, project: dict, report: Report) -> None:
    files = repofiles.list_files(root)
    report.record(
        treecheck.top_level_errors(files, project),
        "top-level paths match the project config",
    )
    report.record(
        treecheck.codeowners_errors(root, files, project),
        "CODEOWNERS names project.owner_login on each rule",
    )
    workflow = treecheck.workflow_errors(root, files, project)
    if workflow is not None:
        report.record(workflow, "workflows match the project CI config and the hardening rules")
    ruleset = treecheck.ruleset_errors(root, files, project)
    if ruleset is not None:
        report.record(ruleset, f"{treecheck.RULESET_PATH} matches the branch rules of the contract")
    form = treecheck.issue_form_errors(root, files, project)
    if form is not None:
        report.record(form, "the work packet form lists the layers of the project file")
    _check_spdx(root, files, project, report)
    report.record(
        treecheck.neutrality_errors(root, files, projectfile.is_template(project)),
        "template paths do not name a product stack",
    )
    _check_imports(root, files, project, report)
    constructs = project["policy"]["forbidden_constructs"]
    report.record(
        treecheck.construct_errors(root, files, project),
        f"the tree has no forbidden construct ({len(constructs)} in the project file)",
    )
    report.record(
        treecheck.secret_errors(root, files),
        "the tree has no environment file and no text with the shape of a secret",
    )


def _check_spdx(root: Path, files: list[str], project: dict, report: Report) -> None:
    errors, checked = treecheck.spdx_errors(root, files, project)
    report.record(errors, f"checked SPDX headers on {checked} files")


def default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gatecheck.py",
        description="Check packets, gate payloads, and the repository shape.",
    )
    parser.add_argument("root", nargs="?", help="repository root. The default is this repository.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--spdx-only", action="store_true", help="check the SPDX headers only")
    mode.add_argument(
        "--architecture",
        action="store_true",
        help="check the catalog, the packets, and the import direction only",
    )
    mode.add_argument(
        "--payload",
        nargs="+",
        metavar="FILE",
        help="check gate payloads in files. A file holds JSON, or text with "
        "json gate-payload blocks. The name - reads standard input.",
    )
    mode.add_argument(
        "--pr",
        action="store_true",
        help="check the commits between the base branch and HEAD: head SHA, "
        "fresh base, packet scope, protected paths, and planned tests",
    )
    mode.add_argument(
        "--evidence",
        action="store_true",
        help="check the test report and the coverage report in ci.evidence",
    )
    parser.add_argument(
        "--base",
        metavar="REF",
        help="base ref for --pr. The default is origin/$GITHUB_BASE_REF, then origin/main.",
    )
    parser.add_argument(
        "--branch",
        metavar="NAME",
        help="branch name for --pr. The default is $GITHUB_HEAD_REF, then the current branch.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root) if args.root else default_root()
    if args.spdx_only:
        report = _spdx_only(root)
    elif args.architecture:
        report = run_architecture(root)
    elif args.payload:
        report = check_payload_files(root, args.payload)
    elif args.pr:
        report = check_pull_request(root, args.base, args.branch)
    elif args.evidence:
        report = check_reports(root)
    else:
        report = run(root)
    sys.stdout.write(str(report))
    return 0 if report.is_clean() else 1


def _spdx_only(root: Path) -> Report:
    report = Report()
    schemas = _load_schemas(root, Report())
    if schemas is None:
        report.fail(f"no schemas found in {SCHEMAS_DIR}")
        return report
    project = _load_project(root, schemas, report)
    if project is None:
        return report
    _check_spdx(root, repofiles.list_files(root), project, report)
    return report


if __name__ == "__main__":
    sys.exit(main())
