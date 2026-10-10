"""The git layer, against a real repository in a temporary directory."""

from pathlib import Path

import pytest
from helpers import git

from renovate_apply.errors import GitError, WorkingCopyError
from renovate_apply.git import commit, require_clean, require_repository


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


def test_commit_stages_only_the_files_it_was_given(repo: Path) -> None:
    """The commit holds the package file that moved and not whatever else was lying around."""
    (repo / "stack" / "compose.yaml").write_text("image: new\n", encoding="utf-8")
    (repo / "unrelated.txt").write_text("untracked\n", encoding="utf-8")
    commit(repo, ["stack/compose.yaml"], ["deps: update the stack images", "atuin  1 -> 2"])

    subject = git(repo, "log", "-1", "--pretty=%s").stdout.strip()
    body = git(repo, "log", "-1", "--pretty=%b").stdout.strip()
    files = git(repo, "show", "--name-only", "--pretty=", "HEAD").stdout.split()
    assert subject == "deps: update the stack images"
    assert body == "atuin  1 -> 2"
    assert files == ["stack/compose.yaml"]


def test_commit_reports_what_a_failing_hook_said(repo: Path) -> None:
    """A hook that refuses the commit stops the run, with its own words in the error."""
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'the hook says no' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    (repo / "stack" / "compose.yaml").write_text("image: new\n", encoding="utf-8")
    with pytest.raises(GitError, match="the hook says no"):
        commit(repo, ["stack/compose.yaml"], ["deps: update the stack images"])


def test_commit_reports_a_file_git_cannot_stage(repo: Path) -> None:
    """A package file that is not there fails at staging, before anything is committed."""
    with pytest.raises(GitError, match="git add failed"):
        commit(repo, ["nothing/here.yaml"], ["deps: update nothing"])
