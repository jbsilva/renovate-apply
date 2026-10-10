"""
Read a package file, make every edit of one group in it, and write it back.

Files are read and written with ``newline=""`` so line endings survive untouched. A repository with
CRLF files would otherwise come back rewritten from top to bottom, and the one-line diff Renovate
promises would be the whole file.
"""

lazy from collections.abc import Sequence
lazy from pathlib import Path

from renovate_apply.errors import ReplaceError
from renovate_apply.replace import apply_all, same_edit
lazy from renovate_apply.models import Group, Update


ENCODING = "utf-8"


def apply_group(root: Path, group: Group, *, write: bool = True) -> tuple[str, ...]:
    """
    Make every edit of *group*, and return the package files it touched.

    Every edit is computed before any of them is written, so a group that fails on its second file
    leaves the first one as it was. Written as it went, that first file would stay edited after the
    group was reported as failed, and the next group to touch it would stage and commit the edit
    under its own message.

    With ``write=False`` every edit is still computed, so a file the report no longer matches fails
    here as loudly as it would when writing. That is what makes a dry run worth reading.
    """
    edited: list[tuple[Path, str]] = []
    for package_file in group.package_files:
        path = root / package_file
        mine = [update for update in group.updates if update.package_file == package_file]
        edited.append((path, apply_all(_read(path), mine)))
    if write:
        for path, text in edited:
            _write(path, text)
    return group.package_files


def split_repeats(
    root: Path,
    updates: Sequence[Update],
) -> tuple[list[Update], list[tuple[Update, Update]]]:
    """
    Split off each update that makes the same edit as one before it, found by another manager.

    Returns the updates to keep, and each repeat paired with the update it repeats.
    """
    kept: list[Update] = []
    repeats: list[tuple[Update, Update]] = []
    texts: dict[str, str] = {}
    for update in updates:
        first = next((one for one in kept if _same_edit(root, texts, one, update)), None)
        if first is None:
            kept.append(update)
        else:
            repeats.append((update, first))
    return kept, repeats


def _same_edit(root: Path, texts: dict[str, str], first: Update, second: Update) -> bool:
    """Compare two updates against their file, reading each file once."""
    if first.package_file != second.package_file:
        return False
    if first.package_file not in texts:
        texts[first.package_file] = _read(root / first.package_file)
    return same_edit(texts[first.package_file], first, second)


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
