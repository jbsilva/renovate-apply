"""
Refresh the lock file after a manifest was edited, the way Renovate refreshes it in a pull request.

Renovate does not stop at the manifest. After it raises a version in ``pyproject.toml`` or
``package.json`` it runs the package manager to update the lock file, and both land in the same
commit. A run that skipped that step would leave the lock file describing the old version, and any
CI that installs with ``uv sync --locked`` or ``npm ci`` would fail on the commit this tool made.

Each package manager here keeps its lock file next to the manifest and can refresh it without
installing anything. A manifest with no lock file beside it needs nothing and is left alone.

npm can also move one dependency inside the range its manifest allows, which Renovate reports as a
lock file update. ``npm install name@version`` does that, but it also writes the new version into
``package.json``. So the manifest is put back afterwards, and a second plain run makes the lock file
match it again while it keeps the version just locked.
"""

import shutil
import subprocess  # nosec B404  # only used to run a package manager, with an argv from _LOCKERS
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
lazy from collections.abc import Sequence

from renovate_apply.errors import LockError, NoSolutionError
lazy from renovate_apply.models import Update


@dataclass(frozen=True, slots=True)
class Locker:
    """One package manager: the manifest it reads, its lock file, and how to refresh it."""

    manifest: str
    lock_file: str
    argv: tuple[str, ...]
    no_solution: str
    """What the tool prints when no versions satisfy the manifest, as opposed to failing to run."""

    manager: str = ""
    """The Renovate manager whose lock file updates this can make; empty when it makes none."""

    @property
    def program(self) -> str:
        """Return the program that has to be on PATH."""
        return self.argv[0]


UV = Locker(
    manifest="pyproject.toml",
    lock_file="uv.lock",
    argv=("uv", "lock"),
    no_solution="No solution found",
)
NPM = Locker(
    manifest="package.json",
    lock_file="package-lock.json",
    # Only the lock file is written: no node_modules, no install scripts, no audit or funding calls.
    argv=("npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"),
    # The error code: npm also warns "ERESOLVE overriding" on runs that fail for other reasons.
    no_solution="code ERESOLVE",
    manager="npm",
)
_LOCKERS = (UV, NPM)


def can_move_in_lock(update: Update) -> bool:
    """Say whether a lock file update can be made here: a package manager moves it, not an edit."""
    locker = _locker_for(PurePosixPath(update.package_file).name)
    if locker is None or locker.manager != update.manager or not update.new_version:
        return False
    # An alias needs "name@npm:package@version". Without it npm installs another package by name.
    if update.package_name not in {None, update.dep_name}:
        return False
    return _joined(update.directory, locker.lock_file) in update.lock_files


def refresh(
    root: Path,
    package_files: Sequence[str],
    lock_updates: Sequence[Update] = (),
) -> tuple[str, ...]:
    """
    Refresh the lock file of every edited manifest that has one beside it.

    Each of *lock_updates*, which ``can_move_in_lock`` accepted, is moved to its new version in the
    lock file of its own manifest.

    Returns the lock files that were refreshed, as repository-relative paths, so the caller can
    commit them together with the manifest. When one of them fails, every lock file is put back as
    it was, so a group that touches two projects does not leave the first one relocked.
    """
    targets = _targets(root, package_files)
    before = {lock_file: (root / lock_file).read_bytes() for _, _, lock_file in targets}
    try:
        return tuple(
            _relock(root, locker, directory, _specs(locker, directory, lock_updates))
            for locker, directory, _ in targets
        )
    except LockError:
        for lock_file, content in before.items():
            (root / lock_file).write_bytes(content)
        raise


def _targets(root: Path, package_files: Sequence[str]) -> list[tuple[Locker, str, str]]:
    """Return each edited manifest's locker, directory and lock file, each lock file once."""
    found: dict[str, tuple[Locker, str, str]] = {}
    for package_file in package_files:
        path = PurePosixPath(package_file)
        locker = _locker_for(path.name)
        if locker is None:
            continue
        directory = "" if path.parent == PurePosixPath(".") else str(path.parent)
        lock_file = _joined(directory, locker.lock_file)
        if lock_file not in found and (root / lock_file).exists():
            found[lock_file] = (locker, directory, lock_file)
    return list(found.values())


def _specs(locker: Locker, directory: str, lock_updates: Sequence[Update]) -> list[str]:
    """Return ``name@version`` for each lock file update of the manifest in *directory*."""
    manifest = _joined(directory, locker.manifest)
    return [
        f"{update.dep_name}@{update.new_version}"
        for update in lock_updates
        if update.package_file == manifest
    ]


def _relock(root: Path, locker: Locker, directory: str, specs: Sequence[str] = ()) -> str:
    """
    Run the package manager in one directory and return the lock file it refreshed.

    With *specs*, the manager first locks each of them, and the manifest it rewrote is put back.
    """
    if not shutil.which(locker.program):
        msg = (
            f"{_joined(directory, locker.manifest)} was edited and {locker.lock_file} sits beside "
            f"it, but {locker.program} is not on PATH. Install {locker.program}, or pass "
            "--no-lock and refresh the lock file yourself."
        )
        raise LockError(msg)
    if specs:
        manifest = root / directory / locker.manifest
        original = manifest.read_bytes()
        try:
            _run(root, locker, directory, specs)
        finally:
            manifest.write_bytes(original)
    _run(root, locker, directory)
    return _joined(directory, locker.lock_file)


def _run(root: Path, locker: Locker, directory: str, specs: Sequence[str] = ()) -> None:
    """Run the package manager once, raising with what it said when it fails."""
    completed = subprocess.run(  # noqa: S603  # nosec B603 B607  # argv from _LOCKERS, no shell
        [*locker.argv, *specs],
        cwd=root / directory,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        msg = f"{' '.join(locker.argv[:2])} failed in {directory or '.'}:\n{detail}"
        raise (NoSolutionError if locker.no_solution in detail else LockError)(msg)


def _locker_for(manifest: str) -> Locker | None:
    """Return the package manager that reads a manifest of this file name, if this tool has one."""
    return next((one for one in _LOCKERS if one.manifest == manifest), None)


def _joined(directory: str, name: str) -> str:
    """Return a repository-relative path with the forward slashes the report uses."""
    return str(PurePosixPath(directory) / name) if directory else name
