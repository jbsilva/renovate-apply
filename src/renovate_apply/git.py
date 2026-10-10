"""
The git this tool needs: is the working copy clean, stage these files, commit them.

A commit takes the whole index, not the files this staged, so the clean check is what keeps an
unrelated change out of a dependency commit. The hooks are never skipped: a hook that rewrites a
file is a reason to stop, not a reason to pass ``--no-verify``.
"""

import shutil
import subprocess  # nosec B404  # only used to run git, with an argv this package builds
lazy from collections.abc import Sequence
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
    """
    Raise when a tracked file is modified or staged, naming what is in the way.

    A staged change is already in the index the commit takes. An unstaged one reaches the commit
    when it sits in a package file this run also edits, because staging that file stages all of it.

    Untracked files are not counted. ``git add`` is given the files this wrote and nothing else, so
    no untracked file can reach the commit, and a scratch file left in the tree is no reason to
    refuse a whole run.
    """
    completed = run(root, "status", "--porcelain", "--untracked-files=no")
    if completed.returncode != 0:
        msg = f"git status failed: {completed.stderr.strip()}"
        raise GitError(msg)
    changed = completed.stdout.strip()
    if changed:
        msg = (
            "the working copy has changes to tracked files, and a commit would take them too. "
            f"Commit or stash them first:\n{changed}"
        )
        raise WorkingCopyError(msg)


def commit(root: Path, package_files: Sequence[str], paragraphs: Sequence[str]) -> None:
    """
    Stage *package_files* and commit them with *paragraphs* as the message.

    The hooks run. When one of them fails, or rewrites a file so the commit stops, this raises with
    what git and the hook said, and leaves the tree exactly as they left it.
    """
    staged = run(root, "add", "--", *package_files)
    if staged.returncode != 0:
        msg = f"git add failed: {staged.stderr.strip()}"
        raise GitError(msg)

    arguments = [*("-m", paragraph) for paragraph in paragraphs]
    committed = run(root, "commit", *arguments)
    if committed.returncode != 0:
        detail = (committed.stdout + committed.stderr).strip()
        msg = (
            "the commit failed, most likely a hook. The files are written and staged, "
            f"and nothing was undone:\n{detail}"
        )
        raise GitError(msg)
