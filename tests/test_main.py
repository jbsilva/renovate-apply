"""The command itself, over a real repository, with the scan replaced by a report."""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from helpers import (
    WORKFLOW,
    docker_update,
    git,
    hook_update,
    npm_lock_update,
    report_for,
    run_cli,
    wrangler_updates,
)

from renovate_apply import main as main_module
from renovate_apply.errors import LockError, NoSolutionError
from renovate_apply.main import NOTHING_LEFT
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


def test_prints_the_names_of_a_group_aligned_as_in_its_commit_body(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The terminal lists the moves of a group the way git show will."""
    postgres = docker_update(
        dep_name="postgres",
        update_type="digest",
        current_value="18-alpine",
        new_value="18-alpine",
        current_digest="sha256:bbbb",
        new_digest="sha256:dddd",
        replace_string="postgres:18-alpine@sha256:bbbb",
    )
    given_report(monkeypatch, docker_update(), postgres)
    assert run_cli(str(repo)) == 0

    output = capsys.readouterr().out
    assert "    ghcr.io/atuinsh/atuin  v18.13.3 -> 18.22.0\n" in output
    assert "    postgres               18-alpine, new digest\n" in output


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


def test_a_step_after_a_repeat_follows_the_branch_the_repeat_stands_for(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regex minor is held as a repeat, so its major follows the github-actions minor."""
    action, regex = wrangler_updates()
    major = replace(
        regex, update_type="major", branch_name="renovate/major-tools", new_value="5.0.0"
    )
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / action.package_file).write_text(WORKFLOW, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "workflow")
    given_report(monkeypatch, action, regex, major)
    assert run_cli(str(repo), "--major") == 0

    assert subjects(repo)[2:] == [
        "deps: update wrangler to 4.148.0",
        "deps: update wrangler to 5.0.0",
    ]
    assert 'wranglerVersion: "5.0.0"' in (repo / action.package_file).read_text(encoding="utf-8")


