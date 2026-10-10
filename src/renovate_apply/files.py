"""
Read a package file, make every edit of one group in it, and write it back.

Files are read and written with ``newline=""`` so line endings survive untouched. A repository with
CRLF files would otherwise come back rewritten from top to bottom, and the one-line diff Renovate
promises would be the whole file.
"""

lazy from pathlib import Path

from renovate_apply.errors import ReplaceError
from renovate_apply.replace import apply_all
lazy from renovate_apply.models import Group


ENCODING = "utf-8"


def apply_group(root: Path, group: Group, *, write: bool = True) -> tuple[str, ...]:
    """
    Make every edit of *group*, and return the package files it touched.

    With ``write=False`` every edit is still computed, so a file the report no longer matches fails
    here as loudly as it would when writing. That is what makes a dry run worth reading.
    """
    for package_file in group.package_files:
        path = root / package_file
        mine = [update for update in group.updates if update.package_file == package_file]
        text = apply_all(_read(path), mine)
        if write:
            _write(path, text)
    return group.package_files


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
