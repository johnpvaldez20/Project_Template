<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Owner setup on the host

Files in the repository do not change the host settings.
Only the owner can change them.
Until the owner does these steps, Law 9 is discipline only.
Do each section one time for each repository.

Each section gives the steps in the web page of the host.
Some sections also give the same change as a command.
Replace `OWNER/REPO` with `project.repository`.

## 1. Choose the accounts

The host does not let the author of a pull request approve it.
The host can also refuse an approval from the account that made the last push.
These two rules are how the host keeps the worker apart from the gatekeeper.

Make this decision first.

| Choice | Result |
|---|---|
| Two accounts. The workers push and open pull requests with one account. The gatekeeper reviews and merges with the owner account. | The host enforces Gate 3. Use the ruleset file as it is. |
| One account. That account does the work, the review, and the merge. | The account cannot approve its own pull request. The ruleset blocks each merge. Add the bypass in section 4. The host then does not enforce Gate 3. |

The second account can be a machine user or an application.
Give it write access only. Do not make it an administrator.
Do not put it in `CODEOWNERS`.

## 2. Set the merge method

1. Open **Settings**, then **General**, then **Pull Requests**.
2. Clear **Allow merge commits**.
3. Clear **Allow rebase merging**.
4. Keep **Allow squash merging**. Set its default message to **Pull request title**.
5. Set **Automatically delete head branches**.
6. Clear **Allow auto-merge**.

```text
gh repo edit OWNER/REPO --enable-merge-commit=false --enable-rebase-merge=false --enable-squash-merge --delete-branch-on-merge --enable-auto-merge=false
gh api --method PATCH repos/OWNER/REPO -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=BLANK
```

The title of a packet pull request starts with the packet id.
The squash commit on `main` then contains the packet id.

## 3. Import the ruleset

The ruleset file is `.github/rulesets/main.json`.

1. Open **Settings**, then **Rules**, then **Rulesets**.
2. Select **New ruleset**, then **Import a ruleset**.
3. Select `.github/rulesets/main.json` from a local copy of the repository.
4. Make sure that the status check is `gate` and its source is **GitHub Actions**.
5. Select **Create**.

```text
gh api --method POST repos/OWNER/REPO/rulesets --input .github/rulesets/main.json
```

A public repository can use a ruleset on each plan.
A private repository needs a paid plan for a ruleset.
If the plan cannot enforce the ruleset, write that in each Gate 3 verdict.

Make sure that the ruleset is active:

```text
gh api repos/OWNER/REPO/rules/branches/main
```

The answer must list `pull_request`, `required_status_checks`, `non_fast_forward`, `deletion`, and `required_linear_history`.

## 4. Add a bypass only when one account does all the jobs

Do this section only for the second choice in section 1.

1. Open the ruleset.
2. In **Bypass list**, add **Repository admin**.
3. Set the bypass to **Allow for pull requests only**.
4. Write the same change in `.github/rulesets/main.json`:

```json
"bypass_actors": [
  { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request" }
]
```

The owner can then merge a pull request that has no approval.
The host shows the bypass on the pull request.
A direct push to `main` stays blocked.
The gate checker does not accept the bypass mode `always`.

## 5. Create the labels

The issue form sets the label `gate-1:pending`.
The host drops a label that does not exist.

```text
for label in gate-1:pending gate-1:pass gate-1:reject gate-2:pass gate-2:reject gate-2:stale gate-3:merge-approved gate-3:reject gate-3:sabotage lane:local lane:cloud reverted; do
  gh label create "$label" --repo OWNER/REPO --force
done
```

## 6. Limit the workflows

1. Open **Settings**, then **Actions**, then **General**.
2. Under **Actions permissions**, select **Allow OWNER, and select non-OWNER, actions and reusable workflows**.
3. Set **Allow actions created by GitHub**.
4. Set **Require actions to be pinned to a full-length commit SHA**.
5. Under **Approval for running fork pull request workflows**, select the option for all external contributors.
6. Under **Workflow permissions**, select **Read repository contents and packages permissions**.
7. Clear **Allow GitHub Actions to create and approve pull requests**.
8. Select **Save** in each part.

A workflow must not approve a pull request. Step 7 makes that sure.
Add an action from another owner to the allowed list before a workflow uses it.

## 7. Turn on the security features

1. Open **Settings**, then the security settings page. Its name is **Advanced Security**.
2. Turn on **Secret Protection**. Turn on **Push protection**.
3. Turn on **Dependabot alerts**.
4. Turn on **Private vulnerability reporting** for a public repository.

The gate checker finds only a small set of secret shapes.
Push protection on the host finds more. Use the two together.

`.github/dependabot.yml` asks for a pull request when a pinned action has a new release.
That pull request changes a protected path. The owner reviews it.
Remove the file if you do not want those pull requests.

## 8. Make the template a template

Do this section only in the template repository.

1. Open **Settings**, then **General**.
2. Set **Template repository**.

```text
gh repo edit OWNER/REPO --template
```

A new project then starts with **Use this template**.
The new repository has the files and no history.

## 9. Choose the license

The template does not choose a license.
`LicenseRef-UNSET` grants no rights.
The steps are in `ADOPTING.md`.

## 10. Record the result

Write in `docs/design/decisions.md` which sections are done.
Write there which account is the worker and which account is the gatekeeper.
A gatekeeper reads that page before it writes a Gate 3 verdict.
