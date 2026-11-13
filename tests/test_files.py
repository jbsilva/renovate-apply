"""Writing the package files: every edit of a group, and nothing else about the file."""

from dataclasses import replace
from pathlib import Path

import pytest
from helpers import WORKFLOW, docker_update, wrangler_updates

from renovate_apply.errors import ReplaceError
from renovate_apply.files import apply_group, repeats_of, restore, snapshot
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


def test_apply_group_writes_nothing_when_given_drafts(tmp_path: Path) -> None:
    """A dry run computes every edit, keeps it in the drafts, and leaves the file as it was."""
    path = tmp_path / "stack" / "compose.yaml"
    path.parent.mkdir()
    original = "a: ghcr.io/atuinsh/atuin:v18.13.3@sha256:aaaa\n"
    path.write_text(original, encoding="utf-8")
    drafts: dict[str, str] = {}
    group = Group("renovate/stack-images", (docker_update(),))
    assert apply_group(tmp_path, group, drafts=drafts) == ("stack/compose.yaml",)
    assert path.read_text(encoding="utf-8") == original
    assert drafts == {"stack/compose.yaml": "a: ghcr.io/atuinsh/atuin:18.22.0@sha256:cccc\n"}


def test_apply_group_reads_a_file_from_the_drafts_first(tmp_path: Path) -> None:
    """A later group of a dry run edits the text an earlier group would have written."""
    path = tmp_path / "stack" / "compose.yaml"
    path.parent.mkdir()
    path.write_text("a: ghcr.io/atuinsh/atuin:v18.13.3@sha256:aaaa\n", encoding="utf-8")
    drafts = {"stack/compose.yaml": "a: ghcr.io/atuinsh/atuin:18.22.0@sha256:cccc\n"}
    major = docker_update(
        current_value="18.22.0",
        new_value="19.0.0",
        current_digest="sha256:cccc",
        new_digest="sha256:eeee",
        replace_string="ghcr.io/atuinsh/atuin:18.22.0@sha256:cccc",
    )
    apply_group(tmp_path, Group("renovate/major-atuin", (major,)), drafts=drafts)
    assert drafts["stack/compose.yaml"] == "a: ghcr.io/atuinsh/atuin:19.0.0@sha256:eeee\n"


def test_apply_group_keeps_windows_line_endings(tmp_path: Path) -> None:
    """A CRLF file stays CRLF, so the diff is the one line that moved."""
    path = tmp_path / "stack" / "compose.yaml"
    path.parent.mkdir()
    path.write_bytes(b"a: ghcr.io/atuinsh/atuin:v18.13.3@sha256:aaaa\r\nb: keep\r\n")
    apply_group(tmp_path, Group("renovate/stack-images", (docker_update(),)))
    assert path.read_bytes() == b"a: ghcr.io/atuinsh/atuin:18.22.0@sha256:cccc\r\nb: keep\r\n"


def test_apply_group_reports_a_file_it_cannot_read(tmp_path: Path) -> None:
    """A package file the report names and the disk does not have is a fault, not a skip."""
    group = Group("renovate/stack-images", (docker_update(),))
    with pytest.raises(ReplaceError, match="cannot read"):
        apply_group(tmp_path, group)


def test_repeats_of_names_the_first_of_one_edit_found_twice(tmp_path: Path) -> None:
    """The later report of the same line points at the update that already makes the edit."""
    action, regex = wrangler_updates()
    path = tmp_path / action.package_file
    path.parent.mkdir(parents=True)
    path.write_text(WORKFLOW, encoding="utf-8")
    other = docker_update()
    assert repeats_of(tmp_path, [action, other, regex]) == [None, None, action]


def test_repeats_of_keeps_the_second_use_of_a_text_another_manager_found_once(
    tmp_path: Path,
) -> None:
    """A regex manager that also finds the second copy of a line edits that copy itself."""
    (tmp_path / "Dockerfile").write_text("FROM node:18.0.0\nFROM node:18.0.0\n", encoding="utf-8")
    built_in = docker_update(
        manager="dockerfile",
        package_file="Dockerfile",
        dep_name="node",
        current_value="18.0.0",
        new_value="18.0.1",
        current_digest=None,
        new_digest=None,
        replace_string="node:18.0.0",
        replace_template="{{depName}}:{{newValue}}",
    )
    first_line = replace(built_in, manager="regex", dep_index=0)
    second_line = replace(first_line, dep_index=1)
    assert repeats_of(tmp_path, [built_in, first_line, second_line]) == [None, built_in, None]


def test_repeats_of_compares_uses_by_line_across_branches(tmp_path: Path) -> None:
    """Two equal lines a built-in manager puts on two branches are still a first and a second."""
    (tmp_path / "Dockerfile").write_text("FROM node:18.0.0\nFROM node:18.0.0\n", encoding="utf-8")
    stage = docker_update(
        manager="dockerfile",
        package_file="Dockerfile",
        dep_name="node",
        branch_name="renovate/stage",
        current_value="18.0.0",
        new_value="18.0.1",
        current_digest=None,
        new_digest=None,
        replace_string="node:18.0.0",
        replace_template="{{depName}}:{{newValue}}",
        dep_index=0,
    )
    final = replace(stage, branch_name="renovate/final", dep_index=1)
    first_line = replace(stage, manager="regex", branch_name="renovate/regex")
    second_line = replace(first_line, dep_index=1)
    updates = [stage, final, first_line, second_line]
    assert repeats_of(tmp_path, updates) == [None, None, stage, final]


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


def test_restore_puts_back_what_snapshot_read(tmp_path: Path) -> None:
    """An edit that has to be undone comes back byte for byte, Windows line endings included."""
    path = tmp_path / "pyproject.toml"
    path.write_bytes(b"[project]\r\ndependencies = []\r\n")
    originals = snapshot(tmp_path, ["pyproject.toml"])
    path.write_text("edited\n", encoding="utf-8")

    restore(tmp_path, originals)
    assert path.read_bytes() == b"[project]\r\ndependencies = []\r\n"
