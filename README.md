# gclientid

`gclientid` creates a personal Google OAuth application in your own Google Cloud account. It can also authorize Google accounts and save standard refreshable tokens for Gmail, Drive, Calendar, Contacts, Tasks, Google Cloud, and Workspace administration.

There are two independent operations:

1. **Provisioning** creates a dedicated Cloud project, enables its APIs, then configures consent and creates a Web OAuth client in a signed-in Chrome. A first run can create the project through Cloud Console with no existing credentials; `--owner` uses Google APIs when a cloud-authorized gclientid account already exists. Google provides no supported API for a general-purpose OAuth client; its programmatic client API creates IAP-only clients.
2. **Authorization** grants that client access to one Google account and writes a token. Normally it drives a signed-in Chrome and receives Google's response on a one-shot local callback; remote sessions can instead use a PKCE-protected appapis copy/paste callback.

`gclientid` can do both in one command, but provisioning is the default. Everything runs locally and `gcloud` is neither used nor required.

## Install

```bash
pip install gclientid
```

## Quick start

### 1. Choose a browser for OAuth setup

Provisioning needs access to a Google Cloud Console session. Choose either approach.

**Your normal Chrome:** enable **Allow remote debugging** in `chrome://inspect/#remote-debugging`, then run `gclientid` normally. Chrome asks you to approve the connection. This is convenient when your usual browser is already signed into the Cloud account that should own the project.

**Dedicated CDP Chrome:** install the launcher once, start **CDP Chrome**, and sign into the desired Cloud account:

```bash
fastcdp-setup
gclientid --cdp-chrome
```

CDP Chrome uses a separate profile and does not show a connection-approval prompt.

### 2. Create the project and OAuth client

```bash
gclientid
```

This creates a globally unique `gclientids-*` project through the signed-in Cloud Console, enables its APIs, configures its branding, consent screen, and scopes, publishes an External app as an unverified production application, and creates a Web OAuth client registered with both `http://127.0.0.1:53682/` and `https://oauth.appapis.org/redirect`. No existing token is needed.

Complete any Google terms screen that appears, or allow gclientid to accept it:

```bash
gclientid --accept-terms
```

Provisioning writes `config.ini` and `oauth-client.json`. It does **not** grant access to Gmail or create a token.

When an existing gclientid token has `cloud-platform` access, `--owner` instead creates and configures the project through Resource Manager and Service Usage:

```bash
gclientid --owner me@example.com
```

Chrome must also be signed into that account so gclientid can require the same support/contact email. API provisioning grants the owner explicit Service Usage Consumer access. `--internal` requires this path because the owner token resolves the Workspace organization.

To prepare an owner token during an initial External setup, request the `developer` preset and authorize in the same run:

```bash
gclientid --preset developer --authorize --account me@example.com
```

### 3. Authorize a Google account when needed

```bash
gclientid-auth --account me@example.com
```

`gclientid-auth` connects to your normal Chrome, opens the authorization there, advances Google's account and consent screens once, and receives the result automatically through a one-shot listener bound only to `127.0.0.1:53682`. Chrome asks you to approve the debugging connection. Complete any passkey or other browser-native security prompt Google requires.

When a Workspace login makes Chrome offer to create a managed browser profile, gclientid selects **Use Chrome without an account** and returns to the authorization tab. This keeps the dedicated CDP profile usable with multiple Google accounts. Native passkey and Touch ID prompts still require the user.

Use the dedicated CDP Chrome profile instead with:

```bash
gclientid-auth --account me@example.com --cdp-chrome
```

The authorized data account can differ from the Cloud Console account that owns the project. `--account` supplies a Google login hint and verifies the returned identity before the token is saved.

For SSH sessions or containers where the CLI and browser are on different machines:

```bash
gclientid-auth --account me@example.com --remote
```

The URL is printed and opened in the default browser. Click **Copy** on the appapis result page and paste its compact `code=...&state=...` result into the waiting CLI. Add `--no-open-browser` when the browser is on another machine. The PKCE verifier remains on the machine running gclientid.

To provision and immediately authorize in one invocation:

```bash
gclientid --authorize --account me@example.com
```

The same Chrome connection handles setup and authorization. Add `--cdp-chrome` for the dedicated profile or `--remote` to close the setup browser and use appapis copy/paste for authorization.

## Access presets

The default `google-apps` preset requests broad access to Gmail, Drive, Calendar, Contacts, Tasks, Docs, Sheets, and Slides.

- `gmail` requests identity information and unrestricted Gmail access.
- `workspace-addon` requests identity and Google Cloud access and enables the APIs needed to manage Workspace add-on deployments.
- `developer` combines `google-apps` with `cloud-platform`. Cloud access remains limited by the authorized account's IAM roles.
- `workspace-admin` combines `google-apps` with broad Admin SDK and Enterprise License Manager access. Admin operations remain limited by the account's Workspace privileges.
- `max` combines `google-apps`, `developer`, and `workspace-admin`. It is every scope and API in gclientid's built-in presets, not every API Google offers.

