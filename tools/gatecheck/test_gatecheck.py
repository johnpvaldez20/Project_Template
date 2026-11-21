# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Tests for the language-neutral gate checker.

Run: python3 -m unittest discover -s tools/gatecheck -v
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import architecture
import gatecheck
import projectfile
import repo_fixture
import repofiles
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


class PacketFileTest(repo_fixture.RepoCopyCase):
    PACKET = "docs/design/packets/PKT-0001.json"

    def test_copy_of_the_repository_is_clean(self):
        self.assert_clean()

    def test_design_packet_rejects_base_sha(self):
        repo_fixture.edit_json(
            self.root, self.PACKET, lambda packet: packet.update(base_sha="a" * 40)
        )
        self.assert_fails_with("base_sha")

    def test_design_packet_rejects_issue_number(self):
        repo_fixture.edit_json(
            self.root, self.PACKET, lambda packet: packet.update(issue_number=7)
        )
        self.assert_fails_with("issue_number")

    def test_overlap_without_dependency_fails(self):
        self._add_packet("PKT-0002", depends_on=[])
        self.assert_fails_with("without a declared dependency")

    def test_overlap_with_dependency_passes(self):
        self._add_packet("PKT-0002", depends_on=["PKT-0001"])
        self.assert_clean()

    def test_indirect_dependency_orders_an_overlap(self):
        self._add_packet("PKT-0002", depends_on=["PKT-0001"])
        self._add_packet("PKT-0003", depends_on=["PKT-0002"])
        self.assert_clean()

    def test_dependency_cycle_fails(self):
        self._add_packet("PKT-0002", depends_on=["PKT-0003"])
        self._add_packet("PKT-0003", depends_on=["PKT-0002"])
        self.assert_fails_with("dependency cycle")

    def test_packet_file_that_is_not_json_fails(self):
        repo_fixture.write_text(self.root, "docs/design/packets/PKT-0002.json", "{ not json")
        self.assert_fails_with("PKT-0002.json: invalid JSON")

    def _add_packet(self, packet_id: str, depends_on: list) -> None:
        packet = repo_fixture.read_json(self.root, self.PACKET)
        packet["packet_id"] = packet_id
        packet["subsystem_scope"]["depends_on_packets"] = depends_on
        repo_fixture.write_json(self.root, f"docs/design/packets/{packet_id}.json", packet)


class AdoptionTest(repo_fixture.RepoCopyCase):
    """Edits that the adoption page tells a new project to make."""

    def test_project_can_set_its_identity(self):
        self._set_identity()
        self.assert_clean()
        self.assertIn("project identity is set", gatecheck.run(self.root).passed)

    def test_project_can_set_its_language(self):
        self._set_identity()
        repo_fixture.edit_json(
            self.root,
            ".governance/project.json",
            lambda project: project["toolchain"].update(language="other-language"),
        )
        self.assert_clean()

    def _set_identity(self) -> None:
        def identity(project):
            project["project"].update(
                name="Widget",
                full_name="Widget service",
                repository="example/widget",
                owner_login="example-owner",
            )

        repo_fixture.edit_json(self.root, ".governance/project.json", identity)
        text = (self.root / "CODEOWNERS").read_text(encoding="utf-8")
        repo_fixture.write_text(
            self.root, "CODEOWNERS", text.replace("@replace-me", "@example-owner")
        )

    def test_project_can_raise_the_coverage_floor(self):
        repo_fixture.edit_json(
            self.root,
            ".governance/project.json",
            lambda project: project["policy"].update(coverage_floor_percent=100),
        )
        self.assert_clean()

    def test_project_can_replace_the_architecture_catalog(self):
        def use_cases(catalog):
            catalog["use_cases"][0]["title"] = "Keep one setting"
            catalog["use_cases"][0]["constraint_test"] = "setting_survives_restart"

        def machines(catalog):
            catalog["machines"] = [
                {
                    "entity": "Switch",
                    "linear": False,
                    "initial": "off",
                    "states": ["off", "on"],
                    "transitions": [
                        {"from": "off", "to": "on", "test": "switch_off_to_on"},
                        {"from": "on", "to": "off", "test": "switch_on_to_off"},
                    ],
                }
            ]

        def packet(value):
            value["state_machines"] = ["Switch"]
            value["verification_plan"]["regression_tests"] = [
                {"name": name, "kind": "UNIT", "asserts": "The named rule holds in this test."}
                for name in ("setting_survives_restart", "switch_off_to_on", "switch_on_to_off")
            ]

        repo_fixture.edit_json(self.root, "docs/design/fixtures/use-cases.json", use_cases)
        repo_fixture.edit_json(self.root, "docs/design/fixtures/state-machines.json", machines)
        repo_fixture.edit_json(self.root, "docs/design/packets/PKT-0001.json", packet)
        self.assert_clean()

    def test_examples_need_their_architecture_file(self):
        (self.root / "docs/governance/examples/architecture.json").unlink()
        self.assert_fails_with("missing docs/governance/examples/architecture.json")


