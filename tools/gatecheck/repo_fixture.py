#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Test support. Copy the repository under test into a temporary directory.

A test changes one fact in the copy. Then the test runs the gate on the copy.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

import gatecheck
import repofiles

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def copy_repo(destination: Path) -> Path:
    """Copy each repository file into destination. Return destination."""
    for relative in repofiles.list_files(SOURCE_ROOT):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE_ROOT / relative, target)
    return destination


def read_json(root: Path, relative: str) -> Any:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def write_json(root: Path, relative: str, value: Any) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def edit_json(root: Path, relative: str, change: Callable[[Any], None]) -> Any:
    """Load one JSON file, apply the change, and write the file again."""
    value = read_json(root, relative)
    change(value)
    write_json(root, relative, value)
    return value


def write_text(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RepoCopyCase(unittest.TestCase):
    """A test case that owns one copy of the repository."""

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = copy_repo(Path(holder.name))

    def failures(self) -> list[str]:
        return gatecheck.run(self.root).failures

    def assert_clean(self) -> None:
        report = gatecheck.run(self.root)
        self.assertTrue(report.is_clean(), str(report))

    def assert_fails_with(self, fragment: str) -> None:
        failures = self.failures()
        self.assertTrue(
            any(fragment in line for line in failures),
            f"no failure contains {fragment!r}: {failures}",
        )


class AdoptedRepoCase(RepoCopyCase):
    """A copy of the repository after a project set its identity."""

    CONFIG = ".governance/project.json"

    def setUp(self) -> None:
        super().setUp()
        self.edit(
            lambda project: project["project"].update(
                name="Widget",
                full_name="Widget service",
                repository="example/widget",
                owner_login="example-owner",
            )
        )
        owners = (self.root / "CODEOWNERS").read_text(encoding="utf-8")
        write_text(self.root, "CODEOWNERS", owners.replace("@replace-me", "@example-owner"))

    def edit(self, change: Callable[[Any], None]) -> None:
        edit_json(self.root, self.CONFIG, change)


class ExampleCase(unittest.TestCase):
    """A test case that changes one fact in a valid example."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas, cls.project = gatecheck.load_context(SOURCE_ROOT)
        cls.context = gatecheck.example_project(SOURCE_ROOT, cls.project, gatecheck.Report())

    def example(self, name: str) -> dict:
        """Load one valid example with the project tokens filled in."""
        payload = read_json(SOURCE_ROOT, f"docs/governance/examples/valid/{name}.json")
        expanded = gatecheck.expand_placeholders(payload, self.context)
        return gatecheck.materialize_payload(expanded, self.context)

    def packet(self) -> dict:
        return read_json(SOURCE_ROOT, "docs/design/packets/PKT-0001.json")

    def errors(self, payload: dict, live: bool = False) -> list[str]:
        """Return the checker errors. A live payload uses the project catalog."""
        project = self.project if live else self.context
        return gatecheck.payload_errors(self.schemas, payload, project, SOURCE_ROOT)

    def assert_rejected(self, payload: dict, fragment: str, live: bool = False) -> None:
        errors = self.errors(payload, live)
        self.assertTrue(
            any(fragment in line for line in errors),
            f"no error contains {fragment!r}: {errors}",
        )
