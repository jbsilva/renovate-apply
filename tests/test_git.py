"""The git layer, against a real repository in a temporary directory."""

from pathlib import Path

import pytest

from renovate_apply.errors import WorkingCopyError
from renovate_apply.git import require_clean, require_repository


def test_require_repository_accepts_a_working_copy(repo: Path) -> None:
    """A repository passes without saying anything."""
    require_repository(repo)


def test_require_repository_rejects_a_plain_directory(tmp_path: Path, git_env: None) -> None:
    """A directory that was never set up is named in the error, so the fix is obvious."""
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(WorkingCopyError, match="not a git repository"):
        require_repository(plain)


def test_require_clean_passes_on_a_clean_tree(repo: Path) -> None:
    """Nothing modified, nothing staged, nothing to say."""
    require_clean(repo)


def test_require_clean_names_what_is_in_the_way(repo: Path) -> None:
    """A commit would swallow an unrelated change, so the error lists it."""
    (repo / "notes.txt").write_text("in progress\n", encoding="utf-8")
    with pytest.raises(WorkingCopyError, match=r"notes\.txt"):
        require_clean(repo)
