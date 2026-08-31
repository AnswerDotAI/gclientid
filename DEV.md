# Development notes

`gclientid` uses fastgws for Cloud Resource Manager and Service Usage when an
existing cloud-authorized `--owner` is available, including organization lookup,
project creation/deletion, operation polling, and API enablement. A bootstrap run
without `--owner` creates the first project and enables its APIs through Cloud
Console. fastcdp also handles the remaining generic OAuth configuration and
client creation in the signed-in Console session.
Local account authorization uses CDP plus a one-shot loopback callback; remote
authorization uses the same Web client through appapis copy/paste. No path
requires `gcloud`.

`connect_browser()` uses `CDP.connect(timeout=60)` by default. This connects to the normal Chrome profile after the developer enables **Allow remote debugging** in `chrome://inspect/#remote-debugging`; Chrome asks the developer to approve each new connection. `connect_browser(default_browser=False)` uses `CDP.remote()` and the dedicated CDP Chrome profile on port 9223. Both paths return `(cdp, page)` with a new tab, so setup never navigates the developer's focused tab away. fastcdp's `active_page()` skips `chrome://` and `devtools://` targets because Chrome accepts attachment but never answers page commands for them.

After initially adding this repository with `ws-add`, restart any persistent
Python/clikernel process so it sees the new workspace editable install.

## CLI

The `gclientid` entry point is `gclientid.cli:main`; `gclientid-auth` is `gclientid.cli:auth`. `fastcore.script.call_parse` creates their arguments from the function signatures and docments. A bare `gclientid` bootstraps the project, APIs, and client through Console with the `google-apps` preset, then stops. `gclientid --owner <account>` uses Resource Manager and Service Usage instead; the owner must already have a gclientid token containing `cloud-platform`. `gclientid --authorize` reuses its Console CDP connection for local authorization. A bare `gclientid-auth` connects to normal Chrome; `--cdp-chrome` selects the dedicated profile and `--remote` uses appapis without CDP. Provisioning generates `gclientids-<10 random hex digits>` and stores files directly under `$XDG_CONFIG_HOME/gclientid/` by default. `--output` replaces that directory; it does not add a project subdirectory.

Provisioning writes `config.ini` using `fastcore.xdg.Config`. It records the project, name, preset, and custom scopes/APIs separately from the standard Web-client `oauth-client.json`. `gclientid-auth` reads the saved preset and custom scopes by default; its own `--preset` overrides the base preset and repeatable `--scope` values augment the saved scopes. This also allows authorization from a client JSON created elsewhere: without `config.ini`, `gclientid-auth` defaults to `google-apps`.

`--internal` selects the Internal OAuth audience and an independent local profile: `config-internal.ini`, `oauth-client-internal.json`, and `oauth-token-<account>-internal.json`. Default commands ignore Internal token files and Internal commands ignore default token files, so provisioning or authorizing one profile cannot overwrite the other. The `workspace-addon` preset combines identity and `cloud-platform` scopes with Cloud Resource Manager, Service Usage, IAM, and Workspace Add-ons APIs. Internal apps skip publication because only External apps have the testing-to-production lifecycle.

Authorization stores one `oauth-token-<account>.json` per verified Google account. Email characters safe in filenames remain readable; other characters are percent-encoded. Token files use google-auth's authorized-user format with the verified `account` field retained.

The `max` preset is the union of `google-apps`, `developer`, and `workspace-admin`. It is the broadest built-in preset, not every scope and API offered by Google.

Without `--owner`, project creation and API enablement use the signed-in Console and need no prior gclientid credentials. The `--owner` token selects API provisioning instead. For an Internal app, its email domain selects the single visible Cloud organization and the project is created under that organization; Internal provisioning therefore requires `--owner`. The same email must be offered as a support address in the active Console session, preventing accidental client creation under a different login. `--account` on `gclientid-auth` or combined `gclientid --authorize` selects the separate data account during OAuth. The provisioning CLI checks both destination credential files before creating the Cloud project, closes its setup tab and CDP connection on success or failure, and never prints client secrets or OAuth tokens. Provisioning and authorization both confirm the output directory is writable before opening an OAuth flow or mutating Google-side state.

## Google Cloud project lifecycle

`cloud_clients(account)` loads the owner's existing gclientid authorized-user
token and creates Resource Manager v3 and Service Usage v1 fastgws clients.
`provision_project` searches projects by global project ID and is idempotent: it
creates a missing project, validates an existing Internal project's parent,
idempotently grants the owner `roles/serviceusage.serviceUsageConsumer`, and
batch-enables the requested services. Internal organization selection uses
`organizations.search(query='domain:<domain>')` and deliberately requires one
match rather than silently choosing. All long-running operations are polled
through each service's `operations.get` resource. `delete_project` uses Resource
Manager's recoverable project deletion API.

Workspace Add-ons is absent from Google's central discovery index. fastgws'
`GWSApi.from_discovery_url` fetches its authenticated discovery document from
`https://gsuiteaddons.googleapis.com/$discovery/rest?version=v1` and then builds
the normal dynamic client.

