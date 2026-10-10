---
icon: lucide/shield-check
---

# Code quality

Every tool below runs as a git hook and again in CI, so a fork without hooks cannot skip one.

| Tool           | What it is for                                       |
| -------------- | ---------------------------------------------------- |
| `ruff`         | Lint and format. The full rule set, at 100 columns.  |
| `ty`           | Type checking. Every warning fails it like an error. |
| `bandit`       | Common security mistakes.                            |
| `zizmor`       | Audits the GitHub Actions workflows.                 |
| `cspell`       | Spell check, on files and on the commit message.     |
| `typos`        | Common typos.                                        |
| `mdformat`     | Formats Markdown at 100 columns.                     |
| `docformatter` | Reflows docstrings.                                  |

Two more run only when you ask: `uv run poe zuban`, a strict mypy-compatible type check, and
`uv run poe pycroscope`, a semi-static analyzer. No hook or CI job runs them, so a finding of theirs
never blocks a commit.

Run them all:

```bash
prek run -a
```

Or one at a time:

```bash
uv run poe lint
uv run poe format
uv run poe typecheck
uv run zizmor .
```

!!! note

    `ty` checks the whole project, never a file list. A change in one file can break a caller in
    another, so the hook passes it no file names.

## Style

- Python 3.15. Modern syntax is fine: PEP 695 generics, `match`, `except` without parentheses.
- 100 columns for code, comments and docstrings.
- Plain language in comments. Explain the *why*, not the *what*.
- Keep comments short. Write it, then delete every line that would not change what a reader does.
- Never write a fact a later release makes false: a version, a count, a file list, a line number.
    State the rule, not today's value.
- No em-dashes. Use a colon, a semicolon, parentheses, or two sentences.

## Silencing a finding

The default is to fix, not to silence. When a finding clearly does not apply, silence it with a
reason, and mind the format of each one:

| Tool      | Format                         | Why                                                                                     |
| --------- | ------------------------------ | --------------------------------------------------------------------------------------- |
| ruff      | `# noqa: PLR0913 - the reason` | No comma. SonarQube reads a comma-separated tail as more rule codes and reports S7632.  |
| bandit    | `# nosec B603  # the reason`   | Second `#`. Bandit reads everything up to it as more test IDs, and warns once per word. |
| SonarQube | `# NOSONAR - the reason`       |                                                                                         |

## CI

| Workflow     | What it runs                                                              |
| ------------ | ------------------------------------------------------------------------- |
| `tests.yml`  | The suite on Linux, macOS and Windows, then the linters, then SonarCloud. |
| `codeql.yml` | CodeQL, on the Python source and on the workflows.                        |
| `zizmor.yml` | The workflow audit, uploading SARIF to the Security tab.                  |
| `docs.yml`   | Builds this site and deploys it to GitHub Pages.                          |

Windows is in the test matrix on purpose. This package drives git and reads files byte for byte, and
line endings and path separators are what break there and nowhere else.

A workflow edit has to keep zizmor clean: actions pinned to a full commit SHA,
`persist-credentials: false` on every checkout, no caching in `publish.yml`, and the narrowest
`permissions` per job.
