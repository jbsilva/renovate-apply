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

    A group that fails on its second file leaves the first one as it was, whether the edit or the
    write failed. Left edited, the next group to touch that file would commit the edit under its own
    message.

    With *drafts*, nothing is written: the edited texts go into *drafts* and are read back from it,
    so a later group of a dry run finds what an earlier one would have written.
    """
    originals: dict[str, str] = {}
    edited: dict[str, str] = {}
    for package_file in group.package_files:
        # A lock file update has no text in the package file; the package manager moves it.
        mine = [
            update
            for update in group.updates
            if update.package_file == package_file and not update.is_lockfile_update
        ]
        known = drafts or {}
        text = known[package_file] if package_file in known else _read(root / package_file)
        originals[package_file] = text
        edited[package_file] = apply_all(text, mine)
    if drafts is None:
        _write_all(root, edited, originals)
    else:
        drafts.update(edited)
    return group.package_files


def _write_all(root: Path, edited: Mapping[str, str], originals: Mapping[str, str]) -> None:
    """Write every edited file, or, when one write fails, put back the ones already written."""
    written: dict[str, str] = {}
    try:
        for package_file, text in edited.items():
            _write(root / package_file, text)
            written[package_file] = originals[package_file]
    except ReplaceError:
        restore(root, written)
        raise


def repeats_of(root: Path, updates: Sequence[Update]) -> list[Update | None]:
    """
    Return, for each update, the earlier one it repeats: the same edit, found by another manager.

    None stands for an update that repeats nothing. The list lines up with *updates*.
    """
    kept: list[tuple[Update, int]] = []
    firsts: list[Update | None] = []
    texts: dict[str, str] = {}
    for update, use in zip(updates, _uses(updates), strict=True):
        first = next(
            (one for one, at in kept if _same_edit(root, texts, (one, at), (update, use))),
            None,
        )
        if first is None:
            kept.append((update, use))
        firsts.append(first)
    return firsts


def _uses(updates: Sequence[Update]) -> list[int]:
    """
    Return which copy of its text each update edits, counting from 1.

    The n-th line holding one text, for one manager, is its n-th copy, whatever branch each update
    of that line is on. Without a line number, equal updates count as successive uses.
    """
    lines: dict[tuple[object, ...], set[int]] = {}
    for update in updates:
        if update.dep_index is not None:
            lines.setdefault(_text_of(update), set()).add(update.dep_index)
    uses: list[int] = []
    for index, update in enumerate(updates):
        if update.dep_index is None:
            uses.append(updates[:index].count(update) + 1)
        else:
            uses.append(sorted(lines[_text_of(update)]).index(update.dep_index) + 1)
    return uses


def _text_of(update: Update) -> tuple[object, ...]:
    """Return what one manager found on a line, which equal lines share."""
    return (
        update.manager,
        update.package_file,
        update.replace_string,
        update.current_value,
        update.current_digest,
    )


def _same_edit(
    root: Path,
    texts: dict[str, str],
    first: tuple[Update, int],
    second: tuple[Update, int],
) -> bool:
    """Compare two uses of a text against their file, reading each file once."""
    (one, one_use), (other, other_use) = first, second
    if one.package_file != other.package_file:
        return False
    if one.package_file not in texts:
        texts[one.package_file] = _read(root / one.package_file)
    return same_edit(texts[one.package_file], one, other, uses=(one_use, other_use))


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
