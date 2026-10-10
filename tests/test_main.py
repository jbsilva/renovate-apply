"""The command itself, over a real repository, with the scan replaced by a report."""

from collections.abc import Sequence
from pathlib import Path

import pytest
from helpers import (
    WORKFLOW,
    docker_update,
    git,
    hook_update,
    report_for,
    run_cli,
    wrangler_updates,
)

from renovate_apply import main as main_module
from renovate_apply.errors import LockError, NoSolutionError
from renovate_apply.models import Update
from renovate_apply.report import HELD_NO_SOLUTION


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
    """A commit takes the whole index, so a tracked change stops the run before the scan."""
    (repo / ".pre-commit-config.yaml").write_text("half done\n", encoding="utf-8")
    given_report(monkeypatch, docker_update())
    assert run_cli(str(repo)) == 1
    assert "working copy has changes" in capsys.readouterr().err


def test_an_untracked_file_does_not_stop_the_run(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing untracked reaches a commit, so a scratch file in the tree is not in the way."""
    (repo / "notes.txt").write_text("in progress\n", encoding="utf-8")
    given_report(monkeypatch, docker_update())
    assert run_cli(str(repo)) == 0

    assert subjects(repo)[1:] == ["deps: update ghcr.io/atuinsh/atuin to 18.22.0"]
    assert git(repo, "status", "--porcelain").stdout.strip() == "?? notes.txt"


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


def test_takes_the_commit_prefix_it_is_given(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A project on semantic commits gets build(deps): without editing anything here."""
    given_report(monkeypatch, docker_update())
    assert run_cli(str(repo), "--prefix", "build(deps):") == 0

    assert subjects(repo)[-1].startswith("build(deps): update ")


def write_prefix(directory: Path, prefix: str) -> None:
    """Give a directory a pyproject.toml that sets the commit prefix and nothing else."""
    (directory / "pyproject.toml").write_text(
        f'[tool.renovate-apply]\nprefix = "{prefix}"\n',
        encoding="utf-8",
    )


def test_defaults_come_from_the_repository_being_updated(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The settings belong to the repository named on the command line, not to the shell's directory.

    cyclopts resolves a Toml config against the working directory, so left alone it would write the
    caller's own prefix into another repository's commits.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    write_prefix(elsewhere, "caller:")
    write_prefix(repo, "target:")
    monkeypatch.chdir(elsewhere)
    given_report(monkeypatch, docker_update())
    assert run_cli(str(repo)) == 0

    assert subjects(repo)[-1] == "target: update ghcr.io/atuinsh/atuin to 18.22.0"


def test_a_flag_beats_the_file(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The file holds defaults, so what is typed for one run wins over it."""
    write_prefix(repo, "target:")
    given_report(monkeypatch, docker_update())
    assert run_cli(str(repo), "--prefix", "typed:") == 0

    assert subjects(repo)[-1].startswith("typed: ")


def test_a_repository_without_a_manifest_uses_the_built_in_defaults(
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An infrastructure repository has no pyproject.toml, and no parent of it speaks for it."""
    write_prefix(tmp_path, "parent:")
    given_report(monkeypatch, docker_update())
    assert run_cli(str(repo)) == 0

    assert subjects(repo)[-1].startswith("deps: ")


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


def test_a_failed_group_leaves_nothing_for_the_next_group_to_commit(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A group that fails puts nothing in the commit of a group that shares one of its files.

    Both groups edit the compose file; the first also edits a hook rev the file no longer holds.
    Were the compose edit written before that failure, the second group's ``git add`` would stage it
    and commit an update the run had just reported as not applied.
    """
    given_report(
        monkeypatch,
        docker_update(branch_name="renovate/first"),
        hook_update(branch_name="renovate/first", current_value="v9.9.9-gone", new_value="v9.9.10"),
        docker_update(
            branch_name="renovate/second",
            dep_name="postgres",
            replace_string="postgres:18-alpine@sha256:bbbb",
            current_value="18-alpine",
            new_value="18.1-alpine",
            current_digest="sha256:bbbb",
            new_digest="sha256:dddd",
        ),
    )
    assert run_cli(str(repo)) == 1

    compose = (repo / "stack" / "compose.yaml").read_text(encoding="utf-8")
    assert subjects(repo)[1:] == ["deps: update postgres to 18.1-alpine"]
    assert "atuin:v18.13.3@sha256:aaaa" in compose
    assert "postgres:18.1-alpine@sha256:dddd" in compose
    assert git(repo, "status", "--porcelain").stdout == ""


def test_a_token_can_come_from_the_environment(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GITHUB_TOKEN keeps the token out of argv, which every process on the machine can read."""
    seen: dict[str, object] = {}

    def fake_scan(_root: Path, **kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return report_for()

    monkeypatch.setattr(main_module, "scan", fake_scan)
    monkeypatch.setenv("GITHUB_TOKEN", "gho_from_env")
    assert run_cli(str(repo)) == 0

    assert seen["token"] == "gho_from_env"  # noqa: S105 - a made-up token, not a credential


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


def test_passes_on_what_renovate_complained_about(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A warning from Renovate is the user's to see, even when the run went fine."""
    report = report_for(docker_update())
    report["problems"] = [{"msg": "GitHub rate limit reached"}]
    monkeypatch.setattr(main_module, "scan", lambda *_args, **_kwargs: report)
    assert run_cli(str(repo)) == 0

    assert "GitHub rate limit reached" in capsys.readouterr().err


def test_skips_a_dependency_named_on_the_command_line(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--skip is the answer to a dependency the report cannot say is on the dashboard."""
    given_report(monkeypatch, docker_update(), hook_update())
    assert run_cli(str(repo), "--skip", "ghcr.io/atuinsh/*") == 0

    assert "skipped by configuration" in capsys.readouterr().out
    assert subjects(repo)[1:] == ["deps: update crate-ci/typos to v0.16.9"]


def test_one_line_two_managers_found_is_one_commit(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The second report of a line is held, so the run neither fails on it nor edits it twice."""
    action, regex = wrangler_updates()
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / action.package_file).write_text(WORKFLOW, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "workflow")
    given_report(monkeypatch, action, regex)
    assert run_cli(str(repo)) == 0

    assert subjects(repo)[2:] == ["deps: update wrangler to 4.148.0"]
    assert 'wranglerVersion: "4.148.0"' in (repo / action.package_file).read_text(encoding="utf-8")
    held = "the same edit as the github-actions update, in renovate/github-actions"
    assert f"wrangler -> 4.148.0 ({held})" in capsys.readouterr().out


def with_manifest(repo: Path) -> None:
    """Commit a pyproject.toml with a uv.lock beside it, for the lock file tests."""
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    (repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "add a manifest")


def manifest_update(**overrides: object) -> Update:
    """Return an update to the manifest that with_manifest commits."""
    fields: dict[str, object] = {
        "manager": "pep621",
        "package_file": "pyproject.toml",
        "dep_name": "cyclopts",
        "branch_name": "renovate/python",
        "replace_string": 'name = "x"',
        "replace_template": None,
        "current_value": "x",
        "new_value": "y",
        "current_digest": None,
        "new_digest": None,
    }
    fields.update(overrides)
    return docker_update(**fields)


def relocks(root: Path, package_files: Sequence[str]) -> tuple[str, ...]:
    """Stand in for refresh: rewrite uv.lock the way a successful uv lock would."""
    if "pyproject.toml" not in package_files:
        return ()
    (root / "uv.lock").write_text("version = 1  # relocked\n", encoding="utf-8")
    return ("uv.lock",)


def fails_to_lock(error: LockError) -> object:
    """Stand in for refresh: fail with *error* on the manifest, pass over any other file."""

    def refresh(_root: Path, package_files: Sequence[str]) -> tuple[str, ...]:
        if "pyproject.toml" in package_files:
            raise error
        return ()

    return refresh


def test_refreshes_the_lock_file_beside_an_edited_manifest(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manifest and the lock file that matches it belong in the same commit."""
    with_manifest(repo)
    monkeypatch.setattr(main_module, "refresh", relocks)
    given_report(monkeypatch, manifest_update())
    assert run_cli(str(repo)) == 0

    files = git(repo, "show", "--name-only", "--pretty=", "HEAD").stdout.split()
    assert files == ["pyproject.toml", "uv.lock"]


def test_a_group_that_does_not_lock_is_undone_and_held_back(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    A floor uv cannot satisfy is put back and listed, and the rest of the run goes on.

    Left edited, the manifest would be refused by the repository's own uv-lock hook at the next
    commit, long after this run reported it.
    """
    with_manifest(repo)
    monkeypatch.setattr(
        main_module,
        "refresh",
        fails_to_lock(NoSolutionError("uv lock failed in .:\nNo solution found")),
    )
    given_report(monkeypatch, manifest_update(), docker_update())
    assert run_cli(str(repo)) == 0

    captured = capsys.readouterr()
    assert "does not lock, undone" in captured.err
    assert "No solution found" in captured.err
    assert f"cyclopts -> y ({HELD_NO_SOLUTION})" in captured.out
    assert subjects(repo)[2:] == ["deps: update ghcr.io/atuinsh/atuin to 18.22.0"]
    assert (repo / "pyproject.toml").read_text(encoding="utf-8") == '[project]\nname = "x"\n'
    assert git(repo, "status", "--porcelain").stdout == ""


def test_a_group_held_back_alone_leaves_nothing_to_apply(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When the one group does not lock, the run says nothing was applied, and does not fail."""
    with_manifest(repo)
    monkeypatch.setattr(main_module, "refresh", fails_to_lock(NoSolutionError("no solution")))
    given_report(monkeypatch, manifest_update())
    assert run_cli(str(repo)) == 0

    assert "Nothing to apply." in capsys.readouterr().out


def test_a_lock_that_fails_for_another_reason_fails_the_group(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A uv that could not run says nothing about the update, so the run fails, still undone."""
    with_manifest(repo)
    monkeypatch.setattr(main_module, "refresh", fails_to_lock(LockError("Failed to fetch")))
    given_report(monkeypatch, manifest_update())
    assert run_cli(str(repo)) == 1

    assert "Failed to fetch" in capsys.readouterr().err
    assert (repo / "pyproject.toml").read_text(encoding="utf-8") == '[project]\nname = "x"\n'
    assert git(repo, "status", "--porcelain").stdout == ""


def test_stage_stages_each_group_and_commits_nothing(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--stage is for one review of the run's own edits in the index, apart from anything else."""
    with_manifest(repo)
    monkeypatch.setattr(main_module, "refresh", relocks)
    given_report(monkeypatch, manifest_update(), docker_update())
    assert run_cli(str(repo), "--stage") == 0

    staged = git(repo, "diff", "--cached", "--name-only").stdout.split()
    assert staged == ["pyproject.toml", "stack/compose.yaml", "uv.lock"]
    assert len(subjects(repo)) == 2
    assert "Staged, not committed." in capsys.readouterr().out


def test_dry_run_beats_stage(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag that does less wins, so nothing is written, let alone staged."""
    before = (repo / "stack" / "compose.yaml").read_text(encoding="utf-8")
    given_report(monkeypatch, docker_update())
    assert run_cli(str(repo), "--stage", "--dry-run") == 0

    assert (repo / "stack" / "compose.yaml").read_text(encoding="utf-8") == before
    assert git(repo, "status", "--porcelain").stdout == ""
