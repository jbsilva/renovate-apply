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
| `npm`   | Only if a `package.json` you update has a `package-lock.json` beside it. npm comes with Node.js.                                      |
| `gh`    | Any run, really. It supplies the GitHub token that keeps lookups from being rate limited.                                             |

If `uv` or `npm` is missing when its lock file needs refreshing, that group fails and is undone. The
other groups still run, and the run exits with status 1. Pass `--no-lock` to skip that step and
update the lock file yourself.

## From source

For a development checkout, see [Development](../development/index.md).
