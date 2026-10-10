# renovate-apply

[![MIT License](https://img.shields.io/badge/license-MIT-007EC7.svg?style=flat-square)](https://github.com/jbsilva/renovate-apply/blob/main/LICENSE)
[![Python 3.15+](https://img.shields.io/badge/python-3.15+-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/renovate-apply.svg?style=flat-square)](https://pypi.org/project/renovate-apply)
[![tests](https://github.com/jbsilva/renovate-apply/actions/workflows/tests.yml/badge.svg)](https://github.com/jbsilva/renovate-apply/actions/workflows/tests.yml)
[![CodeQL](https://github.com/jbsilva/renovate-apply/actions/workflows/codeql.yml/badge.svg)](https://github.com/jbsilva/renovate-apply/actions/workflows/codeql.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=jbsilva_renovate-apply&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=jbsilva_renovate-apply)
[![codecov](https://codecov.io/github/jbsilva/renovate-apply/graph/badge.svg)](https://codecov.io/github/jbsilva/renovate-apply)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![prek](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/j178/prek/master/docs/assets/badge-v0.json)](https://github.com/j178/prek)

Apply the dependency updates [Renovate](https://docs.renovatebot.com) finds, in your working copy,
without a pull request. One commit per group, the same grouping your Renovate configuration gives a
pull request. Nothing is pushed.

```console
$ rnv
renovate-apply: scanning /home/you/infra ...
applied  deps: update the atuin images
    ghcr.io/atuinsh/atuin  v18.13.3 -> 18.22.0
    postgres               18-alpine, new digest
applied  deps: update the hook revs
    astral-sh/ruff-pre-commit  v0.16.5 -> v0.16.8
    crate-ci/typos             v1.50.1 -> v1.50.2

Committed. Nothing is pushed.
```

## Why this exists

Renovate can read a local working copy. `renovate --platform=local` finds every pending update and
reports it. It cannot write one: the local platform turns the run into a lookup-only dry run as it
starts, so the run ends after the lookup, before the step that edits a file. No flag turns that off,
because the clamp is inside the platform, not in the configuration.

So the updates Renovate finds on your laptop can only be applied by hand, or by merging the pull
requests it opens on the server. This tool is the missing half: it runs that same scan, reads the
JSON report, and makes the replacement the report describes for each update.

The edit is not guesswork. For every dependency, the report carries `replaceString`, the exact text
the manager found in the file, and `autoReplaceStringTemplate`, how to write that text again with
the new version or digest in it. That pair is Renovate's own auto-replace, handed over as data.

## Highlights

- Works with everything Renovate's own managers report: image tags and digests in compose files and
  Dockerfiles, GitHub Actions SHA pins with their version comment, pre-commit and prek hook revs,
  versions matched by a custom regex manager, and the rest
- One commit per Renovate branch, so a grouped pull request and a local run produce the same commits
- Refreshes `uv.lock` when it raises a floor in `pyproject.toml`, and commits the two together, the
  way Renovate's own pull request carries them
- Reads your repository's Renovate configuration by running Renovate itself, so grouping, holds,
  package rules and versioning schemes all apply without being restated here
- Holds every major back until you ask for it
- Never skips your git hooks, and never commits anything it did not write
- `--dry-run` to read first, `--no-commit` to review everything at once

## Requirements

- Python 3.15+
- `git`
- Either `renovate` on `PATH` (`npm i -g renovate`) or Node.js, for `npx` to fetch it
- Optional: [`gh`](https://cli.github.com), logged in. Without a token, everything Renovate looks up
  on GitHub is rate limited, and updates can silently go missing.

## Installation

```sh
uv tool install renovate-apply
```

Or run it without installing:

```sh
uvx renovate-apply --dry-run
```

## Usage

```console
$ renovate-apply --help
```

| Command                       | What it does                                              |
| ----------------------------- | --------------------------------------------------------- |
| `rnv`                         | Scan, apply, one commit per group                         |
| `rnv --dry-run`               | Say what would change and write nothing                   |
| `rnv --no-commit`             | Write the files and stop, for one review of everything    |
| `rnv --major`                 | Include the major updates, which are held back by default |
| `rnv --skip python`           | Hold a dependency back by name, as a glob, repeatable     |
| `rnv --prefix "build(deps):"` | Set the first word of every commit subject                |
| `rnv --no-lock`               | Do not refresh `uv.lock` after editing a `pyproject.toml` |
| `rnv ~/code/other-repo`       | Work on another repository                                |

`renovate-apply` and `rnv` are the same command.

The working copy must be clean before a run that commits: a commit takes the whole index, not only
the files this staged, so anything else in flight would be swept into a dependency commit.

### Commit messages

The subject says what a person needs in `git log --oneline`; the body lists the group, aligned:

```text
deps: update the action pins

astral-sh/setup-uv          v10.1.0 -> v10.2.0
github/codeql-action        v4.38.0 -> v4.38.2
docker/setup-buildx-action  v4.3.0 -> v4.4.1
actions/upload-artifact     v7.0.1 -> v7.0.2
```

Match `--prefix` to what your `renovate.json5` writes, so local commits and merged pull requests
read alike: `deps:` for `commitMessagePrefix`, `build(deps):` for semantic commits.

### Per-repository defaults

Any option can be set once, in the `pyproject.toml` of the repository being updated:

```toml
[tool.renovate-apply]
prefix = "build(deps):"
skip = ["python"]
```

The file is read from the directory being updated, so `rnv ~/code/other-repo` takes that
repository's settings and not those of wherever you happen to be standing. Only that directory is
read, never a parent of it, and a flag typed for one run wins over the file.

A repository without a `pyproject.toml` (an infrastructure repository, say) passes the flags
instead.

## What is held back

Nothing is applied silently past a hold. Whatever is held is listed at the end of the run, with the
reason:

- **Majors**, unless `--major`. Renovate can be configured to send some majors to the dependency
  dashboard to be approved by hand. The report does not say which ones carry that flag, so holding
  every major is the only reading that cannot contradict your configuration.
- **Updates Renovate would not open yet**, the ones still waiting out `minimumReleaseAge`. A
  security fix bypasses that hold in Renovate, and bypasses it here too.
- **Renames**, where Renovate wants to replace a dependency with a different one. That edit is not a
  version bump, and this tool does not write it.
- **Lock file updates**, where the range in the manifest already allows the new version, so only the
  lock file beside it moves. There is no edit to make in the package file, and moving the lock file
  takes that package manager. Only `uv.lock` is refreshed here, after an edit to its manifest.
- **A line two managers found**, when a regex manager in your Renovate configuration matches a line
  a built-in manager also reads. Renovate reports the line twice. The first update makes the edit,
  and the second is listed with it.
- **Anything named in `--skip`**, as a glob. That is the answer to the blind spot above on an update
  that is not a major: a repository that keeps `requires-python` on the dependency dashboard writes
  `skip = ["python"]` once and stops being asked.

## Limits

- **`dependencyDashboardApproval` is invisible.** Renovate resolves it per package and the report
  does not carry it, so this tool cannot see which updates your configuration wants approved by
  hand. Holding every major covers the usual case; `--skip` covers the rest.
- **Lock files: uv only.** A `pyproject.toml` with a `uv.lock` beside it is relocked and committed
  together. Any other package manager's lock file is left untouched, so run its update yourself.
- **Renovate's lock file maintenance is not applied.** Those branches carry no dependency updates,
  so they are not in the report at all.
- **A group that cannot be applied is reported and passed over.** The groups after it are still
  applied and committed, and the run ends non-zero. Only a failure before the first group, such as a
  scan that did not run or a working copy that is not clean, ends the run with nothing done.
- The scan is a full Renovate run, so it takes as long as Renovate takes, usually under a minute.
- A dependency Renovate cannot look up is one this cannot apply. Everything upstream of the report
  is Renovate's own behavior, configuration included.
- This writes files and commits. It never pushes, never merges and never deploys.

## Development

```sh
uv sync --group dev --group test
uv run pytest
uv run poe check
```

## License

MIT. See [LICENSE](LICENSE).
