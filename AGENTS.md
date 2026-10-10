# CLAUDE.md

Guidance for AI tools like Claude Code (claude.ai/code) when working in this repository.

## What this is

`renovate-apply` writes the updates Renovate finds. Renovate's `--platform=local` reports every
pending update and never writes one: its `initPlatform` clamps the run to a lookup-only dry run, so
the run ends before the step that edits a file. There is no flag for it. This package is that step.

The whole flow is: run Renovate, read its JSON report, make each edit, commit one group per Renovate
branch. Each module owns one slice:

- `main.py` - the cyclopts entry point and the orchestration. Keep it thin: it wires the modules
  together and turns domain errors into exit codes. New flags go on `apply_updates`.
- `config.py` - the cyclopts configuration source, which reads `[tool.renovate-apply]` out of the
  repository being updated rather than out of the directory the command was started from.
- `scan.py` - runs Renovate (`--platform=local` plus `RENOVATE_REPORT_TYPE=file`) and hands back the
  parsed report. Nothing else in the package knows how Renovate is invoked.
- `report.py` - flattens the report's manager/file/dependency/update nesting into `Update` objects,
  splits off what is held back, and groups the rest by branch. This is the only module that reads
  the report's shape, so a shape Renovate changes fails loudly in one place.
- `replace.py` - the edit itself: render Renovate's `autoReplaceStringTemplate`, find its
  `replaceString`, swap one for the other. **This is the module where a mistake corrupts a file.**
- `files.py` - reads and writes the package files, preserving line endings.
- `lockfiles.py` - runs `uv lock` when an edited `pyproject.toml` has a `uv.lock` beside it, so the
  manifest and its lock file are committed together, as Renovate's own pull request carries them.
- `messages.py` - the commit subject and body; `git.py` - the clean check, the staging, the commit.
- `models.py` - `Update`, `Group`, `Held`; `errors.py` - the domain exception hierarchy.

The version is single-sourced: `renovate_apply.__version__` reads installed distribution metadata,
so `pyproject.toml`'s `[project].version` is the only code-side source. Do not reintroduce a
hardcoded version string.

## Code style

- Python 3.15: use modern syntax. PEP 695 generics, `match`, structural pattern matching, and PEP
  758 `except` without parentheses (`except ValueError, TypeError:`) are all fine.
- An import used only in annotations is a PEP 810 `lazy` import, not an `if TYPE_CHECKING:` block.
  pyupgrade rewrites the one into the other.
- 100-column width for code, comments, and docstrings.
- Write comments and docstrings in plain, simple language. Explain the _why_, not the _what_.
- Keep them short. Two lines of comment is usually one line too many. Write it, then delete every
  line that would not change what a reader does. A line that names a discoverable command, or
  restates the code, gets deleted rather than shortened. Commit bodies the same: a subject and two
  or three lines of cause, not a narrative.
- Never write a fact that a later release makes false: a version number, a count, a file list, a
  line number. State the rule, not today's value. A comment that rots is worse than no comment,
  because it is believed.
- Never use em-dash (`—`) or en-dash (`–`). Rephrase instead: a colon, a semicolon, parentheses, or
  two sentences. A spaced hyphen is not a substitute, it means something else. Hyphens are for
  compound words (`event-scoped`) and ranges (`09:00 - 17:30`).

## Tests and code quality

- Add or update tests whenever you change behavior. Target: 90%+ coverage.
- `uv run pytest` (full suite) or `uv run pytest -k test_name` (single test).
- Keep functions small and focused. If a function grows complex (deep nesting, many branches, hard
  to test), refactor before adding more to it. Extract helpers, split responsibilities.
- SonarQube has many false positives. Silence with `# NOSONAR` (and a one-line reason) only when the
  finding clearly does not apply. Default is to fix, not silence.
- Write the reason after a `# noqa` code without a comma. Ruff ignores the text, but SonarQube reads
  it as more codes and reports rule S7632. Example: `# noqa: PLR0913 - every argument is one knob.`
- A `# nosec` reason goes after a second `#`. Bandit reads everything up to the next `#` as more
  test IDs and warns once per word. Example: `# nosec B603  # fixed argv, no shell`.
- **Never widen an edit on a guess.** Everything in `replace.py` either matches what the report
  described or raises. A fallback that "probably finds the right line" writes the wrong version into
  somebody's infrastructure, silently, and the commit looks fine. Tests for that module carry the
  cases that matter: a version two hooks share, a reference that appears twice, a file that already
  moved.
- The test suite must not reach the network or run Renovate. `tests/helpers.py` builds reports; the
  git tests run against a real repository in `tmp_path` with `GIT_CONFIG_GLOBAL` pointed away from
  the developer's own configuration.

## Before committing

```bash
uv run poe check   # ruff lint and format, ty, then every prek hook
uv run poe test    # The test suite
```

`uv run poe` lists every task. Two of them run only when asked, and no hook or CI job runs them:
`poe zuban`, a strict mypy-compatible type check, and `poe pycroscope`, a semi-static analyzer.

Anything under `.github/workflows/` is audited by [`zizmor`](https://docs.zizmor.sh)
(`uv run zizmor .`), as a prek hook and in `zizmor.yml`, which also uploads SARIF to the Security
tab. A workflow edit must keep it clean: actions pinned to a full commit SHA,
`persist-credentials: false` on every checkout, no caching in `publish.yml`, and the narrowest
`permissions` per job.

## Git

- Make small, atomic commits. One logical change per commit.
- **Commit as you go.** After finishing a discrete change, run the checks and create the commit
  before moving to the next change.
- Write clear commit messages: short imperative subject, body describing the _why_.

## Things Claude (or any AI tool) must never do

- **Never push to GitHub** unless the user explicitly asks in this turn. Creating local commits is
  fine; `git push` is not.
- **Never skip hooks** (`--no-verify`). If a hook fails, fix the cause.
- **Never silence lint/type/SonarQube findings just to make CI pass.** Fix the underlying issue;
  silence only with a documented reason.
- **Never rewrite shared history** (`git rebase`, `git reset --hard`, force-push) on any branch that
  has been pushed, unless the user asks.
