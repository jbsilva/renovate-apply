"""Running Renovate: which command, which token, and what a failed run says."""

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from renovate_apply.errors import ScanError
from renovate_apply.scan import REPORT_ENV_PATH, github_token, renovate_command, scan


def fake_run(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    report: object | str | None = None,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Return a stand-in for subprocess.run that can also write the report Renovate would."""

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env")
        env = env if isinstance(env, dict) else {}
        if report is not None and REPORT_ENV_PATH in env:
            path = Path(str(env[REPORT_ENV_PATH]))
            path.write_text(
                report if isinstance(report, str) else json.dumps(report),
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    return run


def test_renovate_command_prefers_one_already_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A renovate on PATH starts in a second; npx would re-resolve the package every run."""
    monkeypatch.setattr(shutil, "which", lambda _name: f"/usr/bin/{_name}")
    assert renovate_command(None) == ["renovate"]


def test_renovate_command_asks_npx_for_a_named_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pinning a version has to go through npx, whatever is installed."""
    monkeypatch.setattr(shutil, "which", lambda _name: f"/usr/bin/{_name}")
    assert renovate_command("43.224.0")[:4] == ["npx", "--yes", "--package", "renovate@43.224.0"]


def test_renovate_command_falls_back_to_npx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without renovate installed, npx fetches the latest."""
    monkeypatch.setattr(
        shutil,
        "which",
        lambda _name: None if _name == "renovate" else "/usr/bin/npx",
    )
    assert renovate_command(None)[3] == "renovate@latest"


def test_renovate_command_says_what_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """With neither on PATH the error names both ways out."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(ScanError, match=r"install Node\.js"):
        renovate_command(None)


def test_github_token_is_empty_without_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """No gh means no token, and a run that is rate limited rather than one that fails."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert github_token() == ""


def test_github_token_reads_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """The token comes from gh, never from argv or the shell history."""
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(subprocess, "run", fake_run(stdout="gho_secret\n"))
    assert github_token() == "gho_secret"


def test_github_token_is_empty_when_gh_is_logged_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing gh is not a reason to stop; it is a reason to expect rate limits."""
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(subprocess, "run", fake_run(returncode=1))
    assert github_token() == ""


def test_scan_returns_the_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The report is read back from the path Renovate was told to write it to."""
    monkeypatch.setattr(shutil, "which", lambda _name: f"/usr/bin/{_name}")
    monkeypatch.setattr(subprocess, "run", fake_run(report={"repositories": {}}))
    assert scan(tmp_path, token="") == {"repositories": {}}


def test_scan_reports_a_failed_run_with_its_last_words(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Renovate says why it stopped on its own error stream; that is what the user needs."""
    monkeypatch.setattr(shutil, "which", lambda _name: f"/usr/bin/{_name}")
    monkeypatch.setattr(
        subprocess,
        "run",
        fake_run(returncode=60, stderr="Invalid log level"),
    )
    with pytest.raises(ScanError, match="Invalid log level"):
        scan(tmp_path, token="")


def test_scan_failure_keeps_the_fatal_error_past_the_warnings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Renovate logs its fatal error to stdout, so warnings on stderr must not push it out."""
    monkeypatch.setattr(shutil, "which", lambda _name: f"/usr/bin/{_name}")
    warnings = "\n".join(f"npm warn {number}" for number in range(20))
    monkeypatch.setattr(
        subprocess,
        "run",
        fake_run(returncode=1, stdout="FATAL: Authentication failure", stderr=warnings),
    )
    with pytest.raises(ScanError, match="Authentication failure"):
        scan(tmp_path, token="")


def test_scan_reports_a_run_that_wrote_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An exit of zero with no report means the run did not do what was asked of it."""
    monkeypatch.setattr(shutil, "which", lambda _name: f"/usr/bin/{_name}")
    monkeypatch.setattr(subprocess, "run", fake_run(stdout="all good"))
    with pytest.raises(ScanError, match="wrote no report"):
        scan(tmp_path, token="")


def test_scan_reports_a_report_that_is_not_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A truncated or half-written report is a fault to name, not to parse around."""
    monkeypatch.setattr(shutil, "which", lambda _name: f"/usr/bin/{_name}")
    monkeypatch.setattr(subprocess, "run", fake_run(report="{not json"))
    with pytest.raises(ScanError, match="cannot read the report"):
        scan(tmp_path, token="")


def test_scan_reports_a_report_that_is_not_an_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Valid JSON of the wrong shape is caught here rather than three modules later."""
    monkeypatch.setattr(shutil, "which", lambda _name: f"/usr/bin/{_name}")
    monkeypatch.setattr(subprocess, "run", fake_run(report=[1, 2]))
    with pytest.raises(ScanError, match="not an object"):
        scan(tmp_path, token="")
