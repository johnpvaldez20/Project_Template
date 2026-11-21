# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Tests for the checks on the repository tree.

Run: python3 -m unittest discover -s tools/gatecheck -v
"""

import unittest

import repo_fixture

HEADER = "# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER\n# SPDX-License-Identifier: LicenseRef-UNSET\n\n"
CI = ".github/workflows/ci.yml"
RULESET = ".github/rulesets/main.json"
PINNED = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
OTHER_WORKFLOW = (
    HEADER
    + "name: other\n\non:\n  push:\n\n{permissions}"
    + "jobs:\n  other:\n    runs-on: ubuntu-24.04\n    steps:\n{steps}"
)


class WorkflowCase(repo_fixture.RepoCopyCase):
    def replace(self, old: str, new: str) -> None:
        text = (self.root / CI).read_text(encoding="utf-8")
        self.assertIn(old, text)
        repo_fixture.write_text(self.root, CI, text.replace(old, new))

    def other(self, steps: str, permissions: str = "permissions:\n  contents: read\n\n") -> None:
        repo_fixture.write_text(
            self.root,
            ".github/workflows/other.yml",
            OTHER_WORKFLOW.format(permissions=permissions, steps=steps),
        )


class CiWorkflowTest(WorkflowCase):
    def test_missing_workflow_fails(self):
        (self.root / CI).unlink()
        self.assert_fails_with("missing .github/workflows/ci.yml")

    def test_missing_command_fails(self):
        self.replace("run: python3 tools/gatecheck/gatecheck.py --pr", "run: true")
        self.assert_fails_with("workflow is missing command: python3 tools/gatecheck/gatecheck.py --pr")

    def test_command_in_a_comment_does_not_count(self):
        self.replace(
            "run: python3 tools/gatecheck/gatecheck.py --pr",
            "run: true # python3 tools/gatecheck/gatecheck.py --pr",
        )
        self.assert_fails_with("workflow is missing command: python3 tools/gatecheck/gatecheck.py --pr")

    def test_job_name_must_be_the_required_check(self):
        self.replace("    name: gate\n", "    name: build\n")
        self.assert_fails_with("workflow job name must be gate")

    def test_workflow_must_not_cancel_a_run(self):
        self.replace(
            "permissions:\n  contents: read\n",
            "permissions:\n  contents: read\n\nconcurrency:\n  group: ci\n  cancel-in-progress: true\n",
        )
        self.assert_fails_with("workflow must not cancel a run")

    def test_checkout_must_use_the_pull_request_head(self):
        self.replace("          ref: ${{ github.event.pull_request.head.sha || github.sha }}\n", "")
        self.assert_fails_with("workflow must check out github.event.pull_request.head.sha")

    def test_checkout_needs_the_full_history(self):
        self.replace("          fetch-depth: 0\n", "")
        self.assert_fails_with("workflow checkout needs fetch-depth: 0")

    def test_checkout_must_not_keep_the_token(self):
        self.replace("          persist-credentials: false\n", "")
        self.assert_fails_with("each actions/checkout step needs persist-credentials: false")

    def test_action_must_be_pinned_to_a_commit(self):
        self.replace(PINNED, "actions/checkout@v7")
        self.assert_fails_with(f"{CI}: action actions/checkout@v7 is not pinned to a full commit SHA")

    def test_short_commit_is_not_a_pin(self):
        self.replace(PINNED, "actions/checkout@3d3c42e")
        self.assert_fails_with("is not pinned to a full commit SHA")


class EachWorkflowTest(WorkflowCase):
    STEP = f"      - uses: {PINNED}\n        with:\n          persist-credentials: false\n"

    def test_second_workflow_that_follows_the_rules_passes(self):
        self.other(self.STEP)
        self.assert_clean()

    def test_second_workflow_needs_permissions(self):
        self.other(self.STEP, permissions="")
        self.assert_fails_with(".github/workflows/other.yml: the workflow needs a top-level permissions block")

    def test_write_all_is_not_least_privilege(self):
        self.other(self.STEP, permissions="permissions: write-all\n\n")
        self.assert_fails_with("permissions: write-all is not least privilege")

    def test_second_workflow_must_pin_each_action(self):
        self.other("      - uses: some-owner/some-action@main\n")
        self.assert_fails_with(
            ".github/workflows/other.yml: action some-owner/some-action@main is not pinned"
        )

    def test_container_action_needs_a_digest(self):
        self.other("      - uses: docker://example.invalid/tool:1.2\n")
        self.assert_fails_with("action docker://example.invalid/tool:1.2 is not pinned")

    def test_container_action_with_a_digest_passes(self):
        self.other(f"      - uses: docker://example.invalid/tool@sha256:{'a' * 64}\n")
        self.assert_clean()

    def test_local_action_passes(self):
        self.other("      - uses: ./.github/actions/local\n")
        self.assert_clean()

    def test_pull_request_target_fails(self):
        text = OTHER_WORKFLOW.format(permissions="permissions:\n  contents: read\n\n", steps=self.STEP)
        text = text.replace("on:\n  push:\n", "on:\n  pull_request_target:\n")
        repo_fixture.write_text(self.root, ".github/workflows/other.yml", text)
        self.assert_fails_with("pull_request_target gives a write token to untrusted code")

    def test_trigger_name_in_a_comment_passes(self):
        self.other(self.STEP + "      # Do not use pull_request_target here.\n")
        self.assert_clean()


class RulesetTest(repo_fixture.RepoCopyCase):
    def rule(self, name: str, change) -> None:
        def edit(ruleset):
            for rule in ruleset["rules"]:
                if rule["type"] == name:
                    change(rule["parameters"])

        repo_fixture.edit_json(self.root, RULESET, edit)

    def test_missing_ruleset_fails(self):
        (self.root / RULESET).unlink()
        self.assert_fails_with("missing .github/rulesets/main.json")

    def test_squash_is_the_only_merge_method(self):
        self.rule("pull_request", lambda rule: rule["allowed_merge_methods"].append("merge"))
        self.assert_fails_with("pull_request.allowed_merge_methods must be squash only")

    def test_one_approval_is_the_minimum(self):
        self.rule("pull_request", lambda rule: rule.update(required_approving_review_count=0))
        self.assert_fails_with("pull_request.required_approving_review_count must be 1 or more")

    def test_code_owner_review_is_required(self):
        self.rule("pull_request", lambda rule: rule.update(require_code_owner_review=False))
        self.assert_fails_with("pull_request.require_code_owner_review must be true")

    def test_last_push_needs_another_approver(self):
        self.rule("pull_request", lambda rule: rule.update(require_last_push_approval=False))
        self.assert_fails_with("pull_request.require_last_push_approval must be true")

    def test_status_check_must_be_the_ci_job(self):
        self.rule(
            "required_status_checks",
            lambda rule: rule["required_status_checks"][0].update(context="build"),
        )
        self.assert_fails_with("required_status_checks must contain the context gate")

    def test_status_check_must_name_its_source(self):
        self.rule(
            "required_status_checks",
            lambda rule: rule["required_status_checks"][0].pop("integration_id"),
        )
        self.assert_fails_with("the context gate needs an integration_id")

    def test_branch_must_be_up_to_date(self):
        self.rule(
            "required_status_checks",
            lambda rule: rule.update(strict_required_status_checks_policy=False),
        )
        self.assert_fails_with("required_status_checks must require an up-to-date branch")

    def test_each_branch_rule_is_required(self):
        repo_fixture.edit_json(
            self.root,
            RULESET,
            lambda ruleset: ruleset.update(
                rules=[rule for rule in ruleset["rules"] if rule["type"] != "non_fast_forward"]
            ),
        )
        self.assert_fails_with("rule non_fast_forward is missing")

    def test_ruleset_must_be_active(self):
        repo_fixture.edit_json(self.root, RULESET, lambda ruleset: ruleset.update(enforcement="disabled"))
        self.assert_fails_with("enforcement must be active")

    def test_bypass_must_go_through_a_pull_request(self):
        actor = {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}
        repo_fixture.edit_json(
            self.root, RULESET, lambda ruleset: ruleset.update(bypass_actors=[actor])
        )
        self.assert_fails_with("a bypass actor must have bypass_mode pull_request")

    def test_bypass_through_a_pull_request_passes(self):
        actor = {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}
        repo_fixture.edit_json(
            self.root, RULESET, lambda ruleset: ruleset.update(bypass_actors=[actor])
        )
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
