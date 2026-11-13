---
icon: lucide/git-commit-horizontal
---

# Commits and lock files

## One commit per group

Updates are grouped by the branch Renovate would have opened. Each group is one commit, over its own
set of files. A grouped pull request merged on the server and a local run produce the same history.

## The message

The subject says what a person needs in `git log --oneline`. The body lists the group, aligned:

```text
deps: update the action pins

astral-sh/setup-uv          v10.1.0 -> v10.2.0
github/codeql-action        v4.38.0 -> v4.38.2
docker/setup-buildx-action  v4.3.0 -> v4.4.1
actions/upload-artifact     v7.0.1 -> v7.0.2
```

A group that moves one thing says everything in its subject already, so it gets no body.

The subject is picked by what the group holds:

| The group                             | Subject                         |
| ------------------------------------- | ------------------------------- |
| One dependency                        | `update <name> to <version>`    |
| One dependency, only the digest moved | `update the <name> digest`      |
| Several images in one directory       | `update the <directory> images` |
| Several images at the repository root | `update the images`             |
| Only pre-commit hooks                 | `update the hook revs`          |
| Only GitHub Actions                   | `update the action pins`        |
| Anything else                         | `update <branch name>`          |

A dependency used twice is named once. Two jobs running the same action is two edits but one thing
to say about it.

Set the first word with [`--prefix`](../usage/command-reference.md#-prefix-text).

## What gets staged

Only the files the run wrote, by name:

```bash
git add -- stack/compose.yaml uv.lock
git commit -m "<subject>" -m "<body>"
```

`git commit` takes the index, not the working tree, which is why a run that commits wants a clean
tree first. Untracked files cannot reach the commit and do not block the run.

With `--stage`, the run does the `git add` for each group and stops there, so you can read
everything with `git diff --cached` and commit it yourself.

## Hooks always run

Your git hooks run on every commit. They are never skipped, and `--no-verify` is never passed.

A hook that rewrites a file is a reason to stop, not a reason to bypass it. When a commit fails, the
run says what git and the hook said, and leaves the tree exactly as they left it:

```console
renovate-apply: the commit failed, most likely a hook. The files are written and staged,
and nothing was undone:
...
```

## Lock files

Renovate does not stop at the manifest. After it raises a version in `pyproject.toml` or
`package.json`, it runs the package manager to update the lock file, and both land in the same
commit. A run that skipped that would leave the lock file describing the old version, and any CI
installing with `uv sync --locked` or `npm ci` would fail on the commit this tool just made.

So when an edited manifest has its lock file beside it, the package manager runs in that directory
before the commit, and the two are committed together:

| Manifest         | Lock file           | Command                                                                 |
| ---------------- | ------------------- | ----------------------------------------------------------------------- |
| `pyproject.toml` | `uv.lock`           | `uv lock`                                                               |
| `package.json`   | `package-lock.json` | `npm install --package-lock-only --ignore-scripts --no-audit --no-fund` |

The npm command writes only the lock file. It does not create `node_modules` and does not run
install scripts.

```console
applied  deps: update cyclopts to 4.26.0
    cyclopts  4.25.3 -> 4.26.0
    uv.lock  refreshed
```

Only uv and npm are handled. Any other lock file, such as `yarn.lock` or `pnpm-lock.yaml`, is left
alone; run its update yourself.

A manifest in a subdirectory is relocked in that subdirectory, not at the repository root.

A lock file that git does not track is left alone. For example, a library can list
`package-lock.json` in `.gitignore`. Renovate still reads that file from disk, but the commit does
not carry it. A lock file update for it is held back.

The tool looks for the lock file only beside the manifest. In an npm or uv workspace, the members
share one lock file at the workspace root. An edit to a member then leaves that lock file as it was.
If your CI installs with `npm ci` or `uv sync --locked`, refresh the root lock file yourself before
you push.

### Lock file updates with npm

A lock file update moves a dependency to a new version that the range in `package.json` already
allows. Nothing in `package.json` changes. npm makes the update in three steps:

1. The tool runs the npm command above with `name@version` for each update of the group.
2. npm also writes the new version into `package.json`, so the tool puts `package.json` back.
3. The tool runs the plain npm command again. The lock file then matches `package.json` again and
    keeps the new versions.

The commit holds only `package-lock.json`:

```console
applied  deps: update non-major
    osls                       4.3.1 -> 4.5.0
    serverless-domain-manager  10.3.1 -> 10.5.1
    docker/package-lock.json  refreshed
```

A lock file that does not match its `package.json` is corrected by the first group that refreshes
it. A later group that only asked for that same correction then changes no file. The run says so and
goes on:

```console
unchanged  deps: update serverless-domain-manager to 11.0.0
    serverless-domain-manager  10.3.1 -> 11.0.0
    no file changed, so there is nothing to commit
```

A group can also change nothing on its own. For example, an `overrides` entry in `package.json` can
keep npm at the version it has. The tool cannot tell these cases apart. If you see this line for a
group that no earlier group covers, read the lock file.

If the package manager fails, the group is undone: its manifests and lock files go back to what they
held before the group. A manifest left edited would otherwise fail the repository's own lock file
hook at the next commit. When the package manager finds no solution, the group is
[held back](../usage/held-back.md#updates-that-do-not-lock). Any other failure fails the group.

!!! warning

    If `uv` or `npm` is not on your `PATH` when its lock file needs refreshing, the group fails rather
    than committing a manifest that no longer matches its lock file. Install it, or pass `--no-lock` and
    refresh the lock file yourself.
