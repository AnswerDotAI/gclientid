# gclientid

`gclientid` creates a personal Google OAuth application in your own Google Cloud account, with a Web client for scripts and local web apps and a Desktop client for software you distribute. It can also authorize Google accounts and save standard refreshable tokens for Gmail, Drive, Calendar, Contacts, Tasks, Google Cloud, and Workspace administration.

There are two independent operations:

1. **Provisioning** finds or creates one stable Cloud project per owner, enables its APIs, configures consent, and creates an OAuth client in a signed-in Chrome. Every run converges on that state, so it is safe to repeat. A first run can create the project through Cloud Console with no existing credentials; `--owner` uses Google APIs when a cloud-authorized gclientid account already exists. Google provides no supported API for a general-purpose OAuth client; its programmatic client API creates IAP-only clients.
2. **Authorization** grants a client access to one Google account and writes a token. Normally it drives a signed-in Chrome and receives Google's response on a one-shot local callback; remote sessions can instead use a PKCE-protected appapis copy/paste callback.

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

This finds or creates your default project through the signed-in Cloud Console, enables the APIs of the `max` preset, configures branding, declared scopes, and the consent screen, publishes an External app as an unverified production application, and creates a Web OAuth client. No existing token is needed.

The default project ID is `gclientids-` plus a hash of the signed-in account's email, so it is the same on every machine and every run. Running `gclientid` again converges: the project, APIs, app, and client are checked and only what is missing is created.

