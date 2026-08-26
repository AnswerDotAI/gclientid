# gclientid

Create Google OAuth desktop client IDs locally, without requiring `gcloud`.

## CLI

Install `gclientid`, enable **Allow remote debugging** in `chrome://inspect/#remote-debugging`, and run:

```bash
pip install gclientid
gclientid
```

Chrome asks you to approve the debugging connection. `gclientid` opens a separate tab, creates a dedicated project with a unique `gclientids-*` ID, configures and publishes its unverified Gmail OAuth application, creates a Desktop client, and authorizes the selected Gmail account.

Credentials are written with mode `0600` under `~/.config/gclientid/<project-id>/`:

```text
oauth-client.json
oauth-token.json
```

The main options are:

```bash
gclientid --project my-unique-project-id
gclientid --account j@example.com
gclientid --accept-terms
gclientid --cdp-chrome
gclientid --output ./credentials
```

Run `gclientid --help` for all options. Existing credential files are never overwritten.

## Python API

`gclientid` uses an existing signed-in [fastcdp](https://github.com/AnswerDotAI/fastcdp) Chrome session. Enable **Allow remote debugging** in `chrome://inspect/#remote-debugging`, then create a globally unique project ID, provision its Gmail Desktop OAuth client, and authorize the Gmail account:

```python
from gclientid import authorize_gmail, connect_browser, create_gmail_client, create_project

cdp, page = await connect_browser()
project_id = 'gclientids-your-unique-suffix'

await create_project(page, project_id, name='gclientids')
await create_gmail_client(page, project_id, 'oauth-client.json')
await authorize_gmail(cdp, 'oauth-client.json', 'oauth-token.json')
```

`connect_browser()` uses the normal Chrome profile by default. Chrome gives you 60 seconds to approve the debugging connection. The function opens a new tab instead of navigating the currently focused tab. To use the separate CDP Chrome profile on port 9223 instead:

```python
cdp, page = await connect_browser(default_browser=False)
```

`create_gmail_client` enables the Gmail API, configures an External OAuth application, adds the full Gmail scope, publishes the unverified application, creates a Desktop client, and writes Google's installed-app client JSON. It selects an email offered by the signed-in Google account for the support and contact fields. It does not require an email or username argument.

On a new Google Auth Platform application, `create_gmail_client` pauses at Google's API Services terms screen. Complete that visible screen in Chrome and the function continues. Pass `accept_terms=True` to accept and submit that screen automatically:

```python
await create_gmail_client(page, project_id, 'oauth-client.json', accept_terms=True)
```

`authorize_gmail` opens Google's account and consent screens in a new Chrome tab. It selects the account automatically when Google offers one existing account, then approves the requested Gmail access. When Google offers multiple existing accounts, select one by display name or email substring:

```python
await authorize_gmail(cdp, 'oauth-client.json', 'oauth-token.json', account='j@example.com')
```

The function uses a PKCE loopback flow and writes the access token, refresh token, granted scope, client ID, and creation time to `oauth-token.json`.

Both JSON files are created with mode `0600`. `create_gmail_client` refuses to overwrite an existing client file because Google only exposes the Desktop client secret at creation time. `authorize_gmail` replaces the token file when authorization succeeds. Keep both files out of git.

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

The unrestricted Gmail scope is `https://mail.google.com/`. It is a restricted
scope and allows reading, composing, sending, and permanently deleting mail.
The application must request this scope during authorization even when it is
already listed on the Google Auth Platform Data Access page.

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
