---
icon: lucide/flask-conical
---

# Testing

```bash
uv run pytest                 # the full suite
uv run pytest -k test_name    # one test
```

The suite runs in about two seconds. It targets 90%+ coverage, so a new code path usually needs a
new test with it.

## Two rules

**The suite never reaches the network, and never runs Renovate.** A test that needed a Renovate
install and a GitHub token would not be a test. `tests/helpers.py` builds reports in the shape the
real one has, and the tests swap them in for the scan.

**The git tests use a real repository.** Mocking git would test the mock. They build one in
`tmp_path` instead, with `GIT_CONFIG_GLOBAL` pointed at a throwaway file so a developer's own
`commit.gpgsign` or missing `user.email` cannot fail them.

## What is where

| File                | Covers                                                |
| ------------------- | ----------------------------------------------------- |
| `helpers.py`        | Builders: sample files, updates, and reports.         |
| `conftest.py`       | Fixtures: the isolated git env and a test repository. |
| `test_main.py`      | The command end to end, over a real repository.       |
| `test_replace.py`   | Templates and placing the edit.                       |
| `test_report.py`    | Reading the report, holds, grouping.                  |
| `test_scan.py`      | Which command runs, which token, what a failure says. |
| `test_files.py`     | Reading and writing package files.                    |
| `test_git.py`       | The clean check, staging, commits, hooks.             |
| `test_lockfiles.py` | Finding and refreshing `uv.lock`.                     |
| `test_messages.py`  | Commit subjects and bodies.                           |

## Settings that matter

These are in `[tool.pytest.ini_options]`:

- `--random-order` runs tests in a shuffled order, so a test that depends on another one fails
    instead of passing by luck.
- `--numprocesses=logical` runs them in parallel across cores.
- `filterwarnings = ["error"]` makes warnings fail the suite. This tool exists to bump dependencies,
    so a new `DeprecationWarning` from a bump has to be seen and not scrolled past.
- `--cov-branch` counts branch coverage, not just line coverage.

## Writing one

Tests read as sentences and the docstring says why the behavior matters, not what the code does:

```python
def test_split_applies_a_security_fix_even_while_it_is_pending() -> None:
    """A vulnerability alert bypasses Renovate's own hold, so it bypasses this one."""
    update = docker_update(pending=True, is_security=True)
    to_apply, held = split([update], with_major=False)
    assert to_apply == [update]
    assert held == []
```

Build updates with `docker_update()` or `hook_update()` from `helpers.py` and override the fields
that matter to the test. They are the two shapes Renovate reports: one with a `replaceString` and a
template, one with neither.

!!! tip

    When you fix a bug, check the new test fails against the old code. A regression test that passes
    either way is not guarding anything.
