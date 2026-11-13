"""
Read a package file, make every edit of one group in it, and write it back.

Files are read and written with ``newline=""`` so line endings survive untouched. A repository with
CRLF files would otherwise come back rewritten from top to bottom, and the one-line diff Renovate
promises would be the whole file.
"""

lazy from collections.abc import Mapping, Sequence
lazy from pathlib import Path

from renovate_apply.errors import ReplaceError
from renovate_apply.replace import apply_all, same_edit
lazy from renovate_apply.models import Group, Update


ENCODING = "utf-8"


def apply_group(
    root: Path,
    group: Group,
    *,
    drafts: dict[str, str] | None = None,
) -> tuple[str, ...]:
    """
    Make every edit of *group*, and return the package files it touched.

    Every edit is computed before any of them is written, so a group that fails on its second file
    leaves the first one as it was. Written as it went, that first file would stay edited after the
    group was reported as failed, and the next group to touch it would stage and commit the edit
    under its own message.

    With *drafts*, nothing is written: the edited texts go into *drafts* and are read back from it,
    so a later group of a dry run finds what an earlier one would have written.
    """
    edited: list[tuple[str, str]] = []
    for package_file in group.package_files:
        # A lock file update has no text in the package file; the package manager moves it.
        mine = [
            update
            for update in group.updates
            if update.package_file == package_file and not update.is_lockfile_update
        ]
        known = drafts or {}
        text = known[package_file] if package_file in known else _read(root / package_file)
        edited.append((package_file, apply_all(text, mine)))
    for package_file, text in edited:
        if drafts is None:
            _write(root / package_file, text)
        else:
            drafts[package_file] = text
    return group.package_files


def repeats_of(root: Path, updates: Sequence[Update]) -> list[Update | None]:
    """
    Return, for each update, the earlier one it repeats: the same edit, found by another manager.

    None stands for an update that repeats nothing. The list lines up with *updates*.
    """
    kept: list[Update] = []
    firsts: list[Update | None] = []
    texts: dict[str, str] = {}
    for update in updates:
        first = next((one for one in kept if _same_edit(root, texts, one, update)), None)
        if first is None:
            kept.append(update)
        firsts.append(first)
    return firsts


def _same_edit(root: Path, texts: dict[str, str], first: Update, second: Update) -> bool:
    """Compare two updates against their file, reading each file once."""
    if first.package_file != second.package_file:
        return False
    if first.package_file not in texts:
        texts[first.package_file] = _read(root / first.package_file)
    return same_edit(texts[first.package_file], first, second)


def snapshot(root: Path, package_files: Sequence[str]) -> dict[str, str]:
    """Return what each package file holds now, for ``restore`` to put back."""
    return {package_file: _read(root / package_file) for package_file in package_files}


def restore(root: Path, originals: Mapping[str, str]) -> None:
    """Write back what ``snapshot`` read, undoing a group that cannot be finished."""
    for package_file, text in originals.items():
        _write(root / package_file, text)


def _read(path: Path) -> str:
    """Read a package file, saying which one when it cannot be read."""
    try:
        return path.read_text(encoding=ENCODING, newline="")
    except OSError as error:
        msg = f"cannot read {path}: {error}"
        raise ReplaceError(msg) from error


def _write(path: Path, text: str) -> None:
    """Write a package file back, saying which one when it cannot be written."""
    try:
        path.write_text(text, encoding=ENCODING, newline="")
    except OSError as error:
        msg = f"cannot write {path}: {error}"
        raise ReplaceError(msg) from error
