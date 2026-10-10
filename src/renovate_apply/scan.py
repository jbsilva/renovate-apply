"""
Run Renovate over a working copy and hand back the report it writes.

Renovate reads the repository from disk with ``--platform=local``, which is the only platform that
needs no server, no clone and no credentials beyond a read token. That platform also refuses to
write: its ``initPlatform`` forces the run into a lookup-only dry run, so the file updates never
happen. Everything this package does after this module exists because of that.

The report comes from ``--report-type=file``, a supported output meant for machines. It is not the
debug log, so it stays stable and small.
"""

import json
import os
import shutil
import subprocess  # nosec B404  # only used to run renovate and gh, each with a fixed argv
import tempfile
from pathlib import Path

from renovate_apply.errors import ScanError


REPORT_ENV_TYPE = "RENOVATE_REPORT_TYPE"
REPORT_ENV_PATH = "RENOVATE_REPORT_PATH"

# Renovate reads LOG_LEVEL and takes bunyan's names, so a shell that exports the longer "warning"
# for everything else makes it exit 60 with "Invalid log level" and nothing about the repository.
# Setting it here means the caller's shell cannot break the run.
LOG_LEVEL = "warn"


def github_token() -> str:
    """
    Return a GitHub token from ``gh``, or an empty string when gh is missing or logged out.

    Without a token, Renovate still runs, but everything it looks up on GitHub (actions, pre-commit
    hooks, release tags) is rate limited and may come back empty. Taking it from ``gh auth token``
    keeps the token out of the shell history and out of this process's argv.
    """
    if not shutil.which("gh"):
        return ""
    completed = subprocess.run(  # nosec B603 B607  # fixed argv, no shell, gh comes from PATH
        ["gh", "auth", "token"],  # noqa: S607 - gh is resolved from PATH on purpose
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def renovate_command(version: str | None) -> list[str]:
    """
    Return the argv that runs Renovate, preferring an installed one over a download.

    A ``renovate`` already on PATH (``npm i -g renovate``) starts in about a second. Without one,
    npx fetches the package and caches it. Asking for a version always goes through npx, because the
    installed one is whatever it is.
    """
    if version is None and shutil.which("renovate"):
        return ["renovate"]
    if not shutil.which("npx"):
        msg = "neither 'renovate' nor 'npx' is on PATH; install Node.js or renovate itself"
        raise ScanError(msg)
    return ["npx", "--yes", "--package", f"renovate@{version or 'latest'}", "--", "renovate"]


def scan(root: Path, *, version: str | None = None, token: str | None = None) -> dict[str, object]:
    """
    Run Renovate over *root* and return the parsed report.

    *token* defaults to whatever ``gh`` can give. Pass an empty string to run without one.
    """
    argv = [*renovate_command(version), "--platform=local"]
    env = {
        **os.environ,
        REPORT_ENV_TYPE: "file",
        "LOG_LEVEL": LOG_LEVEL,
        "GITHUB_COM_TOKEN": github_token() if token is None else token,
    }
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / "renovate-report.json"
        env[REPORT_ENV_PATH] = str(report)
        completed = subprocess.run(  # noqa: S603  # nosec B603  # argv built above, not a shell string
            argv,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            msg = f"renovate exited {completed.returncode}\n{_tail(completed)}"
            raise ScanError(msg)
        if not report.exists():
            msg = f"renovate wrote no report\n{_tail(completed)}"
            raise ScanError(msg)
        return _load(report)


def _load(report: Path) -> dict[str, object]:
    """Read the report, failing with the file's own words when it is not JSON."""
    try:
        loaded = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        msg = f"cannot read the report renovate wrote: {error}"
        raise ScanError(msg) from error
    if not isinstance(loaded, dict):
        msg = f"the report is a {type(loaded).__name__}, not an object"
        raise ScanError(msg)
    return loaded


def _tail(completed: subprocess.CompletedProcess[str], lines: int = 15) -> str:
    """Return the last lines of a failed run, which is where Renovate says what went wrong."""
    output = (completed.stderr or completed.stdout or "").strip()
    return "\n".join(output.splitlines()[-lines:])
