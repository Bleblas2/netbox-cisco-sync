# Publishing

The package version is `1.0.1`. Keep `pyproject.toml`,
`netbox_cisco_sync/__init__.py`, and `COMPATIBILITY.md` in sync.

## Before making the repository public

- Review the full Git history for credentials and private data. Ignoring a
  file does not remove an already tracked file or its earlier revisions.
- Review screenshots and every GIF frame at full resolution. The current
  screenshots show an older UI and should be replaced with current demo views.
- Review the staged changes. Keep local environment files and agent notes out
  of the public commit. `.plan` is already tracked; its ignore rule alone does
  not remove it from Git.
- Run the Installation checks workflow on GitHub and require it to pass before release.
  Local checks do not confirm that the hosted workflow works.
- Confirm the license and attribution for adapted code.

## Package checks

Use a clean Python environment:

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Inspect the wheel and source archive. The wheel must contain the templates,
migrations, and license, and must not contain local configuration or credentials.
Run database tests only against an isolated test database or `netbox-demo`.

## Release

Configure a PyPI Trusted Publisher for this repository, the `publish.yml`
workflow, and the `pypi` GitHub environment. Review the environment protection
settings before enabling publication.

The publish workflow checks installation and migrations, builds and checks the package, and uploads it
to PyPI. Publishing a GitHub release or manually running that workflow starts
this process. Use the Installation checks workflow for validation without publication.
Regression tests remain local and are excluded from Git, the source archive,
and Docker builds. Run them in the local demo environment before release.

Use a release tag that matches the package version, such as `v1.0.1`, and
describe supported platforms, compatibility, and migration limits in its notes.
