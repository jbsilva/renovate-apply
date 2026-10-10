"""
Refresh the lock file after a manifest was edited, the way Renovate refreshes it in a pull request.

Renovate does not stop at the manifest. After it raises a floor in ``pyproject.toml`` it runs the
package manager to update the lock file, and both land in the same commit. A run that skipped that
step would leave ``uv.lock`` describing the old floor, and any CI that installs with ``--locked``
would fail on the commit this tool just made.

Only uv is handled, because that is the manager whose lock file sits next to the manifest and
refreshes without touching the network for anything else. A manifest with no ``uv.lock`` beside it
needs nothing and is left alone.
"""

import shutil
import subprocess  # nosec B404  # only used to run uv, with an argv this module builds
from pathlib import Path, PurePosixPath
lazy from collections.abc import Sequence

from renovate_apply.errors import LockError, NoSolutionError


MANIFEST = "pyproject.toml"
LOCK_FILE = "uv.lock"
# What uv prints when the manifest cannot be satisfied, as opposed to uv failing to run at all.
NO_SOLUTION = "No solution found"


def refresh(root: Path, package_files: Sequence[str]) -> tuple[str, ...]:
    """
    Run ``uv lock`` for every edited manifest that has a lock file beside it.

    Returns the lock files that were refreshed, as repository-relative paths, so the caller can
    commit them together with the manifest. When one of them fails, every lock file is put back as
    it was, so a group that touches two projects does not leave the first one relocked.
    """
    directories = _directories_to_relock(root, package_files)
    before = {directory: (root / directory / LOCK_FILE).read_bytes() for directory in directories}
    try:
        return tuple(_relock(root, directory) for directory in directories)
    except LockError:
        for directory, content in before.items():
            (root / directory / LOCK_FILE).write_bytes(content)
        raise


def _directories_to_relock(root: Path, package_files: Sequence[str]) -> list[str]:
    """Return the directories holding an edited manifest and a lock file, each once."""
    found: list[str] = []
    for package_file in package_files:
        path = PurePosixPath(package_file)
        if path.name != MANIFEST:
            continue
        directory = "" if path.parent == PurePosixPath(".") else str(path.parent)
        if directory not in found and (root / directory / LOCK_FILE).exists():
            found.append(directory)
    return found


def _relock(root: Path, directory: str) -> str:
    """Run uv in one directory and return the lock file it refreshed."""
    if not shutil.which("uv"):
        msg = (
            f"{_joined(directory)} was edited and {LOCK_FILE} sits beside it, but uv is not on "
            "PATH. Install uv, or pass --no-lock and refresh the lock file yourself."
        )
        raise LockError(msg)
    completed = subprocess.run(  # nosec B603 B607  # fixed argv, no shell, uv from PATH
        ["uv", "lock"],  # noqa: S607 - uv is resolved from PATH on purpose
        cwd=root / directory,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        msg = f"uv lock failed in {directory or '.'}:\n{detail}"
        raise (NoSolutionError if NO_SOLUTION in detail else LockError)(msg)
    return _joined(directory, LOCK_FILE)


def _joined(directory: str, name: str = MANIFEST) -> str:
    """Return a repository-relative path with the forward slashes the report uses."""
    return str(PurePosixPath(directory) / name) if directory else name
