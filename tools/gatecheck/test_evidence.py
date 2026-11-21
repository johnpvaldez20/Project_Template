# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Tests for the pull request check and the report check.

Run: python3 -m unittest discover -s tools/gatecheck -v
"""

import contextlib
import io
import subprocess
import unittest

import gatecheck
import repo_fixture
import repofiles

HEADER = "<!--\nSPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER\nSPDX-License-Identifier: LicenseRef-UNSET\n-->\n\n"
PACKET = "docs/design/packets/PKT-0001.json"
BRANCH = "pkt/PKT-0001-item-record"
TESTS = "item_id_present_after_save\nitem_draft_to_active\nitem_active_to_archived\n"
GIT_OPTIONS = [
    "-c", "user.name=Test",
    "-c", "user.email=test@example.invalid",
    "-c", "commit.gpgsign=false",
    "-c", "core.fsmonitor=false",
    "-c", "core.hooksPath=/dev/null",
]


class GitRepoCase(repo_fixture.RepoCopyCase):
    """A copy of the repository with one commit on main."""

    def setUp(self) -> None:
        super().setUp()
        self.git("init", "-q", "-b", "main")
        self.commit("base")

    def git(self, *args: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(self.root), *GIT_OPTIONS, *args],
            check=True,
            capture_output=True,
            env=repofiles.git_env(),
        )
        return done.stdout.decode("utf-8").strip()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def write(self, relative: str, body: str = TESTS) -> None:
        repo_fixture.write_text(self.root, relative, HEADER + body)

    def edit_packet(self, change) -> None:
        repo_fixture.edit_json(self.root, PACKET, change)

    def check(self, base: str = "main") -> gatecheck.Report:
        return gatecheck.check_pull_request(self.root, base, None, env={})

    def assert_pr_fails(self, fragment: str) -> None:
        failures = self.check().failures
        self.assertTrue(
            any(fragment in line for line in failures),
            f"no failure contains {fragment!r}: {failures}",
        )


class PullRequestTest(GitRepoCase):
    def test_packet_branch_in_its_scope_passes(self):
        self.git("checkout", "-q", "-b", BRANCH)
        self.write("src/domain/item.md")
        head = self.commit("add the item record")
        report = self.check()
        self.assertTrue(report.is_clean(), str(report))
        for fact in (
            f"head_sha {head}",
            "merge_base_is_main_head true",
            "commits_in_pr 1",
            "files_modified 1",
            "modified src/domain/item.md",
            "touches_protected_paths false",
            "packet PKT-0001 is read from the base commit",
            "each modified file is in the allowed_files of PKT-0001",
            "each of the 3 planned regression tests is in the tree",
        ):
            self.assertIn(fact, report.passed)
        self.assertEqual(len(head), 40)

    def test_stale_base_fails(self):
        self.git("checkout", "-q", "-b", BRANCH)
        self.write("src/domain/item.md")
        self.commit("add the item record")
        self.git("checkout", "-q", "main")
        self.commit("main moves")
        self.git("checkout", "-q", BRANCH)
        self.assert_pr_fails("STALE_BASE")

    def test_file_outside_the_packet_scope_fails(self):
        self.git("checkout", "-q", "-b", BRANCH)
        self.write("src/domain/item.md")
        self.write("src/domain/other.md", "other\n")
        self.commit("add two files")
        self.assert_pr_fails("SCOPE_VIOLATION: src/domain/other.md is not in the allowed_files of PKT-0001")

    def test_deleted_file_is_a_modified_file(self):
        self.git("checkout", "-q", "-b", BRANCH)
        self.write("src/domain/item.md")
        (self.root / "src/presentation/README.md").unlink()
        self.commit("add one file and remove one file")
        self.assert_pr_fails("SCOPE_VIOLATION: src/presentation/README.md")

    def test_protected_file_needs_a_gatekeeper_packet(self):
        self._base_scope([".github/workflows/ci.yml"])
        self.git("checkout", "-q", "-b", BRANCH)
        self._append(".github/workflows/ci.yml", "# changed\n")
        self.commit("change the workflow")
        self.assert_pr_fails("PROTECTED_PATH: .github/workflows/ci.yml needs a packet with gatekeeper_packet true")

    def test_gatekeeper_packet_can_change_a_protected_file(self):
        self._base_scope([".github/workflows/ci.yml"], gatekeeper_packet=True)
        self.git("checkout", "-q", "-b", BRANCH)
        self._append(".github/workflows/ci.yml", "# changed\n" + "# " + TESTS.replace("\n", " ") + "\n")
        self.commit("change the workflow")
        report = self.check()
        self.assertFalse(any("PROTECTED_PATH" in line for line in report.failures), str(report))
        self.assertIn("touches_protected_paths true", report.passed)
        self.assertIn("modified .github/workflows/ci.yml (protected)", report.passed)

    def test_architecture_path_needs_an_architecture_packet(self):
        self._base_scope(["docs/design/ARCHITECTURE.md"])
        self.git("checkout", "-q", "-b", BRANCH)
        self._append("docs/design/ARCHITECTURE.md", "\nOne more line.\n")
        self.commit("change the architecture page")
        self.assert_pr_fails("docs/design/ARCHITECTURE.md is an architecture path")

    def test_branch_cannot_widen_its_own_scope(self):
        self.git("checkout", "-q", "-b", BRANCH)
        self.edit_packet(
            lambda packet: packet["subsystem_scope"]["allowed_files"].append("src/domain/other.md")
        )
        self.write("src/domain/item.md")
        self.write("src/domain/other.md", "other\n")
        self.commit("widen the plan and use it")
        failures = self.check().failures
        self.assertTrue(any("SCOPE_VIOLATION: src/domain/other.md" in line for line in failures), failures)
        self.assertTrue(any(f"SCOPE_VIOLATION: {PACKET}" in line for line in failures), failures)

    def test_packet_that_is_new_on_the_branch_is_read_from_the_branch(self):
        self.git("checkout", "-q", "-b", "pkt/PKT-0002-second-record")
        packet = repo_fixture.read_json(self.root, PACKET)
        packet["packet_id"] = "PKT-0002"
        packet["subsystem_scope"]["allowed_files"] = [
            "docs/design/packets/PKT-0002.json",
            "src/domain/second.md",
        ]
        packet["subsystem_scope"]["depends_on_packets"] = ["PKT-0001"]
        repo_fixture.write_json(self.root, "docs/design/packets/PKT-0002.json", packet)
        self.write("src/domain/second.md")
        self.commit("add the second packet")
        report = self.check()
        self.assertTrue(report.is_clean(), str(report))
        self.assertIn("packet PKT-0002 is new on this branch", report.passed)

    def test_packet_branch_without_a_packet_file_fails(self):
        self.git("checkout", "-q", "-b", "pkt/PKT-0009-no-plan")
        self.write("src/domain/item.md")
        self.commit("code with no plan")
        self.assert_pr_fails("no packet file docs/design/packets/PKT-0009.json for this branch")

    def test_blocked_packet_fails(self):
        def block(packet):
            packet["status"] = "BLOCKED"
            packet["blocked_on"] = ["OQ-1"]

        self.edit_packet(block)
        self.commit("block the packet")
        self.git("checkout", "-q", "-b", BRANCH)
        self.write("src/domain/item.md")
        self.commit("code a blocked packet")
        self.assert_pr_fails("packet PKT-0001 is not READY")

    def test_planned_test_must_be_in_the_tree(self):
        self.git("checkout", "-q", "-b", BRANCH)
        self.write("src/domain/item.md", "item_id_present_after_save\nitem_draft_to_active\n")
        self.commit("add two of three tests")
        self.assert_pr_fails("REGRESSION_TEST_MISSING: the plan of PKT-0001 names item_active_to_archived")

    def test_name_inside_a_longer_name_is_not_the_test(self):
        self.git("checkout", "-q", "-b", BRANCH)
        self.write("src/domain/item.md", TESTS.replace("item_active_to_archived", "item_active_to_archived_later"))
        self.commit("add a test with a longer name")
        self.assert_pr_fails("names item_active_to_archived,")

    def test_branch_that_is_not_a_packet_branch_passes_with_a_notice(self):
        self.git("checkout", "-q", "-b", "chore/update-readme")
        self._append("README.md", "\nOne more line.\n")
        self.commit("update the readme")
        report = self.check()
        self.assertTrue(report.is_clean(), str(report))
        self.assertTrue(any("is not a packet branch" in line for line in report.passed))

    def test_missing_base_ref_fails(self):
        report = gatecheck.check_pull_request(self.root, None, None, env={})
        self.assertTrue(
            any("base ref origin/main does not exist" in line for line in report.failures),
            str(report),
        )

    def test_environment_gives_the_base_and_the_branch(self):
        self.git("update-ref", "refs/remotes/origin/main", "main")
        self.git("checkout", "-q", "-b", BRANCH)
        self.write("src/domain/item.md")
        self.commit("add the item record")
        self.git("checkout", "-q", "--detach")
        env = {"GITHUB_BASE_REF": "main", "GITHUB_HEAD_REF": BRANCH}
        report = gatecheck.check_pull_request(self.root, None, None, env=env)
        self.assertTrue(report.is_clean(), str(report))
        self.assertIn("packet PKT-0001 is read from the base commit", report.passed)

    def test_command_line_exit_code(self):
        self.git("checkout", "-q", "-b", BRANCH)
        self.write("src/domain/other.md", "other\n")
        self.commit("add a file outside the plan")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = gatecheck.main([str(self.root), "--pr", "--base", "main", "--branch", BRANCH])
        self.assertEqual(code, 1)
        self.assertIn("FAIL  SCOPE_VIOLATION", output.getvalue())

    def _base_scope(self, extra: list, gatekeeper_packet: bool = False) -> None:
        def widen(packet):
            packet["subsystem_scope"]["allowed_files"].extend(extra)
            packet["gatekeeper_packet"] = gatekeeper_packet

        self.edit_packet(widen)
        self.commit("set the plan on main")

    def _append(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="unit" tests="3">
    <testcase classname="a" name="one"/>
    <testcase classname="a" name="two"/>
    <testcase classname="a" name="three">{child}</testcase>
  </testsuite>
</testsuites>
"""
COBERTURA = '<?xml version="1.0" ?>\n<coverage line-rate="{rate}" lines-valid="{valid}" lines-covered="{covered}"></coverage>\n'


