---
icon: lucide/list
---

# Command reference

`renovate-apply` and `rnv` are the same command.

```text
rnv [DIRECTORY] [OPTIONS]
```

Every flag here can also be a default in `pyproject.toml`. See
[Configuration](../getting-started/configuration.md#per-repository-defaults).

## Argument

### `DIRECTORY`

The repository to update. Defaults to the current directory.

```bash
rnv ~/code/other-repo
```

The directory also decides which `pyproject.toml` is read for defaults.

The directory must be the top of the repository. Renovate reads its configuration only from there,
so a run from a subdirectory stops with this message:

```console
renovate-apply: /code/repo/services is inside the repository at /code/repo. Renovate reads its configuration only from the top, so run this there: rnv /code/repo
```

## Options

### `--dry-run`

Compute every edit, write nothing. Default off.

Use it first. It reports every edit that cannot be made, as a real run does. It does not run uv or
npm, so it does not find a missing package manager, a missing lock file, or a lock file with no
solution. A real run reports those.

### `--no-commit`

Write the files and stop. Default is to commit.

For reviewing everything at once with `git diff` instead of reading one commit per group. The clean
working copy check is skipped, because nothing is committed.

### `--stage`

Write the files and stage them, one group after the other, and commit nothing. Default off.

For reviewing everything at once with `git diff --cached`. The index then holds the run's edits and
the matching lock files, apart from anything else in your tree. `--stage` implies `--no-commit`, and
`--dry-run` wins over it. The clean working copy check is skipped, because nothing is committed.

!!! warning

    If a file the run edits already holds a change of yours, staging it stages your change too.

### `--major`

Include major updates. Default off.

Majors are held back because the report does not say which of them your configuration sends to the
dependency dashboard. See [What is held back](held-back.md#majors).

### `--no-lock`

Do not refresh the lock file beside an edited manifest: `uv lock` for a `pyproject.toml` with a
`uv.lock`, and `npm install --package-lock-only` for a `package.json` with a `package-lock.json`.
Default is to refresh it.

Use this when `uv` or `npm` is not installed, or when you want to update the lock file yourself. The
commit will then hold a manifest whose lock file does not match it, and a group that does not lock
is not held back. See [Updates that do not lock](held-back.md#updates-that-do-not-lock).

### `--lock-maintenance`

After the groups, move every dependency in each lock file to the newest version its manifest allows,
as Renovate's lock file maintenance does. Default off, because the report does not say whether your
configuration turns lock file maintenance on. `--no-lock` turns it off too. See
[Lock file maintenance](../how-it-works/commits.md#lock-file-maintenance).

### `--skip PATTERN`

Hold a dependency back by name. Repeatable, and the pattern is a glob:

```bash
rnv --skip python --skip 'ghcr.io/internal/*'
```

Matched against the dependency name as Renovate reports it: `ghcr.io/atuinsh/atuin` for an image,
`crate-ci/typos` for a hook, `ruff` for a Python package.

### `--prefix TEXT`

The first word of every commit subject. Default `deps:`.

```bash
rnv --prefix "build(deps):"
```

### `--renovate-version VERSION`

The npm version of Renovate to run. Without it, a `renovate` on your `PATH` is used, and otherwise
`npx` fetches the latest.

```bash
rnv --renovate-version 43.224.0
```

Asking for a version always goes through `npx`, because whatever is installed is whatever it is.

### `--token TOKEN`

A GitHub token. Also read from `GITHUB_TOKEN`, and otherwise from `gh auth token`.

!!! warning

    A token on the command line lands in argv and in your shell history. Set `GITHUB_TOKEN` instead, or
    log in with `gh` and pass nothing.

### `--version`, `--help`

Print the version, or the help.

## Exit codes

| Code | Meaning                                                              |
| ---- | -------------------------------------------------------------------- |
| `0`  | Everything applied, or there was nothing to apply.                   |
| `1`  | The run could not start, or at least one group could not be applied. |

A run that applies three groups and fails on a fourth exits `1`. The three are still committed.

A held-back update is not a failure. That includes a group that `uv lock` or `npm install` finds no
solution for.
