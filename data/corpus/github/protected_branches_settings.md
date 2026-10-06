---
doc_id: github/protected_branches_settings
title: "About protected branches (other settings: signed commits, linear history, merge queue, lock, bypass, push restrictions, force pushes, deletions)"
source_url: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-conversation-resolution-before-merging
retrieved: 2026-10-05
subdomain: branch_protection
---

## About branch protection settings (continued)

### Require conversation resolution before merging

Requires all comments on the pull request to be resolved before it can be merged to a protected branch. This ensures that all comments are addressed or acknowledged before merge.

### Require signed commits

When you enable required commit signing on a branch, contributors and bots can only push commits that have been signed and verified to the branch. For more information, see [related GitHub Docs article](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification).

> [!NOTE]

> * If you have enabled vigilant mode, which indicates that your commits will always be signed, any commits that GitHub identifies as "Partially verified" are permitted on branches that require signed commits. For more information about vigilant mode, see [related GitHub Docs article](https://docs.github.com/en/authentication/managing-commit-signature-verification/displaying-verification-statuses-for-all-of-your-commits).
> * If a collaborator pushes an unsigned commit to a branch that requires commit signatures, the collaborator will need to rebase the commit to include a verified signature, then force push the rewritten commit to the branch.

You can push local commits to the branch if the commits are signed and verified.

You can also merge signed and verified commits into the branch using a pull request. When GitHub evaluates whether a pull request can be merged, it creates a test merge commit whose parents are the latest commit on the base branch and the pull request's head commit. GitHub checks the commits introduced by this test merge, including commits from the head branch. As a result, unsigned commits on the head branch can block a squash merge, even though GitHub would sign the final squash commit. This restriction can also apply to the author of the pull request.

To merge a blocked pull request, rewrite and sign the unsigned commits on the head branch, or ask someone with permission to bypass the applicable protections to merge the pull request.

You can squash and merge pull requests locally, but you must sign the resulting commit before pushing it to the branch. If another protection requires changes to be made through a pull request, you may also need bypass permissions to push the locally merged commit. See [related GitHub Docs article](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/checking-out-pull-requests-locally) and [related GitHub Docs article](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits).

 For more information about merge methods, see [related GitHub Docs article](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/about-merge-methods-on-github).

### Require linear history

Enforcing a linear commit history prevents collaborators from pushing merge commits to the branch. This means that any pull requests merged into the protected branch must use a squash merge or a rebase merge. A strictly linear commit history can help teams revert changes more easily. For more information about merge methods, see [related GitHub Docs article](https://docs.github.com/en/pull-requests/reference/pull-request-merges).

Before you can require a linear commit history, your repository must allow squash merging or rebase merging. For more information, see [related GitHub Docs article](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges).

### Require merge queue

A merge queue helps increase velocity by automating pull request merges into a busy branch and ensuring the branch is never broken by incompatible changes.

The merge queue provides the same benefits as the **Require branches to be up to date before merging** branch protection, but does not require a pull request author to update their pull request branch and wait for status checks to finish before trying to merge.

Using a merge queue is particularly useful on branches that have a relatively high number of pull requests merging each day from many different users.

Once a pull request has passed all required branch protection checks, a user with write access to the repository can add the pull request to the queue. The merge queue will ensure the pull request's changes pass all required status checks when applied to the latest version of the target branch and any pull requests already in the queue.

A merge queue may use GitHub Actions or your own CI provider to run required checks on pull requests in a merge queue. For more information, see [related GitHub Docs article](https://docs.github.com/en/actions).

GitHub merges the pull request according to the merge strategy configured in the branch protection once all required CI checks pass.
For more information about merge queues, see [related GitHub Docs article](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue).

### Require deployments to succeed before merging

You can require that changes are successfully deployed to specific environments before a branch can be merged. For example, you can use this rule to ensure that changes are successfully deployed to a staging environment before the changes merge to your default branch.

### Lock branch

Locking a branch will make the branch read-only and ensures that no commits can be made to the branch. Locked branches can also not be deleted.

By default, a forked repository does not support syncing from its upstream repository. You can enable **Allow fork syncing** to pull changes from the upstream repository while preventing other contributions to the fork's branch.

### Do not allow bypassing the above settings

By default, the restrictions of a branch protection rule do not apply to people with admin permissions to the repository or custom roles with the "bypass branch protections" permission in a repository.

You can enable this setting to apply the restrictions to admins and roles with the "bypass branch protections" permission, too. For more information, see [related GitHub Docs article](https://docs.github.com/en/enterprise-cloud@latest/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/managing-custom-repository-roles-for-an-organization).

### Restrict who can push to matching branches

You can enable branch restrictions in public repositories owned by a GitHub Free organization and in all repositories owned by an organization using GitHub Team or GitHub Enterprise Cloud.

When you enable branch restrictions, only users, teams, or apps that have been given permission can push to the protected branch. You can view and edit the users, teams, or apps with push access to a protected branch in the protected branch's settings. When status checks are required, the people, teams, and apps that have permission to push to a protected branch will still be prevented from merging into the branch when the required checks fail. People, teams, and apps that have permission to push to a protected branch will still need to create a pull request when pull requests are required.

Optionally, you can apply the same restrictions to the creation of branches that match the rule. For example, if you create a rule that only allows a certain team to push to any branches that contain the word `release`, only members of that team would be able to create a new branch that contains the word `release`.

You can only give push access to a protected branch, or give permission to create a matching branch, to users, teams, or installed GitHub Apps with write access to a repository. People and apps with admin permissions to a repository are always able to push to a protected branch or create a matching branch.

### Allow force pushes

By default, GitHub blocks force pushes on all protected branches. When you enable force pushes to a protected branch, you can choose one of two groups who can force push:

1. Allow everyone with at least write permissions to the repository to force push to the branch, including those with admin permissions.
1. Allow only specific people or teams to force push to the branch.

If someone force pushes to a branch, the force push may mean commits that other collaborators based their work on are removed from the history of the branch. People may have merge conflicts or corrupted pull requests. Force pushing can also be used to delete branches or point a branch to commits that were not approved in a pull request.

Enabling force pushes will not override any other branch protection rules. For example, if a branch requires a linear commit history, you cannot force push merge commits to that branch.

### Allow deletions

By default, you cannot delete a protected branch. When you enable deletion of a protected branch, anyone with at least write permissions to the repository can delete the branch.

> [!NOTE]
> If the branch is locked, you cannot delete the branch even if you have permission to delete it.
