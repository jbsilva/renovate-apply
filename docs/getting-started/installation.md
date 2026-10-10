---
icon: lucide/download
---

# Installation

`renovate-apply` installs like any Python command-line tool. It also shells out to a few programs
that it does not bundle, listed further down.

## Install the tool

=== "uv (recommended)"

    ```bash
    uv tool install renovate-apply
    ```

=== "uvx (no install)"

    ```bash
    uvx renovate-apply --dry-run
    ```

=== "pipx"

    ```bash
    pipx install renovate-apply
    ```

The package installs two commands, `renovate-apply` and `rnv`. They are the same thing; `rnv` is
shorter to type.

Check that it worked:

```bash
rnv --version
```

## Install Renovate

The scan is a real Renovate run, so Renovate has to be available.

=== "Install it (faster)"

    ```bash
    npm i -g renovate
    ```

    A `renovate` already on your `PATH` starts in about a second.

=== "Let npx fetch it"

    Install [Node.js](https://nodejs.org) and do nothing else. Without a `renovate` on `PATH`, the tool
    calls `npx --yes --package renovate@latest -- renovate`, which downloads and caches the package on
    first use.

To pin a version instead of using whatever is installed, pass `--renovate-version`. That always goes
through `npx`:

```bash
rnv --renovate-version 43.224.0
```

## Optional pieces

| Program | When you need it                                                                                                                      |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `uv`    | Only if a `pyproject.toml` you update has a `uv.lock` beside it. See [Commits and lock files](../how-it-works/commits.md#lock-files). |
| `gh`    | Any run, really. It supplies the GitHub token that keeps lookups from being rate limited.                                             |

If `uv` is missing when a lock file needs refreshing, the run stops and says so. Pass `--no-lock` to
skip that step and update the lock file yourself.

## From source

For a development checkout, see [Development](../development/index.md).