The Web client is registered with `http://127.0.0.1:53682/` for the local callback, `https://oauth.appapis.org/redirect` for remote authorization, and `http://localhost:<port>/redirect` and `http://127.0.0.1:<port>/redirect` for ports 5001, 5002, and 8000, so a local [fasthtml](https://www.fastht.ml/) app can sign in with the same client. Add more with `--redirect`; re-running registers any the client lacks.

A Desktop client for software you distribute, which accepts any loopback port and has no redirect list, is one flag away and lives in the same project:

```bash
gclientid --desktop
```

Complete any Google terms screen that appears, or allow gclientid to accept it:

```bash
gclientid --accept-terms
```

Provisioning writes `config.ini` and `oauth-client.json` (or `oauth-client-desktop.json`). It does **not** grant access to Gmail or create a token.

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
gclientid-auth me@example.com
```

`gclientid-auth` connects to your normal Chrome, opens the authorization there, advances Google's account and consent screens once, and receives the result automatically through a one-shot listener bound only to `127.0.0.1:53682`. Chrome asks you to approve the debugging connection. Complete any passkey or other browser-native security prompt Google requires.

When a Workspace login makes Chrome offer to create a managed browser profile, gclientid selects **Use Chrome without an account** and returns to the authorization tab. This keeps the dedicated CDP profile usable with multiple Google accounts. Native passkey and Touch ID prompts still require the user.

Use the dedicated CDP Chrome profile instead with:

```bash
gclientid-auth me@example.com --cdp-chrome
```

The authorized data account can differ from the Cloud Console account that owns the project. The email supplies a Google login hint, selects the token file, and verifies the returned identity before the token is saved.

Authorize the Desktop client instead of the Web client with `--desktop`. Its listener uses whichever loopback port is free, and its token is stored separately:

```bash
gclientid-auth me@example.com --desktop
```

For SSH sessions or containers where the CLI and browser are on different machines:

```bash
gclientid-auth me@example.com --remote
```

The URL is printed and opened in the default browser. Click **Copy** on the appapis result page and paste its compact `code=...&state=...` result into the waiting CLI. Add `--no-open-browser` when the browser is on another machine. The PKCE verifier remains on the machine running gclientid. Only the Web client can use this route.

To provision and immediately authorize in one invocation:

```bash
gclientid --authorize --account me@example.com
```

The same Chrome connection handles setup and authorization. Add `--cdp-chrome` for the dedicated profile or `--remote` to close the setup browser and use appapis copy/paste for authorization.

## Access presets

Provisioning declares every scope in the `max` preset on the project and enables every API it needs. Any later authorization can therefore request any subset without touching the Console again. Presets choose what one authorization requests:

- `google-apps`, the default, requests broad access to Gmail, Drive, Calendar, Contacts, Tasks, Docs, Sheets, and Slides.
- `gmail` requests identity information and unrestricted Gmail access.
- `workspace-addon` requests identity and Google Cloud access and enables the APIs needed to manage Workspace add-on deployments.
- `developer` combines `google-apps` with `cloud-platform`. Cloud access remains limited by the authorized account's IAM roles.
- `workspace-admin` combines `google-apps` with broad Admin SDK and Enterprise License Manager access. Admin operations remain limited by the account's Workspace privileges.
- `max` combines `google-apps`, `developer`, and `workspace-admin`. It is every scope and API in gclientid's built-in presets, not every API Google offers.

Choose the default while provisioning, or override it for one authorization:

```bash
gclientid --preset max
gclientid-auth me@example.com --preset gmail
```

Scopes and APIs beyond `max` are declared and enabled on the project while provisioning, and every later authorization requests them:

```bash
gclientid --scope https://www.googleapis.com/auth/forms.body --api forms.googleapis.com
```

Repeat `--scope` and `--api` as needed. `gclientid-auth --scope` adds a scope to one authorization.

### Internal Workspace applications

Use `--internal` when every user belongs to the Cloud project's Google Workspace or Cloud Identity organization:

```bash
gclientid --owner me@example.com --internal --preset workspace-addon
gclientid-auth me@example.com --internal
```

The owner email's domain is resolved to its Cloud organization through Resource Manager, and the project is created under it. Internal credentials are kept alongside, rather than replacing, the default External profile: `config-internal.ini`, `oauth-client-internal.json`, and `oauth-token-<account>-internal.json`.

## Stored files

Credentials and settings live directly under `$XDG_CONFIG_HOME/gclientid/`, normally `~/.config/gclientid/`:

```text
config.ini
oauth-client.json
oauth-client-desktop.json
oauth-token-alice@example.com.json
oauth-token-alice@example.com-desktop.json
oauth-token-bob@example.com.json
config-internal.ini
oauth-client-internal.json
oauth-token-alice@example.com-internal.json
```

`config.ini` records the project, application name, default preset, custom scopes/APIs, the browser you use, and whether tokens re-authorize automatically. `oauth-client.json` holds Google's Web client and `oauth-client-desktop.json` the Desktop client, in the `web` and `installed` shapes Google's own downloads use. Each verified account gets one `oauth-token-<account>.json` per client in google-auth's authorized-user format. Credential JSON files are written with mode `0600`.

gclientid also loads, refreshes, and revokes these tokens, and [fastgws](https://answerdotai.github.io/fastgws/) re-exports the same functions from `fastgws.auth`. A refresh failure names the `gclientid-auth` command that recreates the grant:

```python
from gclientid import oauth_creds

creds = await oauth_creds(account='alice@example.com')
desktop = await oauth_creds(account='alice@example.com', desktop=True)
```

Pass `--output` to either command to use another credential directory. Provisioning converges on the requested state and never replaces an existing client; successful authorization replaces only the selected account's token.

## How authorization is protected

Every authorization request uses a fresh random `state` and PKCE verifier. The verifier stays in the waiting gclientid process. `oauth.appapis.org` only displays the short-lived callback parameters needed by the CLI: `code` and `state`, or Google's error fields. gclientid validates `state` before exchanging the single-use code.

Google access tokens normally last about one hour. The saved refresh token obtains replacements automatically. Production refresh tokens have no fixed lifetime, but Google can invalidate one after six months without use, explicit revocation, account security changes, or other security events.

Before opening OAuth, gclientid checks that a saved refresh token matches the client, account, and requested scopes, then verifies it with Google's token endpoint. If it is missing or unusable, the first authorization request includes explicit consent. Otherwise Google may omit a new refresh token and gclientid retains the verified one. Authorization always uses one browser/copy-paste round trip; it never launches a second consent flow.

## Automatic re-authorization

A stored token stops working when Google rejects a refresh: a Workspace session policy asked for fresh proof of identity, the refresh token was revoked or idle for six months, or an account security change invalidated it. Every case has one repair, a new browser authorization, and gclientid can run it for you.

`gclientid` writes `reauth = true` and the browser you used (`browser = chrome` or `cdp-chrome`) into `config.ini`. While `reauth` is on, `oauth_creds` reacts to a rejected refresh, a missing token, or a token that lacks the requested scopes by running the equivalent of `gclientid-auth` in that browser, waiting for you to complete any passkey prompt, and returning the fresh credentials. It runs one authorization only; a second failure is an error. Set `reauth = false` to get an error naming the command instead, which is what a copied token on a machine without `config.ini` does. `oauth_creds(..., reauth=True)` or `reauth=False` overrides the setting for one call.

Nothing here uses Google's RAPT protocol. A full authorization satisfies the same policy and also replaces the refresh token, so gclientid keeps one identity path.

## Personal, unverified applications

The intended setup is one Cloud project and OAuth client per developer or small team. gclientid configures an **External**, **In production**, unverified application. Google warns that sensitive or restricted scopes require verification, but an unverified personal-use application can still authorize up to 100 distinct users over its lifetime. Verification is needed to remove the warning or exceed that cap.

Do not leave a Gmail application in **Testing**: test users need an allowlist, and grants involving Gmail expire after seven days. An unverified production application avoids both limitations.

Google may still require a passkey or Touch ID for a broad grant even when the account is already signed in. Those are browser-native security decisions; complete them in the browser. An immediate repeat often reuses Google's recent authentication and does not prompt again.

## Python API

`provision` and `authorize_account` are the two commands as functions, with the same options:

```python
from gclientid import authorize_account, provision

await provision(desktop=True, cdp_chrome=True)
token_path = await authorize_account('me@example.com', desktop=True, cdp_chrome=True)
```

Each Console step is its own function taking a signed-in page: `console_account`, `ensure_project_ui`, `enable_apis_ui`, `configure_app`, `create_client`, and `add_redirects`. `provision_project` is the Resource Manager equivalent of the project and API steps:

```python
from gclientid import add_redirects, configure_app, connect_browser, create_client, provision_project

project_id = 'gclientids-your-unique-suffix'
await provision_project('me@example.com', project_id, name='gclientids', domain='example.com',
    apis=['cloudresourcemanager.googleapis.com', 'gsuiteaddons.googleapis.com'])

cdp, page = await connect_browser()
await configure_app(page, project_id, internal=True, support_email='me@example.com')
await create_client(page, project_id, 'oauth-client-internal.json')
await add_redirects(page, 'oauth-client-internal.json', ['http://localhost:3000/redirect'])
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
