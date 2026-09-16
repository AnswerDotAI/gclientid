# Working with gclientid

Use `kernel-notebook-editing` and fastcdp for semi-interactive setup. Call the public Python functions from a persistent kernel rather than asking the human to run the CLI.

## Learn the workflow from source

Read `README.md` for product choices, then read the Python implementation:
- `gclientid/cli.py`: `provision` and `authorize_account` define the automated process, defaults, settings, and file handoff.
- `gclientid/oauth.py`: browser operations and authorization. `setup_auth`, `set_branding`, `set_scopes`, and `publish_app` are public alternatives to the combined `configure_app`.
- `gclientid/projects.py`: project lookup/creation, IAM, enabled-service checks, and batch enablement.
- `gclientid/creds.py` and `config.py`: credential loading, path/profile conventions, and configuration.
- `gclientid/__init__.py`: the public operation menu.

Use those functions as building blocks according to the state you find. The source is the workflow reference; do not maintain a second implementation or step-by-step recipe in this file. `DEV.md` records Console-specific findings.

## CDP Chrome and the human

`fastcdp-setup` creates the CDP Chrome launcher using installed Chrome. On macOS it is `~/Applications/CDP Chrome.app`. It uses port 9223 and a persistent profile separate from normal Chrome. `fastcdp-setup --install` installs Chrome for Testing instead.

Reuse an existing installation/session. Handle launcher setup, browser opening, and navigation to `https://console.cloud.google.com/` yourself with the available tools and permissions. Ask the human to complete sign-in only if it is needed. Whenever a passkey or other verification prompt appears, notify the human and wait.

Use the sole signed-in account without a confirmation question unless it conflicts with the request or saved setup. Ask only about unresolved account or use-case choices. Apply existing settings and the code's defaults rather than turning flags into a questionnaire. ToS acceptance defaults to automatic because staff have already accepted the terms.

## Local findings worth knowing

- `No project selected` briefly appears while existing projects load. Use the resolved-state check in `project_exists_ui`; an inaccessible project can also look absent.
- `create_client` checks for local JSON, not for an existing remote client. Missing local credentials are not a reason to create a duplicate. Inspect the Console's client list when recovering an existing setup.
- `create_client` and `authorize_google` return secret-bearing dictionaries. Assign their results rather than displaying them in the kernel. Use the file/path helpers and config-writing pattern in the source.
