"""
Refresh the lock file after a manifest was edited, the way Renovate refreshes it in a pull request.

Renovate does not stop at the manifest. After it raises a version in ``pyproject.toml`` or
``package.json`` it runs the package manager to update the lock file, and both land in the same
commit. A run that skipped that step would leave the lock file describing the old version, and any
CI that installs with ``uv sync --locked`` or ``npm ci`` would fail on the commit this tool made.

Each package manager here keeps its lock file next to the manifest and can refresh it without
installing anything. A manifest with no lock file beside it needs nothing and is left alone.

Both can also move one dependency inside the range its manifest allows, which Renovate reports as a
lock file update, a transitive dependency included. uv does it with ``--upgrade-package
name==version``, as Renovate's own pull request does. ``npm install name@version`` also writes the
version into ``package.json``, so the manifest is put back afterwards, and a second plain run makes
the lock file match it again while it keeps the version just locked.

Lock file maintenance moves every dependency in its lock file to the newest version the manifest
allows, as Renovate's lock file maintenance branch does.
"""

import shutil
import subprocess  # nosec B404  # only used to run a package manager, with an argv from _LOCKERS
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
lazy from collections.abc import Callable, Sequence

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
    """The Renovate manager whose lock file updates this can make."""

    pin: Callable[[str, str], tuple[str, ...]] = lambda _name, _version: ()
    """The arguments that lock one package at one version."""

    rewrites_manifest: bool = False
    """Whether pinning also writes the version into the manifest, which then has to be put back."""

    upgrade: tuple[str, ...] = ()
    """The command that moves every dependency to the newest version the manifest allows."""

    @property
    def program(self) -> str:
        """Return the program that has to be on PATH."""
        return self.argv[0]


