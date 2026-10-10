"""Writing the package files: every edit of a group, and nothing else about the file."""

from pathlib import Path

import pytest
from helpers import WORKFLOW, docker_update, wrangler_updates

from renovate_apply.errors import ReplaceError
from renovate_apply.files import apply_group, split_repeats
from renovate_apply.models import Group


def test_apply_group_makes_every_edit_of_one_file(tmp_path: Path) -> None:
    """Two images in one compose file are two edits and one write."""
    path = tmp_path / "stack" / "compose.yaml"
    path.parent.mkdir()
    path.write_text(
        "a: ghcr.io/atuinsh/atuin:v18.13.3@sha256:aaaa\nb: postgres:18-alpine@sha256:bbbb\n",
        encoding="utf-8",
    )
    group = Group(
        "renovate/stack-images",
        (
            docker_update(),
            docker_update(
                dep_name="postgres",
                current_value="18-alpine",
                new_value="18.1-alpine",
                current_digest="sha256:bbbb",
                new_digest="sha256:dddd",
                replace_string="postgres:18-alpine@sha256:bbbb",
            ),
        ),
    )
    assert apply_group(tmp_path, group) == ("stack/compose.yaml",)
    assert path.read_text(encoding="utf-8") == (
        "a: ghcr.io/atuinsh/atuin:18.22.0@sha256:cccc\nb: postgres:18.1-alpine@sha256:dddd\n"
    )


def test_apply_group_writes_nothing_when_asked_not_to(tmp_path: Path) -> None:
    """A dry run computes every edit and leaves the file byte for byte as it was."""
    path = tmp_path / "stack" / "compose.yaml"
    path.parent.mkdir()
    original = "a: ghcr.io/atuinsh/atuin:v18.13.3@sha256:aaaa\n"
    path.write_text(original, encoding="utf-8")
    group = Group("renovate/stack-images", (docker_update(),))
    assert apply_group(tmp_path, group, write=False) == ("stack/compose.yaml",)
    assert path.read_text(encoding="utf-8") == original


def test_apply_group_keeps_windows_line_endings(tmp_path: Path) -> None:
    """A CRLF file stays CRLF, so the diff is the one line that moved."""
    path = tmp_path / "stack" / "compose.yaml"
    path.parent.mkdir()
    path.write_bytes(b"a: ghcr.io/atuinsh/atuin:v18.13.3@sha256:aaaa\r\nb: keep\r\n")
    apply_group(tmp_path, Group("renovate/stack-images", (docker_update(),)))
    assert path.read_bytes() == b"a: ghcr.io/atuinsh/atuin:18.22.0@sha256:cccc\r\nb: keep\r\n"


def test_apply_group_reports_a_file_it_cannot_read(tmp_path: Path) -> None:
    """A package file the report names and the disk does not have is a fault, not a skip."""
    with pytest.raises(ReplaceError, match="cannot read"):
        apply_group(tmp_path, Group("renovate/stack-images", (docker_update(),)))


def test_split_repeats_keeps_the_first_of_one_edit_found_twice(tmp_path: Path) -> None:
    """The later report of the same line is paired with the update that already makes the edit."""
    action, regex = wrangler_updates()
    path = tmp_path / action.package_file
    path.parent.mkdir(parents=True)
    path.write_text(WORKFLOW, encoding="utf-8")
    other = docker_update()
    assert split_repeats(tmp_path, [action, other, regex]) == ([action, other], [(regex, action)])


def test_apply_group_writes_nothing_when_a_later_file_cannot_be_edited(tmp_path: Path) -> None:
    """
    A group is all of its files or none of them.

    Written as it went, the first file would stay edited after the group was reported as failed, and
    the next group to touch it would stage and commit that edit under its own message.
    """
    first = tmp_path / "compose.yaml"
    original = "a: ghcr.io/atuinsh/atuin:v18.13.3@sha256:aaaa\n"
    first.write_text(original, encoding="utf-8")
    (tmp_path / "other.yaml").write_text("b: postgres:18-alpine@sha256:bbbb\n", encoding="utf-8")
    group = Group(
        "renovate/stack-images",
        (
            docker_update(package_file="compose.yaml"),
            docker_update(
                package_file="other.yaml",
                dep_name="postgres",
                replace_string="postgres:1-already-gone@sha256:zzzz",
            ),
        ),
    )
    with pytest.raises(ReplaceError, match="is not in"):
        apply_group(tmp_path, group)
    assert first.read_text(encoding="utf-8") == original
