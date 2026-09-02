# Development notes

gclientid owns the Google credential store, `$XDG_CONFIG_HOME/gclientid/`, and
`gclientid.creds` is its API: `client_file` and `token_file` name the files for
the `internal`/`desktop` axes, `oauth_creds`, `refresh_creds`, and `logout`
load, refresh, and revoke tokens, `token_name` reads the account and axes back
out of a token filename, and `reauth_cmd` and `reauthorize` turn that into the
`gclientid-auth` command or the same call in Python. fastgws depends on gclientid
and re-exports the token functions from `fastgws.auth`; gclientid imports
nothing from fastgws.

Automatic re-authorization is a store setting, not a library default: `provision`
writes `reauth = true` and `browser` into `config.ini`, `authorize_account`
refreshes `browser`, and `oauth_creds`/`refresh_creds` read them from the token's
own directory when `reauth=None`. Any `RefreshError` (a RAPT `Reauthentication is
needed` or an `invalid_grant`), a missing token, or missing scopes then runs one
`authorize_account` through `reauthorize`, which imports `cli` lazily to avoid
the cycle. A token outside a provisioned store, or `reauth=False`, raises with
the command instead. The September 2, 2026 live check broke the Desktop token's
refresh token by hand and `oauth_creds(account=..., desktop=True)` repaired it
through CDP Chrome without arguments.

`gclientid` uses Resource Manager and Service Usage directly over httpx2 when an
existing cloud-authorized `--owner` is available, including organization lookup,
project creation/deletion, operation polling, and API enablement. A run without
`--owner` finds or creates the project and enables its APIs through Cloud
Console. fastcdp also handles the remaining generic OAuth configuration and
client creation or update in the signed-in Console session.
Local account authorization uses CDP plus a one-shot loopback callback; remote
authorization uses the Web client through appapis copy/paste. No path
requires `gcloud`.

`connect_browser()` uses `CDP.connect(timeout=60)` by default. This connects to the normal Chrome profile after the developer enables **Allow remote debugging** in `chrome://inspect/#remote-debugging`; Chrome asks the developer to approve each new connection. `connect_browser(default_browser=False)` uses `CDP.remote()` and the dedicated CDP Chrome profile on port 9223. Both paths return `(cdp, page)` with a new tab, so setup never navigates the developer's focused tab away. fastcdp's `active_page()` skips `chrome://` and `devtools://` targets because Chrome accepts attachment but never answers page commands for them.

After initially adding this repository with `ws-add`, restart any persistent
Python/clikernel process so it sees the new workspace editable install.

## CLI

The `gclientid` entry point is `gclientid.cli:main`; `gclientid-auth` is `gclientid.cli:auth`. Both are thin `fastcore.script.call_parse` wrappers over `provision` and `authorize_account`, which take the same options as keyword arguments. `gclientid-auth` takes the account email as its positional argument. A bare `gclientid` converges the project, APIs, OAuth app, and Web client through Console, then stops. `gclientid --desktop` does the same for the Desktop client. `gclientid --owner <account>` uses Resource Manager and Service Usage for the project and APIs instead; the owner must already have a gclientid token containing `cloud-platform`. `gclientid --authorize` reuses its Console CDP connection for local authorization. A bare `gclientid-auth` connects to normal Chrome; `--cdp-chrome` selects the dedicated profile and `--remote` uses appapis without CDP. Files live directly under `$XDG_CONFIG_HOME/gclientid/` by default. `--output` replaces that directory; it does not add a project subdirectory.

The project is resolved in order: `--project`, the ID saved in `config.ini`, then `project_id(owner)`, which is `gclientids-` plus ten hex characters of a SHA-256 of the casefolded owner email (`-internal` appended for the Internal project). The owner is `--owner` when given, otherwise the email `console_account` reads from the Console banner. Project IDs are globally unique, so the hash keeps the default stable across machines while avoiding collisions between owners. `ensure_project_ui` checks the Console banner and creates the project only when the signed-in account cannot open it; `provision_project` does the same through Resource Manager. `enable_apis_ui` and `configure_app` are idempotent, and the client step creates a missing client or, for an existing Web client, registers any missing redirect URIs. `enable_apis_ui` reads the enabled services once from the APIs dashboard (the row links carry the service names) and opens only the missing API library pages, so a convergent re-run against a configured project spends a few seconds on APIs rather than one page load per API.

