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
import subprocess  # nosec B404  # only used to run renovate, with a fixed argv
import tempfile
from pathlib import Path

from renovate_apply.errors import ScanError


REPORT_ENV_TYPE = "RENOVATE_REPORT_TYPE"
REPORT_ENV_PATH = "RENOVATE_REPORT_PATH"


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


def scan(root: Path, *, version: str | None = None) -> dict[str, object]:
    """Run Renovate over *root* and return the parsed report."""
    argv = [*renovate_command(version), "--platform=local"]
    env = {**os.environ, REPORT_ENV_TYPE: "file"}
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
