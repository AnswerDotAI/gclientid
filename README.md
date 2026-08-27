# gclientid

`gclientid` creates a personal Google OAuth application and Desktop client ID in your Google Cloud account. It can also authorize a Google account and save a refresh token for local access to Gmail, Drive, Calendar, Contacts, Tasks, Docs, Sheets, Slides, Google Cloud, or Workspace administration. Everything runs on your computer. It does not require `gcloud`.

## Install

```bash
pip install gclientid
```

## 1. Choose a browser

`gclientid` drives Google Cloud Console and Google's OAuth screens through Chrome. Choose one browser setup and use it for both commands.

### Normal Chrome

Use normal Chrome when you want `gclientid` to use your existing Google logins. Enable **Allow remote debugging** in `chrome://inspect/#remote-debugging`. Chrome asks you to approve each connection from `gclientid`.

Normal Chrome is the default. Do not pass a browser flag in the commands below.

### CDP Chrome

CDP Chrome is a separate browser profile for automation. It does not show connection-approval prompts. Install its launcher once:

```bash
fastcdp-setup
```

Start the installed **CDP Chrome** launcher and sign in to the Google accounts you want to use. Add `--cdp-chrome` to every command below.

## 2. Create the project and OAuth client

The default `google-apps` preset requests broad access to Gmail, Drive, Calendar, Contacts, Tasks, Docs, Sheets, and Slides. Run:

```bash
gclientid
```

Choose a different preset during setup when needed:

- `gmail` requests identity information and unrestricted Gmail access.
- `developer` adds `cloud-platform` to `google-apps`. Google Cloud access remains limited by the authorized account's IAM roles.
- `workspace-admin` adds Workspace Admin SDK access to `google-apps`. Admin operations remain limited by the authorized account's Workspace privileges.

```bash
gclientid --preset gmail
gclientid --preset developer
gclientid --preset workspace-admin
```

Add scopes and APIs that are not in a preset with repeatable `--scope` and `--api` options:

```bash
gclientid --scope https://www.googleapis.com/auth/forms.body --api forms.googleapis.com
```

`gclientid` saves the selected preset and additions for later use by `gclientid-auth`.

Add `--cdp-chrome` when using CDP Chrome. `gclientid` creates a dedicated Google Cloud project with a unique `gclientids-*` project ID. It configures the project's OAuth branding, consent screen, audience, scopes, and APIs. It publishes the unverified application and creates a Desktop OAuth client ID.

The Google account active in Cloud Console owns the project and OAuth client. Complete any Google terms screen that appears in the browser. Pass `--accept-terms` to submit that screen automatically.

This step creates `oauth-client.json`. It does not grant access to a Google account or create an access token.

## 3. Authorize a Google account (optional)

Authorization creates the refresh token that another local program can use to access Google APIs. You can authorize during initial setup:

```bash
gclientid --authorize
```

You can also authorize later with the separate command:

```bash
gclientid-auth
```

Add `--cdp-chrome` to either command when using CDP Chrome. Use `--account name@example.com` to select an account when Chrome offers several signed-in accounts. `gclientid-auth` reads the existing OAuth client and does not require Cloud Console access. The authorized data account can differ from the account that owns the Cloud project.

Google issues access tokens for about one hour. The saved refresh token obtains new access tokens without repeating consent. A production refresh token has no fixed expiry, but Google invalidates it after six months without use or after events such as revocation and some account security changes.

## Stored files

`gclientid` stores configuration and credentials under `$XDG_CONFIG_HOME/gclientid/`. The default is `~/.config/gclientid/`:

```text
config.ini
oauth-client.json
oauth-token.json
```

`config.ini` records the project, name, preset, and custom scopes and APIs. `oauth-client.json` is Google's unmodified Desktop client file. `oauth-token.json` is only created by authorization. Both credential JSON files use mode `0600`.

Pass `--output` to either command to use a different directory. Provisioning never overwrites existing credential files. Successful authorization replaces `oauth-token.json`.

Run `gclientid --help` or `gclientid-auth --help` for all options.

## Python API

