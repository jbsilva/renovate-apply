"""
The git this tool needs: is the working copy clean, stage these files, commit them.

A commit takes the whole index, not the files this staged, so the clean check is what keeps an
unrelated change out of a dependency commit.
"""

import shutil
import subprocess  # nosec B404  # only used to run git, with an argv this package builds
lazy from pathlib import Path

from renovate_apply.errors import GitError, WorkingCopyError


def run(root: Path, *args: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one git command in *root* and hand back the finished process, failure and all."""
    if not shutil.which("git"):
        msg = "git is not on PATH"
        raise GitError(msg)
    return subprocess.run(  # noqa: S603  # nosec B603 B607  # fixed argv, no shell, git from PATH
        ["git", "-C", str(root), *args],  # noqa: S607 - git is resolved from PATH on purpose
        capture_output=capture,
        text=True,
        check=False,
    )


def require_repository(root: Path) -> None:
    """Raise unless *root* is inside a git working copy."""
    completed = run(root, "rev-parse", "--is-inside-work-tree")
    if completed.returncode != 0 or completed.stdout.strip() != "true":
        msg = f"not a git repository: {root}"
        raise WorkingCopyError(msg)


def require_clean(root: Path) -> None:
    """Raise when anything is modified or staged, naming what is in the way."""
    completed = run(root, "status", "--porcelain")
    if completed.returncode != 0:
        msg = f"git status failed: {completed.stderr.strip()}"
        raise GitError(msg)
    changed = completed.stdout.strip()
    if changed:
        msg = (
            "the working copy has changes in it, and a commit would take them too. "
            f"Commit or stash them first:\n{changed}"
        )
        raise WorkingCopyError(msg)
