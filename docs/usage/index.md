---
icon: lucide/terminal
---

# Usage

One command, a handful of flags. The default run scans the current directory, applies what it finds,
and makes one commit per group.

```bash
rnv
```

## The three modes

| Command           | What you get                                                  |
| ----------------- | ------------------------------------------------------------- |
| `rnv --dry-run`   | A list of what would change. Nothing is written.              |
| `rnv --no-commit` | The files are written. Nothing is committed. Read `git diff`. |
| `rnv`             | The files are written and committed, one commit per group.    |

All three compute every edit. A dry run is not a shallow check: if an edit cannot be placed, the dry
run says so, in the same words a real run would.

## Reading the output

```console
$ rnv
renovate-apply: scanning /home/you/infra ...
applied  deps: update the atuin images
    ghcr.io/atuinsh/atuin  v18.13.3 -> 18.22.0
    postgres               18-alpine, new digest

Held back:
  python -> 3.15 (skipped by configuration)

Committed. Nothing is pushed.
```

The bold line after `applied` is the commit subject. The lines under it are what moved, and they
become the commit body when a group holds more than one thing. Anything found but not applied is
listed under **Held back**, with the reason.

The last line tells you the state of the working copy: `Committed`, `Written, not committed`, or
`Nothing was written`.

## When a group cannot be applied

A group whose files no longer match the report is reported and passed over. The groups after it are
still applied and committed, and the run ends non-zero:

```console
renovate-apply: postgres: 'postgres:18-alpine' is not in stack/compose.yaml. Was it already updated?

1 of 2 groups could not be applied.
```

Nothing of that group is written, not even the files it could have edited. Each group is all of its
files or none of them.

Only a failure before the first group stops the whole run: a scan that would not start, or a working
copy that is not clean.

## The working copy must be clean

A run that commits needs a clean tree first, because a commit takes the whole index:

```console
renovate-apply: the working copy has changes to tracked files, and a commit would take them too.
Commit or stash them first:
 M stack/compose.yaml
```

Untracked files are fine and do not stop a run. The commit stages the files the run wrote, by name,
so nothing untracked can reach it.

## Next steps

- [Command reference](command-reference.md): every flag.
- [What is held back](held-back.md): the reasons an update is found but not applied.
