---
icon: lucide/settings
---

# Configuration

Most of what shapes a run comes from your repository's own Renovate configuration, which the tool
reads by running Renovate. Grouping, package rules, versioning schemes and `minimumReleaseAge` all
apply without being restated here.

What is left is a handful of settings for this tool. You can pass them as flags every time, or write
them down once.

## Per-repository defaults

Put them under `[tool.renovate-apply]` in the `pyproject.toml` of the repository you are updating:

```toml
[tool.renovate-apply]
prefix = "build(deps):"
skip = ["python"]
major = true
```

The key is the flag name without its dashes, so `--no-lock` is `lock = false`. Underscores work too,
if you prefer `dry_run` to `dry-run`.

| Key                | Type           | Default   | Flag                 |
| ------------------ | -------------- | --------- | -------------------- |
| `dry-run`          | boolean        | `false`   | `--dry-run`          |
| `commit`           | boolean        | `true`    | `--no-commit`        |
| `stage`            | boolean        | `false`   | `--stage`            |
| `major`            | boolean        | `false`   | `--major`            |
| `lock`             | boolean        | `true`    | `--no-lock`          |
| `skip`             | list of string | empty     | `--skip`             |
| `prefix`           | string         | `"deps:"` | `--prefix`           |
| `renovate-version` | string         | unset     | `--renovate-version` |
| `token`            | string         | unset     | `--token`            |

!!! note

    The key for `--no-commit` is `commit`, not `commit_each`. Cyclopts derives the negative flag from
    the name, and the config reads that same name. An unknown key stops the run rather than being
    ignored, so a typo shows up straight away.

Two rules about which file is read:

- It is the `pyproject.toml` of the directory being updated, not of the directory you are standing
    in. `rnv ~/code/other-repo` takes that repository's settings.
- Only that one directory is read. A parent of it does not speak for it, so an infrastructure
    repository with no `pyproject.toml` just uses the built-in defaults.

A flag you type always wins over the file.

## Commit prefix

Every commit subject starts with `prefix`. The default is `deps:`. Match it to what your Renovate
configuration writes, so local commits and merged pull requests read alike:

| Your Renovate configuration    | Set                       |
| ------------------------------ | ------------------------- |
| `commitMessagePrefix: "deps:"` | `prefix = "deps:"`        |
| `semanticCommits: "enabled"`   | `prefix = "build(deps):"` |

## Holding a dependency back

`skip` takes glob patterns matched against the dependency name, and it is repeatable:

```bash
rnv --skip python --skip 'ghcr.io/internal/*'
```

This exists because of a blind spot. Renovate can be told to park some updates on the dependency
dashboard for approval by hand, and the report does not say which ones carry that flag. Majors are
held by default for the same reason. Naming a dependency in `skip` is how you cover the rest. See
[What is held back](../usage/held-back.md).

## GitHub token

Renovate looks up actions, hooks and release tags on GitHub. Without a token those lookups are rate
limited, and updates can quietly go missing.

The tool takes a token from three places, in this order:

1. `--token`, if you pass it.
2. `GITHUB_TOKEN` in the environment.
3. `gh auth token`, if `gh` is installed and logged in.

!!! warning

    Prefer `GITHUB_TOKEN` or `gh` over `--token`. A token on the command line goes into argv, which
    every process on the machine can read, and into your shell history.

The token is passed to Renovate through the environment as `GITHUB_COM_TOKEN`. It never reaches argv
unless you put it there yourself.
