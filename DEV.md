# Development notes

`gclientid` drives an existing, signed-in Google Cloud Console tab through
fastcdp. It does not require `gcloud` and should not own the developer's Google
credentials.

After initially adding this repository with `ws-add`, restart any persistent
Python/clikernel process so it sees the new workspace editable install.

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
application homepage and
`https://github.com/AnswerDotAI/gclientid/blob/main/PRIVACY.md` as the privacy
policy. Add `github.com` to the consent screen's authorized domains. This keeps
the setup independent of a particular developer's email address.

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
