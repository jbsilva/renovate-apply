---
icon: lucide/heart-handshake
---

# Contributing

Bug reports, documentation fixes and code changes are all welcome.

## Before you start

Get an environment and the hooks installed. [Development](development/index.md) covers the setup;
you need Python 3.15+ and `git`, plus Node.js if you want to run the tool against a real repository.

## Commits

Small and atomic: one logical change each. Commit as you go rather than batching unrelated edits at
the end.

Write a short imperative subject, and use the body to say *why*, not what. The diff already says
what.

## Tests

Add or update tests whenever you change behavior. If you are fixing a bug, check that the new test
fails against the old code first. See [Testing](development/testing.md).

## Before you push

```bash
uv run poe check
```

!!! warning

    Never skip the hooks with `--no-verify`. Never silence a lint, type or SonarQube finding to make CI
    pass. If a hook fails, fix the cause. Silence a finding only when it clearly does not apply, and
    write down why.

## Pull requests

Four workflows gate a pull request: the tests and linters, CodeQL, the zizmor workflow audit, and
the docs build. [Code quality](development/code-quality.md) lists what each one does.

## A note on this tool in particular

This one writes files and makes commits in other people's repositories. That raises the bar on two
things:

- **Never widen an edit on a guess.** Everything in `replace.py` either matches what the report
    described or raises. A fallback that "probably finds the right line" writes a wrong version into
    somebody's infrastructure, silently, and the commit looks fine.
- **Never commit what the run did not write.** Staging is by name, the working copy is checked
    first, and a group that fails writes nothing at all.

If a change touches either, say so in the pull request and add the test that proves it.

## Security

Report a vulnerability privately through
[GitHub security advisories](https://github.com/jbsilva/renovate-apply/security/advisories/new), not
as a public issue. [`SECURITY.md`](https://github.com/jbsilva/renovate-apply/blob/main/SECURITY.md)
says what is in scope.

Never commit a token. Pass it through `GITHUB_TOKEN` or `gh`.
