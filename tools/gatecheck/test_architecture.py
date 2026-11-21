# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Tests for the import rules and the state-machine catalog.

Run: python3 -m unittest discover -s tools/gatecheck -v
"""

import contextlib
import io
import unittest

import architecture
import gatecheck
import importscan
import repo_fixture

HEADER = (
    "# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER\n"
    "# SPDX-License-Identifier: LicenseRef-UNSET\n"
    "\n"
)
CONFIG = ".governance/project.json"
LAYERS = {
    "presentation": ["src/presentation/"],
    "application": ["src/application/"],
    "domain": ["src/domain/", "tests/domain/"],
    "infrastructure": ["src/infrastructure/"],
}
PYTHON = {"parser": "python", "extensions": [".py"], "roots": ["", "src/"]}


class ImportScanTest(unittest.TestCase):
    """The python parser on one file. No repository is needed."""

    def scan(self, source: str, path: str = "src/application/sync.py") -> dict:
        found = importscan.scan(source, path, PYTHON, LAYERS)
        return {item.text: item.layers for item in found}

    def test_absolute_import_from_the_repository_root(self):
        self.assertEqual(self.scan("import src.domain.item\n"), {"src.domain.item": ("domain",)})

    def test_absolute_import_from_a_source_root(self):
        self.assertEqual(self.scan("import infrastructure.store\n")["infrastructure.store"], ("infrastructure",))

    def test_import_of_the_layer_package_itself(self):
        self.assertEqual(self.scan("import src.domain\n")["src.domain"], ("domain",))

    def test_name_after_import_can_be_a_layer(self):
        found = self.scan("from src import presentation\n")
        self.assertEqual(found["src"], ())
        self.assertEqual(found["src.presentation"], ("presentation",))

    def test_relative_import_to_another_layer(self):
        found = self.scan("from ..infrastructure import store\n")
        self.assertEqual(found["..infrastructure"], ("infrastructure",))
        self.assertEqual(found["..infrastructure.store"], ("infrastructure",))

    def test_relative_import_of_a_layer_name(self):
        self.assertEqual(self.scan("from .. import presentation\n")["..presentation"], ("presentation",))

    def test_relative_import_in_the_same_layer(self):
        found = self.scan("from . import rules\nfrom .rules import check\n")
        self.assertEqual(set(found.values()), {("application",)})

    def test_relative_import_above_the_repository_is_not_an_import_of_a_layer(self):
        self.assertEqual(self.scan("from ..... import x\n"), {})

    def test_standard_library_import_is_in_no_layer(self):
        self.assertEqual(self.scan("import json\nfrom pathlib import Path\n")["json"], ())

    def test_import_in_a_function_and_in_a_condition(self):
        source = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from src.presentation import view\n"
            "def late():\n"
            "    import src.infrastructure.store\n"
        )
        found = self.scan(source)
        self.assertEqual(found["src.presentation"], ("presentation",))
        self.assertEqual(found["src.infrastructure.store"], ("infrastructure",))

    def test_dynamic_import_with_a_literal_name(self):
        source = (
            "import importlib\n"
            "importlib.import_module('src.infrastructure.store')\n"
            "__import__('src.presentation')\n"
        )
        found = self.scan(source)
        self.assertEqual(found["src.infrastructure.store"], ("infrastructure",))
        self.assertEqual(found["src.presentation"], ("presentation",))

    def test_import_text_in_a_string_is_not_an_import(self):
        source = '"""\nfrom src.infrastructure import store\n"""\nTEXT = "import src.presentation"\n'
        self.assertEqual(self.scan(source), {})

    def test_line_number_is_the_line_of_the_statement(self):
        found = importscan.scan("\n\nimport src.domain\n", "src/application/a.py", PYTHON, LAYERS)
        self.assertEqual(found[0].line, 3)

    def test_test_directory_can_be_part_of_a_layer(self):
        self.assertEqual(importscan.layer_of("tests/domain/test_item.py", LAYERS), "domain")
        self.assertIsNone(importscan.layer_of("tests/conftest.py", LAYERS))

    def test_regex_parser_reads_the_group_and_the_layer_patterns(self):
        scanner = {
            "parser": "regex",
            "extensions": [".x"],
            "import_patterns": [r"^\s*use\s+([\w:]+);"],
            "layer_patterns": {"infrastructure": [r"(^|::)infrastructure(::|$)"]},
        }
        source = "use app::domain::item;\n  use app::infrastructure::store;\n"
        found = importscan.scan(source, "src/domain/item.x", scanner, LAYERS)
        self.assertEqual(
            [(item.line, item.text, item.layers) for item in found],
            [(1, "app::domain::item", ()), (2, "app::infrastructure::store", ("infrastructure",))],
        )


class ProjectCase(repo_fixture.RepoCopyCase):
    """A copy of the repository that a project adopted."""

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
        repo_fixture.write_text(self.root, "CODEOWNERS", owners.replace("@replace-me", "@example-owner"))

    def edit(self, change) -> None:
        repo_fixture.edit_json(self.root, CONFIG, change)

    def rules(self, change) -> None:
        self.edit(lambda project: change(project["architecture"]["import_rules"]))

    def source(self, relative: str, body: str) -> None:
        repo_fixture.write_text(self.root, relative, HEADER + body)


class ImportRuleTest(ProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.rules(lambda rules: rules["scanners"].append(dict(PYTHON)))

    def test_imports_that_follow_the_direction_pass(self):
        self.source("src/domain/item.py", "import json\nfrom . import rules\n")
        self.source("src/domain/rules.py", "LIMIT = 3\n")
        self.source("src/application/save.py", "from src.domain import item\n")
        self.source("src/infrastructure/store.py", "from src.domain.item import LIMIT\nimport src.application.save\n")
        self.source("src/presentation/view.py", "from src.application.save import run\n")
        self.assert_clean()
        self.assertIn(
            "layer imports follow architecture.import_rules (5 source files)",
            gatecheck.run(self.root).passed,
        )

    def test_domain_must_not_import_infrastructure(self):
        self.source("src/domain/item.py", "from src.infrastructure.store import Store\n")
        self.assert_fails_with(
            "src/domain/item.py:4: layer domain must not import layer infrastructure (src.infrastructure.store)"
        )

    def test_one_statement_gives_one_failure(self):
        self.source("src/domain/item.py", "from src.infrastructure.store import Store, Other\n")
        failures = [line for line in self.failures() if "must not import layer" in line]
        self.assertEqual(len(failures), 1, failures)

    def test_domain_must_not_import_application(self):
        self.source("src/domain/item.py", "import application.save\n")
        self.assert_fails_with("layer domain must not import layer application")

    def test_application_must_not_import_presentation(self):
        self.source("src/application/save.py", "from ..presentation import view\n")
        self.assert_fails_with("layer application must not import layer presentation (..presentation)")

    def test_application_must_not_import_infrastructure(self):
        self.source("src/application/save.py", "def run():\n    import src.infrastructure.store\n")
        self.assert_fails_with("src/application/save.py:5: layer application must not import layer infrastructure")

    def test_presentation_must_not_import_infrastructure(self):
        self.source("src/presentation/view.py", "import importlib\nimportlib.import_module('src.infrastructure.store')\n")
        self.assert_fails_with("layer presentation must not import layer infrastructure")

    def test_project_file_can_allow_one_more_direction(self):
        self.source("src/presentation/view.py", "import src.infrastructure.store\n")
        self.source("src/infrastructure/store.py", "VALUE = 1\n")
        self.rules(lambda rules: rules["allowed"]["presentation"].append("infrastructure"))
        self.assert_clean()

    def test_layer_must_not_import_a_forbidden_name(self):
        self.rules(lambda rules: rules["forbidden"].update(domain=[r"^socket(\.|$)"]))
        self.source("src/domain/item.py", "import json\nimport socket\n")
        self.assert_fails_with("src/domain/item.py:5: layer domain must not import socket")

    def test_forbidden_name_applies_to_its_layer_only(self):
        self.rules(lambda rules: rules["forbidden"].update(domain=[r"^socket(\.|$)"]))
        self.source("src/infrastructure/store.py", "import socket\n")
        self.assert_clean()

    def test_source_file_outside_every_layer_fails(self):
        self.source("src/main.py", "import src.infrastructure.store\n")
        self.assert_fails_with("src/main.py: source file is outside every layer")

    def test_exempt_file_can_import_each_layer(self):
        self.source("src/main.py", "import src.infrastructure.store\nimport src.presentation.view\n")
        self.edit(lambda project: project["architecture"]["layer_exempt_prefixes"].append("src/main.py"))
        self.assert_clean()

    def test_file_type_without_a_scanner_fails(self):
        repo_fixture.write_text(self.root, "src/domain/table.dat", "1 2 3\n")
        self.assert_fails_with("src/domain/table.dat: no scanner reads this file type")

    def test_declared_non_source_suffix_passes(self):
        repo_fixture.write_text(self.root, "src/domain/table.dat", "1 2 3\n")
        self.rules(lambda rules: rules["non_source_extensions"].append(".dat"))
        self.assert_clean()

    def test_file_that_does_not_parse_fails(self):
        self.source("src/domain/item.py", "def broken(:\n")
        self.assert_fails_with("src/domain/item.py: cannot parse the file: line 4")

    def test_file_with_a_byte_order_mark_is_read(self):
        repo_fixture.write_text(self.root, "src/domain/item.py", "\ufeff" + HEADER + "import src.presentation.view\n")
        self.assert_fails_with("src/domain/item.py:4: layer domain must not import layer presentation")

    def test_test_directory_follows_the_rules_of_its_layer(self):
        def tests_in_domain(project):
            project["scope"]["allowed_top_level"].append("tests")
            project["architecture"]["layers"]["domain"].append("tests/domain/")

        self.edit(tests_in_domain)
        self.source("tests/domain/test_item.py", "import src.infrastructure.store\n")
        self.assert_fails_with("tests/domain/test_item.py:4: layer domain must not import layer infrastructure")

    def test_architecture_command_reports_an_import_failure(self):
        self.source("src/domain/item.py", "import src.presentation.view\n")
        report = gatecheck.run_architecture(self.root)
        self.assertTrue(any("must not import layer presentation" in line for line in report.failures))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(architecture.main([str(self.root)]), 1)
        self.assertIn("FAIL  src/domain/item.py:4", output.getvalue())


class RegexScannerTest(ProjectCase):
    SCANNER = {
        "parser": "regex",
        "extensions": [".x"],
        "import_patterns": [r"^\s*use\s+([\w:]+);"],
        "layer_patterns": {
            "presentation": [r"(^|::)presentation(::|$)"],
            "application": [r"(^|::)application(::|$)"],
            "domain": [r"(^|::)domain(::|$)"],
            "infrastructure": [r"(^|::)infrastructure(::|$)"],
        },
    }

    def setUp(self) -> None:
        super().setUp()
        self.rules(lambda rules: rules["scanners"].append(dict(self.SCANNER)))

    def test_regex_scanner_finds_a_wrong_direction(self):
        repo_fixture.write_text(self.root, "src/domain/item.x", "use app::infrastructure::store;\n")
        self.assert_fails_with("src/domain/item.x:1: layer domain must not import layer infrastructure")

    def test_regex_scanner_accepts_the_right_direction(self):
        repo_fixture.write_text(self.root, "src/application/save.x", "use app::domain::item;\n")
        self.assert_clean()


class ImportRuleConfigTest(ProjectCase):
    def test_template_must_not_set_a_scanner(self):
        self.edit(lambda project: project["project"].update(repo_fixture.read_json(repo_fixture.SOURCE_ROOT, CONFIG)["project"]))
        self.rules(lambda rules: rules["scanners"].append(dict(PYTHON)))
        self.assert_fails_with("import_rules.scanners is set but the project identity is a placeholder")

    def test_allowed_map_must_not_contain_a_cycle(self):
        self.rules(lambda rules: rules["allowed"]["domain"].append("application"))
        self.assert_fails_with("import_rules.allowed contains a cycle")

    def test_allowed_map_needs_each_layer(self):
        self.rules(lambda rules: rules["allowed"].pop("domain"))
        self.assert_fails_with("import_rules.allowed needs one key for each layer")

    def test_allowed_map_must_name_known_layers(self):
        self.rules(lambda rules: rules["allowed"]["application"].append("core"))
        self.assert_fails_with("import_rules.allowed.application names the unknown layer core")

    def test_forbidden_map_must_name_known_layers(self):
        self.rules(lambda rules: rules["forbidden"].update(core=["^x$"]))
        self.assert_fails_with("import_rules.forbidden names the unknown layer core")

    def test_two_scanners_must_not_read_one_suffix(self):
        self.rules(lambda rules: rules["scanners"].extend([dict(PYTHON), dict(PYTHON)]))
        self.assert_fails_with("which scanner 0 also reads")

    def test_scanner_suffix_must_not_be_a_non_source_suffix(self):
        def both(rules):
            rules["scanners"].append(dict(PYTHON))
            rules["non_source_extensions"].append(".py")

        self.rules(both)
        self.assert_fails_with("reads .py, which is in non_source_extensions")

    def test_python_scanner_needs_roots(self):
        self.rules(lambda rules: rules["scanners"].append({"parser": "python", "extensions": [".py"]}))
        self.assert_fails_with("missing required property roots")

    def test_regex_scanner_needs_a_group(self):
        scanner = dict(RegexScannerTest.SCANNER, import_patterns=[r"^use \w+;"])
        self.rules(lambda rules: rules["scanners"].append(scanner))
        self.assert_fails_with("needs one group for the imported name")


class MachineCatalogTest(repo_fixture.RepoCopyCase):
    MACHINES = "docs/design/fixtures/state-machines.json"
    PACKET = "docs/design/packets/PKT-0001.json"

    def machine(self, change) -> None:
        repo_fixture.edit_json(self.root, self.MACHINES, lambda catalog: change(catalog["machines"][0]))

    def test_event_guard_id_and_title_are_valid(self):
        def describe(machine):
            machine.update(id="SM-01", title="Item life cycle")
            machine["transitions"][0].update(event="publish", guard="the item has a name")

        self.machine(describe)
        self.assert_clean()

    def test_unknown_key_fails(self):
        self.machine(lambda machine: machine.update(invalid_transitions=[]))
        self.assert_fails_with("additional property invalid_transitions")

    def test_id_must_match_the_pattern(self):
        self.machine(lambda machine: machine.update(id="machine-1"))
        self.assert_fails_with("machines/0/id: does not match pattern")

    def test_ids_must_be_unique(self):
        def two(catalog):
            first = catalog["machines"][0]
            first["id"] = "SM-01"
            second = dict(first, entity="Other")
            catalog["machines"].append(second)

        repo_fixture.edit_json(self.root, self.MACHINES, two)
        self.assert_fails_with("duplicate state machine id SM-01")

    def test_forbidden_transition_needs_a_test_in_the_packet(self):
        self._forbid("draft", "archived", "item_draft_to_archived_is_rejected")
        self.assert_fails_with(
            "verification plan is missing transition test item_draft_to_archived_is_rejected for Item"
        )

    def test_packet_that_lists_the_forbidden_test_passes(self):
        self._forbid("draft", "archived", "item_draft_to_archived_is_rejected")

        def add(packet):
            packet["verification_plan"]["regression_tests"].append(
                {
                    "name": "item_draft_to_archived_is_rejected",
                    "kind": "UNIT",
                    "asserts": "A draft item cannot move to archived.",
                }
            )

        repo_fixture.edit_json(self.root, self.PACKET, add)
        self.assert_clean()

    def test_forbidden_transition_must_not_be_a_transition(self):
        self._forbid("draft", "active", "item_draft_to_active_is_rejected")
        self.assert_fails_with("Item forbidden transition draft -> active is also a transition")

    def test_forbidden_transition_needs_known_states(self):
        self._forbid("draft", "deleted", "item_draft_to_deleted_is_rejected")
        self.assert_fails_with("Item forbidden transition arrives at an unknown state")

    def test_each_state_must_be_reachable(self):
        def island(machine):
            machine["linear"] = False
            machine["states"].append("lost")

        self.machine(island)
        self.assert_fails_with("Item state lost cannot be reached from the initial state")

    def test_transition_must_not_repeat(self):
        def twice(machine):
            machine["linear"] = False
            machine["transitions"].append(dict(machine["transitions"][0], test="item_draft_to_active_again"))

        self.machine(twice)
        self.assert_fails_with("Item transition draft -> active is in the list twice")

    def test_one_test_must_not_prove_two_transitions(self):
        self.machine(
            lambda machine: machine["transitions"][1].update(test=machine["transitions"][0]["test"])
        )
        self.assert_fails_with("Item test name item_draft_to_active is on two transitions")

    def test_use_case_with_an_unknown_key_fails(self):
        repo_fixture.edit_json(
            self.root,
            "docs/design/fixtures/use-cases.json",
            lambda catalog: catalog["use_cases"][0].update(owner="team"),
        )
        self.assert_fails_with("additional property owner")

    def _forbid(self, source: str, target: str, test: str) -> None:
        self.machine(
            lambda machine: machine.update(
                forbidden_transitions=[{"from": source, "to": target, "test": test}]
            )
        )


if __name__ == "__main__":
    unittest.main()
