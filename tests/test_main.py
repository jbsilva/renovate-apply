"""The command itself, over a real repository, with the scan replaced by a report."""

from pathlib import Path

import pytest
from helpers import docker_update, git, hook_update, report_for, run_cli

from renovate_apply import main as main_module
from renovate_apply.models import Update


def given_report(monkeypatch: pytest.MonkeyPatch, *updates: Update) -> None:
    """Replace the Renovate run with a report holding *updates*, so no network is needed."""
    report = report_for(*updates)
    monkeypatch.setattr(main_module, "scan", lambda *_args, **_kwargs: report)


def subjects(repo: Path) -> list[str]:
    """Return the commit subjects on the branch, newest last."""
    log = git(repo, "log", "--reverse", "--pretty=%s").stdout.strip()
    return log.splitlines()


def test_applies_and_commits_one_group_per_branch(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The images and the hook revs are two Renovate branches, so they are two commits."""
    given_report(monkeypatch, docker_update(), hook_update())
    assert run_cli(str(repo)) == 0

    assert subjects(repo)[1:] == [
        "deps: update ghcr.io/atuinsh/atuin to 18.22.0",
        "deps: update crate-ci/typos to v0.16.9",
    ]
    compose = (repo / "stack" / "compose.yaml").read_text(encoding="utf-8")
    hooks = (repo / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "atuin:18.22.0@sha256:cccc" in compose
    assert "typos\n    rev: v0.16.9" in hooks
    assert git(repo, "status", "--porcelain").stdout == ""


def test_dry_run_changes_nothing_at_all(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A dry run is for reading: no file written, no commit made."""
    before = (repo / "stack" / "compose.yaml").read_text(encoding="utf-8")
    given_report(monkeypatch, docker_update())
    assert run_cli(str(repo), "--dry-run") == 0

    assert (repo / "stack" / "compose.yaml").read_text(encoding="utf-8") == before
    assert len(subjects(repo)) == 1


def test_no_commit_leaves_the_edits_to_be_read(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One review of everything at once: the files move, git does not."""
    given_report(monkeypatch, docker_update())
    assert run_cli(str(repo), "--no-commit") == 0

    assert "atuin:18.22.0" in (repo / "stack" / "compose.yaml").read_text(encoding="utf-8")
    assert len(subjects(repo)) == 1
    assert git(repo, "status", "--porcelain").stdout.strip().endswith("stack/compose.yaml")


def test_refuses_to_commit_on_a_dirty_working_copy(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A commit takes the whole index, so an unrelated change stops the run before the scan."""
    (repo / "notes.txt").write_text("in progress\n", encoding="utf-8")
    given_report(monkeypatch, docker_update())
    assert run_cli(str(repo)) == 1
    assert "working copy has changes" in capsys.readouterr().err


def test_holds_a_major_and_says_so(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A major is reported, not applied, until it is asked for by name."""
    given_report(monkeypatch, docker_update(update_type="major", new_value="19.0.0"))
    assert run_cli(str(repo)) == 0

    output = capsys.readouterr().out
    assert "Held back" in output
    assert "Nothing to apply." in output
    assert len(subjects(repo)) == 1


def test_applies_a_major_when_it_is_asked_for(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--major is the answer to the hold, and it commits like anything else."""
    given_report(monkeypatch, docker_update(update_type="major", new_value="19.0.0"))
    assert run_cli(str(repo), "--major") == 0

    assert subjects(repo)[-1] == "deps: update ghcr.io/atuinsh/atuin to 19.0.0"


def test_stops_when_a_file_no_longer_holds_what_the_report_described(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An edit that cannot be placed is a fault: nothing is written and nothing is committed."""
    given_report(monkeypatch, docker_update(replace_string="ghcr.io/atuinsh/atuin:v9@sha256:zzzz"))
    assert run_cli(str(repo)) == 1
    assert "is not in" in capsys.readouterr().err
    assert len(subjects(repo)) == 1


def test_applies_the_other_groups_when_one_cannot_be_placed(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    One group that cannot be applied does not take the rest of the run with it.

    Each group is its own commit over its own files, so a stale dependency in one says nothing about
    the others. The bad group is reported, the good ones are committed, and the run still ends with
    an error so nothing reads it as a clean pass.
    """
    given_report(
        monkeypatch,
        docker_update(replace_string="ghcr.io/atuinsh/atuin:v9@sha256:zzzz"),
        hook_update(),
    )
    assert run_cli(str(repo)) == 1

    assert "is not in" in capsys.readouterr().err
    assert subjects(repo)[1:] == ["deps: update crate-ci/typos to v0.16.9"]
    assert git(repo, "status", "--porcelain").stdout == ""


def test_says_when_there_is_nothing_to_do(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An up-to-date repository gets one line and no commits."""
    given_report(monkeypatch)
    assert run_cli(str(repo)) == 0

    assert "Nothing to apply." in capsys.readouterr().out
    assert len(subjects(repo)) == 1
