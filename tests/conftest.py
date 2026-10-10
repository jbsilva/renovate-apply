"""Shared pytest fixtures for the renovate-apply test suite."""

from pathlib import Path

import pytest
from helpers import COMPOSE, HOOKS, git


@pytest.fixture
def git_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Cut git off from the machine it runs on.

    Without this the suite would read the developer's own ~/.gitconfig, and a commit.gpgsign or a
    missing user.email there would fail the commit tests for reasons that have nothing to do with
    this package.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(tmp_path / "gitconfig-system"))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")


@pytest.fixture
def repo(tmp_path: Path, git_env: None) -> Path:
    """Return a git repository holding one compose file and one pre-commit config, committed."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "stack").mkdir()
    (root / "stack" / "compose.yaml").write_text(COMPOSE, encoding="utf-8")
    (root / ".pre-commit-config.yaml").write_text(HOOKS, encoding="utf-8")
    git(root, "init", "--initial-branch=main")
    git(root, "add", "-A")
    git(root, "commit", "-m", "initial")
    return root
