# gclientid

Create Google OAuth desktop client IDs locally, without requiring `gcloud`.

The first implemented primitives create and delete Google Cloud projects through
an existing signed-in Chrome session:

```python
from gclientid import create_project, delete_project

await create_project(page, 'globally-unique-project-id', name='gclientids')
await delete_project(page, 'globally-unique-project-id')
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
