#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Measure the facts that a gate verdict records.

The pull request check reads the diff from Git. It gives the head SHA,
the base SHA, the file list, and the scope result for the packet.
The report check reads a test report and a coverage report from CI.
A gatekeeper copies these lines. A gatekeeper does not estimate them.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any, Mapping

import payloadrules
import projectfile
import repofiles

PACKETS_DIR = "docs/design/packets"
DEFAULT_BASE = "origin/main"
NOT_PRODUCT_PREFIXES = ("docs/", ".governance/", ".github/", "tools/gatecheck/")
IGNORED_STATUS = {"skipped", "disabled", "ignored", "notrun"}


class Findings:
    """Evidence lines and failure lines from one check."""

    def __init__(self) -> None:
        self.facts: list[str] = []
        self.errors: list[str] = []

    def fact(self, line: str) -> None:
        self.facts.append(line)

    def error(self, line: str) -> None:
        self.errors.append(line)


class GitError(Exception):
    """Git could not answer."""


def pull_request(
    root: Path,
    project: dict,
    base_ref: str | None = None,
    branch: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Findings:
    """Check the commits between the base and HEAD."""
    env = os.environ if env is None else env
    found = Findings()
    try:
        _measure(found, root, project, base_ref or _default_base(env), branch, env)
    except GitError as exc:
        found.error(str(exc))
    return found


def _measure(
    found: Findings,
    root: Path,
    project: dict,
    base_ref: str,
    branch: str | None,
    env: Mapping[str, str],
) -> None:
    branch = branch or env.get("GITHUB_HEAD_REF") or _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    head = _git(root, "rev-parse", "HEAD")
    base = _resolve(root, base_ref)
    merge_base = _git(root, "merge-base", head, base)
    found.fact(f"head_sha {head}")
    found.fact(f"base_sha {base} ({base_ref})")
    _check_fresh(found, base_ref, base, merge_base)
    changed = _changed_files(root, merge_base, head)
    protected = [path for path in changed if projectfile.path_is_protected(path, project)]
    found.fact(f"commits_in_pr {_git(root, 'rev-list', '--count', f'{merge_base}..{head}')}")
    found.fact(f"files_modified {len(changed)}")
    for path in changed:
        found.fact(f"modified {path}" + (" (protected)" if path in protected else ""))
    found.fact(f"touches_protected_paths {'true' if protected else 'false'}")
    _check_branch(found, root, project, branch, merge_base, changed, protected)


def _default_base(env: Mapping[str, str]) -> str:
    name = env.get("GITHUB_BASE_REF")
    return f"origin/{name}" if name else DEFAULT_BASE


def _resolve(root: Path, ref: str) -> str:
    try:
        return _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except GitError:
        raise GitError(f"base ref {ref} does not exist. Fetch the base branch.") from None


def _check_fresh(found: Findings, base_ref: str, base: str, merge_base: str) -> None:
    fresh = merge_base == base
    found.fact(f"merge_base_is_main_head {'true' if fresh else 'false'}")
    if not fresh:
        found.error(
            f"STALE_BASE: the merge base {merge_base} is not the head of {base_ref}. "
            "Rebase the branch and push it."
        )


def _changed_files(root: Path, merge_base: str, head: str) -> list[str]:
    text = _git(root, "diff", "--name-only", "--no-renames", "-z", merge_base, head, strip=False)
    return sorted(item for item in text.split("\0") if item)


def _check_branch(
    found: Findings,
    root: Path,
    project: dict,
    branch: str,
    merge_base: str,
    changed: list[str],
    protected: list[str],
) -> None:
    packet_id = _packet_id(branch, project)
    if packet_id is None and branch.startswith("pkt/"):
        found.error(
            f"branch {branch} starts with pkt/ but does not name a packet. "
            "Use pkt/<packet id>-<slug> with lower-case letters, digits, and hyphens."
        )
        return
    if packet_id is None:
        found.fact(
            f"branch {branch} is not a packet branch. The packet scope rules do not apply. "
            "The owner must review this pull request."
        )
        return
    packet = _load_packet(found, root, packet_id, merge_base)
    if packet is None:
        return
    _check_scope(found, project, packet_id, packet, changed, protected)
    _check_planned_tests(found, root, packet_id, packet)


def _packet_id(branch: str, project: dict) -> str | None:
    prefix = re.escape(project["packet"]["id_prefix"])
    match = re.fullmatch(rf"pkt/({prefix}-[0-9]{{4,}})-[a-z0-9]+(?:-[a-z0-9]+)*", branch)
    return match.group(1) if match else None


def _load_packet(found: Findings, root: Path, packet_id: str, merge_base: str) -> dict | None:
    """Read the packet from the base commit. A branch cannot widen its own scope."""
    relative = f"{PACKETS_DIR}/{packet_id}.json"
    try:
        text = _git(root, "show", f"{merge_base}:{relative}", strip=False)
        found.fact(f"packet {packet_id} is read from the base commit")
    except GitError:
        path = root / relative
        if not path.is_file():
            found.error(f"no packet file {relative} for this branch")
            return None
        text = path.read_text(encoding="utf-8")
        found.fact(f"packet {packet_id} is new on this branch")
    try:
        packet = payloadrules.json_object(text)
    except ValueError as exc:
        found.error(f"{relative}: {exc}")
        return None
    if packet.get("status") != "READY":
        found.error(f"packet {packet_id} is not READY. Do not code a packet that is not READY.")
        return None
    return packet


def _check_scope(
    found: Findings,
    project: dict,
    packet_id: str,
    packet: dict,
    changed: list[str],
    protected: list[str],
) -> None:
    allowed = payloadrules.allowed_files(packet)
    outside = [
        path
        for path in changed
        if not any(payloadrules.paths_overlap(entry, path) for entry in allowed)
    ]
    for path in outside:
        found.error(f"SCOPE_VIOLATION: {path} is not in the allowed_files of {packet_id}")
    if packet.get("gatekeeper_packet") is not True:
        for path in protected:
            found.error(f"PROTECTED_PATH: {path} needs a packet with gatekeeper_packet true")
    if packet.get("architecture_change") is not True:
        for path in _architecture_paths(changed, project):
            found.error(
                f"{path} is an architecture path. It needs its own packet "
                "with architecture_change true."
            )
    if not outside:
        found.fact(f"each modified file is in the allowed_files of {packet_id}")


def _architecture_paths(changed: list[str], project: dict) -> list[str]:
    prefixes = project["architecture"]["change_paths"]
    return [path for path in changed if any(_under(path, prefix) for prefix in prefixes)]


def _check_planned_tests(found: Findings, root: Path, packet_id: str, packet: dict) -> None:
    """Each test that the plan names must be in the tree by name."""
    names = sorted(payloadrules.regression_test_names(packet))
    if not names:
        return
    text = "\n".join(_tree_text(root))
    missing = [name for name in names if not _has_word(text, name)]
    for name in missing:
        found.error(
            f"REGRESSION_TEST_MISSING: the plan of {packet_id} names {name}, "
            "but no product file contains that name"
        )
    if not missing:
        found.fact(f"each of the {len(names)} planned regression tests is in the tree")


def _tree_text(root: Path) -> list[str]:
    texts: list[str] = []
    for relative in repofiles.list_files(root):
        if relative.startswith(NOT_PRODUCT_PREFIXES):
            continue
        try:
            texts.append((root / relative).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return texts


def _has_word(text: str, name: str) -> bool:
    last = re.split(r"[.:]", name)[-1]
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(last)}(?![A-Za-z0-9_])", text) is not None


def _under(path: str, prefix: str) -> bool:
    return path.startswith(prefix) if prefix.endswith("/") else path == prefix


def _git(root: Path, *args: str, strip: bool = True) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            env=repofiles.git_env(),
            check=False,
        )
    except OSError as exc:
        raise GitError(f"git is not available: {exc}") from None
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git {args[0]} failed: {detail}")
    text = done.stdout.decode("utf-8", "surrogateescape")
    return text.strip() if strip else text


