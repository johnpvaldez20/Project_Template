# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Tests for the payload rules.

Each test changes one fact in a valid example. The checker must reject it.
Run: python3 -m unittest discover -s tools/gatecheck -v
"""

import copy
import unittest

import payloadrules
import repo_fixture

OWNER = {
    "agent_id": "owner-example",
    "role": "OWNER",
    "runtime": "LOCAL",
    "host": {"kind": "OWNER_MACHINE", "name": "owner-host"},
    "model": {"provider": "HUMAN", "name": "owner"},
}


class ValidExampleTest(repo_fixture.ExampleCase):
    def test_each_valid_example_has_no_error(self):
        for name in (
            "gate1-pass",
            "gate1-reject-prose-plan",
            "gate2-pass",
            "gate2-reject-stale-base",
            "gate3-merge-approved",
            "gate3-reject-ci-missing",
            "gate3-reject-test-sabotage",
        ):
            self.assertEqual(self.errors(self.example(name)), [], name)

    def test_example_packet_has_no_error(self):
        self.assertEqual(self.errors(self.packet(), live=True), [])


class SignerTest(repo_fixture.ExampleCase):
    """A worker does not sign its own gate. A worker does not merge."""

    def test_gate1_needs_a_gatekeeper_or_owner_author(self):
        payload = self.example("gate1-pass")
        payload["provenance"]["author"]["role"] = "PLANNER"
        self.assert_rejected(payload, "$/provenance/author/role: value is not in enum")

    def test_gate2_needs_a_gatekeeper_or_owner_author(self):
        payload = self.example("gate2-pass")
        payload["provenance"]["author"]["role"] = "CODER"
        self.assert_rejected(payload, "$/provenance/author/role: value is not in enum")

    def test_gate3_needs_a_gatekeeper_or_owner_author(self):
        payload = self.example("gate3-merge-approved")
        payload["provenance"]["author"]["role"] = "QA"
        self.assert_rejected(payload, "$/provenance/author/role: value is not in enum")

    def test_worker_that_writes_a_verdict_gets_a_clear_message(self):
        payload = self.example("gate1-pass")
        payload["provenance"]["author"] = copy.deepcopy(payload["provenance"]["worker"])
        self.assert_rejected(payload, "Ask the gatekeeper for the verdict.")
        self.assert_rejected(payload, "author is the worker")

    def test_coder_cannot_approve_its_own_gate3(self):
        payload = self.example("gate3-merge-approved")
        payload["provenance"]["worker"]["role"] = "CODER"
        payload["provenance"]["author"] = copy.deepcopy(payload["provenance"]["worker"])
        self.assert_rejected(payload, "author is the worker")
        self.assert_rejected(payload, "$/provenance/author/role: value is not in enum")

    def test_author_cannot_be_the_worker_on_gate1(self):
        payload = self.example("gate1-pass")
        payload["provenance"]["worker"]["agent_id"] = payload["provenance"]["author"]["agent_id"]
        self.assert_rejected(payload, "author is the worker")

    def test_author_cannot_be_the_worker_on_gate2(self):
        payload = self.example("gate2-pass")
        payload["provenance"]["worker"]["agent_id"] = payload["provenance"]["author"]["agent_id"]
        self.assert_rejected(payload, "author is the worker")

    def test_packet_author_can_be_its_worker(self):
        packet = self.packet()
        self.assertEqual(
            packet["provenance"]["author"]["agent_id"], packet["provenance"]["worker"]["agent_id"]
        )
        self.assertEqual(self.errors(packet, live=True), [])

    def test_owner_can_sign_a_verdict(self):
        payload = self.example("gate2-pass")
        payload["provenance"]["author"] = copy.deepcopy(OWNER)
        self.assertEqual(self.errors(payload), [])

    def test_merger_cannot_be_the_worker(self):
        payload = self.example("gate3-merge-approved")
        payload["provenance"]["worker"]["agent_id"] = "owner-example"
        payload["merge"]["merged_by"] = copy.deepcopy(OWNER)
        self.assert_rejected(payload, "merged_by is the worker")

    def test_merger_with_gatekeeper_role_needs_a_gatekeeper_id(self):
        payload = self.example("gate3-merge-approved")
        payload["merge"]["merged_by"]["agent_id"] = "cursor-cloud-coder-01"
        self.assert_rejected(payload, "merged_by gatekeeper agent_id does not match")

    def test_owner_role_needs_an_owner_id(self):
        payload = self.example("gate2-pass")
        payload["provenance"]["author"] = copy.deepcopy(OWNER)
        payload["provenance"]["author"]["agent_id"] = "cursor-cloud-coder-02"
        self.assert_rejected(payload, "author owner agent_id does not match owner.agent_id_pattern")

    def test_local_run_agent_is_checked(self):
        payload = self.example("gate3-merge-approved")
        agent = copy.deepcopy(payload["provenance"]["worker"])
        agent["host"]["kind"] = "OWNER_MACHINE"
        payload["local_runs"] = [
            {
                "agent": agent,
                "command": "python3 -m unittest discover -s tools/gatecheck -v",
                "exit_code": 0,
                "advisory": True,
            }
        ]
        self.assert_rejected(payload, "local_runs[0] agent host kind OWNER_MACHINE does not match")


class ModelSettingsTest(repo_fixture.ExampleCase):
    def test_current_reasoning_effort_names_are_valid(self):
        for effort in ("none", "minimal", "low", "medium", "high", "xhigh", "max"):
            payload = self.example("gate2-pass")
            payload["provenance"]["worker"]["model"]["settings"]["reasoning_effort"] = effort
            self.assertEqual(self.errors(payload), [], effort)

    def test_unknown_reasoning_effort_is_rejected(self):
        payload = self.example("gate2-pass")
        payload["provenance"]["worker"]["model"]["settings"]["reasoning_effort"] = "extreme"
        self.assert_rejected(payload, "reasoning_effort: value is not in enum")


class ScopePathTest(repo_fixture.ExampleCase):
    def test_path_is_normal(self):
        for path in ("src/domain/item.md", "src/domain/", "README.md", ".github/workflows/ci.yml"):
            self.assertTrue(payloadrules.path_is_normal(path), path)
        for path in ("src/../x", "./src", "src//x", "/src", "..", "", "/", "src/./x"):
            self.assertFalse(payloadrules.path_is_normal(path), path)

    def test_dot_segments_cannot_hide_a_protected_path(self):
        packet = self.packet()
        packet["subsystem_scope"]["allowed_files"] = ["src/domain/../../.github/workflows/ci.yml"]
        self.assert_rejected(packet, "is not a normal repository path", live=True)

    def test_definition_path_must_be_normal(self):
        packet = self.packet()
        packet["data_contracts"]["definitions"][0]["path"] = "src/domain/../item.md"
        self.assert_rejected(packet, "definition path src/domain/../item.md", live=True)

    def test_worker_packet_cannot_list_the_checker(self):
        packet = self.packet()
        packet["subsystem_scope"]["allowed_files"] = ["tools/gatecheck/gatecheck.py"]
        self.assert_rejected(packet, "requires gatekeeper_packet true", live=True)

    def test_gatekeeper_packet_can_list_the_checker(self):
        packet = self.packet()
        packet["subsystem_scope"]["allowed_files"] = ["tools/gatecheck/gatecheck.py"]
        packet["gatekeeper_packet"] = True
        self.assertEqual(self.errors(packet, live=True), [])


class Gate2DiffTest(repo_fixture.ExampleCase):
    def test_protected_file_needs_the_flag(self):
        payload = self.example("gate2-pass")
        payload["diff_hygiene"]["files_modified"].append("tools/gatecheck/gatecheck.py")
        self.assert_rejected(payload, "names the protected path tools/gatecheck/gatecheck.py")

    def test_protected_flag_needs_a_gatekeeper_or_owner_worker(self):
        payload = self.example("gate2-pass")
        payload["diff_hygiene"]["files_modified"].append(".github/workflows/ci.yml")
        payload["diff_hygiene"]["touches_protected_paths"] = True
        self.assert_rejected(payload, "$/allOf2/provenance/worker/role: value is not in enum")

    def test_out_of_scope_file_must_be_a_modified_file(self):
        payload = self.example("gate2-reject-stale-base")
        payload["diff_hygiene"]["out_of_scope_files"] = ["src/other.md"]
        self.assert_rejected(payload, "out_of_scope_files names src/other.md")

    def test_diff_path_must_be_normal(self):
        payload = self.example("gate2-pass")
        payload["diff_hygiene"]["files_modified"] = ["docs/../.github/workflows/ci.yml"]
        self.assert_rejected(payload, "diff path docs/../.github/workflows/ci.yml")

    def test_complexity_limit_comes_from_the_project_file(self):
        payload = self.example("gate2-pass")
        limit = self.project["policy"]["max_cyclomatic_complexity"]
        payload["taste_metrics"]["max_cyclomatic_complexity"] = limit
        self.assertEqual(self.errors(payload), [])
        payload["taste_metrics"]["max_cyclomatic_complexity"] = limit + 1
        self.assert_rejected(payload, "is above the configured limit")


class Gate3EvidenceTest(repo_fixture.ExampleCase):
    def test_approval_must_record_each_test_counter(self):
        for counter in payloadrules.TEST_COUNTERS:
            payload = self.example("gate3-merge-approved")
            del payload["ci_evidence"]["checks"]["test"][counter]
            self.assert_rejected(payload, f"test must record {counter}")

    def test_approval_rejects_an_ignored_test(self):
        payload = self.example("gate3-merge-approved")
        payload["ci_evidence"]["checks"]["test"]["ignored_tests"] = 1
        self.assert_rejected(payload, "test ignored_tests is not 0")

    def test_approval_rejects_a_failed_test(self):
        payload = self.example("gate3-merge-approved")
        payload["ci_evidence"]["checks"]["test"]["failed_tests"] = 1
        self.assert_rejected(payload, "test failed_tests is not 0")

    def test_approval_needs_one_test(self):
        payload = self.example("gate3-merge-approved")
        payload["ci_evidence"]["checks"]["test"]["total_tests"] = 0
        self.assert_rejected(payload, "test total_tests is below 1")

    def test_red_run_and_green_run_are_two_commits(self):
        payload = self.example("gate3-merge-approved")
        runs = payload["test_integrity_audit"]["regression_test"]
        runs["red_run"]["head_sha"] = runs["green_run"]["head_sha"]
        self.assert_rejected(payload, "red_run and green_run name the same commit")

    def test_red_run_and_green_run_are_two_runs(self):
        payload = self.example("gate3-merge-approved")
        runs = payload["test_integrity_audit"]["regression_test"]
        runs["red_run"]["run_url"] = runs["green_run"]["run_url"]
        self.assert_rejected(payload, "red_run and green_run name the same CI run")

    def test_run_url_must_end_with_the_run_id(self):
        payload = self.example("gate3-merge-approved")
        payload["ci_evidence"]["run_id"] = 7
        self.assert_rejected(payload, "ci_evidence.run_url does not end with ci_evidence.run_id")

    def test_coverage_below_the_floor_needs_a_waiver(self):
        payload = self.example("gate3-merge-approved")
        payload["coverage"]["line_percentage"] = 0
        self.assert_rejected(payload, "coverage 0 is below the configured floor")
        payload["coverage"]["waiver"] = {
            "granted": True,
            "reason": "The owner accepts this result for one packet only.",
        }
        self.assertEqual(self.errors(payload), [])

    def test_ci_head_must_be_the_pull_request_head(self):
        payload = self.example("gate3-merge-approved")
        payload["ci_evidence"]["head_sha"] = "b" * 40
        self.assert_rejected(payload, "does not match github.head_sha")

    def test_short_sha_is_rejected(self):
        payload = self.example("gate3-merge-approved")
        payload["github"]["head_sha"] = "5e6d7c8"
        self.assert_rejected(payload, "$/github/head_sha: does not match pattern")


if __name__ == "__main__":
    unittest.main()