class ProjectFileTest(repo_fixture.RepoCopyCase):
    CONFIG = ".governance/project.json"

    def test_unknown_key_fails(self):
        self._edit(lambda project: project.update(extra=True))
        self.assert_fails_with("additional property extra")

    def test_missing_architecture_block_fails(self):
        self._edit(lambda project: project.pop("architecture"))
        self.assert_fails_with("missing required property architecture")

    def test_coverage_floor_must_be_a_number(self):
        self._edit(lambda project: project["policy"].update(coverage_floor_percent="85"))
        self.assert_fails_with("policy/coverage_floor_percent: expected type number")

    def test_pattern_that_does_not_compile_fails(self):
        self._edit(lambda project: project["scope"]["protected_path_patterns"].append("("))
        self.assert_fails_with("is not a regular expression")

    def test_required_check_needs_a_command(self):
        self._edit(lambda project: project["ci"]["required_checks"].append("lint"))
        self.assert_fails_with("no command for the required check lint")

    def test_test_check_must_be_a_required_check(self):
        self._edit(lambda project: project["ci"].update(test_check="other"))
        self.assert_fails_with("ci.test_check must be one of ci.required_checks")

    def test_check_command_needs_an_allowed_prefix(self):
        self._edit(lambda project: project["ci"]["check_commands"].update(test="make test"))
        self.assert_fails_with("ci.check_commands.test does not start with a prefix")

    def test_checker_directory_must_be_protected(self):
        self._edit(
            lambda project: project["scope"]["protected_path_patterns"].remove("^tools/gatecheck/")
        )
        self.assert_fails_with("tools/gatecheck/gatecheck.py must match scope.protected_path_patterns")

    def test_layer_paths_must_not_overlap(self):
        self._edit(
            lambda project: project["architecture"]["layers"]["application"].append("src/domain/rules/")
        )
        self.assert_fails_with("layer paths src/domain/rules/ and src/domain/ overlap")

    def test_layer_name_must_be_lower_case(self):
        self._edit(lambda project: project["architecture"]["layers"].update(Core=["src/core/"]))
        self.assert_fails_with("invalid layer name 'Core'")

    def test_identity_that_is_partly_set_fails(self):
        self._edit(lambda project: project["project"].update(name="Widget"))
        self.assert_fails_with("project.repository still holds the template placeholder")

    def test_template_must_not_choose_a_language(self):
        self._edit(lambda project: project["toolchain"].update(language="other-language"))
        self.assert_fails_with("toolchain.language is set but the project identity is a placeholder")

    def test_schema_version_must_match_the_schema(self):
        self._edit(lambda project: project.update(schema_version="9.9.9"))
        self.assert_fails_with("schema_version 9.9.9 is not the schema constant")

    def test_pin_file_is_a_protected_path(self):
        project = repo_fixture.read_json(self.root, self.CONFIG)
        self.assertFalse(gatecheck.path_is_protected("toolchain.lock", project))
        project["toolchain"]["pin_file"] = "toolchain.lock"
        self.assertTrue(gatecheck.path_is_protected("toolchain.lock", project))

    def _edit(self, change) -> None:
        repo_fixture.edit_json(self.root, self.CONFIG, change)


class CodeownersTest(repo_fixture.RepoCopyCase):
    HEADER = repo_fixture.hash_header()

    def test_missing_file_fails(self):
        (self.root / "CODEOWNERS").unlink()
        self.assert_fails_with("missing CODEOWNERS at the repository root")

    def test_second_file_fails(self):
        repo_fixture.write_text(self.root, ".github/CODEOWNERS", self.HEADER + "* @replace-me\n")
        self.assert_fails_with(".github/CODEOWNERS must not exist")

    def test_rule_without_the_owner_fails(self):
        self._write("* @replace-me\n/src/ @someone-else\n")
        self.assert_fails_with("CODEOWNERS rule /src/ does not name @replace-me")

    def test_owner_in_a_comment_does_not_count(self):
        self._write("# @replace-me\n* @someone-else\n")
        self.assert_fails_with("CODEOWNERS rule * does not name @replace-me")

    def test_file_needs_a_rule_for_every_path(self):
        self._write("/docs/ @replace-me\n")
        self.assert_fails_with("CODEOWNERS needs a rule for *")

    def test_login_case_does_not_matter(self):
        self._write("* @Replace-Me\n")
        self.assert_clean()

    def _write(self, rules: str) -> None:
        repo_fixture.write_text(self.root, "CODEOWNERS", self.HEADER + rules)


class RepositoryFilesTest(repo_fixture.RepoCopyCase):
    def test_walk_lists_each_file_once(self):
        files = repofiles.list_files(self.root)
        self.assertIn(".governance/project.json", files)
        self.assertEqual(len(files), len(set(files)))

    def test_file_that_git_ignores_is_not_repository_content(self):
        self._git("init", "-q")
        (self.root / ".pytest_cache").mkdir()
        repo_fixture.write_text(self.root, ".pytest_cache/README.md", "cache\n")
        repo_fixture.write_text(self.root, ".env", "TOKEN=value\n")
        repo_fixture.write_text(self.root, "tools/gatecheck/__pycache__/x.pyc", "x")
        files = repofiles.list_files(self.root)
        self.assertNotIn(".env", files)
        self.assertNotIn(".pytest_cache/README.md", files)
        self.assert_clean()

    def test_file_that_git_does_not_ignore_is_repository_content(self):
        self._git("init", "-q")
        repo_fixture.write_text(self.root, "stray.txt", "stray\n")
        self.assertIn("stray.txt", repofiles.list_files(self.root))
        self.assert_fails_with("top-level path stray.txt is not in the project config")

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            env=repofiles.git_env(),
        )


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

    def test_snapshot_equals_the_template_files(self):
        """A project that adopted the template keeps the snapshot as it is."""
        project = repo_fixture.read_json(repo_fixture.SOURCE_ROOT, repo_fixture.CONFIG)
        if projectfile.is_template(project):
            self.assertEqual(
                repo_fixture.snapshot_differences(),
                [],
                "run python3 tools/gatecheck/repo_fixture.py",
            )

    def test_tests_do_not_read_the_project_of_this_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo_fixture.copy_repo(Path(tmp))
            self.assertTrue(projectfile.is_template(repo_fixture.read_json(root, repo_fixture.CONFIG)))
            self.assertFalse((root / "tools").exists())
            report = gatecheck.run(root)
            self.assertTrue(report.is_clean(), str(report))


if __name__ == "__main__":
    unittest.main()