def reports(root: Path, project: dict) -> Findings:
    """Check the test report and the coverage report that the project file names."""
    found = Findings()
    evidence = project["ci"]["evidence"]
    test_report = evidence["test_report"]
    coverage_report = evidence["coverage_report"]
    if test_report is None and coverage_report is None:
        found.error(
            "ci.evidence names no report. Set test_report and coverage_report in the project file."
        )
        return found
    if test_report is not None:
        _check_test_report(found, root, test_report)
    if coverage_report is not None:
        _check_coverage_report(found, root, coverage_report, project)
    return found


def _check_test_report(found: Findings, root: Path, relative: str) -> None:
    """Count the test cases of a JUnit XML report. No test can be ignored."""
    document = _parse_xml(found, root, relative)
    if document is None:
        return
    cases = list(document.iter("testcase"))
    failed = sum(1 for case in cases if _has_child(case, ("failure", "error")))
    ignored = sum(1 for case in cases if _is_ignored(case))
    found.fact(f"total_tests {len(cases)}")
    found.fact(f"failed_tests {failed}")
    found.fact(f"ignored_tests {ignored}")
    if not cases:
        found.error(f"{relative} records no test")
    if failed:
        found.error(f"{relative} records {failed} failed tests")
    if ignored:
        found.error(
            f"{relative} records {ignored} ignored tests. "
            "A skipped test and an expected failure are ignored tests."
        )


