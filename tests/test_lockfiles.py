"""Refreshing the lock file that sits beside an edited manifest."""

import shutil
import subprocess
from pathlib import Path

import pytest

from renovate_apply.errors import LockError
from renovate_apply.lockfiles import refresh


def uv_run(recorder: list[Path]) -> object:
    """Return a stand-in for subprocess.run that records where uv was asked to run."""

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        cwd = kwargs.get("cwd")
        assert isinstance(cwd, Path)
        recorder.append(cwd)
        return subprocess.CompletedProcess(argv, 0, "", "")

    return run


def test_refresh_relocks_a_manifest_that_has_a_lock_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raised floor in pyproject.toml is only half the change; uv.lock is the other half."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    calls: list[Path] = []
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(subprocess, "run", uv_run(calls))

    assert refresh(tmp_path, ["pyproject.toml"]) == ("uv.lock",)
    assert calls == [tmp_path]


def test_refresh_finds_the_lock_file_of_a_nested_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manifest in a subdirectory is relocked there, not at the repository root."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "app" / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    calls: list[Path] = []
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(subprocess, "run", uv_run(calls))

    assert refresh(tmp_path, ["app/pyproject.toml"]) == ("app/uv.lock",)
    assert calls == [tmp_path / "app"]


def test_refresh_does_nothing_without_a_lock_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A project that does not lock has nothing to refresh, and uv is never run."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    calls: list[Path] = []
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(subprocess, "run", uv_run(calls))

    assert refresh(tmp_path, ["pyproject.toml"]) == ()
    assert calls == []


def test_refresh_ignores_files_that_are_not_manifests(tmp_path: Path) -> None:
    """A compose file or a workflow has no lock file behind it."""
    assert refresh(tmp_path, ["stack/compose.yaml", ".github/workflows/ci.yml"]) == ()


def test_refresh_says_what_to_do_when_uv_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Committing a manifest whose lock file was left behind would break `uv sync --locked`."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(LockError, match="--no-lock"):
        refresh(tmp_path, ["pyproject.toml"])


def test_refresh_reports_what_uv_said_when_it_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unresolvable bump stops the run with uv's own explanation."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 1, "", "No solution found"),
    )

    with pytest.raises(LockError, match="No solution found"):
        refresh(tmp_path, ["pyproject.toml"])