class ReportTest(repo_fixture.AdoptedRepoCase):
    def setUp(self) -> None:
        super().setUp()

        def reports(project):
            project["scope"]["allowed_top_level"].append("reports")
            project["ci"]["evidence"] = {
                "test_report": "reports/junit.xml",
                "coverage_report": "reports/coverage.xml",
            }

        self.edit(reports)
        self.junit()
        self.coverage(COBERTURA.format(rate="0.925", valid="200", covered="185"))

    def junit(self, child: str = "") -> None:
        repo_fixture.write_text(self.root, "reports/junit.xml", JUNIT.format(child=child))

    def coverage(self, text: str) -> None:
        repo_fixture.write_text(self.root, "reports/coverage.xml", text)

    def check(self) -> gatecheck.Report:
        return gatecheck.check_reports(self.root)

    def assert_report_fails(self, fragment: str) -> None:
        failures = self.check().failures
        self.assertTrue(
            any(fragment in line for line in failures),
            f"no failure contains {fragment!r}: {failures}",
        )

    def test_good_reports_pass_and_give_the_numbers(self):
        report = self.check()
        self.assertTrue(report.is_clean(), str(report))
        for fact in ("total_tests 3", "failed_tests 0", "ignored_tests 0", "line_percentage 92.50 (floor 85)"):
            self.assertIn(fact, report.passed)

    def test_skipped_test_fails(self):
        self.junit('<skipped message="later"/>')
        self.assert_report_fails("reports/junit.xml records 1 ignored tests")

    def test_expected_failure_is_an_ignored_test(self):
        self.junit('<skipped type="pytest.xfail" message="known"/>')
        self.assert_report_fails("records 1 ignored tests")

    def test_status_attribute_can_mark_an_ignored_test(self):
        text = JUNIT.format(child="").replace('name="two"', 'name="two" status="Skipped"')
        repo_fixture.write_text(self.root, "reports/junit.xml", text)
        self.assert_report_fails("records 1 ignored tests")

    def test_failed_test_fails(self):
        self.junit('<failure message="no"/>')
        self.assert_report_fails("reports/junit.xml records 1 failed tests")

    def test_test_error_fails(self):
        self.junit('<error message="crash"/>')
        self.assert_report_fails("records 1 failed tests")

    def test_report_without_a_test_fails(self):
        repo_fixture.write_text(self.root, "reports/junit.xml", "<testsuites></testsuites>\n")
        self.assert_report_fails("reports/junit.xml records no test")

    def test_missing_test_report_fails(self):
        (self.root / "reports/junit.xml").unlink()
        self.assert_report_fails("missing report reports/junit.xml")

    def test_test_report_that_is_not_xml_fails(self):
        repo_fixture.write_text(self.root, "reports/junit.xml", "3 passed\n")
        self.assert_report_fails("reports/junit.xml is not XML")

    def test_coverage_below_the_floor_fails(self):
        self.coverage(COBERTURA.format(rate="0.7", valid="100", covered="70"))
        self.assert_report_fails("COVERAGE_BELOW_FLOOR: 70.00 is below the floor 85")

    def test_coverage_at_the_floor_passes(self):
        self.coverage(COBERTURA.format(rate="0.85", valid="100", covered="85"))
        self.assertTrue(self.check().is_clean())

    def test_coverage_is_not_rounded_up(self):
        self.coverage(COBERTURA.format(rate="0.84999", valid="100000", covered="84999"))
        self.assert_report_fails("COVERAGE_BELOW_FLOOR: 84.99 is below the floor 85")

    def test_cobertura_report_with_a_line_rate_only(self):
        self.coverage('<coverage line-rate="0.91"></coverage>\n')
        self.assertIn("line_percentage 91.00 (floor 85)", self.check().passed)

    def test_jacoco_report(self):
        self.coverage(
            '<report name="x"><counter type="BRANCH" missed="9" covered="1"/>'
            '<counter type="LINE" missed="10" covered="90"/></report>\n'
        )
        self.assertIn("line_percentage 90.00 (floor 85)", self.check().passed)

    def test_lcov_report(self):
        self.coverage("SF:a\nLF:60\nLH:57\nend_of_record\nSF:b\nLF:40\nLH:38\nend_of_record\n")
        self.assertIn("line_percentage 95.00 (floor 85)", self.check().passed)

    def test_coverage_report_in_another_format_fails(self):
        self.coverage("total coverage: 99%\n")
        self.assert_report_fails("is not a Cobertura, JaCoCo, or LCOV report with line counts")

    def test_missing_coverage_report_fails(self):
        (self.root / "reports/coverage.xml").unlink()
        self.assert_report_fails("missing coverage report reports/coverage.xml")

    def test_floor_comes_from_the_project_file(self):
        self.edit(lambda project: project["policy"].update(coverage_floor_percent=95))
        self.assert_report_fails("COVERAGE_BELOW_FLOOR: 92.50 is below the floor 95")

    def test_command_line_exit_code(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gatecheck.main([str(self.root), "--evidence"]), 0)
            self.junit('<skipped message="later"/>')
            self.assertEqual(gatecheck.main([str(self.root), "--evidence"]), 1)


class ReportConfigTest(repo_fixture.AdoptedRepoCase):
    def test_no_report_in_the_project_file_fails(self):
        report = gatecheck.check_reports(self.root)
        self.assertTrue(any("ci.evidence names no report" in line for line in report.failures))

    def test_one_report_without_the_other_fails(self):
        self.edit(lambda project: project["ci"]["evidence"].update(test_report="reports/junit.xml"))
        self.assert_fails_with("ci.evidence must name the test report and the coverage report")

    def test_template_must_not_set_a_report(self):
        source = repo_fixture.read_json(repo_fixture.SOURCE_ROOT, self.CONFIG)

        def template_with_reports(project):
            project["project"].update(source["project"])
            project["ci"]["evidence"] = {"test_report": "a.xml", "coverage_report": "b.xml"}

        self.edit(template_with_reports)
        self.assert_fails_with("ci.evidence is set but the project identity is a placeholder")


if __name__ == "__main__":
    unittest.main()