Provisioning writes `config.ini` using `fastcore.xdg.Config`. It records the project, name, default preset, custom scopes/APIs, and audience, separately from the client JSON files. The declared scopes and enabled APIs are always `MAX` plus the custom extras, so the saved preset only chooses what `gclientid-auth` requests by default; its own `--preset` overrides that and repeatable `--scope` values augment the saved scopes for one authorization. Without `config.ini`, `gclientid-auth` defaults to `google-apps`, which allows authorization from a client JSON created elsewhere. Presets are `Preset` records of scopes and APIs; `+` unions two in order, which is how the built-ins compose and how a caller defines a new one.

`--internal` selects the Internal OAuth audience and an independent local profile: `config-internal.ini`, `oauth-client-internal.json`, and `oauth-token-<account>-internal.json`. Google allows one consent audience per project, so the Internal project is separate; the Web and Desktop clients of one audience share a project and its declared scopes. `--desktop` adds `-desktop` to the client and token filenames, after `-internal` when both apply. The `workspace-addon` preset combines identity and `cloud-platform` scopes with Cloud Resource Manager, Service Usage, IAM, and Workspace Add-ons APIs. Internal apps skip publication because only External apps have the testing-to-production lifecycle.

Authorization stores one `oauth-token-<account>[-internal][-desktop].json` per verified Google account and client. Email characters safe in filenames remain readable; other characters are percent-encoded. Token files use google-auth's authorized-user format with the verified `account` field retained. A refresh token is bound to the client that issued it, which is why each client has its own token files.

The `max` preset is the union of `google-apps`, `developer`, and `workspace-admin`. It is the broadest built-in preset, not every scope and API offered by Google; new scopes and APIs developers need are added to it. `workspace-admin` includes the Enterprise License Manager API and its read/write licensing scope.

Without `--owner`, project creation and API enablement use the signed-in Console and need no prior gclientid credentials. The `--owner` token selects API provisioning instead. For an Internal app, its email domain selects the single visible Cloud organization and the project is created under that organization; Internal provisioning therefore requires `--owner`. The same email must be offered as a support address in the active Console session, preventing accidental client creation under a different login. `--account` on `gclientid --authorize`, or the positional email of `gclientid-auth`, selects the data account during OAuth and must be an email. The provisioning CLI closes its setup tab and CDP connection on success or failure, and never prints client secrets or OAuth tokens. Provisioning and authorization both confirm the output directory is writable before opening an OAuth flow or mutating Google-side state.

## Google Cloud project lifecycle

`cloud_creds(account)` loads the owner's stored authorized-user token, which
must carry `cloud-platform` access, for the Resource Manager v3 and Service Usage v1 calls.
`provision_project` searches projects by global project ID and is idempotent: it
creates a missing project, validates an existing Internal project's parent,
idempotently grants the owner `roles/serviceusage.serviceUsageConsumer`, and
batch-enables the requested services. Internal organization selection uses
`organizations.search(query='domain:<domain>')` and deliberately requires one
match rather than silently choosing. All long-running operations are polled
through each service's `operations.get` resource. `delete_project` uses Resource
Manager's recoverable project deletion API.

The API path is seven fixed REST calls (`projects:search`, `projects` create,
`operations` get, `projects` delete, `:getIamPolicy`, `:setIamPolicy`,
`services:batchEnable`) made with httpx2 through `_call`, which refreshes the
stored token when needed and raises Google's error body. `organizations:search`
and `projects:search` are GETs with a `query` parameter. A discovery-driven
client bought nothing for so few known endpoints, and using fastgws here would
put gclientid above the library that depends on it.

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

`configure_app` implements the idempotent Auth Platform Console path: it initializes an External or Internal application when the Overview route still offers `Get started`, configures the Pages branding URLs, declares the `max` scopes plus any extras, and publishes an External application. It waits on the visible API Services terms screen unless `accept_terms=True`. Normal Console waits default to 10 seconds; the terms screen retains its separate long human-interaction timeout.

