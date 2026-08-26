# Development notes

`gclientid` drives an existing, signed-in Google Cloud Console tab through
fastcdp. It does not require `gcloud` and should not own the developer's Google
credentials.

`connect_browser()` uses `CDP.connect(timeout=60)` by default. This connects to the normal Chrome profile after the developer enables **Allow remote debugging** in `chrome://inspect/#remote-debugging`; Chrome asks the developer to approve each new connection. `connect_browser(default_browser=False)` uses `CDP.remote()` and the dedicated CDP Chrome profile on port 9223. Both paths return `(cdp, page)` with a new tab, so setup never navigates the developer's focused tab away. fastcdp's `active_page()` skips `chrome://` and `devtools://` targets because Chrome accepts attachment but never answers page commands for them.

After initially adding this repository with `ws-add`, restart any persistent
Python/clikernel process so it sees the new workspace editable install.

## CLI

The `gclientid` entry point is `gclientid.cli:main`; `gclientid-auth` is `gclientid.cli:auth`. `fastcore.script.call_parse` creates their arguments from the function signatures and docments. A bare `gclientid` invocation provisions the project and client with the `google-apps` preset, then stops. `gclientid --authorize` additionally authorizes a data account in the same browser connection. A bare `gclientid-auth` authorizes from an existing client. Provisioning generates `gclientids-<10 random hex digits>` and stores files directly under `$XDG_CONFIG_HOME/gclientid/` by default. `--output` replaces that directory; it does not add a project subdirectory.

Provisioning writes `config.ini` using `fastcore.xdg.Config`. It records the project, name, preset, and custom scopes/APIs separately from Google's unmodified `oauth-client.json`. `gclientid-auth` reads the saved preset and custom scopes by default; its own `--preset` overrides the base preset and repeatable `--scope` values augment the saved scopes. This also allows authorization from a client JSON created elsewhere: without `config.ini`, `gclientid-auth` defaults to `google-apps`.

The account active in Cloud Console provisions and owns the project and OAuth client. `--account` on `gclientid-auth` or combined `gclientid --authorize` selects the separate data account during OAuth; it does not switch the Console account. The provisioning CLI checks both destination credential files before creating the Cloud project, closes its setup tab and CDP connection on success or failure, and never prints client secrets or OAuth tokens.

## Google Cloud project lifecycle

Project creation starts at `https://console.cloud.google.com/projectcreate`.
`create_project` fills both the display name and the explicit project ID, then
waits for the console's `Navigate to <project-id> project` notification. Google
navigates back to the previously selected project's dashboard while creation
runs, so the navigation alone does not confirm success.

Chrome does not reliably emit a load event when navigating to the current URL
or to `about:blank`. fastcdp's `goto()` therefore waits for document readiness
and network quiet rather than requiring that event.

The current helper preserves the form's default billing account, organization,
and parent resource. Choosing among multiple accounts or organizations remains
future work. Google Cloud project IDs must be globally unique.

For an External app published without verification, use the repository as the
application homepage and privacy policy:

- `https://answerdotai.github.io/gclientid/`
- `https://answerdotai.github.io/gclientid/privacy/`

Add `answerdotai.github.io` to the consent screen's authorized domains. GitHub
blob URLs caused a generic branding-save failure, while the Pages URLs saved
successfully. This keeps setup independent of a particular developer's email.

The August 27, 2026 live OAuth check used a loopback redirect, PKCE, offline
access, and the `google-apps` preset. Authorization as `j@answer.ai` succeeded
without a test-user allowlist, produced a refresh token, and returned every
requested scope. Representative Gmail, Drive, Calendar, People, and Tasks API
calls all returned 200. Google's token endpoint requires the Desktop client
secret despite PKCE; capture the one-time secret from the creation dialog.

`create_client` implements the complete Console path. It enables each preset API, initializes an External Auth Platform application when needed, configures the Pages branding URLs, adds every preset scope, publishes the application, creates a Desktop client, and writes installed-app JSON with mode `0600`. It waits on the visible API Services terms screen unless `accept_terms=True`.

The Data Access route is `/auth/scopes`, not `/auth/dataaccess`. Its manual scope box accepts one scope per line; adding the complete preset again is idempotent. The Console abbreviates most saved scope URLs in the accessibility tree, so `create_client` pastes the desired set rather than trying to reconstruct full URLs from displayed rows.

`authorize_google` opens and activates a new Chrome tab, uses a PKCE loopback callback, and writes token JSON with mode `0600`. It selects the sole existing Google account automatically. The `account` parameter selects a unique display-name or email substring when several existing accounts are available. Consent may use `Continue` or `Allow`; the helper also advances through the unverified-app warning and selects all permissions when Google presents granular consent.

Deletion uses the project's IAM & Admin settings page. Google calls this action
"Shut down" and requires the project ID to be typed into a confirmation dialog.
It is a soft deletion: the project becomes inaccessible immediately but remains
recoverable for 30 days before permanent deletion. `delete_project` waits for
the `Project is pending deletion` dialog before returning.

Scope confirmation controls to the shutdown dialog. The page behind it also has
a `Project ID` textbox, so a page-wide lookup can select the wrong field.
Use fastcdp's `fill_text` rather than calling `Input.insertText` directly;
`fill_text` focuses and selects the control first, so it replaces rather than
appends to Google Cloud's Angular inputs.

## fastcdp

Google Cloud Console's full accessibility-tree response was about 3.1 MB in the
initial live test. fastcdp must connect with `websockets.connect(...,
max_size=None)` rather than its former 1 MB default, or `ax_tree()` closes the
connection before returning.

The live create/delete check used `gclientid-test-20260826-fcdc`. Google
confirmed that it is shut down and scheduled for permanent deletion after
September 25, 2026.

Google API Library navigation can reach a URL before its Angular content is rendered. `_enable_apis` waits for the page text containing the exact service name before reading its AX tree; an immediate `ax_tree()` can otherwise miss the Enable button and silently skip an API.
