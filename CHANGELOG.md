# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