UV = Locker(
    manifest="pyproject.toml",
    lock_file="uv.lock",
    argv=("uv", "lock"),
    no_solution="No solution found",
    manager="pep621",
    pin=lambda name, version: ("--upgrade-package", f"{name}=={version}"),
    upgrade=("uv", "lock", "--upgrade"),
)
NPM = Locker(
    manifest="package.json",
    lock_file="package-lock.json",
    # Only the lock file is written: no node_modules, no install scripts, no audit or funding calls.
    argv=("npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"),
    # The error code: npm also warns "ERESOLVE overriding" on runs that fail for other reasons.
    no_solution="code ERESOLVE",
    manager="npm",
    pin=lambda name, version: (f"{name}@{version}",),
    rewrites_manifest=True,
    upgrade=(
        *("npm", "update", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"),
        "--no-save",
    ),
)
_LOCKERS = (UV, NPM)


def can_move_in_lock(update: Update) -> bool:
    """Say whether a lock file update can be made here: a package manager moves it, not an edit."""
    lock_file = lock_file_of(update)
    if lock_file is None or not update.new_version:
        return False
    # An alias needs "name@npm:package@version". Without it npm installs another package by name.
    if update.manager == NPM.manager and update.package_name not in {None, update.dep_name}:
        return False
    return lock_file in update.lock_files


def lock_file_of(update: Update) -> str | None:
    """Return the lock file this tool relocks for the update's manifest, or None if it has none."""
    locker = _locker_for(PurePosixPath(update.package_file).name)
    if locker is None or locker.manager != update.manager:
        return None
    return _joined(update.directory, locker.lock_file)


def refresh(
    root: Path,
    package_files: Sequence[str],
    lock_updates: Sequence[Update] = (),
    *,
    tracked: Callable[[str], bool] = lambda _path: True,
) -> tuple[str, ...]:
    """
    Refresh the lock file of every edited manifest that has one beside it, and *tracked* accepts.

    Each of *lock_updates*, which ``can_move_in_lock`` accepted, is moved to its new version in the
    lock file of its own manifest.

    Returns the lock files whose content changed, as repository-relative paths, so the caller can
    commit them together with the manifest. When one of them fails, every lock file is put back as
    it was, so a group that touches two projects does not leave the first one relocked.
    """
    targets = [target for target in _targets(root, package_files) if tracked(target[2])]
    _require_lock_files(targets, lock_updates)
    return _each(
        root,
        targets,
        lambda locker, directory: _relock(
            root, locker, directory, _specs(locker, directory, lock_updates)
        ),
    )


def maintenance_targets(
    root: Path,
    package_files: Sequence[tuple[str, str]],
    *,
    tracked: Callable[[str], bool] = lambda _path: True,
) -> tuple[str, ...]:
    """Return the lock files that maintenance moves: of each (manager, path) its locker reads."""
    return tuple(target[2] for target in _maintained(root, package_files, tracked))


def maintain(
    root: Path,
    package_files: Sequence[tuple[str, str]],
    *,
    tracked: Callable[[str], bool] = lambda _path: True,
) -> tuple[str, ...]:
    """
    Move every dependency in each lock file to the newest version its manifest allows.

    Returns the lock files whose content changed. When one fails, every lock file is put back.
    """
    targets = _maintained(root, package_files, tracked)
    return _each(root, targets, lambda locker, directory: _upgrade(root, locker, directory))


def _maintained(
    root: Path,
    package_files: Sequence[tuple[str, str]],
    tracked: Callable[[str], bool],
) -> list[_Target]:
    """Return the targets of the package files that their own manager's locker reads."""
    paths = [
        path
        for manager, path in package_files
        if (locker := _locker_for(PurePosixPath(path).name)) and locker.manager == manager
    ]
    return [target for target in _targets(root, paths) if tracked(target[2])]


def _each(
    root: Path,
    targets: Sequence[_Target],
    action: Callable[[Locker, str], None],
) -> tuple[str, ...]:
    """Run *action* on each target, and return the lock files it changed, or put them all back."""
    before = {lock_file: (root / lock_file).read_bytes() for _, _, lock_file in targets}
    try:
        for locker, directory, _ in targets:
            action(locker, directory)
    except LockError:
        for lock_file, content in before.items():
            (root / lock_file).write_bytes(content)
        raise
    return tuple(name for name, content in before.items() if (root / name).read_bytes() != content)


def _upgrade(root: Path, locker: Locker, directory: str) -> None:
    """Run the package manager's upgrade in one directory, keeping its manifest as it was."""
    _require_program(locker, directory)
    manifest = root / directory / locker.manifest
    original = manifest.read_bytes()
    try:
        _run(root, locker, directory, argv=locker.upgrade)
    finally:
        manifest.write_bytes(original)


def _require_lock_files(targets: Sequence[_Target], lock_updates: Sequence[Update]) -> None:
    """Raise for a lock file update whose lock file is not on disk: there is nothing to move."""
    manifests = {_joined(directory, locker.manifest) for locker, directory, _ in targets}
    for update in lock_updates:
        if update.package_file not in manifests:
            msg = (
                f"{update.dep_name}: the report has a lock file update for {update.package_file}, "
                "but there is no lock file beside it."
            )
            raise LockError(msg)


type _Target = tuple[Locker, str, str]


def _targets(root: Path, package_files: Sequence[str]) -> list[_Target]:
    """Return each edited manifest's locker, directory and lock file, each lock file once."""
    found: dict[str, _Target] = {}
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
    """Return the arguments that pin each lock file update of the manifest in *directory*."""
    manifest = _joined(directory, locker.manifest)
    return [
        *locker.pin(_package(locker, update), str(update.new_version))
        for update in lock_updates
        if update.package_file == manifest
    ]


def _package(locker: Locker, update: Update) -> str:
    """Return the name the package manager knows: uv's is the normalized package name."""
    if locker is UV and update.package_name:
        return update.package_name
    return update.dep_name


def _relock(root: Path, locker: Locker, directory: str, specs: Sequence[str] = ()) -> None:
    """
    Run the package manager in one directory to refresh its lock file.

    With *specs*, the manager locks each of them. One that also rewrote the manifest has it put back
    and runs once more, so the lock file matches the manifest again.
    """
    _require_program(locker, directory)
    if not locker.rewrites_manifest:
        _run(root, locker, directory, specs)
        return
    if specs:
        manifest = root / directory / locker.manifest
        original = manifest.read_bytes()
        try:
            _run(root, locker, directory, specs)
        finally:
            manifest.write_bytes(original)
    _run(root, locker, directory)


def _require_program(locker: Locker, directory: str) -> None:
    """Raise when the package manager is not installed."""
    if not shutil.which(locker.program):
        msg = (
            f"{locker.lock_file} sits beside {_joined(directory, locker.manifest)}, but "
            f"{locker.program} is not on PATH. Install {locker.program}, or pass --no-lock and "
            "refresh the lock file yourself."
        )
        raise LockError(msg)


def _run(
    root: Path,
    locker: Locker,
    directory: str,
    specs: Sequence[str] = (),
    *,
    argv: Sequence[str] = (),
) -> None:
    """Run the package manager once, raising with what it said when it fails."""
    command = [*(argv or locker.argv), *specs]
    completed = subprocess.run(  # noqa: S603  # nosec B603 B607  # argv from _LOCKERS, no shell
        command,
        cwd=root / directory,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        msg = f"{' '.join(command[:2])} failed in {directory or '.'}:\n{detail}"
        raise (NoSolutionError if locker.no_solution in detail else LockError)(msg)


def _locker_for(manifest: str) -> Locker | None:
    """Return the package manager that reads a manifest of this file name, if this tool has one."""
    return next((one for one in _LOCKERS if one.manifest == manifest), None)


def _joined(directory: str, name: str) -> str:
    """Return a repository-relative path with the forward slashes the report uses."""
    return str(PurePosixPath(directory) / name) if directory else name
