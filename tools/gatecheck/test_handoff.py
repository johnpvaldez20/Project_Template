# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Tests for payloads that a person gives to the checker by file.

Run: python3 -m unittest discover -s tools/gatecheck -v
"""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

import gatecheck
import handoff
import repo_fixture

PLAN_KEYS = (
    "title",
    "summary",
    "lane",
    "subsystem_scope",
    "data_contracts",
    "verification_plan",
    "abstraction_audit",
    "contract_notes",
    "use_cases",
    "layer",
    "state_machines",
    "architecture_change",
)
BRANCH = "pkt/PKT-0001-item-record"


class ReadPayloadTest(unittest.TestCase):
    def test_json_object(self):
        payloads, errors = handoff.read_payloads('\n {"gate": "PACKET"}\n')
        self.assertEqual((payloads, errors), ([{"gate": "PACKET"}], []))

    def test_fenced_blocks_in_a_comment(self):
        text = (
            "Verdict below.\n\n"
            "```json gate-payload\n{\"gate\": \"G1_PLANNING\"}\n```\n\n"
            "```json\n{\"not\": \"a payload\"}\n```\n\n"
            "```json gate-payload\n{\"gate\": \"G2_CODING\"}\n```\n"
        )
        payloads, errors = handoff.read_payloads(text)
        self.assertEqual([item["gate"] for item in payloads], ["G1_PLANNING", "G2_CODING"])
        self.assertEqual(errors, [])

    def test_windows_line_ends(self):
        text = "Text\r\n```json gate-payload\r\n{\"gate\": \"G3_QA_MERGE\"}\r\n```\r\n"
        payloads, errors = handoff.read_payloads(text)
        self.assertEqual((payloads, errors), ([{"gate": "G3_QA_MERGE"}], []))

    def test_text_without_a_payload(self):
        payloads, errors = handoff.read_payloads("A plan in prose.\n")
        self.assertEqual(payloads, [])
        self.assertIn("no json gate-payload block", errors[0])

    def test_block_that_is_not_json(self):
        payloads, errors = handoff.read_payloads("```json gate-payload\n{ nope\n```\n")
        self.assertEqual(payloads, [])
        self.assertIn("block 1 is not JSON", errors[0])

    def test_block_that_is_not_an_object(self):
        _payloads, errors = handoff.read_payloads("```json gate-payload\n[1]\n```\n")
        self.assertEqual(errors, ["block 1 is not a JSON object"])


class HandoffCase(repo_fixture.RepoCopyCase):
    """Real payloads for the example packet PKT-0001."""

    def setUp(self) -> None:
        super().setUp()
        _schemas, self.project = gatecheck.load_context(self.root)
        self.packet = repo_fixture.read_json(self.root, "docs/design/packets/PKT-0001.json")
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.box = Path(holder.name)
        self.count = 0

    def write(self, payload: dict) -> str:
        """Write one payload outside the repository copy. Return the file name."""
        self.count += 1
        path = self.box / f"payload-{self.count}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def real(self, name: str) -> dict:
        payload = repo_fixture.read_json(self.root, f"docs/governance/examples/valid/{name}.json")
        payload = gatecheck.expand_placeholders(payload, self.project)
        payload = gatecheck.materialize_payload(payload, self.project)
        payload["packet_id"] = "PKT-0001"
        payload["github"]["branch"] = BRANCH
        return payload

    def gate1(self) -> dict:
        payload = self.real("gate1-pass")
        for key in PLAN_KEYS:
            payload[key] = copy.deepcopy(self.packet[key])
        return payload

    def gate2(self) -> dict:
        payload = self.real("gate2-pass")
        payload["diff_hygiene"]["files_modified"] = ["src/domain/item.md"]
        payload["gate1_verdict_url"] = self.gate1()["handoff_artifact"]["url"]
        return payload

    def gate3(self) -> dict:
        payload = self.real("gate3-merge-approved")
        payload["gate2_verdict_url"] = self.gate2()["handoff_artifact"]["url"]
        payload["test_integrity_audit"]["regression_test"]["name"] = "item_id_present_after_save"
        return payload

    def check(self, *payloads: dict) -> gatecheck.Report:
        return gatecheck.check_payload_files(self.root, [self.write(item) for item in payloads])

    def assert_payload_fails(self, fragment: str, *payloads: dict) -> None:
        failures = self.check(*payloads).failures
        self.assertTrue(
            any(fragment in line for line in failures),
            f"no failure contains {fragment!r}: {failures}",
        )


class PayloadFileTest(HandoffCase):
    def test_three_gates_of_one_packet_agree(self):
        report = self.check(self.gate1(), self.gate2(), self.gate3())
        self.assertTrue(report.is_clean(), str(report))
        self.assertIn("the payloads of each packet agree", report.passed)

    def test_example_with_a_token_is_not_a_real_payload(self):
        report = gatecheck.check_payload_files(
            self.root, [str(self.root / "docs/governance/examples/valid/gate1-pass.json")]
        )
        self.assertTrue(any("unexpanded placeholder" in line for line in report.failures))

    def test_payload_in_a_comment_text(self):
        text = "Gate 1.\n\n```json gate-payload\n" + json.dumps(self.gate1(), indent=2) + "\n```\n"
        report = gatecheck.check_payload_files(self.root, ["-"], stdin_text=text)
        self.assertTrue(report.is_clean(), str(report))

    def test_file_that_does_not_exist(self):
        report = gatecheck.check_payload_files(self.root, [str(self.root / "missing.json")])
        self.assertTrue(any("cannot read the file" in line for line in report.failures))

    def test_command_line_exit_code(self):
        good = self.write(self.gate1())
        bad = self.write(dict(self.gate1(), verdict="MAYBE"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gatecheck.main([str(self.root), "--payload", good]), 0)
            self.assertEqual(gatecheck.main([str(self.root), "--payload", bad]), 1)

    def test_worker_cannot_sign_its_own_gate1(self):
        payload = self.gate1()
        payload["provenance"]["author"] = copy.deepcopy(payload["provenance"]["worker"])
        self.assert_payload_fails("$/provenance/author/role: value is not in enum", payload)
        self.assert_payload_fails("author is the worker", payload)


class PacketComparisonTest(HandoffCase):
    def test_gate1_scope_must_equal_the_packet_scope(self):
        payload = self.gate1()
        payload["subsystem_scope"]["allowed_files"].append("src/domain/extra.md")
        self.assert_payload_fails("Gate 1 allowed_files differs from the packet file", payload)

    def test_gate1_tests_must_equal_the_packet_tests(self):
        payload = self.gate1()
        payload["verification_plan"]["regression_tests"].append(
            {"name": "one_more_test", "kind": "UNIT", "asserts": "One more rule holds here."}
        )
        self.assert_payload_fails("Gate 1 regression test names differs from the packet file", payload)

    def test_gate1_pass_needs_a_ready_packet(self):
        def block(packet):
            packet["status"] = "BLOCKED"
            packet["blocked_on"] = ["OQ-1"]

        repo_fixture.edit_json(self.root, "docs/design/packets/PKT-0001.json", block)
        self.assert_payload_fails("Gate 1 PASS on a packet file that is not READY", self.gate1())

    def test_gate1_reject_is_not_compared(self):
        payload = self.gate1()
        payload["verdict"] = "REJECT"
        payload["rejection_reasons"] = ["The plan lists a file that the packet does not need."]
        payload["subsystem_scope"]["allowed_files"].append("src/domain/extra.md")
        report = self.check(payload)
        self.assertTrue(report.is_clean(), str(report))

    def test_gate1_without_a_packet_file_says_so(self):
        payload = self.gate1()
        payload["packet_id"] = "PKT-0099"
        payload["github"]["branch"] = "pkt/PKT-0099-item-record"
        report = self.check(payload)
        self.assertTrue(report.is_clean(), str(report))
        self.assertTrue(any("No packet file exists to compare" in line for line in report.passed))

    def test_gate2_needs_the_packet_file(self):
        payload = self.gate2()
        payload["packet_id"] = "PKT-0099"
        payload["github"]["branch"] = "pkt/PKT-0099-item-record"
        self.assert_payload_fails("no packet file for PKT-0099", payload)

    def test_gate2_file_outside_the_packet_scope(self):
        payload = self.gate2()
        payload["diff_hygiene"]["files_modified"].append("src/domain/other.md")
        self.assert_payload_fails(
            "src/domain/other.md is outside the packet allowed_files", payload
        )

    def test_gate2_reject_can_name_the_out_of_scope_file(self):
        payload = self.gate2()
        payload["diff_hygiene"]["files_modified"].append("src/domain/other.md")
        payload["diff_hygiene"]["out_of_scope_files"] = ["src/domain/other.md"]
        payload["verdict"] = "REJECT_AND_REVERT"
        payload["violations"] = ["SCOPE_VIOLATION"]
        payload["overseer_critique"] = "The diff has a file that the plan does not list. Remove it."
        report = self.check(payload)
        self.assertTrue(report.is_clean(), str(report))

    def test_gate3_cannot_drop_the_regression_test_that_the_packet_requires(self):
        payload = self.gate3()
        payload["test_integrity_audit"]["regression_test"] = {
            "required": False,
            "reproduces_failure_without_patch": False,
        }
        self.assert_payload_fails(
            "the packet requires a regression test but regression_test.required is not true", payload
        )

    def test_gate3_regression_test_must_be_in_the_plan(self):
        payload = self.gate3()
        payload["test_integrity_audit"]["regression_test"]["name"] = "some_other_test"
        self.assert_payload_fails(
            "regression test some_other_test is not in the packet verification plan", payload
        )


class ChainTest(HandoffCase):
    def test_gate3_head_must_be_the_gate2_head(self):
        gate3 = self.gate3()
        for holder in (
            gate3["github"],
            gate3["ci_evidence"],
            gate3["test_integrity_audit"]["regression_test"]["green_run"],
        ):
            holder["head_sha"] = "c" * 40
        self.assert_payload_fails("Gate 3 head_sha differs from Gate 2", self.gate2(), gate3)

    def test_coder_does_not_qa_its_packet(self):
        gate3 = self.gate3()
        gate3["provenance"]["worker"]["agent_id"] = self.gate2()["provenance"]["worker"]["agent_id"]
        self.assert_payload_fails("The coder does not QA that packet", self.gate2(), gate3)

    def test_gate3_must_cite_the_gate2_verdict(self):
        gate3 = self.gate3()
        gate3["gate2_verdict_url"] = gate3["gate2_verdict_url"] + "9"
        self.assert_payload_fails("Gate 3 gate2_verdict_url is not the Gate 2", self.gate2(), gate3)

    def test_gate2_must_cite_the_gate1_verdict(self):
        gate2 = self.gate2()
        gate2["gate1_verdict_url"] = gate2["gate1_verdict_url"] + "9"
        self.assert_payload_fails("Gate 2 gate1_verdict_url is not the Gate 1", self.gate1(), gate2)

    def test_gate2_pass_needs_a_gate1_pass(self):
        gate1 = self.gate1()
        gate1["verdict"] = "REJECT"
        gate1["rejection_reasons"] = ["The plan does not name the type of the record."]
        self.assert_payload_fails("Gate 2 PASS needs a Gate 1 PASS", gate1, self.gate2())

    def test_gate3_approval_needs_a_gate2_pass(self):
        gate2 = self.gate2()
        gate2["verdict"] = "REJECT_AND_REVERT"
        gate2["violations"] = ["NOISY_DIFF"]
        gate2["overseer_critique"] = "The diff changes the format of lines that the plan does not name."
        self.assert_payload_fails("Gate 3 MERGE_APPROVED needs a Gate 2 PASS", gate2, self.gate3())

    def test_one_payload_for_each_gate(self):
        self.assert_payload_fails("two G2_CODING payloads", self.gate2(), self.gate2())

    def test_one_branch_for_each_packet(self):
        gate3 = self.gate3()
        gate3["github"]["branch"] = "pkt/PKT-0001-other-branch"
        self.assert_payload_fails("the payloads name different branches", self.gate2(), gate3)


if __name__ == "__main__":
    unittest.main()
