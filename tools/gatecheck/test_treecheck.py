# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""Tests for the checks on the repository tree.

Run: python3 -m unittest discover -s tools/gatecheck -v
"""

import unittest

import gatecheck
import repo_fixture

HEADER = repo_fixture.hash_header()
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


FORM = ".github/ISSUE_TEMPLATE/work-packet.yml"
FORM_TEXT = (
    HEADER
    + "name: Work packet\nbody:\n"
    + "  - type: dropdown\n    id: layer\n    attributes:\n      label: Layer\n      options:\n"
    + "{options}"
    + "    validations:\n      required: true\n"
    + "  - type: dropdown\n    id: lane\n    attributes:\n      options:\n        - cloud\n"
)


class IssueFormTest(repo_fixture.RepoCopyCase):
    def form(self, layers: list) -> None:
        options = "".join(f"        - {name}\n" for name in layers)
        repo_fixture.write_text(self.root, FORM, FORM_TEXT.format(options=options))

    def test_form_with_the_project_layers_passes(self):
        self.form(["domain", "application", "presentation", "infrastructure"])
        self.assert_clean()
        self.assertIn(
            "the work packet form lists the layers of the project file",
            gatecheck.run(self.root).passed,
        )

    def test_form_with_an_old_layer_list_fails(self):
        self.form(["domain", "application", "presentation"])
        self.assert_fails_with("the layer options ['application', 'domain', 'presentation'] are not the layers")

    def test_form_without_a_layer_field_fails(self):
        repo_fixture.write_text(self.root, FORM, HEADER + "name: Work packet\nbody: []\n")
        self.assert_fails_with("has no field with the id layer")

    def test_form_of_this_repository_has_a_layer_field(self):
        text = (repo_fixture.SOURCE_ROOT / FORM).read_text(encoding="utf-8")
        self.assertIn("    id: layer\n", text)


MARKDOWN_HEADER = repo_fixture.markdown_header()
CONSTRUCT = {
    "id": "NO_WAIT_CALL",
    "pattern": r"\bwait\(",
    "paths": ["src/domain/", "src/application/"],
    "extensions": [".md"],
    "reason": "A wait call in a rule makes a test slow.",
}


class ForbiddenConstructTest(repo_fixture.AdoptedRepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.edit(lambda project: project["policy"]["forbidden_constructs"].append(dict(CONSTRUCT)))

    def note(self, relative: str, body: str) -> None:
        repo_fixture.write_text(self.root, relative, MARKDOWN_HEADER + body)

    def test_tree_without_the_construct_passes(self):
        self.note("src/domain/notes.md", "The rule does not stop.\n")
        self.assert_clean()

    def test_construct_in_a_listed_path_fails(self):
        self.note("src/domain/notes.md", "first line\nresult = wait(5)\n")
        self.assert_fails_with(
            "src/domain/notes.md:7: forbidden construct NO_WAIT_CALL. A wait call in a rule makes a test slow."
        )

    def test_construct_outside_the_listed_paths_passes(self):
        self.note("src/infrastructure/notes.md", "result = wait(5)\n")
        self.assert_clean()

    def test_construct_in_another_file_type_passes(self):
        self.edit(
            lambda project: project["architecture"]["import_rules"]["non_source_extensions"].append(".txt")
        )
        repo_fixture.write_text(self.root, "src/domain/notes.txt", "result = wait(5)\n")
        self.assert_clean()

    def test_construct_ids_must_be_unique(self):
        self.edit(lambda project: project["policy"]["forbidden_constructs"].append(dict(CONSTRUCT)))
        self.assert_fails_with("policy.forbidden_constructs has the id NO_WAIT_CALL twice")

    def test_construct_pattern_must_compile(self):
        self.edit(lambda project: project["policy"]["forbidden_constructs"][0].update(pattern="("))
        self.assert_fails_with("policy.forbidden_constructs.NO_WAIT_CALL: '(' is not a regular expression")

    def test_construct_needs_a_reason(self):
        self.edit(lambda project: project["policy"]["forbidden_constructs"][0].pop("reason"))
        self.assert_fails_with("missing required property reason")


class TemplateNeutralTest(repo_fixture.RepoCopyCase):
    def test_template_must_not_set_a_forbidden_construct(self):
        repo_fixture.edit_json(
            self.root,
            ".governance/project.json",
            lambda project: project["policy"]["forbidden_constructs"].append(dict(CONSTRUCT)),
        )
        self.assert_fails_with("policy.forbidden_constructs is set but the project identity is a placeholder")

    def test_template_workflow_must_not_name_a_build_tool(self):
        self._add_tool_step()
        self.assert_fails_with(".github/workflows/ci.yml contains non-neutral text")

    def test_governance_page_must_not_name_a_build_tool(self):
        path = self.root / "docs/governance/README.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nRun " + "car" + "go test.\n", encoding="utf-8")
        self.assert_fails_with("docs/governance/README.md contains non-neutral text")

    def _add_tool_step(self) -> None:
        path = self.root / CI
        step = "\n      - name: product\n        run: " + "car" + "go --version\n"
        path.write_text(path.read_text(encoding="utf-8") + step, encoding="utf-8")


class ProjectWorkflowTest(repo_fixture.AdoptedRepoCase):
    def test_project_workflow_can_name_its_build_tool(self):
        path = self.root / CI
        step = "\n      - name: product\n        run: " + "car" + "go --version\n"
        path.write_text(path.read_text(encoding="utf-8") + step, encoding="utf-8")
        self.assert_clean()


class SecretTest(repo_fixture.RepoCopyCase):
    def test_environment_file_fails(self):
        repo_fixture.write_text(self.root, ".env", "TOKEN=value\n")
        self.assert_fails_with(".env: an environment file must not be in the repository")

    def test_environment_file_in_a_directory_fails(self):
        repo_fixture.write_text(self.root, "src/.env.production", "TOKEN=value\n")
        self.assert_fails_with("src/.env.production: an environment file must not be in the repository")

    def test_example_environment_file_passes(self):
        repo_fixture.edit_json(
            self.root,
            ".governance/project.json",
            lambda project: project["scope"]["allowed_top_level"].append(".env.example"),
        )
        repo_fixture.write_text(self.root, ".env.example", "TOKEN=\n")
        self.assert_clean()

    def test_private_key_block_fails(self):
        self._leak("-" * 5 + "BEGIN OPENSSH PRIVATE KEY" + "-" * 5)
        self.assert_fails_with("docs/design/notes.txt:2: the text has the shape of a secret (private key)")

    def test_cloud_access_key_id_fails(self):
        self._leak("key = " + "AKIA" + "ABCDEFGHIJKLMNOP")
        self.assert_fails_with("the text has the shape of a secret (cloud access key id)")

    def test_host_access_token_fails(self):
        self._leak("token: " + "ghp_" + "a1B2" * 9)
        self.assert_fails_with("the text has the shape of a secret (host access token)")

    def test_host_fine_grained_token_fails(self):
        self._leak("github" + "_pat_" + "a1B2_" * 12)
        self.assert_fails_with("the text has the shape of a secret (host fine-grained token)")

    def test_chat_service_token_fails(self):
        self._leak("xox" + "b-" + "1234567890-abcdefghij")
        self.assert_fails_with("the text has the shape of a secret (chat service token)")

    def test_normal_text_passes(self):
        self._leak("The token is in the environment variable API_TOKEN.")
        self.assert_clean()

    def _leak(self, line: str) -> None:
        repo_fixture.write_text(self.root, "docs/design/notes.txt", "notes\n" + line + "\n")


if __name__ == "__main__":
    unittest.main()
