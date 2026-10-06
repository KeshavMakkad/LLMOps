---
doc_id: github/personal_access_tokens
title: "Managing your personal access tokens"
source_url: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
retrieved: 2026-10-05
subdomain: account_security
---

> [!WARNING]
> Treat your access tokens like passwords. For more information, see [Keeping your personal access tokens secure](#keeping-your-personal-access-tokens-secure).

## About personal access tokens

Personal access tokens are an alternative to using passwords for authentication to GitHub when using the [GitHub API](https://docs.github.com/en/rest/authentication/authenticating-to-the-rest-api) or the [command line](#using-a-personal-access-token-on-the-command-line).

Personal access tokens are intended to access GitHub resources on behalf of yourself. To access resources on behalf of an organization, or for long-lived integrations, you should use a GitHub App. For more information, see [related GitHub Docs article](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/about-creating-github-apps).

A token has the same capabilities to access resources and perform actions on those resources that the owner of the token has, and is further limited by any scopes or permissions granted to the token. A token cannot grant additional access capabilities to a user. For example, a personal access token can be configured with an `admin:org` scope, but if the owner of the token is not an organization owner, the token will not give administrative access to the organization.

### Types of personal access tokens

GitHub currently supports two types of personal access tokens: fine-grained personal access tokens and personal access tokens (classic). GitHub recommends that you use fine-grained personal access tokens instead of personal access tokens (classic) whenever possible.

> [!NOTE]
> Fine-grained personal access tokens, while more secure and controllable, cannot accomplish every task that a personal access token (classic) can. See the section on [Fine-grained personal access tokens limitations](#fine-grained-personal-access-tokens-limitations) below to learn more.

Both fine-grained personal access tokens and personal access tokens (classic) are tied to the user who generated them and will become inactive if the user loses access to the resource.

Organization owners can set a policy to restrict the access of personal access tokens (classic) to their organization. For more information, see [related GitHub Docs article](https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/setting-a-personal-access-token-policy-for-your-organization#restricting-access-by-personal-access-tokens).

#### Fine-grained personal access tokens

Fine-grained personal access tokens have several security advantages over personal access tokens (classic), but also have limitations that may prevent you from using them in every scenario. These limits, and our plans to fix them, can be found in the [section below](#fine-grained-personal-access-tokens-limitations).

If you can use a fine-grained personal access token for your scenario, you'll benefit from these improvements:

* Each token is limited to access resources owned by a single user or organization.
* Each token can be further limited to only access specific repositories for that user or organization.
* Each token is granted specific, fine-grained permissions, which offer more control than the scopes granted to personal access tokens (classic).
* Organization owners can require approval for any fine-grained personal access tokens that can access resources in the organization.

##### Fine-grained personal access tokens limitations

Fine-grained personal access tokens do not support every feature of personal access tokens (classic). These feature gaps are not permanent - GitHub is working to close them. You can review [our public roadmap](https://github.com/github/roadmap) for more details on when these scenarios will be supported.

The major gaps in fine-grained personal access tokens are:

* Using fine-grained personal access token to contribute to public repos where the user is not a member.
* Using fine-grained personal access token to contribute to repositories where the user is an outside or repository collaborator.
* Using fine-grained personal access token to access multiple organizations at once.
* Using fine-grained personal access token to access Packages.
* Using fine-grained personal access token to call the Checks API.
* Using fine-grained personal access token to access Projects owned by a user account.

All of these gaps will be solved over time, as GitHub continues to invest in more secure access patterns.

#### Personal access tokens (classic)

Personal access tokens (classic) are less secure. However, some features currently will only work with personal access tokens (classic):

* Only personal access tokens (classic) have write access for public repositories that are not owned by you or an organization that you are not a member of.
* Outside collaborators can only use personal access tokens (classic) to access organization repositories that they are a collaborator on.
* A few REST API endpoints are only available with a personal access tokens (classic). To check whether an endpoint also supports fine-grained personal access tokens, see the documentation for that endpoint, or see [related GitHub Docs article](https://docs.github.com/en/rest/authentication/endpoints-available-for-fine-grained-personal-access-tokens).

If you choose to use a personal access token (classic), keep in mind that it will grant access to all repositories within the organizations that you have access to, as well as all personal repositories in your personal account.

As a security precaution, GitHub automatically removes personal access tokens that haven't been used in a year. To provide additional security, we highly recommend adding an expiration to your personal access tokens.

### Keeping your personal access tokens secure

Personal access tokens are like passwords, and they share the same inherent security risks. Before creating a new personal access token, consider if there is a more secure method of authentication available to you:

* To access GitHub from the command line, you can use [GitHub CLI](https://docs.github.com/en/github-cli/github-cli/about-github-cli) or [Git Credential Manager](https://github.com/GitCredentialManager/git-credential-manager/blob/main/README.md) instead of creating a personal access token.
* When using a personal access token in a GitHub Actions workflow, consider whether you can use the built-in `GITHUB_TOKEN` instead. For more information, see [related GitHub Docs article](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token).

If these options are not possible, and you must create a personal access token, consider using another CLI service to store your token securely.

When using a personal access token in a script, you can store your token as a secret and run your script through GitHub Actions. For more information, see [related GitHub Docs article](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets). You can also store your token as a Codespaces secret and run your script in Codespaces. For more information, see [related GitHub Docs article](https://docs.github.com/en/codespaces/managing-your-codespaces/managing-your-account-specific-secrets-for-github-codespaces).

For more information about best practices, see [related GitHub Docs article](https://docs.github.com/en/rest/authentication/keeping-your-api-credentials-secure).


## Creating a fine-grained personal access token

> [!NOTE]
> There is a limit of 50 fine-grained personal access tokens you can create. If you require more tokens or are building automations, consider using a GitHub App for better scalability and management. For more information, see [related GitHub Docs article](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/deciding-when-to-build-a-github-app#choosing-between-a-github-app-or-a-personal-access-token).

1. [Verify your email address](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/verifying-your-email-address), if it hasn't been verified yet.
1. In the upper-right corner of any page on GitHub, click your profile picture, then click ** Settings**.
1. In the left sidebar, click ** Developer settings**.
1. In the left sidebar, under ** Personal access tokens**, click **Fine-grained tokens**.
1. Click **Generate new token**.
1. Under **Token name**, enter a name for the token.
1. Under **Expiration**, select an expiration for the token. Infinite lifetimes are allowed but may be blocked by a maximum lifetime policy set by your organization or enterprise owner. For more information, See [Enforcing a maximum lifetime policy for personal access tokens](https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/setting-a-personal-access-token-policy-for-your-organization#enforcing-a-maximum-lifetime-policy-for-personal-access-tokens).
1. Optionally, under **Description**, add a note to describe the purpose of the token.
1. Under **Resource owner**, select a resource owner. The token will only be able to access resources owned by the selected resource owner. Organizations that you are a member of will not appear if the organization has blocked the use of fine-grained personal access tokens. For more information, see [related GitHub Docs article](https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/setting-a-personal-access-token-policy-for-your-organization).
1. Optionally, if the resource owner is an organization that requires approval for fine-grained personal access tokens, below the resource owner, in the box, enter a justification for the request.
1. Under **Repository access**, select which repositories you want the token to access. You should choose the minimal repository access that meets your needs. Tokens always include read-only access to all public repositories on GitHub.
1. If you selected **Only select repositories** in the previous step, under the **Selected repositories** dropdown, select the repositories that you want the token to access.
1. Under **Permissions**, select which permissions to grant the token. Depending on which resource owner and which repository access you specified, there are repository, organization, and account permissions. You should choose the minimal permissions necessary for your needs.

   The REST API reference document for each endpoint states whether the endpoint works with fine-grained personal access tokens and states what permissions are required in order for the token to use the endpoint. Some endpoints may require multiple permissions, and some endpoints may require one of multiple permissions. For an overview of which REST API endpoints a fine-grained personal access token can access with each permission, see [related GitHub Docs article](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).

1. Click **Generate token**.

If you selected an organization as the resource owner and the organization requires approval for fine-grained personal access tokens, then your token will be marked as `pending` until it is reviewed by an organization administrator. Your token will only be able to read public resources until it is approved. If you are an owner of the organization, your request is automatically approved. For more information, see [related GitHub Docs article](https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/reviewing-and-revoking-personal-access-tokens-in-your-organization).


## Creating a personal access token (classic)

> [!NOTE]
> Organization owners can restrict the access of personal access token (classic) to their organization. If you try to use a personal access token (classic) to access resources in an organization that has disabled personal access token (classic) access, your request will fail with a 403 response. Instead, you must use a GitHub App, OAuth app, or fine-grained personal access token.

> [!WARNING]
> Your personal access token (classic) can access every repository that you can access. GitHub recommends that you use fine-grained personal access tokens instead, which you can restrict to specific repositories. Fine-grained personal access tokens also enable you to specify fine-grained permissions instead of broad scopes.

1. [Verify your email address](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/verifying-your-email-address), if it hasn't been verified yet.
1. In the upper-right corner of any page on GitHub, click your profile picture, then click ** Settings**.
1. In the left sidebar, click ** Developer settings**.
1. In the left sidebar, under ** Personal access tokens**, click **Tokens (classic)**.
1. Select **Generate new token**, then click **Generate new token (classic)**.
1. In the "Note" field, give your token a descriptive name.
1. To give your token an expiration, select **Expiration**, then choose a default option or click **Custom** to enter a date.
1. Select the scopes you'd like to grant this token. To use your token to access repositories from the command line, select **repo**. A token with no assigned scopes can only access public information. For more information, see [related GitHub Docs article](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps#available-scopes).
1. Click **Generate token**.
1. Optionally, to copy the new token to your clipboard, click .

   ![Screenshot of the "Personal access tokens" page. Next to a blurred-out token, an icon of two overlapping squares is outlined in orange.](https://docs.github.com/en/assets/images/help/settings/personal-access-tokens.png)
1. To use your token to access resources owned by an organization that uses SAML single sign-on, authorize the token. For more information, see [related GitHub Docs article](https://docs.github.com/en/enterprise-cloud@latest/authentication/authenticating-with-single-sign-on/authorizing-a-personal-access-token-for-use-with-single-sign-on) in the GitHub Enterprise Cloud documentation.


## Deleting a personal access token

You should delete a personal access token if it is no longer needed. If you delete a personal access token that was used to create a deploy key, the deploy key will also be deleted.

1. In the upper-right corner of any page on GitHub, click your profile picture, then click ** Settings**.
1. In the left sidebar, click ** Developer settings**.
1. In the left sidebar, under ** Personal access tokens**, click either **Fine-grained tokens** or **Tokens (classic)**, depending on which type of personal access token you'd like to delete.
1. To the right of the personal access token you want to delete, click **Delete**.

> [!NOTE]
> If you find a leaked personal access token belonging to someone else, you can submit a revocation request through the REST API. See [related GitHub Docs article](https://docs.github.com/en/code-security/tutorials/secure-your-organization/prevent-data-leaks#mitigate-data-leaks).


## Using a personal access token on the command line

Once you have a personal access token, you can enter it instead of your password when performing Git operations over HTTPS.

For example, to clone a repository on the command line you would enter the following `git clone` command. You would then be prompted to enter your username and password. When prompted for your password, enter your personal access token instead of a password.

```shell
$ git clone https://github.com/USERNAME/REPO.git
Username: YOUR-USERNAME
Password: YOUR-PERSONAL-ACCESS-TOKEN
```

Although you are required to enter your username along with your personal access token, the username is not used to authenticate you. Instead, the personal access token is used to authenticate you. If you do not enter a username, you will receive an error message that your credentials are invalid.

Personal access tokens can only be used for HTTPS Git operations. If your repository uses an SSH remote URL, you will need to [switch the remote from SSH to HTTPS](https://docs.github.com/en/get-started/git-basics/managing-remote-repositories#switching-remote-urls-from-ssh-to-https).

If you are not prompted for your username and password, your credentials may be cached on your computer. You can [update your credentials in the Keychain](https://docs.github.com/en/get-started/git-basics/updating-credentials-from-the-macos-keychain) to replace your old password with the token.

Instead of manually entering your personal access token for every HTTPS Git operation, you can cache your personal access token with a Git client. Git will temporarily store your credentials in memory until an expiry interval has passed. You can also store the token in a plain text file that Git can read before every request. For more information, see [related GitHub Docs article](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git).


## Further reading

* [related GitHub Docs article](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github)
* [related GitHub Docs article](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/token-expiration-and-revocation)