Google's IAP API can create OAuth clients programmatically, but those clients
are locked to IAP and do not support arbitrary redirect URIs. It therefore
cannot create the general-purpose Web client needed here. The Auth Platform UI
is the only CDP-controlled portion.

For an External app published without verification, use the repository as the
application homepage and privacy policy:

- `https://answerdotai.github.io/gclientid/`
- `https://answerdotai.github.io/gclientid/privacy/`

Add `answerdotai.github.io` to the consent screen's authorized domains. GitHub
blob URLs caused a generic branding-save failure, while the Pages URLs saved
successfully. This keeps setup independent of a particular developer's email.

The August 31, 2026 live Web OAuth check used
`https://oauth.appapis.org/redirect`, PKCE, state validation, offline access,
and the `max` preset. Authorization as `jhoward@gmail.com` succeeded without a
test-user allowlist, produced a refresh token, verified the returned UserInfo,
and wrote the standard account token. Google's token endpoint requires the Web
client secret despite PKCE, so `create_client` waits for the asynchronously
populated completion dialog and captures both values before dismissing it.

`create_client` implements the Auth Platform Console path. It initializes an External or Internal application as requested, configures the Pages branding URLs, adds every preset scope, publishes an External application, creates a Web client with both the fixed loopback and appapis redirect URIs, and writes Web-client JSON with mode `0600`. It waits on the visible API Services terms screen unless `accept_terms=True`. Normal Console waits default to 10 seconds; the terms screen retains its separate long human-interaction timeout.

The Data Access route is `/auth/scopes`, not `/auth/dataaccess`. Its manual scope box accepts one scope per line; adding the complete preset again is idempotent. The Console abbreviates most saved scope URLs in the accessibility tree, so `create_client` pastes the desired set rather than trying to reconstruct full URLs from displayed rows.

`authorize_google` creates a fresh state and PKCE verifier. Its default path opens OAuth in the supplied CDP connection (or the operating system's default browser for direct Python calls) and receives the response from a one-shot server bound to `127.0.0.1:53682`. The listener starts before the browser opens, serves one completion page, and closes after the callback; a bind failure directs the user to `--remote`. The remote path prints and opens an appapis URL, then reads the copied payload; `--no-open-browser` only prints it. The PKCE verifier never leaves the waiting process in either path. An email-valued `account` becomes Google's `login_hint`, and returned UserInfo is verified before saving token JSON with mode `0600`.

The CDP driver is a finite sequence, not a click loop: it selects one named account when offered, expands the unverified-app warning once when present, selects granular permissions once when present, and clicks at most one Continue and one Allow. Browser-native passkey prompts remain manual. Known Google OAuth error pages raise immediately instead of waiting for the callback timeout.

The redirect application displays only `code` and `state` on success, or Google's `error`, `error_description`, and `state` on failure. Extra callback parameters such as scopes and `authuser` are deliberately omitted from the copied payload. `_callback_code` requires exactly one of code or error and rejects a state mismatch before token exchange.

Before opening OAuth, `authorize_google` checks whether the saved refresh token matches the client, requested account, and requested scopes, then submits a refresh grant to Google. A missing, insufficient, or `invalid_grant` token makes the single authorization request include `prompt=consent`; a verified refresh token allows the lighter request and is retained if Google omits a new one. Authorization never starts a second browser or copy/paste round trip.

The August 27 `max` retest without forced consent still required a passkey and completed in 29.9 seconds after the user satisfied it. An immediate repeat completed in 3.1 seconds without a passkey or Chrome-profile prompt. Both attempts verified `j@answer.ai`, granted all 19 expected scopes, and returned a refresh token. Google therefore appears to require recent authentication for the broad grant rather than passkey authentication on every authorization; forced consent was not the sole trigger.

Broad scope grants can still trigger a native passkey or Touch ID prompt, followed by Chrome's prompt to create a browser profile for the web login. The user completes these browser-native controls while the CLI waits for the copied callback.

Resource Manager deletion is a soft deletion: the project becomes inaccessible
immediately but remains recoverable for 30 days before permanent deletion.

## fastcdp

Google Cloud Console's full accessibility-tree response was about 3.1 MB in the
initial live test. fastcdp must connect with `websockets.connect(...,
max_size=None)` rather than its former 1 MB default, or `ax_tree()` closes the
connection before returning.

Console route changes use fastcdp's normal `goto` load wait; they do not catch
navigation timeouts or infer readiness from post-hoc network silence. Save
actions do not navigate, so they wait for the page's Save control to settle (or
its error dialog) before reading the result.

Google Cloud's Angular routes render after the document load event. Auth setup
therefore waits for the Overview route's `OAuth Overview` accessibility heading
before checking whether its `Get started` link is present.

The support-email picker is a custom `cfc-select`: Chrome reports its disabled
state in the accessibility tree even though the element has no stable DOM
disabled or label attributes. Setup polls that AX property and returns the fresh
tree used for the click.

The live create/delete check used `gclientid-test-20260826-fcdc`. Google
confirmed that it is shut down and scheduled for permanent deletion after
September 25, 2026.
