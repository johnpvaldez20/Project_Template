#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Checks on the repository tree.

Each function reads the project values from .governance/project.json.
Each function returns a list of failure lines. An empty list is success.
This module does not name a product or a product language.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

TEMPLATE_DIRS = ("docs/governance", ".github", "tools/gatecheck")
WORKFLOWS_DIR = ".github/workflows/"
RULESET_PATH = ".github/rulesets/main.json"
ISSUE_FORM = ".github/ISSUE_TEMPLATE/work-packet.yml"
REQUIRED_RULES = (
    "deletion",
    "non_fast_forward",
    "required_linear_history",
    "pull_request",
    "required_status_checks",
)
ENV_EXAMPLE_SUFFIXES = (".example", ".sample", ".template")
REVIEW_FLAGS = (
    "dismiss_stale_reviews_on_push",
    "require_code_owner_review",
    "require_last_push_approval",
)

_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?([^'\"\s]+)['\"]?\s*$", re.MULTILINE)


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


def under(path: str, prefix: str) -> bool:
    """True when path is the prefix file, or sits in the prefix directory."""
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix or path.startswith(prefix + "/")


def top_level_errors(files: list[str], project: dict) -> list[str]:
    allowed = set(project["scope"]["allowed_top_level"])
    names = sorted({path.split("/", 1)[0] for path in files})
    return [
        f"top-level path {name} is not in the project config"
        for name in names
        if name not in allowed
    ]


CODEOWNERS_PATHS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")


def codeowners_errors(root: Path, files: list[str], project: dict) -> list[str]:
    """The root file must exist. Each rule must name the owner login."""
    present = [path for path in CODEOWNERS_PATHS if path in files]
    if "CODEOWNERS" not in present:
        return ["missing CODEOWNERS at the repository root"]
    errors = [
        f"{path} must not exist. Keep one CODEOWNERS file at the repository root."
        for path in present
        if path != "CODEOWNERS"
    ]
    login = "@" + project["project"]["owner_login"].lower()
    rules = _codeowners_rules(_read_text(root / "CODEOWNERS"))
    if not any(pattern == "*" for pattern, _owners in rules):
        errors.append("CODEOWNERS needs a rule for *")
    for pattern, owners in rules:
        if login not in owners:
            errors.append(f"CODEOWNERS rule {pattern} does not name {login}")
    return errors


def _codeowners_rules(text: str) -> list[tuple[str, list[str]]]:
    rules: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        parts = line.split("#", 1)[0].split()
        if parts:
            rules.append((parts[0], [owner.lower() for owner in parts[1:]]))
    return rules


def workflow_errors(root: Path, files: list[str], project: dict) -> list[str] | None:
    """Check the CI workflow and the hardening of each workflow file.

    Return None when the repository has no .github directory.
    """
    if not any(path.startswith(".github/") for path in files):
        return None
    name = WORKFLOWS_DIR + project["ci"]["workflow_file"]
    if name not in files:
        return [f"missing {name}"]
    errors = _ci_workflow_errors(_yaml_code(_read_text(root / name)), project)
    for path in files:
        if path.startswith(WORKFLOWS_DIR) and path.endswith((".yml", ".yaml")):
            code = _yaml_code(_read_text(root / path))
            errors.extend(f"{path}: {item}" for item in _hardening_errors(code))
    return errors


def _yaml_code(text: str) -> str:
    """Return the workflow text without comments."""
    lines = [
        re.sub(r"\s+#.*$", "", line)
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
    ]
    return "\n".join(lines) + "\n"


def _ci_workflow_errors(code: str, project: dict) -> list[str]:
    """The CI workflow gives the evidence for one exact commit."""
    job = project["ci"]["job_name"]
    errors: list[str] = []
    if f"\n  {job}:\n" not in code or f"\n    name: {job}\n" not in code:
        errors.append(f"workflow job name must be {job}")
    if "pull_request:" not in code:
        errors.append("workflow must run on pull_request")
    for command in project["ci"]["check_commands"].values():
        if command not in code:
            errors.append(f"workflow is missing command: {command}")
    if re.search(r"cancel-in-progress:\s*true", code):
        errors.append("workflow must not cancel a run. Each run is evidence for one commit.")
    if "github.event.pull_request.head.sha" not in code:
        errors.append("workflow must check out github.event.pull_request.head.sha")
    if not re.search(r"fetch-depth:\s*0\b", code):
        errors.append("workflow checkout needs fetch-depth: 0 for the pull request check")
    return errors


def _hardening_errors(code: str) -> list[str]:
    errors = [
        f"action {target} is not pinned to a full commit SHA"
        for target in _USES.findall(code)
        if not _is_pinned(target)
    ]
    if not re.search(r"^permissions:", code, re.MULTILINE):
        errors.append("the workflow needs a top-level permissions block")
    if re.search(r"^permissions:\s*write-all", code, re.MULTILINE):
        errors.append("permissions: write-all is not least privilege")
    if re.search(r"\bpull_request_target\b", code):
        errors.append("pull_request_target gives a write token to untrusted code. Use pull_request.")
    checkouts = len(re.findall(r"uses:\s*['\"]?actions/checkout@", code))
    if checkouts > len(re.findall(r"persist-credentials:\s*false", code)):
        errors.append("each actions/checkout step needs persist-credentials: false")
    return errors


def _is_pinned(target: str) -> bool:
    if target.startswith("./"):
        return True
    if target.startswith("docker://"):
        return re.search(r"@sha256:[0-9a-f]{64}$", target) is not None
    return re.search(r"@[0-9a-f]{40}$", target) is not None


def ruleset_errors(root: Path, files: list[str], project: dict) -> list[str] | None:
    """Check the ruleset file that the owner imports on the host.

    Return None when the repository has no .github directory.
    """
    if not any(path.startswith(".github/") for path in files):
        return None
    if RULESET_PATH not in files:
        return [f"missing {RULESET_PATH}"]
    try:
        ruleset = json.loads(_read_text(root / RULESET_PATH))
    except json.JSONDecodeError as exc:
        return [f"{RULESET_PATH}: invalid JSON: {exc}"]
    if not isinstance(ruleset, dict):
        return [f"{RULESET_PATH} must be an object"]
    rules = {
        rule.get("type"): _dict(rule.get("parameters"))
        for rule in ruleset.get("rules") or []
        if isinstance(rule, dict)
    }
    errors = _ruleset_shape_errors(ruleset, rules)
    errors.extend(_review_rule_errors(rules.get("pull_request", {})))
    errors.extend(_status_rule_errors(rules.get("required_status_checks", {}), project))
    return [f"{RULESET_PATH}: {item}" for item in errors]


def _ruleset_shape_errors(ruleset: dict, rules: dict) -> list[str]:
    errors: list[str] = []
    if ruleset.get("target") != "branch":
        errors.append("target must be branch")
    if ruleset.get("enforcement") != "active":
        errors.append("enforcement must be active")
    include = _dict(_dict(ruleset.get("conditions")).get("ref_name")).get("include")
    if not isinstance(include, list) or "~DEFAULT_BRANCH" not in include:
        errors.append("conditions.ref_name.include must contain ~DEFAULT_BRANCH")
    for actor in ruleset.get("bypass_actors") or []:
        if _dict(actor).get("bypass_mode") != "pull_request":
            errors.append("a bypass actor must have bypass_mode pull_request")
    for name in REQUIRED_RULES:
        if name not in rules:
            errors.append(f"rule {name} is missing")
    return errors


def _review_rule_errors(parameters: dict) -> list[str]:
    errors = [
        f"pull_request.{key} must be true"
        for key in REVIEW_FLAGS
        if parameters.get(key) is not True
    ]
    count = parameters.get("required_approving_review_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        errors.append("pull_request.required_approving_review_count must be 1 or more")
    if parameters.get("allowed_merge_methods") != ["squash"]:
        errors.append("pull_request.allowed_merge_methods must be squash only")
    return errors


def _status_rule_errors(parameters: dict, project: dict) -> list[str]:
    errors: list[str] = []
    if parameters.get("strict_required_status_checks_policy") is not True:
        errors.append("required_status_checks must require an up-to-date branch")
    job = project["ci"]["job_name"]
    checks = [_dict(item) for item in parameters.get("required_status_checks") or []]
    named = [item for item in checks if item.get("context") == job]
    if not named:
        errors.append(f"required_status_checks must contain the context {job}")
    elif not isinstance(named[0].get("integration_id"), int):
        errors.append(f"the context {job} needs an integration_id. Only CI can give that status.")
    return errors


def issue_form_errors(root: Path, files: list[str], project: dict) -> list[str] | None:
    """The layer list of the work packet form must equal the layers of the project.

    Return None when the repository has no work packet form.
    """
    if ISSUE_FORM not in files:
        return None
    code = _yaml_code(_read_text(root / ISSUE_FORM))
    block = re.search(r"\n    id: layer\n(.*?)(?=\n  - type:|\Z)", code, re.DOTALL)
    if block is None:
        return [f"{ISSUE_FORM} has no field with the id layer"]
    options = set(re.findall(r"^\s+- ([a-z][a-z0-9-]*)\s*$", block.group(1), re.MULTILINE))
    layers = set(project["architecture"]["layers"])
    if options != layers:
        return [
            f"{ISSUE_FORM}: the layer options {sorted(options)} "
            f"are not the layers of the project file {sorted(layers)}"
        ]
    return []


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def spdx_errors(root: Path, files: list[str], project: dict) -> tuple[list[str], int]:
    """Return the failure lines and the count of files that need a header."""
    extensions = {item.lower() for item in project["spdx"]["extensions"]}
    basenames = set(project["spdx"].get("basenames", []))
    exempt = set(project["spdx"].get("exempt_basenames", []))
    copyright_line = project["spdx"]["copyright_line"]
    license_line = f"SPDX-License-Identifier: {project['spdx']['license_id']}"
    errors: list[str] = []
    checked = 0
    for relative in files:
        path = Path(relative)
        if path.name in exempt:
            continue
        if path.name not in basenames and path.suffix.lower() not in extensions:
            continue
        checked += 1
        head = "\n".join(_read_text(root / relative).splitlines()[:12])
        if copyright_line not in head:
            errors.append(f"{relative}: missing {copyright_line}")
        if license_line not in head:
            errors.append(f"{relative}: missing {license_line}")
    if checked == 0:
        errors.append("no files were checked for SPDX headers")
    return errors, checked


def neutrality_errors(root: Path, files: list[str], template: bool) -> list[str]:
    """Template paths must not name a product stack.

    A project names its build tool in its workflows. The workflows are
    checked only while the project identity is the template placeholder.
    """
    errors: list[str] = []
    patterns = _banned_patterns()
    for relative in files:
        if not any(under(relative, directory) for directory in TEMPLATE_DIRS):
            continue
        if relative.startswith(WORKFLOWS_DIR) and not template:
            continue
        text = _read_text(root / relative)
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                errors.append(f"{relative} contains non-neutral text {match.group(0)!r}")
                break
    return errors


def construct_errors(root: Path, files: list[str], project: dict) -> list[str]:
    """Find each forbidden construct of the project file in the tree."""
    errors: list[str] = []
    for construct in project["policy"]["forbidden_constructs"]:
        pattern = re.compile(construct["pattern"])
        suffixes = {item.lower() for item in construct.get("extensions", [])}
        for relative in files:
            if not any(under(relative, prefix) for prefix in construct["paths"]):
                continue
            if suffixes and PurePosixPath(relative).suffix.lower() not in suffixes:
                continue
            for number, line in enumerate(_read_text(root / relative).splitlines(), start=1):
                if pattern.search(line):
                    errors.append(
                        f"{relative}:{number}: forbidden construct {construct['id']}. "
                        f"{construct['reason']}"
                    )
    return errors


def _secret_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Build the patterns so that this file does not contain a match."""
    dashes = "-" * 5
    return (
        ("private key", re.compile(dashes + "BEGIN [A-Z ]*PRIVATE KEY" + dashes)),
        ("cloud access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
        ("host access token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
        ("host fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
        ("chat service token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    )


def secret_errors(root: Path, files: list[str]) -> list[str]:
    """Find an environment file and text that has the shape of a secret."""
    errors: list[str] = []
    patterns = _secret_patterns()
    for relative in files:
        name = PurePosixPath(relative).name
        if (name == ".env" or name.startswith(".env.")) and not name.endswith(ENV_EXAMPLE_SUFFIXES):
            errors.append(f"{relative}: an environment file must not be in the repository")
            continue
        text = _read_text(root / relative)
        for label, pattern in patterns:
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{relative}:{line}: the text has the shape of a secret ({label})")
    return errors


def _read_text(path: Path) -> str:
    """Read text. A file that is not UTF-8 gives an empty string."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""
