#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Test support. Build a template repository in a temporary directory.

The copy does not depend on the project that adopted the template.
It holds the schemas and the examples of this repository.
It holds a snapshot of the files that a project edits when it adopts.
A test changes one fact in the copy. Then the test runs the gate on the copy.

The snapshot is testdata/template_repo.json. In the template repository,
a test fails when the snapshot differs from the files. Write it again:

    python3 tools/gatecheck/repo_fixture.py
"""

from __future__ import annotations

import functools
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

import gatecheck
import projectfile
import repofiles

SOURCE_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = Path(__file__).resolve().parent / "testdata" / "template_repo.json"
CONFIG = ".governance/project.json"
SNAPSHOT_FILES = (
    CONFIG,
    "CODEOWNERS",
    ".gitignore",
    ".github/workflows/ci.yml",
    ".github/rulesets/main.json",
    "docs/design/fixtures/use-cases.json",
    "docs/design/fixtures/state-machines.json",
    "docs/design/packets/PKT-0001.json",
)
LIVE_JSON_DIRS = ("docs/governance/schemas/", "docs/governance/examples/")
LAYERS = ("presentation", "application", "domain", "infrastructure")


@functools.lru_cache(maxsize=1)
def snapshot() -> dict[str, str]:
    """Return the template files of the snapshot. The key is the path."""
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))["files"]


def template_project() -> dict:
    """Return the project file of the template."""
    return json.loads(snapshot()[CONFIG])


def hash_header() -> str:
    """Return the SPDX header of the template for a file with # comments."""
    spdx = template_project()["spdx"]
    return f"# {spdx['copyright_line']}\n# SPDX-License-Identifier: {spdx['license_id']}\n\n"


def markdown_header() -> str:
    """Return the SPDX header of the template for a Markdown file."""
    spdx = template_project()["spdx"]
    return f"<!--\n{spdx['copyright_line']}\nSPDX-License-Identifier: {spdx['license_id']}\n-->\n\n"


def copy_repo(destination: Path) -> Path:
    """Build the template repository in destination. Return destination."""
    for relative in repofiles.list_files(SOURCE_ROOT):
        if relative.startswith(LIVE_JSON_DIRS) and relative.endswith(".json"):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE_ROOT / relative, target)
    for relative, text in snapshot().items():
        write_text(destination, relative, text)
    for relative, text in _page_files(destination).items():
        write_text(destination, relative, text)
    return destination


def _page_files(destination: Path) -> dict[str, str]:
    """Short pages that the gate needs. The gate does not read their text."""
    header = markdown_header()
    invalid = sorted((destination / "docs/governance/examples/invalid").glob("*.json"))
    index = "".join(f"- `{path.stem}`\n" for path in invalid)
    pages = {
        "README.md": header + "# Template repository\n",
        "docs/design/ARCHITECTURE.md": header + "# Architecture\n",
        "docs/governance/README.md": header + "# Governance package\n",
        "docs/governance/examples/README.md": header + "# Examples\n\n" + index,
    }
    for layer in LAYERS:
        pages[f"src/{layer}/README.md"] = header + f"# {layer}\n"
    return pages


def read_json(root: Path, relative: str) -> Any:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def write_json(root: Path, relative: str, value: Any) -> None:
    write_text(root, relative, json.dumps(value, indent=2) + "\n")


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
    """A test case that owns one template repository."""

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
    """A template repository after a project set its identity."""

    CONFIG = CONFIG

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
        holder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(holder.cleanup)
        cls.root = copy_repo(Path(holder.name))
        cls.schemas, cls.project = gatecheck.load_context(cls.root)
        cls.context = gatecheck.example_project(cls.root, cls.project, gatecheck.Report())

    def example(self, name: str) -> dict:
        """Load one valid example with the project tokens filled in."""
        payload = read_json(self.root, f"docs/governance/examples/valid/{name}.json")
        expanded = gatecheck.expand_placeholders(payload, self.context)
        return gatecheck.materialize_payload(expanded, self.context)

    def packet(self) -> dict:
        return read_json(self.root, "docs/design/packets/PKT-0001.json")

    def errors(self, payload: dict, live: bool = False) -> list[str]:
        """Return the checker errors. A live payload uses the project catalog."""
        project = self.project if live else self.context
        return gatecheck.payload_errors(self.schemas, payload, project, self.root)

    def assert_rejected(self, payload: dict, fragment: str, live: bool = False) -> None:
        errors = self.errors(payload, live)
        self.assertTrue(
            any(fragment in line for line in errors),
            f"no error contains {fragment!r}: {errors}",
        )


def snapshot_differences() -> list[str]:
    """Return the snapshot files that differ from the files of this repository."""
    files = snapshot()
    return [
        relative
        for relative in SNAPSHOT_FILES
        if files.get(relative) != (SOURCE_ROOT / relative).read_text(encoding="utf-8")
    ]


def refresh() -> int:
    """Write the snapshot from the files of the template repository."""
    project = read_json(SOURCE_ROOT, CONFIG)
    if not projectfile.is_template(project):
        sys.stdout.write("This repository is not the template. Keep the snapshot.\n")
        return 1
    files = {
        relative: (SOURCE_ROOT / relative).read_text(encoding="utf-8")
        for relative in SNAPSHOT_FILES
    }
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"files": files}, indent=2, sort_keys=True) + "\n"
    SNAPSHOT.write_text(text, encoding="utf-8")
    snapshot.cache_clear()
    sys.stdout.write(f"wrote {SNAPSHOT.relative_to(SOURCE_ROOT).as_posix()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(refresh())
