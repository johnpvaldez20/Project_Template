# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Tests for the language-neutral gate checker.

Run: python3 -m unittest discover -s tools/gatecheck -v
"""

import json
import tempfile
import unittest
from pathlib import Path

import architecture
import gatecheck
import schema_validate


class PathsOverlapTest(unittest.TestCase):
    def test_identical_paths_overlap(self):
        self.assertTrue(gatecheck.paths_overlap("docs/design/a.md", "docs/design/a.md"))

    def test_directory_prefix_overlaps_file_inside_it(self):
        self.assertTrue(gatecheck.paths_overlap("docs/design/", "docs/design/a.md"))
        self.assertTrue(gatecheck.paths_overlap("docs/design/a.md", "docs/design/"))

    def test_sibling_paths_do_not_overlap(self):
        self.assertFalse(gatecheck.paths_overlap("docs/design/", "docs/designer/"))
        self.assertFalse(
            gatecheck.paths_overlap("docs/design/a.md", "docs/design/b.md")
        )

    def test_file_is_not_a_prefix(self):
        self.assertFalse(gatecheck.paths_overlap("docs/design", "docs/design/a.md"))


class PlaceholderTest(unittest.TestCase):
    def test_repository_placeholder_expands(self):
        project = {
            "project": {"repository": "example/widget"},
            "packet": {"id_prefix": "PKT"},
        }
        value = {"url": "https://github.com/{{repository}}/issues/1"}
        got = gatecheck.expand_placeholders(value, project)
        self.assertEqual(got["url"], "https://github.com/example/widget/issues/1")


class ForbiddenKeyTest(unittest.TestCase):
    def test_finds_nested_issue_number_and_base_sha(self):
        payload = {"summary": "ok", "nested": {"base_sha": "abc", "items": [{"issue_number": 1}]}}
        self.assertEqual(
            gatecheck.forbidden_packet_keys(payload),
            ["base_sha", "issue_number"],
        )

    def test_ignores_those_words_inside_strings(self):
        payload = {"summary": "Record issue_number on the pull request, not base_sha."}
        self.assertEqual(gatecheck.forbidden_packet_keys(payload), [])


class ConfigRuleTest(unittest.TestCase):
    def setUp(self):
        self.project = {
            "project": {"repository": "example/widget"},
            "packet": {"id_prefix": "PKT"},
            "verification": {"command_prefixes": ["python3 ", "git "]},
            "lane": {"local_only_requires": ["OWNER_EYES", "PHYSICAL_DEVICE"]},
            "hosts": {
                "local_kinds": ["OWNER_MACHINE"],
                "cloud_kinds": ["CURSOR_CLOUD"],
            },
            "ci": {"required_checks": ["gatecheck", "test", "spdx"], "test_check": "test"},
            "policy": {"max_cyclomatic_complexity": 10, "coverage_floor_percent": 85},
            "scope": {
                "allowed_top_level": ["docs", "tools", "README.md"],
                "protected_path_patterns": ["^docs/governance/", "^\\.github/"],
            },
        }

    def test_command_prefix(self):
        self.assertTrue(gatecheck.command_allowed("python3 -m unittest", self.project))
        self.assertFalse(gatecheck.command_allowed("npm test", self.project))

    def test_lane_local_only(self):
        self.assertTrue(
            gatecheck.lane_conflicts(self.project, "CLOUD", ["PHYSICAL_DEVICE"])
        )
        self.assertFalse(gatecheck.lane_conflicts(self.project, "LOCAL", ["OWNER_EYES"]))
        self.assertFalse(gatecheck.lane_conflicts(self.project, "CLOUD", ["NONE"]))

    def test_packet_id_prefix(self):
        self.assertTrue(gatecheck.packet_id_ok("PKT-0001", self.project))
        self.assertFalse(gatecheck.packet_id_ok("TASK-0001", self.project))

    def test_protected_path(self):
        self.assertTrue(gatecheck.path_is_protected(".github/workflows/ci.yml", self.project))
        self.assertFalse(gatecheck.path_is_protected("docs/design/a.md", self.project))

    def test_merge_approved_uses_config_checks_and_exact_sha(self):
        payload = {
            "gate": "G3_QA_MERGE",
            "verdict": "MERGE_APPROVED",
            "github": {"head_sha": "b" * 40},
            "ci_evidence": {
                "head_sha": "a" * 40,
                "checks": {"gatecheck": {"exit_code": 0}},
            },
            "coverage": {"line_percentage": 10},
        }
        errors = gatecheck.payload_extra_errors(payload, self.project)
        self.assertTrue(any("head_sha" in item for item in errors), errors)
        self.assertTrue(any("test" in item for item in errors), errors)
        self.assertTrue(any("coverage" in item for item in errors), errors)


class SchemaValidatorTest(unittest.TestCase):
    def test_ref_and_if_then(self):
        schema = {
            "$defs": {
                "id": {"type": "string", "pattern": "^PKT-[0-9]{4}$"},
            },
            "type": "object",
            "required": ["packet_id", "verdict"],
            "additionalProperties": False,
            "properties": {
                "packet_id": {"$ref": "#/$defs/id"},
                "verdict": {"type": "string", "enum": ["PASS", "REJECT"]},
                "reasons": {"type": "array", "items": {"type": "string"}},
            },
            "allOf": [
                {
                    "if": {"properties": {"verdict": {"const": "PASS"}}},
                    "then": {"properties": {"reasons": {"maxItems": 0}}},
                    "else": {"properties": {"reasons": {"minItems": 1}}},
                }
            ],
        }
        ok, errors = schema_validate.validate({"packet_id": "PKT-0001", "verdict": "PASS", "reasons": []}, schema)
        self.assertTrue(ok, errors)
        ok, errors = schema_validate.validate({"packet_id": "PKT-0001", "verdict": "PASS", "reasons": ["no"]}, schema)
        self.assertFalse(ok)
        ok, errors = schema_validate.validate({"packet_id": "nope", "verdict": "REJECT", "reasons": ["because this is long enough"]}, schema)
        self.assertFalse(ok)

    def test_sibling_ref_tightens_enum(self):
        schema = {
            "$defs": {
                "kind": {"type": "string", "enum": ["ISSUE", "PULL_REQUEST", "PR_REVIEW"]},
            },
            "type": "object",
            "properties": {
                "kind": {"$ref": "#/$defs/kind", "enum": ["PR_REVIEW"]},
            },
        }
        ok, _errors = schema_validate.validate({"kind": "PR_REVIEW"}, schema)
        self.assertTrue(ok)
        ok, _errors = schema_validate.validate({"kind": "ISSUE"}, schema)
        self.assertFalse(ok)

    def test_file_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            common = {
                "$id": "common.schema.json",
                "$defs": {"name": {"type": "string", "minLength": 3}},
            }
            main = {
                "$id": "main.schema.json",
                "type": "object",
                "properties": {"name": {"$ref": "common.schema.json#/$defs/name"}},
                "required": ["name"],
            }
            docs = schema_validate.SchemaSet.from_documents(
                {"common.schema.json": common, "main.schema.json": main}
            )
            ok, errors = docs.validate_document("main.schema.json", {"name": "ab"})
            self.assertFalse(ok, errors)
            ok, errors = docs.validate_document("main.schema.json", {"name": "abc"})
            self.assertTrue(ok, errors)

    def test_contains_and_unique_and_not(self):
        schema = {
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "uniqueItems": True,
                    "contains": {"const": "STALE_BASE"},
                },
                "exit_code": {"not": {"const": 0}},
            },
        }
        ok, _errors = schema_validate.validate(
            {"codes": ["CI_RED", "STALE_BASE"], "exit_code": 1}, schema
        )
        self.assertTrue(ok)
        ok, _errors = schema_validate.validate(
            {"codes": ["CI_RED"], "exit_code": 1}, schema
        )
        self.assertFalse(ok)
        ok, _errors = schema_validate.validate(
            {"codes": ["STALE_BASE", "STALE_BASE"], "exit_code": 2}, schema
        )
        self.assertFalse(ok)

    def test_bool_is_not_an_integer(self):
        ok, _errors = schema_validate.validate(True, {"type": "integer"})
        self.assertFalse(ok)
        ok, _errors = schema_validate.validate(1, {"type": "integer"})
        self.assertTrue(ok)


class MiniRepoTest(unittest.TestCase):
    def test_design_packet_rejects_base_sha_and_issue_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._mini_repo(Path(tmp))
            packet = json.loads((root / "docs/design/packets/PKT-0001.json").read_text())
            packet["base_sha"] = "a" * 40
            (root / "docs/design/packets/PKT-0001.json").write_text(json.dumps(packet))
            report = gatecheck.run(root)
            self.assertFalse(report.is_clean(), report)
            self.assertTrue(any("base_sha" in line for line in report.failures), report)

    def test_overlap_without_dependency_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._mini_repo(Path(tmp))
            second = json.loads((root / "docs/design/packets/PKT-0001.json").read_text())
            second["packet_id"] = "PKT-0002"
            second["title"] = "Add the second contract file"
            second["subsystem_scope"]["allowed_files"] = ["docs/design/a.md"]
            second["subsystem_scope"]["depends_on_packets"] = []
            (root / "docs/design/packets/PKT-0002.json").write_text(json.dumps(second))
            report = gatecheck.run(root)
            self.assertFalse(report.is_clean(), report)
            self.assertTrue(any("without a declared dependency" in line for line in report.failures), report)

    def _mini_repo(self, root: Path) -> Path:
        project = {
            "schema_version": "1.0.0",
            "project": {
                "name": "Widget",
                "repository": "example/widget",
                "owner_login": "owner",
            },
            "packet": {"id_prefix": "PKT"},
            "spdx": {
                "license_id": "LicenseRef-UNSET",
                "copyright_line": "SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER",
                "extensions": [".py", ".md", ".yml"],
                "basenames": [],
                "exempt_basenames": ["LICENSE"],
            },
            "scope": {
                "allowed_top_level": [
                    ".governance",
                    "docs",
                    "tools",
                    "README.md",
                ],
                "protected_path_patterns": ["^docs/governance/"],
                "amendment_path_patterns": ["^docs/design/packets/"],
            },
            "verification": {"command_prefixes": ["python3 ", "git "]},
            "lane": {"local_only_requires": ["OWNER_EYES", "PHYSICAL_DEVICE"]},
            "hosts": {
                "local_kinds": ["OWNER_MACHINE"],
                "cloud_kinds": ["CURSOR_CLOUD"],
                "ci_kinds": ["GITHUB_ACTIONS"],
            },
            "ci": {
                "workflow_file": "ci.yml",
                "job_name": "gate",
                "required_checks": ["gatecheck", "test", "spdx"],
                "test_check": "test",
                "check_commands": {
                    "gatecheck": "python3 tools/gatecheck/gatecheck.py",
                    "test": "python3 -m unittest discover -s tools/gatecheck -v",
                    "spdx": "python3 tools/gatecheck/gatecheck.py --spdx-only",
                },
            },
            "toolchain": {"language": "undecided", "pin_file": None},
            "policy": {
                "max_cyclomatic_complexity": 10,
                "coverage_floor_percent": 85,
                "forbidden_constructs": [],
            },
            "gatekeeper": {
                "persona_id": "overseer-linus-v1",
                "agent_id_pattern": "^(overseer-linus-v[0-9]+|owner-[a-z0-9-]+)$",
            },
        }
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.invalid/governance/schemas/packet.schema.json",
            "type": "object",
            "required": ["gate", "packet_id", "title", "subsystem_scope"],
            "additionalProperties": False,
            "properties": {
                "gate": {"const": "PACKET"},
                "packet_id": {"type": "string", "pattern": "^PKT-[0-9]{4}$"},
                "title": {"type": "string", "minLength": 8},
                "subsystem_scope": {
                    "type": "object",
                    "required": ["allowed_files", "depends_on_packets"],
                    "additionalProperties": False,
                    "properties": {
                        "allowed_files": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string"},
                        },
                        "depends_on_packets": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
        }
        packet = {
            "gate": "PACKET",
            "packet_id": "PKT-0001",
            "title": "Add the first contract file",
            "subsystem_scope": {
                "allowed_files": ["docs/design/a.md"],
                "depends_on_packets": [],
            },
        }
        (root / ".governance").mkdir(parents=True)
        (root / "docs/governance/schemas").mkdir(parents=True)
        (root / "docs/governance/examples/valid").mkdir(parents=True)
        (root / "docs/governance/examples/invalid").mkdir(parents=True)
        (root / "docs/design/packets").mkdir(parents=True)
        (root / "tools/gatecheck").mkdir(parents=True)
        (root / ".governance/project.json").write_text(json.dumps(project))
        (root / "docs/governance/schemas/packet.schema.json").write_text(json.dumps(schema))
        (root / "docs/design/packets/PKT-0001.json").write_text(json.dumps(packet))
        (root / "README.md").write_text(
            "<!--\nSPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER\nSPDX-License-Identifier: LicenseRef-UNSET\n-->\n\n# Widget\n"
        )
        return root


class ArchitectureRuleTest(unittest.TestCase):
    def test_linear_machine_rejects_a_skipped_state(self):
        errors = architecture.linear_errors(
            {
                "entity": "Item",
                "linear": True,
                "initial": "draft",
                "states": ["draft", "active", "archived"],
                "transitions": [
                    {"from": "draft", "to": "archived", "test": "item_skips_active"}
                ],
            }
        )
        self.assertTrue(any("skips" in item for item in errors), errors)

    def test_ready_packet_rejects_an_unknown_use_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self._catalog(root)
            payload = {
                "gate": "PACKET",
                "status": "READY",
                "packet_id": "PKT-0001",
                "use_cases": ["UC-99"],
                "layer": "domain",
                "state_machines": [],
                "subsystem_scope": {"allowed_files": ["src/domain/item.md"]},
                "verification_plan": {
                    "regression_tests": [{"name": "item_id_present_after_save"}]
                },
            }
            errors = architecture.payload_errors(payload, project, root)
            self.assertTrue(any("UC-99" in item for item in errors), errors)

    def _catalog(self, root: Path) -> dict:
        (root / "docs/design/fixtures").mkdir(parents=True)
        (root / "docs/design/ARCHITECTURE.md").write_text("architecture\n")
        (root / "docs/design/fixtures/use-cases.json").write_text(
            json.dumps(
                {
                    "use_cases": [
                        {
                            "id": "UC-01",
                            "title": "Save one item",
                            "trigger": "A client asks to save one item.",
                            "flow": "The domain stores the item.",
                            "constraint": "A saved item has an id.",
                            "constraint_test": "item_id_present_after_save",
                        }
                    ]
                }
            )
        )
        (root / "docs/design/fixtures/state-machines.json").write_text(
            json.dumps(
                {
                    "machines": [
                        {
                            "entity": "Item",
                            "linear": True,
                            "initial": "draft",
                            "states": ["draft", "active"],
                            "transitions": [
                                {
                                    "from": "draft",
                                    "to": "active",
                                    "test": "item_draft_to_active",
                                }
                            ],
                        }
                    ]
                }
            )
        )
        return {
            "architecture": {
                "document": "docs/design/ARCHITECTURE.md",
                "use_case_catalog": "docs/design/fixtures/use-cases.json",
                "state_machines": "docs/design/fixtures/state-machines.json",
                "change_paths": [
                    "docs/design/ARCHITECTURE.md",
                    "docs/design/fixtures/",
                ],
                "layers": {"domain": ["src/domain/"]},
                "layer_exempt_prefixes": ["docs/design/"],
            }
        }


class RepositoryTest(unittest.TestCase):
    def test_repository_gate_is_clean(self):
        root = Path(__file__).resolve().parents[2]
        report = gatecheck.run(root)
        self.assertTrue(report.is_clean(), str(report))


if __name__ == "__main__":
    unittest.main()