`create_client` creates one Web or Desktop client and writes its JSON with mode `0600`, in Google's `web` or `installed` shape. Web clients register `REDIRECT_URIS`: the fixed loopback callback, the appapis redirect, and the fasthtml set `DEV_REDIRECT_URIS` (`localhost` and `127.0.0.1` on ports 5001, 5002, and 8000 at `/redirect`; Google matches host and port literally, so both hosts are needed). The redirect fields are `URIs <n>` textboxes inside the `Authorized redirect URIs` group, on both the create form and the client edit page, so `_add_redirect_fields` serves `create_client` and `add_redirects`. `add_redirects` reads the URIs Google currently holds from the edit page, adds only the missing ones, and rewrites the JSON list from that truth. Desktop clients have no redirect list; their JSON records Google's conventional `http://localhost`.

The Data Access route is `/auth/scopes`, not `/auth/dataaccess`. Its manual scope box accepts one scope per line; adding the complete preset again is idempotent. The Console abbreviates most saved scope URLs in the accessibility tree, so `configure_app` pastes the desired set rather than trying to reconstruct full URLs from displayed rows.

`authorize_google` creates a fresh state and PKCE verifier. Its default path opens OAuth in the supplied CDP connection (or the operating system's default browser for direct Python calls) and receives the response from a one-shot loopback server. A Web client binds the registered port `127.0.0.1:53682`; a Desktop client binds port 0 and uses whichever port it gets, which Google permits for `installed` clients. The listener starts before the authorization URL is built, serves one completion page, and closes after the callback; a bind failure directs the user to `--remote`. The remote path prints and opens an appapis URL, then reads the copied payload; `--no-open-browser` only prints it. Desktop clients cannot register the appapis redirect, so `remote=True` raises for them. The PKCE verifier never leaves the waiting process in either path. An email-valued `account` becomes Google's `login_hint`, and returned UserInfo is verified before saving token JSON with mode `0600`.

The CDP driver is a finite sequence, not a click loop: it selects one named account when offered, expands the unverified-app warning once when present, selects granular permissions once when present, and clicks at most one Continue and one Allow. Browser-native passkey prompts remain manual. Known Google OAuth error pages raise immediately instead of waiting for the callback timeout.

The redirect application displays only `code` and `state` on success, or Google's `error`, `error_description`, and `state` on failure. Extra callback parameters such as scopes and `authuser` are deliberately omitted from the copied payload. `_callback_code` requires exactly one of code or error and rejects a state mismatch before token exchange.

Before opening OAuth, `authorize_google` checks whether the saved refresh token matches the client, requested account, and requested scopes, then submits a refresh grant to Google. A missing, insufficient, or `invalid_grant` token makes the single authorization request include `prompt=consent`; a verified refresh token allows the lighter request and is retained if Google omits a new one. Authorization never starts a second browser or copy/paste round trip.

The August 27 `max` retest without forced consent still required a passkey and completed in 29.9 seconds after the user satisfied it. An immediate repeat completed in 3.1 seconds without a passkey or Chrome-profile prompt. Both attempts verified `j@answer.ai`, granted all 19 expected scopes, and returned a refresh token. Google therefore appears to require recent authentication for the broad grant rather than passkey authentication on every authorization; forced consent was not the sole trigger.

Broad scope grants can still trigger a native passkey or Touch ID prompt. The user completes those browser-native controls while the CLI waits for the callback. A Workspace login can also open `chrome://managed-user-profile-notice/`; `_open_cdp` watches Chrome targets during authorization, selects **Use Chrome without an account**, and reactivates the OAuth tab so that profile creation does not stall the flow.

Resource Manager deletion is a soft deletion: the project becomes inaccessible
immediately but remains recoverable for 30 days before permanent deletion.

## fastcdp

Google Cloud Console's full accessibility-tree response was about 3.1 MB in the
initial live test. fastcdp must connect with `websockets.connect(...,
max_size=None)` rather than its former 1 MB default, or `ax_tree()` closes the
connection before returning.

Console route changes use fastcdp's normal `goto` load wait; they do not catch
navigation timeouts or infer readiness from post-hoc network silence. Save
actions on the branding and scope pages do not navigate, so they wait for the
page's Save control to settle (or its error dialog) before reading the result.
Save on a client's edit page navigates back to the clients list, so
`add_redirects` uses `click_and_wait`.

Project existence is read from the Console banner: the project picker button
starts with `No project selected` when the signed-in account cannot open the
requested project. The signed-in email is read from the banner's `Account:`
button on the welcome route.

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
