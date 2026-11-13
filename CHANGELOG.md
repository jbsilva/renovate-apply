# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-13

### Added

- npm: `package-lock.json` is relocked with its `package.json`. A workspace root lock file is not
  refreshed.
- Lock file updates, including transitive ones, are applied:
  `uv lock --upgrade-package name==version` for `uv.lock`, and `npm install name@version` for
  `package-lock.json`.
- With `--major`, each version step of a line is applied on top of the one before it, as after a
  Renovate rebase.
- A group that changes no file is reported as unchanged instead of failing the run.
- `--lock-maintenance` upgrades every `uv.lock` and `package-lock.json` in one more commit, as
  Renovate's lock file maintenance does.

### Changed

- The run must start at the top of the repository, where Renovate finds its configuration.
- An edit stops when the text it would change is in the file more often than the group edits it.
- `renovate-version` and `token` are no longer read from the repository's `pyproject.toml`.

### Fixed

- An edit could land in another dependency's line, such as `redis:7.2` in `bitnami/redis:7.2`.
- A gomod or npm digest update wrote the full hash where the file holds a short one.
- `{{packageName}}` rendered the dependency name, and template fields this tool does not know
  rendered as empty text. Templates that custom managers set on the package file were ignored.
- Only the first copy of a version in a `replaceString` moved.
- A regex manager's second copy of a line was held as a repeat and kept its old version.
- A failed write left a group half applied, and a file that is not UTF-8 stopped the run.
- Lock files that git does not track were relocked and committed.
- Paths with glob characters, such as `app/[id]`, also staged look-alike untracked files.
- An exported `GITHUB_COM_TOKEN` was replaced with an empty one when `gh` had none.
- Digest and pinned digest updates read as version moves.

### Removed

- The pending-hold bypass for `isVulnerabilityAlert`, which Renovate never reports.

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
[0.2.0]: https://github.com/jbsilva/renovate-apply/releases/tag/v0.2.0
[unreleased]: https://github.com/jbsilva/renovate-apply/compare/v0.2.0...HEAD
