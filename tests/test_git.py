"""The git layer, against a real repository in a temporary directory."""

from pathlib import Path

import pytest
from helpers import git

from renovate_apply.errors import GitError, WorkingCopyError
from renovate_apply.git import commit, is_tracked, require_clean, require_repository, stage


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


def test_require_clean_names_the_tracked_file_in_the_way(repo: Path) -> None:
    """Staging a package file stages all of it, so an edit in flight would ride along."""
    (repo / "stack" / "compose.yaml").write_text("image: half done\n", encoding="utf-8")
    with pytest.raises(WorkingCopyError, match=r"compose\.yaml"):
        require_clean(repo)


def test_require_clean_rejects_a_staged_change(repo: Path) -> None:
    """A commit takes the index, so anything already staged is already in it."""
    (repo / "notes.txt").write_text("in progress\n", encoding="utf-8")
    git(repo, "add", "notes.txt")
    with pytest.raises(WorkingCopyError, match=r"notes\.txt"):
        require_clean(repo)


def test_require_clean_ignores_an_untracked_file(repo: Path) -> None:
    """
    A scratch file cannot reach a commit, so it is no reason to refuse the run.

    The commit stages the files this run wrote, by name, and then takes the index. An untracked file
    is in neither, as test_commit_stages_only_the_files_it_was_given shows.
    """
    (repo / "notes.txt").write_text("in progress\n", encoding="utf-8")
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


@pytest.mark.parametrize(
    ("path", "tracked"),
    [("stack/compose.yaml", True), ("notes.txt", False), ("missing.txt", False)],
    ids=["committed", "untracked", "missing"],
)
def test_is_tracked_says_whether_git_tracks_a_path(
    repo: Path,
    *,
    path: str,
    tracked: bool,
) -> None:
    """Only a committed file is one a commit may carry a change to."""
    (repo / "notes.txt").write_text("scratch\n", encoding="utf-8")
    assert is_tracked(repo, path) is tracked


def test_stage_adds_only_the_files_it_was_given_and_commits_nothing(repo: Path) -> None:
    """Staging is for a review before the commit, so the index holds the run's files alone."""
    (repo / "stack" / "compose.yaml").write_text("image: new\n", encoding="utf-8")
    (repo / ".pre-commit-config.yaml").write_text("not mine\n", encoding="utf-8")
    stage(repo, ["stack/compose.yaml"])

    assert git(repo, "diff", "--cached", "--name-only").stdout.split() == ["stack/compose.yaml"]
    assert git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_stage_reads_a_path_with_brackets_as_a_name_not_a_glob(repo: Path) -> None:
    """A Next.js route directory is one file, and an untracked look-alike stays out of it."""
    route = repo / "app" / "[id]" / "package.json"
    route.parent.mkdir(parents=True)
    route.write_text("{}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "add a route")
    route.write_text('{"a": 1}\n', encoding="utf-8")
    look_alike = repo / "app" / "i" / "package.json"
    look_alike.parent.mkdir()
    look_alike.write_text("{}\n", encoding="utf-8")

    stage(repo, ["app/[id]/package.json"])
    staged = git(repo, "diff", "--cached", "--name-only").stdout.split()
    assert staged == ["app/[id]/package.json"]
    assert not is_tracked(repo, "app/[i]/package.json")


def test_commit_leaves_the_hooks_free_to_match_paths_by_glob(repo: Path) -> None:
    """A hook that picks its files with a pattern sees the staged file, as in a commit by hand."""
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\ngit diff --cached --name-only -- '*.yaml' | grep -q .\n", encoding="utf-8"
    )
    hook.chmod(0o755)
    (repo / "stack" / "compose.yaml").write_text("image: x\n", encoding="utf-8")
    commit(repo, ["stack/compose.yaml"], ["deps: x"])


def test_stage_reads_literal_paths_when_the_environment_turns_magic_off(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exported GIT_LITERAL_PATHSPECS would make ":(literal)" part of the file name."""
    monkeypatch.setenv("GIT_LITERAL_PATHSPECS", "1")
    (repo / "stack" / "compose.yaml").write_text("image: x\n", encoding="utf-8")
    assert is_tracked(repo, "stack/compose.yaml")
    stage(repo, ["stack/compose.yaml"])
