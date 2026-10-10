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

## Options

### `--dry-run`

Compute every edit, write nothing. Default off.

Use it first. It reports the same errors a real run would, so a dry run that passes is a good sign
the real one will too.

### `--no-commit`

Write the files and stop. Default is to commit.

For reviewing everything at once with `git diff` instead of reading one commit per group. The clean
working copy check is skipped, because nothing is committed.

### `--major`

Include major updates. Default off.

Majors are held back because the report does not say which of them your configuration sends to the
dependency dashboard. See [What is held back](held-back.md#majors).

### `--no-lock`

Do not run `uv lock` after editing a `pyproject.toml` that has a `uv.lock` beside it. Default is to
run it.

Use this when `uv` is not installed, or when you want to update the lock file yourself. The commit
will then hold a manifest whose lock file does not match it.

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