`gclientid` uses an existing signed-in [fastcdp](https://github.com/AnswerDotAI/fastcdp) Chrome session. Enable **Allow remote debugging** in `chrome://inspect/#remote-debugging`, then create a globally unique project ID, provision its Desktop OAuth client, and authorize the data account:

```python
from gclientid import authorize_google, connect_browser, create_client, create_project

cdp, page = await connect_browser()
project_id = 'gclientids-your-unique-suffix'

await create_project(page, project_id, name='gclientids')
await create_client(page, project_id, 'oauth-client.json')
await authorize_google(cdp, 'oauth-client.json', 'oauth-token.json', account='j@answer.ai')
```

`connect_browser()` uses the normal Chrome profile by default. Chrome gives you 60 seconds to approve the debugging connection. The function opens a new tab instead of navigating the currently focused tab. To use the separate CDP Chrome profile on port 9223 instead, run `fastcdp-setup` once, start its CDP Chrome launcher, and connect with:

```python
cdp, page = await connect_browser(default_browser=False)
```

`create_client` enables the APIs required by its preset, configures an External OAuth application, adds its scopes, publishes the unverified application, creates a Desktop client, and writes Google's installed-app client JSON. It selects an email offered by the Cloud Console account for the support and contact fields.

The default preset is `google-apps`. `developer` adds `cloud-platform`; `workspace-admin` adds broad Admin SDK scopes; and `gmail` requests only identity and unrestricted Gmail access. Additional scopes and API service names can be supplied with `scopes=` and `apis=`. Cloud and Workspace administration remain limited to permissions already held by the authorized data account.

On a new Google Auth Platform application, `create_client` pauses at Google's API Services terms screen. Complete that visible screen in Chrome and the function continues. Pass `accept_terms=True` to accept and submit that screen automatically:

```python
await create_client(page, project_id, 'oauth-client.json', accept_terms=True)
```

`authorize_google` opens Google's account and consent screens in a new Chrome tab. It selects the account automatically when Google offers one existing account, then approves the requested access. When Google offers multiple existing accounts, select the data account by display name or email substring:

```python
await authorize_google(cdp, 'oauth-client.json', 'oauth-token.json', account='j@answer.ai')
```

The function uses a PKCE loopback flow and writes the authorized account, access token, refresh token, granted scopes, client ID, and creation time to `oauth-token.json`.

Both JSON files are created with mode `0600`. `create_client` refuses to overwrite an existing client file because Google only exposes the Desktop client secret at creation time. `authorize_google` replaces the token file when authorization succeeds. Keep both files out of git.

Project deletion is also available. Google keeps a deleted project recoverable for 30 days:

```python
from gclientid import delete_project

await delete_project(page, project_id)
```

See the [privacy policy](PRIVACY.md) for how Google user data is handled.

## Personal OAuth applications

The intended setup is one Google Cloud project and Desktop OAuth client per
developer. Configure its audience as **External**, publish it **In production**,
and leave it unverified. Google may say that the app "requires verification",
but personal-use applications can still authorize up to 100 distinct users.
Users see an unverified-app warning during initial authorization; verification
is only needed to remove that warning or exceed the lifetime user cap.

Do not leave a continuously running application in **Testing**. Testing requires
an explicit test-user email list, and authorizations requesting Gmail access
expire after seven days. An unverified app that is In production needs neither
the allowlist nor seven-day reauthorization.

The default preset includes restricted Gmail and Drive scopes alongside broad
Calendar, Contacts, Tasks, and identity scopes. The unrestricted Gmail scope is
`https://mail.google.com/`; it allows reading, composing, sending, and
permanently deleting mail. Every scope must be requested during authorization
even when it is already listed on the Google Auth Platform Data Access page.

Google currently requires a Desktop client's `client_secret` during the token
exchange, including when PKCE is used. The secret is shown only when the client
is created, so capture or download the client JSON immediately. Desktop software
cannot keep this value confidential, but it must still be kept out of git along
with user access and refresh tokens.

## Development

```bash
pip install -e .[dev]
```

## Versioning

Version lives in `gclientid/__init__.py` as `__version__`.
Bump it with:

```bash
ship-bump --part 2   # patch
ship-bump --part 1   # minor
ship-bump --part 0   # major
```

## Release

1) Ensure your GitHub issues are labeled (`bug`, `enhancement`, `breaking`).
2) Run:

```bash
ship-release
```
