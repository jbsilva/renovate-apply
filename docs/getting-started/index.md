---
icon: lucide/rocket
---

# Getting started

`renovate-apply` runs Renovate over a working copy and writes the updates it finds. It does not
replace Renovate. It needs Renovate to do the scan, and it reads your repository's own Renovate
configuration by running it.

This section gets you from a clean machine to a first run. Check the prerequisites below, then
install the tool and set the defaults that suit your repository.

## Prerequisites

| Tool                  | Why it is needed                                                         |
| --------------------- | ------------------------------------------------------------------------ |
| Python 3.15+          | The runtime.                                                             |
| `git`                 | Reads the state of the working copy, stages the files, makes the commit. |
| `renovate` or Node.js | Does the scan. Either install Renovate, or let `npx` fetch it.           |
| `uv` (optional)       | Refreshes `uv.lock` after an edit to a `pyproject.toml` beside it.       |
| `gh` (optional)       | Supplies a GitHub token, so lookups are not rate limited.                |

!!! warning

    Without a GitHub token, everything Renovate looks up on GitHub is rate limited, and updates can go
    missing without an error. Log in with `gh`, or set `GITHUB_TOKEN`. See
    [Configuration](configuration.md#github-token).

## Your first run

Start with a dry run. It computes every edit and writes nothing:

```bash
cd ~/code/your-repo
rnv --dry-run
```

If that looks right, run it again without the flag. Each group becomes one commit:

```bash
rnv
```

Read the diff with `git log -p`, then push yourself. The tool never pushes.

!!! tip

    Not sure yet? `rnv --no-commit` writes the files and stops, so you can read everything at once with
    `git diff` and commit it your own way.

## Next steps

- [Installation](installation.md): install the tool and the things it shells out to.
- [Configuration](configuration.md): set your commit prefix and skip list once, per repository.
