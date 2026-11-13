# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A `package.json` with a `package-lock.json` beside it is relocked after an edit, with
  `npm install --package-lock-only --ignore-scripts`, and the two are committed together, as
  `uv.lock` already was. A workspace member's lock file at the workspace root is not refreshed. An
  `ERESOLVE` conflict holds the group back, like a uv lock with no solution.
- npm lock file updates, which move a dependency inside the range of its `package.json`, are applied
  with `npm install name@version` instead of held. `package.json` stays as it was. Other lock file
  updates are still held, and `--no-lock` holds them all.
- A group with nothing left to commit, because an earlier group of the run already made its change,
  is reported and passed over instead of failing the run.

### Fixed

- With `--major`, a dependency with a minor and a major on two branches no longer fails the major's
  group with "Was it already updated?". As after a Renovate rebase, the major is applied on top of
  the minor, in a second commit. Each later step of one line is applied on top of the step before
  it. For example, a minor follows a patch, and a major follows another major. Any other pair of
  updates to one line on two branches holds the later one.

## [0.1.1] - 2026-10-11

### Fixed

- A dependency with a new version and a new digest of its current version on the same branch no
  longer fails its group. As Renovate does, the first update is applied and the other is held.

## [0.1.0] - 2026-10-03

First release.

### Added

- `renovate-apply` (also `rnv`): run Renovate over the working copy, read the JSON report it writes,
  and make the edits it describes. One commit per Renovate branch, so a local run and a merged
  grouped pull request produce the same commits.
- The edit is Renovate's own auto-replace: the `replaceString` the manager found and the
  `autoReplaceStringTemplate` it would write back, with the same fallbacks for the managers that
  report one or neither. An update whose text is no longer in the file raises instead of guessing.
- `--dry-run` computes every edit and writes nothing. `--no-commit` writes the files and leaves them
  for one review.
- Majors are held back until `--major`, because the report does not say which of them a repository
  sends to the dependency dashboard for approval. Updates still waiting out `minimumReleaseAge` and
  dependency renames are held too, and everything held is listed with its reason.
- `--prefix` sets the first word of every commit subject, to match `commitMessagePrefix` or the
  semantic-commit type the repository's Renovate configuration uses.
- Any option can be set per repository under `[tool.renovate-apply]` in the `pyproject.toml` of the
  repository being updated, whichever directory the run was started from.
- `uv lock` runs after an edit to a `pyproject.toml` that has a `uv.lock` beside it, and both land
  in the same commit, so a repository whose CI installs with `--locked` stays installable.
  `--no-lock` turns it off.
- `--skip` holds a dependency back by name, as a glob, for the updates a repository sends to the
  dependency dashboard. The report does not say which those are, so naming them is the only way.
- The working copy must be clean before a run that commits, because a commit takes the whole index.
- Git hooks always run. A hook that refuses a commit stops the run and its output is reported.

[0.1.0]: https://github.com/jbsilva/renovate-apply/releases/tag/v0.1.0
[0.1.1]: https://github.com/jbsilva/renovate-apply/releases/tag/v0.1.1
[unreleased]: https://github.com/jbsilva/renovate-apply/compare/v0.1.1...HEAD
