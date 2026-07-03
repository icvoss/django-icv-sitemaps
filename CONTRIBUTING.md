# Contributing to django-icv-sitemaps

Practical guide for contributors.

---

## Prerequisites

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Django 5.1 or later (installed as part of the dev setup)

No database server is required. The test suite uses SQLite.

---

## Local Development Setup

```bash
git clone https://github.com/nigelcopley/django-icv-sitemaps.git
cd django-icv-sitemaps

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install the package and dev dependencies
pip install -e ".[dev]"
pip install "Django~=5.1" pytest pytest-django pytest-cov factory-boy httpx
```

---

## Running Tests

Tests live in `tests/` and use pytest with `DJANGO_SETTINGS_MODULE=settings`.

```bash
DJANGO_SETTINGS_MODULE=settings PYTHONPATH=src:tests pytest tests/ -v --tb=short
```

Or simply `pytest tests/` if `pyproject.toml` is picked up automatically
(the `[tool.pytest.ini_options]` section sets both env vars).

---

## Code Standards

All Python code is linted and formatted with [ruff](https://docs.astral.sh/ruff/),
configured in `pyproject.toml`.

| Setting | Value |
|---------|-------|
| Line length | 120 |
| Quote style | Double |
| Target Python | 3.11 |

```bash
ruff check .              # lint
ruff format .             # format in place
ruff format --check .     # check formatting without writing (what CI runs)
```

CI will fail if either check reports errors. Run both before pushing.

---

## Package Structure

```
django-icv-sitemaps/
    src/icv_sitemaps/       # importable package
    tests/
        settings.py         # Django settings for the test suite
    CHANGELOG.md
    README.md
    pyproject.toml          # package metadata, dependencies, tool config
    RELEASING.md
```

---

## Git Workflow

### Commits

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>
```

| Type | When to use |
|------|-------------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `chore` | Maintenance, version bumps, dependency updates |
| `docs` | Documentation only |
| `test` | Adding or updating tests |
| `style` | Formatting, whitespace, no logic change |
| `refactor` | Code change that is neither a fix nor a feature |

Scope is optional for a single-package repo; use it when it adds clarity
(e.g. `fix(redirects): handle empty path in prefix match`).

### Branches and PRs

Push feature branches and open a pull request against `main`. CI must pass
before merging. Prefer small, focused commits over large ones.

---

## Releasing

See [RELEASING.md](RELEASING.md) for the full release flow.

The short version:

1. Bump the version in `pyproject.toml` and `src/icv_sitemaps/__init__.py`.
2. Update `CHANGELOG.md` (rename `[Unreleased]` to `[<version>] - <date>`).
3. Open a PR, get it reviewed, merge to `main`.
4. Tag the merged commit: `git tag v<version> && git push origin v<version>`.

The tag push triggers the publish workflow in CI.
