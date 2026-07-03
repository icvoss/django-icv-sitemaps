# Releasing

How to cut a release for `django-icv-sitemaps`.

## TL;DR

```
branch  ->  PR  ->  review  ->  merge to main  ->  tag the merged commit  ->  CI publishes
```

The **tag is the trigger**. Pushing a tag of the form `v<semver>` runs the
publish workflow, which tests, builds, uploads to PyPI (OIDC trusted
publishing, no token required), and creates a GitHub release. **Tagging is
publishing. There is no separate "publish" step and no undo.**

## Canonical flow

1. **Branch** off `main`: `release/<version>` (e.g. `release/0.7.0`).
2. **Bump** on the branch:
   - `pyproject.toml` -> `version`
   - `src/icv_sitemaps/__init__.py` -> `__version__` (keep in sync)
   - `CHANGELOG.md` -> rename `[Unreleased]` to `[<version>] - <YYYY-MM-DD>`
3. **Open a PR** to `main`. CI runs lint and tests. Get it reviewed. This is
   the gate; do not skip it.
4. **Merge to `main`** (squash or merge, per your preference).
5. **Tag the merged commit on `main`** and push the tag:
   ```bash
   git checkout main && git pull
   git tag v<version>
   git push origin v<version>
   ```
6. **Watch the publish run** and confirm PyPI:
   ```bash
   gh run watch --exit-status
   curl -s https://pypi.org/pypi/django-icv-sitemaps/json | \
     python -c "import sys,json;print(json.load(sys.stdin)['info']['version'])"
   ```

> **Tag the commit that is on `main`, not a feature branch.** Tags point at
> commits, not branches, so tagging a feature branch will publish; but it
> publishes code that may never have been merged. Always tag after the merge so
> what is on PyPI is exactly what is on `main`.

## Tag format (strict)

`v<semver>` — a literal `v` followed by the version number.

Examples: `v0.7.0`, `v1.0.0`, `v1.2.3`.

The publish workflow matches `v*` and parses the version with `${TAG#v}`.

## Version files

The version must be kept in sync in two places:

- `pyproject.toml`: `version = "0.7.0"`
- `src/icv_sitemaps/__init__.py`: `__version__ = "0.7.0"`

A mismatch is a defect. Update both in the same commit.

## Versioning (SemVer)

[Semantic Versioning](https://semver.org/). Pre-1.0, the rules still apply
with the usual pre-1.0 caveat that minor bumps may carry breaking changes:

- **Patch** (`0.6.1 -> 0.6.2`): bug fixes, doc-only changes, no API or
  behaviour change.
- **Minor** (`0.6.1 -> 0.7.0`): new public API, any behaviour change (even a
  safer one), or a raised minimum dependency floor (e.g. Django).
- **Major** (`0.x -> 1.0`): the stability commitment; breaking changes after
  1.0.

If in doubt between patch and minor, choose minor. Burning a version number is
free; shipping a behaviour change as a patch surprises consumers.

## CHANGELOG (required, every release)

**A release must include a CHANGELOG entry for its version. No entry, no tag.**
CI enforces this: the publish workflow greps `CHANGELOG.md` for a heading
matching `## [<version>]` and exits with an error if it is absent.

Use [Keep a Changelog](https://keepachangelog.com/) format. Accumulate entries
under `## [Unreleased]` as you work; at release time, rename that heading to
`## [<version>] - <YYYY-MM-DD>`. Subsections: Added / Changed / Fixed / Removed.

Call out behaviour changes explicitly, including ones that are "safer". A
consumer relying on the old behaviour still needs to know.

The GitHub release body is generated from the tag (auto-generated notes), but
that is not a substitute for the curated CHANGELOG entry. Write the CHANGELOG
by hand so consumers reading the package on PyPI or GitHub get a human-authored
summary, not just a commit list.

## Django pin in the publish workflow

The `test` job in `.github/workflows/publish.yml` pins `Django~=5.1.0`. When
you raise the package's minimum Django in `pyproject.toml`, update the pin in
the same PR, or the tagged build's test job can fail to resolve dependencies
and block the publish.

## Pre-tag checklist

Before pushing the tag (the irreversible step):

- [ ] `CHANGELOG.md` has a `[<version>] - <date>` entry (renamed from
      `[Unreleased]`). Mandatory; every release ships with a changelog.
- [ ] Behaviour changes and breaking changes are called out in that entry.
- [ ] Version bumped in `pyproject.toml` and `src/icv_sitemaps/__init__.py`,
      and they match.
- [ ] Django pin in `publish.yml` matches the package minimum if the floor
      changed.
- [ ] Tests pass locally and the package builds (`python -m build`).
- [ ] The PR is merged to `main` and you are tagging that commit.
- [ ] Tag format is `v<version>` (e.g. `v0.7.0`).
- [ ] This exact version has never been published (PyPI rejects re-uploads).

## If something goes wrong

**PyPI rejects the upload (version exists).** That version is permanently
taken. You cannot re-upload, even after deleting. Bump to the next patch and
re-tag.

**The test or build job fails after tagging.** Nothing was published (publish
is the last job and depends on test and build). Fix on a new PR, merge, delete
the bad tag (`git push --delete origin v<version>`), and re-tag the new commit
with the same version (since nothing reached PyPI).

**Published, but the code is not on `main`.** Open a PR from the release branch
to `main` immediately and merge, so `main` reflects what is on PyPI. Avoid
this by always tagging after the merge.

## Optional hardening

Consider adding a **manual approval gate** to the `publish` job via a protected
GitHub Environment (`pypi`), so "push tag" and "irreversibly upload to PyPI"
are decoupled. A human approves the upload after seeing test and build go green.
The workflow already declares `environment: pypi`; add a required-reviewer
protection rule to that environment to enable the gate.
