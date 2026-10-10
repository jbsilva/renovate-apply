---
icon: lucide/house
---

# renovate-apply

Renovate can read a local working copy and tell you every update it would make. It cannot make one.
`renovate-apply` is the missing half: it runs that scan, reads the report, and writes the changes
the report describes. One commit per group, the same grouping your Renovate configuration gives a
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

## Why it exists

`renovate --platform=local` finds every pending update and reports it. It never writes one. The
local platform turns the run into a lookup-only dry run as it starts, so the run ends after the
lookup and before the step that edits a file. No flag turns that off, because the clamp sits inside
the platform and not in the configuration.

So the updates Renovate finds on your laptop can only be applied by hand, or by merging the pull
requests it opens on the server. This tool does the writing.

The edit is not guesswork. For every dependency the report carries `replaceString`, the exact text
the manager found in the file, and `autoReplaceStringTemplate`, how to write that text again with
the new version in it. That pair is Renovate's own auto-replace, handed over as data. See
[How it works](how-it-works/index.md).

## Highlights

- Works with everything Renovate's managers report: image tags and digests, GitHub Actions SHA pins
    with their version comment, pre-commit and prek hook revs, versions matched by a custom regex
    manager, and the rest.
- One commit per Renovate branch, so a local run and a merged grouped pull request produce the same
    commits.
- Refreshes `uv.lock` when it raises a floor in `pyproject.toml`, and commits the two together.
- Reads your repository's Renovate configuration by running Renovate itself, so grouping, holds,
    package rules and versioning schemes all apply without being restated here.
- Holds every major back until you ask for it.
- Never skips your git hooks, and never commits anything it did not write.
- Never leaves a `pyproject.toml` that does not lock: such a group is undone and held back.
- `--dry-run` to read first, `--no-commit` or `--stage` to review everything at once.

## Quick start

Install it with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install renovate-apply
```

Then read what it would do, without writing anything:

```bash
rnv --dry-run
```

!!! tip

    `renovate-apply` needs `git` and either `renovate` on your `PATH` or Node.js for `npx` to fetch it.
    See [Installation](getting-started/installation.md).

## Where to go next

- [Getting started](getting-started/index.md): install the tool and set its defaults.
- [Usage](usage/index.md): every flag, and what the tool holds back.
- [How it works](how-it-works/index.md): the scan, the edit, and the commit.
- [Development](development/index.md): set up the project, run the tests, keep the checks green.
- [License](license.md): MIT.