def _has_child(case: ElementTree.Element, names: tuple[str, ...]) -> bool:
    return any(case.find(name) is not None for name in names)


def _is_ignored(case: ElementTree.Element) -> bool:
    if case.find("skipped") is not None:
        return True
    return (case.get("status") or "").lower() in IGNORED_STATUS


def _check_coverage_report(found: Findings, root: Path, relative: str, project: dict) -> None:
    percent = _coverage_percent(found, root, relative)
    if percent is None:
        return
    floor = project["policy"]["coverage_floor_percent"]
    shown = math.floor(percent * 100) / 100
    found.fact(f"line_percentage {shown:.2f} (floor {floor})")
    if percent < floor:
        found.error(f"COVERAGE_BELOW_FLOOR: {shown:.2f} is below the floor {floor}")


def _coverage_percent(found: Findings, root: Path, relative: str) -> float | None:
    """Read Cobertura XML, JaCoCo XML, or LCOV text. Return the line percentage."""
    path = root / relative
    if not path.is_file():
        found.error(f"missing coverage report {relative}")
        return None
    data = path.read_bytes()
    if data.lstrip().startswith(b"<"):
        try:
            counts = _xml_line_counts(ElementTree.fromstring(data))
        except ElementTree.ParseError as exc:
            found.error(f"{relative} is not XML: {exc}")
            return None
    else:
        counts = _lcov_line_counts(data.decode("utf-8", "replace"))
    if counts is None or counts[1] <= 0:
        found.error(f"{relative} is not a Cobertura, JaCoCo, or LCOV report with line counts")
        return None
    return 100.0 * counts[0] / counts[1]


def _xml_line_counts(document: ElementTree.Element) -> tuple[float, float] | None:
    if document.tag == "coverage":
        return _cobertura_counts(document)
    if document.tag == "report":
        for counter in document.findall("counter"):
            if counter.get("type") == "LINE":
                covered = _number(counter.get("covered"))
                missed = _number(counter.get("missed"))
                if covered is not None and missed is not None:
                    return covered, covered + missed
    return None


def _cobertura_counts(document: ElementTree.Element) -> tuple[float, float] | None:
    valid = _number(document.get("lines-valid"))
    covered = _number(document.get("lines-covered"))
    if valid is not None and covered is not None and valid > 0:
        return covered, valid
    rate = _number(document.get("line-rate"))
    if rate is not None:
        return rate * 100.0, 100.0
    return None


def _lcov_line_counts(text: str) -> tuple[float, float] | None:
    found = sum(int(value) for value in re.findall(r"^LF:(\d+)\s*$", text, re.MULTILINE))
    hit = sum(int(value) for value in re.findall(r"^LH:(\d+)\s*$", text, re.MULTILINE))
    if found == 0:
        return None
    return float(hit), float(found)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_xml(found: Findings, root: Path, relative: str) -> ElementTree.Element | None:
    path = root / relative
    if not path.is_file():
        found.error(f"missing report {relative}")
        return None
    try:
        return ElementTree.parse(path).getroot()
    except ElementTree.ParseError as exc:
        found.error(f"{relative} is not XML: {exc}")
        return None
