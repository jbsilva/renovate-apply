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
- A group that changes no file, for example because an earlier group of the run already made its
  change, is reported as unchanged and passed over instead of failing the run.

### Fixed

- With `--major`, a dependency with a minor and a major on two branches no longer fails the major's
  group with "Was it already updated?". As after a Renovate rebase, the major is applied on top of
  the minor, in a second commit. Each later step of one line is applied on top of the step before
  it. For example, a minor follows a patch, and a major follows another major. Any other pair of
  updates to one line on two branches holds the later one.
- A lock file that git does not track is no longer refreshed or committed. Before, an ignored
  `uv.lock` beside an edited `pyproject.toml` stopped the run when `git add` refused it, and an
  untracked one entered the commit as a new file. A lock file update for such a file is held back.

- A replacement template that uses `{{packageName}}` now gets the package name from the report.
  Before, it got the dependency name, so a regex manager that names a dependency apart from its
  image wrote the wrong image.
- An update that the report gives no `replaceString`, as for npm and pep621, now edits the version
  that follows its own name. Before, a name in a script or inside a longer name, such as `eslint` in
  `@typescript-eslint/parser`, sent the edit to another dependency's line. If the name is not in the
  file, the group fails instead of editing the first copy of the version.
- When a regex manager finds two copies of a line and a built-in manager finds only the first, the
  second copy is now updated. Before, it was held as a repeat of the first copy, and it kept its old
  version.
- A custom `regex` or `jsonata` manager's `autoReplaceStringTemplate` is now used. Renovate reports
  it on the package file, and this tool read it only on each dependency, so it substituted the
  version into the old text instead.
- A template that names a field this tool does not carry, such as `{{{datasource}}}`, now fails its
  group. Before, the field rendered as empty text, and the edited line lost that part.
- A `replaceString` with no template that holds the version twice, such as a download URL, now has
  both copies moved, as Renovate moves them. Before, only the first one moved.
- If a group cannot write one of its files, for example a read-only file, the files it already wrote
  are put back. Before, they stayed edited, and the next group that touched them committed the edit
  under its own message.
- A package file that is not valid UTF-8 now fails only the group that edits it. Before, the run
  stopped with a traceback, and the groups after it were never tried.

  that follows its own name. Before, a name elsewhere sent the edit to another dependency's line: in
  a script, inside a longer name such as `@typescript-eslint/parser` for `eslint`, or inside an npm
  alias or a Cargo rename that names the package. If the name is not in the file, the group fails
  instead of editing the first copy of the version. A version also no longer matches part of a
  longer one, such as `==4.2` in `==4.2.11`. If the number of copies that follow the name differs
  from the number the group edits, the group fails instead of editing the first copy. An npm update
  looks only under its own `depType`, so `devDependencies` and `peerDependencies` with one range are
  told apart. A Cargo update looks only in the tables of its own `depType`, and a YAML version only
  in the list item of its own name.
- When a regex manager finds two copies of a line and a built-in manager finds only the first, the
  second copy is now updated. Before, it was held as a repeat of the first copy, and it kept its old
  version.
- A custom `regex` or `jsonata` manager's `autoReplaceStringTemplate` is now used. Renovate reports
  it on the package file, and this tool read it only on each dependency, so it substituted the
  version into the old text instead.
- A template that names a field this tool does not carry, such as `{{{datasource}}}`, now fails its
  group. Before, the field rendered as empty text, and the edited line lost that part.
- A `replaceString` with no template that holds the version twice, such as a download URL, now has
  both copies moved, as Renovate moves them. Before, only the first one moved.
- If a group cannot write one of its files, for example a read-only file, the files it already wrote
  are put back. Before, they stayed edited, and the next group that touched them committed the edit
  under its own message.
- A package file that is not valid UTF-8 now fails only the group that edits it. Before, the run
  stopped with a traceback, and the groups after it were never tried.
- A lock file that git does not track is no longer refreshed or committed. Before, an ignored
  `uv.lock` beside an edited `pyproject.toml` stopped the run when `git add` refused it, and an
  untracked one entered the commit as a new file. A lock file update for such a file is held back.
- A package file in a directory whose name holds glob characters, such as `app/[id]/package.json`,
  is now staged by its name only. Before, git also staged an untracked file that the name matched as
  a pattern, such as `app/i/package.json`.
- A run from a subdirectory of a repository now stops and names the top of the repository. Before,
  Renovate missed the repository's configuration there and ran with its defaults, so updates that
  the configuration ignores or groups apart were applied.
- A `GITHUB_COM_TOKEN` exported for Renovate is now passed on when `gh` gives no token. Before, it
  was replaced with an empty token, and Renovate's GitHub lookups were rate limited.
- A `pinDigest` update now reads "pin the X digest" and "v4, digest pinned". Before, it read "update
  X to v4" and "v4 -> v4", as if the version moved.
- The terminal now aligns the names of a group's dependencies, as the commit body and the examples
  in the docs do.

### Removed

- The rule that applied an `isVulnerabilityAlert` update while it was pending. Renovate does not put
  that flag on a reported update, so the rule never ran. Renovate does not make a security fix wait
  for `minimumReleaseAge`, so such a fix is not pending in the report.

### Removed

- The rule that applied an `isVulnerabilityAlert` update while it was pending. Renovate does not put
  that flag on a reported update, so the rule never ran. Renovate does not make a security fix wait
  for `minimumReleaseAge`, so such a fix is not pending in the report.

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
