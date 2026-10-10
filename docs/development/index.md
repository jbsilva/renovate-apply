---
icon: lucide/wrench
---

# Development

## Set up

Clone the repository and let uv build the environment:

```bash
git clone https://github.com/jbsilva/renovate-apply
cd renovate-apply
uv sync
```

`uv sync` installs the `dev` and `test` groups, because both are in `default-groups`. The `docs`
group is opt-in; add `--group docs` when you want to build the site.

Install the git hooks with [prek](https://prek.j178.dev):

```bash
prek install
```

That wires up both the pre-commit and the commit-msg hooks, so the commit message spell check runs
too.

## The layout

```text
src/renovate_apply/
├── main.py        the CLI and the orchestration
├── config.py      where per-repository defaults are read from
├── scan.py        runs Renovate, returns the parsed report
├── report.py      flattens the report, holds some back, groups the rest
├── replace.py     turns one update into one text replacement
├── files.py       reads and writes the package files
├── lockfiles.py   runs uv lock
├── messages.py    the commit subject and body
├── git.py         clean check, staging, commit
├── models.py      Update, Group, Held
└── errors.py      the exception hierarchy
```

Each module owns one slice. `main.py` stays thin: it wires the others together and turns errors into
exit codes.

!!! warning

    `replace.py` is the module where a mistake corrupts somebody's file. Everything in it either matches
    what the report described or raises. A fallback that "probably finds the right line" writes a wrong
    version into somebody's infrastructure, silently, and the commit looks fine.

## Day to day

```bash
uv run pytest               # the suite
uv run pytest -k test_name  # one test
uv run poe lint             # lint
uv run poe format           # format
uv run poe typecheck        # types
uv run poe hooks            # every hook
uv run poe check            # lint, format, types and hooks, before a commit
```

## Read on

- [Testing](testing.md): how the suite is built and what it refuses to do.
- [Code quality](code-quality.md): the tools and what each one is for.
- [Documentation](documentation.md): building and writing this site.
