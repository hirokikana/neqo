# Publishing NEQO

PyPI publication uses GitHub Actions OIDC Trusted Publishing. No long-lived PyPI
API token or repository secret is needed.

The publisher configuration on PyPI must match:

| Setting | Value |
| --- | --- |
| PyPI project | `neqo` |
| GitHub owner | `hirokikana` |
| Repository | `neqo` |
| Workflow filename | `release.yml` |
| GitHub environment | `pypi` |

The GitHub repository must have the `pypi` environment. If its deployment rules
restrict refs, allow release tags such as `v0.1.0`. A required environment reviewer
can be configured when manual release approval is desired.

## Release procedure

1. Update both `project.version` in `pyproject.toml` and `neqo.__version__` in
   `src/neqo/__init__.py`, then run `uv lock`.
2. Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`,
   `uv build`, and `uv run twine check dist/*`.
3. Commit and push the release changes to `main`; confirm CI succeeds.
4. Create and push the matching version tag:

   ```bash
   git tag -a v0.1.0 -m "NEQO 0.1.0"
   git push origin v0.1.0
   ```

The `Release` workflow tests Python 3.11, 3.12 and 3.13 and checks that the tag,
package version and Python API version agree. It builds a wheel and sdist, checks
their metadata, and installs the built wheel in a fresh environment for a CLI
smoke test. Only these artifacts pass to the publish job, which has OIDC permission
and uses the `pypi` environment. The publish job does not check out or build code.

Check the workflow and <https://pypi.org/project/neqo/> after publication. Test
installation from PyPI in a fresh environment using `pip install 'neqo[duckdb]'`
and `neqo query 'SELECT 42 AS answer' --json`.

PyPI does not allow reusing an uploaded distribution filename. For changed code,
release a new version instead of moving an existing tag. If publishing fails
before upload, correct the publisher configuration and rerun the failed job.
Publication happens on tag pushes; ordinary branch pushes and pull requests
run CI without publishing. The workflow creates a PyPI release, not a GitHub
Release page; the version tag is available on GitHub.

Official reference: [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/).
