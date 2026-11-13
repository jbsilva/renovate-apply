"""Refreshing the lock file that sits beside an edited manifest."""

import shutil
import subprocess
from pathlib import Path

import pytest
from helpers import npm_lock_update

from renovate_apply.errors import LockError, NoSolutionError
from renovate_apply.lockfiles import NPM, refresh


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

    with pytest.raises(NoSolutionError, match="No solution found"):
        refresh(tmp_path, ["pyproject.toml"])


def test_refresh_tells_a_broken_uv_from_an_unsolvable_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A network failure says nothing about the update, so it is a plain failure, not a hold."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 2, "", "Failed to fetch"),
    )

    with pytest.raises(LockError, match="Failed to fetch") as raised:
        refresh(tmp_path, ["pyproject.toml"])
    assert not isinstance(raised.value, NoSolutionError)


def test_refresh_puts_back_a_lock_file_it_already_refreshed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A group over two projects that fails on the second leaves the first one's lock as it was."""
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (tmp_path / name / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        cwd = kwargs.get("cwd")
        assert isinstance(cwd, Path)
        if cwd.name == "second":
            return subprocess.CompletedProcess(argv, 1, "", "No solution found")
        (cwd / "uv.lock").write_text("version = 1  # relocked\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(NoSolutionError):
        refresh(tmp_path, ["first/pyproject.toml", "second/pyproject.toml"])
    assert (tmp_path / "first" / "uv.lock").read_text(encoding="utf-8") == "version = 1\n"


def with_npm_project(root: Path) -> None:
    """Write a package.json with a package-lock.json beside it."""
    (root / "package.json").write_text("{}\n", encoding="utf-8")
    (root / "package-lock.json").write_text("{}\n", encoding="utf-8")


def test_refresh_relocks_a_package_json_with_npm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new version in package.json leaves package-lock.json behind until npm writes it."""
    with_npm_project(tmp_path)
    commands: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(subprocess, "run", run)

    assert refresh(tmp_path, ["package.json"]) == ("package-lock.json",)
    assert commands == [list(NPM.argv)]


def test_refresh_never_lets_npm_install_or_run_scripts() -> None:
    """Only the lock file is written: a dependency's install script has no business running here."""
    assert {"--package-lock-only", "--ignore-scripts"} <= set(NPM.argv)


def test_refresh_relocks_uv_and_npm_projects_of_one_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each manifest goes to its own package manager, in its own directory."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / "web").mkdir()
    with_npm_project(tmp_path / "web")
    calls: list[tuple[str, Path]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        cwd = kwargs.get("cwd")
        assert isinstance(cwd, Path)
        calls.append((argv[0], cwd))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(subprocess, "run", run)

    files = refresh(tmp_path, ["pyproject.toml", "web/package.json"])
    assert files == ("uv.lock", "web/package-lock.json")
    assert calls == [("uv", tmp_path), ("npm", tmp_path / "web")]


def test_refresh_does_nothing_for_a_package_json_without_a_lock_file(tmp_path: Path) -> None:
    """A package.json that is never locked, or locked by another tool, is left to its owner."""
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("\n", encoding="utf-8")
    assert refresh(tmp_path, ["package.json"]) == ()


def test_refresh_says_what_to_do_when_npm_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The message names npm, not uv, and the way around it."""
    with_npm_project(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(LockError, match=r"npm is not on PATH.*--no-lock"):
        refresh(tmp_path, ["package.json"])


def test_refresh_holds_a_package_json_npm_cannot_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A peer dependency conflict is npm's "no solution", so the group is held, not failed."""
    with_npm_project(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(
            argv, 1, "", "npm error code ERESOLVE\nnpm error ERESOLVE unable to resolve"
        ),
    )

    with pytest.raises(NoSolutionError, match="npm install failed in"):
        refresh(tmp_path, ["package.json"])


def test_refresh_fails_an_npm_run_that_only_warned_about_eresolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A warning about a peer override is not the reason the run failed, so nothing is held."""
    with_npm_project(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(
            argv, 1, "", "npm warn ERESOLVE overriding peer dependency\nnpm error code ETARGET"
        ),
    )

    with pytest.raises(LockError, match="ETARGET") as raised:
        refresh(tmp_path, ["package.json"])
    assert not isinstance(raised.value, NoSolutionError)


def test_refresh_moves_a_lock_file_update_and_keeps_the_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Npm saves name@version into package.json, so it is put back and npm runs again to match."""
    with_npm_project(tmp_path)
    seen: list[tuple[list[str], str]] = []

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append((argv, (tmp_path / "package.json").read_text(encoding="utf-8")))
        if argv[-1] == "osls@4.5.0":
            (tmp_path / "package.json").write_text('{"osls": "^4.5.0"}\n', encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(subprocess, "run", run)

    assert refresh(tmp_path, ["package.json"], [npm_lock_update()]) == ("package-lock.json",)
    assert seen == [([*NPM.argv, "osls@4.5.0"], "{}\n"), (list(NPM.argv), "{}\n")]
    assert (tmp_path / "package.json").read_text(encoding="utf-8") == "{}\n"


def test_refresh_puts_the_manifest_back_when_a_lock_file_update_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed npm run that already rewrote package.json leaves it as it was."""
    with_npm_project(tmp_path)

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        (tmp_path / "package.json").write_text('{"osls": "^4.5.0"}\n', encoding="utf-8")
        return subprocess.CompletedProcess(argv, 1, "", "npm error code ETARGET")

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(LockError, match="ETARGET"):
        refresh(tmp_path, ["package.json"], [npm_lock_update()])
    assert (tmp_path / "package.json").read_text(encoding="utf-8") == "{}\n"