Choose a preset while provisioning; `gclientid-auth` remembers it:

```bash
gclientid --preset max
gclientid --preset workspace-admin
```

Override it during authorization or add custom scopes and APIs:

```bash
gclientid-auth --account me@example.com --preset gmail
gclientid --scope https://www.googleapis.com/auth/forms.body --api forms.googleapis.com
```

Repeat `--scope` and `--api` as needed.

### Internal Workspace applications

Use `--internal` when every user belongs to the Cloud project's Google Workspace or Cloud Identity organization:

```bash
gclientid --owner me@example.com --internal --preset workspace-addon
gclientid-auth --internal --account me@example.com
```

The owner email's domain is resolved to its Cloud organization through Resource Manager, and the project is created under it. Internal credentials are kept alongside, rather than replacing, the default External profile: `config-internal.ini`, `oauth-client-internal.json`, and `oauth-token-<account>-internal.json`.

## Stored files

Credentials and settings live directly under `$XDG_CONFIG_HOME/gclientid/`, normally `~/.config/gclientid/`:

```text
config.ini
oauth-client.json
oauth-token-alice@example.com.json
oauth-token-bob@example.com.json
config-internal.ini
oauth-client-internal.json
oauth-token-alice@example.com-internal.json
```

`config.ini` records the project, application name, preset, and custom scopes/APIs. `oauth-client.json` contains Google's Web client configuration. Each verified account gets its own `oauth-token-<account>.json` in google-auth's authorized-user format. Credential JSON files are written with mode `0600`.

Libraries such as [fastgws](https://answerdotai.github.io/fastgws/) can use the standard account location directly:

```python
from fastgws.auth import oauth_creds

creds = await oauth_creds(account='alice@example.com')
```

Pass `--output` to either command to use another credential directory. Provisioning refuses to overwrite existing credentials; successful authorization replaces only the selected account's token.

## How authorization is protected

Every authorization request uses a fresh random `state` and PKCE verifier. The verifier stays in the waiting gclientid process. `oauth.appapis.org` only displays the short-lived callback parameters needed by the CLI: `code` and `state`, or Google's error fields. gclientid validates `state` before exchanging the single-use code.

Google access tokens normally last about one hour. The saved refresh token obtains replacements automatically. Production refresh tokens have no fixed lifetime, but Google can invalidate one after six months without use, explicit revocation, account security changes, or other security events.

Before opening OAuth, gclientid checks that a saved refresh token matches the client, account, and requested scopes, then verifies it with Google's token endpoint. If it is missing or unusable, the first authorization request includes explicit consent. Otherwise Google may omit a new refresh token and gclientid retains the verified one. Authorization always uses one browser/copy-paste round trip; it never launches a second consent flow.

## Personal, unverified applications

The intended setup is one Cloud project and OAuth client per developer or small team. gclientid configures an **External**, **In production**, unverified application. Google warns that sensitive or restricted scopes require verification, but an unverified personal-use application can still authorize up to 100 distinct users over its lifetime. Verification is needed to remove the warning or exceed that cap.

Do not leave a Gmail application in **Testing**: test users need an allowlist, and grants involving Gmail expire after seven days. An unverified production application avoids both limitations.

Google may still require a passkey or Touch ID for a broad grant even when the account is already signed in. Those are browser-native security decisions; complete them in the browser. An immediate repeat often reuses Google's recent authentication and does not prompt again.

## Python API

Project creation and API enablement use fastgws:

```python
from gclientid import connect_browser, create_client, provision_project

project_id = 'gclientids-your-unique-suffix'
await provision_project(
    'me@example.com', project_id, name='gclientids', domain='example.com',
    apis=['cloudresourcemanager.googleapis.com', 'gsuiteaddons.googleapis.com'])

cdp, page = await connect_browser()
await create_client(page, project_id, 'oauth-client-internal.json', internal=True,
    support_email='me@example.com')
```

`connect_browser()` targets normal Chrome and gives the user up to 60 seconds to approve the debugging connection. Use the dedicated profile with `connect_browser(default_browser=False)`.

Authorization can reuse an existing CDP connection; without one it opens the system's default browser and still receives the local callback automatically:

```python
from gclientid import authorize_google

token = await authorize_google(
    'oauth-client.json',
    'oauth-token.json',
    preset='google-apps',
    account='me@example.com')
```

Pass `cdp=cdp` to open the flow in a particular CDP browser, or `remote=True` to print the appapis URL and read its copied result. Both paths verify the account and write the same standard authorized-user token.

Project deletion is also available. Google treats this as a recoverable shutdown for 30 days:

```python
from gclientid import delete_project

await delete_project('me@example.com', project_id)
```

See [DEV.md](DEV.md) for the API and remaining Cloud Console implementation details, and [PRIVACY.md](PRIVACY.md) for the privacy policy.

## Development

```bash
pip install -e .[dev]
```

Version lives in `gclientid/__init__.py`. Releases use:

```bash
ship-release
```
