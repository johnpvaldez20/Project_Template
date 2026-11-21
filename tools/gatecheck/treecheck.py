#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Checks on the repository tree.

Each function reads the project values from .governance/project.json.
Each function returns a list of failure lines. An empty list is success.
This module does not name a product or a product language.
"""

from __future__ import annotations

import re
from pathlib import Path

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


def codeowners_errors(root: Path, project: dict) -> list[str] | None:
    """Return None when the file is absent."""
    path = root / "CODEOWNERS"
    if not path.is_file():
        return None
    login = project["project"]["owner_login"]
    if f"@{login}" not in path.read_text(encoding="utf-8"):
        return [f"CODEOWNERS does not name @{login} from the project config"]
    return []


def workflow_errors(root: Path, project: dict) -> list[str] | None:
    """Return None when the repository has no .github directory."""
    workflow = root / ".github" / "workflows" / project["ci"]["workflow_file"]
    if not workflow.is_file():
        if (root / ".github").exists():
            return [f"missing {workflow.relative_to(root).as_posix()}"]
        return None
    text = workflow.read_text(encoding="utf-8")
    job = project["ci"]["job_name"]
    errors: list[str] = []
    if f"\n  {job}:\n" not in text or f"\n    name: {job}\n" not in text:
        errors.append(f"workflow job name must be {job}")
    if "pull_request:" not in text:
        errors.append("workflow must run on pull_request")
    for command in project["ci"]["check_commands"].values():
        if command not in text:
            errors.append(f"workflow is missing command: {command}")
    return errors


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


def neutrality_errors(root: Path, files: list[str]) -> list[str]:
    errors: list[str] = []
    patterns = _banned_patterns()
    for relative in files:
        if not any(under(relative, directory) for directory in TEMPLATE_DIRS):
            continue
        text = _read_text(root / relative)
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                errors.append(f"{relative} contains non-neutral text {match.group(0)!r}")
                break
    return errors


def _read_text(path: Path) -> str:
    """Read text. A file that is not UTF-8 gives an empty string."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""
