# gclientid

Create Google OAuth desktop client IDs locally, without requiring `gcloud`.

## CLI

Install `gclientid`, enable **Allow remote debugging** in `chrome://inspect/#remote-debugging`, and run:

```bash
pip install gclientid
gclientid
```

Chrome asks you to approve the debugging connection. `gclientid` opens a separate tab, creates a dedicated project with a unique `gclientids-*` ID, configures and publishes its unverified OAuth application, creates a Desktop client, and stops.

Then authorize a Google account using that client:

```bash
gclientid-auth --account j@answer.ai
```

Provisioning and authorization are deliberately separate. `gclientid` uses the account active in Google Cloud Console to create the project and client, then stops. `gclientid-auth` needs no Cloud Console access: it uses the saved client to authorize the selected data account. To do both in one browser connection instead, run `gclientid --authorize`, optionally with `--account`.

The default `google-apps` preset requests broad access to Gmail, Drive, Calendar, Contacts, Tasks, Docs, Sheets, and Slides. The account active in Google Cloud Console owns the project and client; the account selected during OAuth owns the data. They may be different accounts, so a personal account can provision the client while a Workspace account authorizes its Google Apps data.

Configuration and credentials are stored under `$XDG_CONFIG_HOME/gclientid/`, which defaults to `~/.config/gclientid/`:

```text
config.ini
oauth-client.json
oauth-token.json
```

`config.ini` records the provisioned project, name, preset, and custom scopes/APIs, so `gclientid-auth` automatically requests the same access without repeating those options. The Google-generated client JSON is left unchanged. `oauth-token.json` is only created by `gclientid-auth` or `gclientid --authorize`.
Both credential JSON files are written with mode `0600`.

The main options are:

```bash
gclientid --project my-unique-project-id
gclientid --preset developer
gclientid --preset workspace-admin
gclientid --preset gmail
gclientid --scope https://www.googleapis.com/auth/forms.body --api forms.googleapis.com
gclientid --authorize --account j@answer.ai
gclientid --accept-terms
gclientid --cdp-chrome
gclientid --output ./credentials
gclientid-auth --account j@answer.ai
gclientid-auth --scope https://www.googleapis.com/auth/forms.body
gclientid-auth --cdp-chrome
```

Run `gclientid --help` or `gclientid-auth --help` for all options. `--output` replaces the complete credential directory rather than adding a project subdirectory. Provisioning never overwrites existing credential files; successful authorization replaces the token file.

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

`connect_browser()` uses the normal Chrome profile by default. Chrome gives you 60 seconds to approve the debugging connection. The function opens a new tab instead of navigating the currently focused tab. To use the separate CDP Chrome profile on port 9223 instead:

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