def test_a_version_and_a_digest_of_one_image_in_one_branch_is_the_version(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Made second, the digest would find its text already rewritten and fail the group."""
    digest = docker_update(update_type="digest", new_value="v18.13.3", new_digest="sha256:dddd")
    given_report(monkeypatch, docker_update(), digest)
    assert run_cli(str(repo)) == 0

    assert subjects(repo)[1:] == ["deps: update ghcr.io/atuinsh/atuin to 18.22.0"]
    held = "renovate/stack-images updates the same text to 18.22.0"
    assert f"ghcr.io/atuinsh/atuin -> v18.13.3, new digest ({held})" in capsys.readouterr().out


def test_a_minor_and_a_major_of_one_image_are_two_commits_in_turn(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Made from the same line, the major would find its text already rewritten by the minor."""
    major = docker_update(
        update_type="major",
        branch_name="renovate/major-atuin",
        new_value="19.0.0",
        new_digest="sha256:eeee",
    )
    given_report(monkeypatch, docker_update(), major)
    assert run_cli(str(repo), "--major") == 0

    assert subjects(repo)[1:] == [
        "deps: update ghcr.io/atuinsh/atuin to 18.22.0",
        "deps: update ghcr.io/atuinsh/atuin to 19.0.0",
    ]
    compose = (repo / "stack/compose.yaml").read_text(encoding="utf-8")
    assert "ghcr.io/atuinsh/atuin:19.0.0@sha256:eeee" in compose


def test_a_dry_run_reads_a_major_on_top_of_the_minor(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Nothing is written, so the major has to find the minor's text in the run's own drafts."""
    major = docker_update(
        update_type="major",
        branch_name="renovate/major-atuin",
        new_value="19.0.0",
        new_digest="sha256:eeee",
    )
    given_report(monkeypatch, docker_update(), major)
    assert run_cli(str(repo), "--major", "--dry-run") == 0

    assert "would apply  deps: update ghcr.io/atuinsh/atuin to 19.0.0" in capsys.readouterr().out
    assert git(repo, "status", "--porcelain").stdout == ""


def test_a_major_is_held_when_the_minor_it_follows_fails(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The minor's text was never written, so the major is held, not counted as a second failure."""
    stale = docker_update(dep_name="ghost", replace_string="ghost:1.0")
    major = docker_update(
        update_type="major",
        branch_name="renovate/major-atuin",
        new_value="19.0.0",
        new_digest="sha256:eeee",
    )
    given_report(monkeypatch, docker_update(), stale, major)
    assert run_cli(str(repo), "--major") == 1

    out = capsys.readouterr().out
    assert "1 of 2 groups could not be applied" in out
    assert "(rebased onto renovate/stack-images, which was not applied)" in out
    assert git(repo, "status", "--porcelain").stdout == ""


def test_two_lines_of_one_dependency_on_two_branches_are_both_edited(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The same range in devDependencies and peerDependencies is two lines, not two steps.

    Renovate lists devDependencies first whatever the file's order, so each goes by its depType.
    """
    manifest = repo / "package.json"
    manifest.write_text(
        '{"peerDependencies": {"react": "^18.2.0"}, "devDependencies": {"react": "^18.2.0"}}\n',
        encoding="utf-8",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "add package.json")
    dev = Update(
        manager="npm",
        package_file="package.json",
        dep_name="react",
        update_type="major",
        branch_name="renovate/major-dev-dependencies",
        current_value="^18.2.0",
        new_value="^19.0.0",
        dep_type="devDependencies",
        dep_index=0,
    )
    peer = replace(
        dev,
        branch_name="renovate/react-19.x",
        new_value="^18.2.0 || ^19.0.0",
        dep_type="peerDependencies",
        dep_index=1,
    )
    given_report(monkeypatch, dev, peer)
    assert run_cli(str(repo), "--major", "--no-lock") == 0

    assert manifest.read_text(encoding="utf-8") == (
        '{"peerDependencies": {"react": "^18.2.0 || ^19.0.0"}, '
        '"devDependencies": {"react": "^19.0.0"}}\n'
    )


def test_two_majors_of_one_image_follow_each_other(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a branch per major, each major moves on from the version the previous one wrote."""
    majors = [
        docker_update(
            update_type="major",
            branch_name=f"renovate/major-{version}",
            new_value=f"{version}.0.0",
            new_digest=f"sha256:{digest}",
        )
        for version, digest in (("19", "eeee"), ("20", "ffff"))
    ]
    given_report(monkeypatch, docker_update(), *majors)
    assert run_cli(str(repo), "--major") == 0

    assert len(subjects(repo)) == 4
    compose = (repo / "stack/compose.yaml").read_text(encoding="utf-8")
    assert "ghcr.io/atuinsh/atuin:20.0.0@sha256:ffff" in compose


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


def relocks(
    root: Path,
    package_files: Sequence[str],
    _lock_updates: Sequence[Update] = (),
    **_kwargs: object,
) -> tuple[str, ...]:
    """Stand in for refresh: rewrite uv.lock the way a successful uv lock would."""
    if "pyproject.toml" not in package_files:
        return ()
    (root / "uv.lock").write_text("version = 1  # relocked\n", encoding="utf-8")
    return ("uv.lock",)


def fails_to_lock(error: LockError) -> object:
    """Stand in for refresh: fail with *error* on the manifest, pass over any other file."""

    def refresh(
        _root: Path,
        package_files: Sequence[str],
        _lock_updates: Sequence[Update] = (),
        **_kwargs: object,
    ) -> tuple[str, ...]:
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


def test_commits_a_lock_file_update_with_the_manifest_unchanged(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing in package.json moves, so the commit holds package-lock.json alone."""
    (repo / "package.json").write_text("{}\n", encoding="utf-8")
    (repo / "package-lock.json").write_text("{}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "add an npm project")
    moved: list[Update] = []

    def refresh(
        root: Path,
        _package_files: Sequence[str],
        lock_updates: Sequence[Update] = (),
        **_kwargs: object,
    ) -> tuple[str, ...]:
        moved.extend(lock_updates)
        (root / "package-lock.json").write_text('{"osls": "4.5.0"}\n', encoding="utf-8")
        return ("package-lock.json",)

    monkeypatch.setattr(main_module, "refresh", refresh)
    given_report(monkeypatch, npm_lock_update())
    assert run_cli(str(repo)) == 0

    assert moved == [npm_lock_update()]
    assert subjects(repo)[2:] == ["deps: update osls to 4.5.0"]
    files = git(repo, "show", "--name-only", "--pretty=", "HEAD").stdout.split()
    assert files == ["package-lock.json"]


def test_a_group_an_earlier_group_already_made_is_not_a_failure(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A lock file out of step with its manifest is put right by the first group to refresh it."""
    (repo / "package.json").write_text("{}\n", encoding="utf-8")
    (repo / "package-lock.json").write_text("{}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "add an npm project")

    def refresh(root: Path, *_args: object, **_kwargs: object) -> tuple[str, ...]:
        lock = root / "package-lock.json"
        if lock.read_text(encoding="utf-8") == '{"fixed": true}\n':
            return ()
        lock.write_text('{"fixed": true}\n', encoding="utf-8")
        return ("package-lock.json",)

    monkeypatch.setattr(main_module, "refresh", refresh)
    repair = npm_lock_update(
        dep_name="serverless-domain-manager",
        update_type="major",
        branch_name="renovate/serverless-domain-manager-11.x-lockfile",
        new_version="11.0.0",
    )
    given_report(monkeypatch, npm_lock_update(), repair)
    assert run_cli(str(repo), "--major") == 0

    assert subjects(repo)[2:] == ["deps: update osls to 4.5.0"]
    assert NOTHING_LEFT in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["--commit", "--no-commit", "--stage"])
def test_a_run_whose_only_group_has_nothing_to_commit_applies_nothing(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    """A lock file that already holds the version changes nothing, in any mode that writes."""
    (repo / "package.json").write_text("{}\n", encoding="utf-8")
    (repo / "package-lock.json").write_text("{}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "add an npm project")
    monkeypatch.setattr(main_module, "refresh", lambda *_args, **_kwargs: ())
    given_report(monkeypatch, npm_lock_update())
    assert run_cli(str(repo), mode) == 0

    out = capsys.readouterr().out
    assert (
        f"unchanged  deps: update osls to 4.5.0\n    osls  4.3.1 -> 4.5.0\n    {NOTHING_LEFT}"
        in out
    )
    assert "Nothing to apply." in out
    assert "applied" not in out


def test_an_ignored_lock_file_is_neither_relocked_nor_committed(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A library that ignores package-lock.json commits package.json alone, as Renovate would."""
    (repo / ".gitignore").write_text("package-lock.json\n", encoding="utf-8")
    (repo / "package.json").write_text('{"dependencies": {"a": "^1.0.0"}}\n', encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "add an npm library")
    (repo / "package-lock.json").write_text("{}\n", encoding="utf-8")
    update = Update(
        manager="npm",
        package_file="package.json",
        dep_name="a",
        update_type="minor",
        branch_name="renovate/a",
        current_value="^1.0.0",
        new_value="^1.1.0",
    )
    given_report(monkeypatch, update)
    assert run_cli(str(repo)) == 0

    files = git(repo, "show", "--name-only", "--pretty=", "HEAD").stdout.split()
    assert files == ["package.json"]
    assert (repo / "package-lock.json").read_text(encoding="utf-8") == "{}\n"


def test_a_lock_file_update_of_an_ignored_lock_file_is_held(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With nothing to commit it in, the update is held back rather than failing the run."""
    (repo / ".gitignore").write_text("package-lock.json\n", encoding="utf-8")
    (repo / "package.json").write_text('{"dependencies": {"osls": "^4.0.0"}}\n', encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "add an npm library")
    (repo / "package-lock.json").write_text("{}\n", encoding="utf-8")
    given_report(monkeypatch, npm_lock_update())
    assert run_cli(str(repo)) == 0
    assert "git does not track the lock file" in capsys.readouterr().out


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


def test_a_commit_failure_stops_the_run_before_the_next_group(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A commit failure leaves the index dirty, so subsequent groups must not commit over it."""
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    given_report(
        monkeypatch,
        docker_update(branch_name="renovate/first"),
        hook_update(branch_name="renovate/second"),
    )
    assert run_cli(str(repo)) == 1

    captured = capsys.readouterr()
    assert "commit failed" in captured.err
    assert "Groups not tried: 1" in captured.err
    assert "2 of 2 groups could not be applied" in captured.out
    assert "Committed" not in captured.out
    hooks = (repo / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "typos\n    rev: v0.16.5" in hooks
