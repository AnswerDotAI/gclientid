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
