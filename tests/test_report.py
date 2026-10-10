"""Reading Renovate's report: what it holds, what is held back, and how it groups."""

import pytest
from helpers import docker_update, hook_update, report_for

from renovate_apply.errors import ReportError
from renovate_apply.report import (
    HELD_LOCKFILE,
    HELD_MAJOR,
    HELD_PENDING,
    HELD_RENAME,
    group,
    read_updates,
    split,
)


def test_read_updates_flattens_manager_file_dependency_and_update() -> None:
    """One Update comes out per update, carrying where it was found."""
    updates = read_updates(report_for(docker_update(), hook_update()))
    assert [update.dep_name for update in updates] == ["ghcr.io/atuinsh/atuin", "crate-ci/typos"]
    assert updates[0].manager == "docker-compose"
    assert updates[0].package_file == "stack/compose.yaml"
    assert updates[1].branch_name == "renovate/pre-commit-hooks"


def test_read_updates_keeps_two_dependencies_of_one_file_together() -> None:
    """A compose file with two images reports both under the same package file."""
    second = docker_update(dep_name="postgres", replace_string="postgres:18-alpine@sha256:bbbb")
    updates = read_updates(report_for(docker_update(), second))
    assert [update.package_file for update in updates] == ["stack/compose.yaml"] * 2


def test_read_updates_ignores_a_dependency_with_no_name() -> None:
    """A nameless dependency cannot be placed in a file, so it is skipped rather than guessed at."""
    report = report_for(docker_update())
    repository = report["repositories"]["local"]
    repository["packageFiles"]["docker-compose"][0]["deps"][0].pop("depName")
    assert read_updates(report) == []


def test_split_holds_a_major_until_it_is_asked_for() -> None:
    """A major waits, because the report does not say whether it needs approval by hand."""
    major = docker_update(update_type="major", new_value="19.0.0")
    to_apply, held = split([major], with_major=False)
    assert to_apply == []
    assert held[0].reason == HELD_MAJOR

    wanted, none_held = split([major], with_major=True)
    assert wanted == [major]
    assert none_held == []


def test_split_holds_an_update_renovate_would_not_open_yet() -> None:
    """PendingChecks means Renovate is waiting out minimumReleaseAge; so does this."""
    _, held = split([docker_update(pending=True)], with_major=False)
    assert held[0].reason == HELD_PENDING


def test_split_applies_a_security_fix_even_while_it_is_pending() -> None:
    """A vulnerability alert bypasses Renovate's own hold, so it bypasses this one."""
    update = docker_update(pending=True, is_security=True)
    to_apply, held = split([update], with_major=False)
    assert to_apply == [update]
    assert held == []


def test_split_holds_a_rename() -> None:
    """Renaming a dependency is a different edit, and this tool does not write it."""
    _, held = split([docker_update(new_name="ghcr.io/other/atuin")], with_major=False)
    assert held[0].reason == HELD_RENAME


def test_split_holds_a_lock_file_update() -> None:
    """
    An npm range that already allows the new version moves the lock file, not the manifest.

    Renovate still reports it, with the same value on both sides. There is no edit to make, so it is
    held rather than sent to the replacement engine, which would refuse it as a write for nothing
    and take every other group in the run down with it.
    """
    update = docker_update(
        manager="npm",
        package_file="docker/package.json",
        dep_name="@scope/cli",
        current_value="^2.49.0",
        new_value="^2.49.0",
        current_digest=None,
        new_digest="sha512-abcd",
        replace_string=None,
        replace_template=None,
        is_lockfile_update=True,
    )
    to_apply, held = split([update], with_major=False)
    assert to_apply == []
    assert held[0].reason == HELD_LOCKFILE


def test_read_updates_carries_the_lock_file_flag() -> None:
    """The flag comes off the update, not the dependency, so it is read where Renovate writes it."""
    update = docker_update(is_lockfile_update=True)
    assert read_updates(report_for(update))[0].is_lockfile_update is True


def test_group_gathers_by_branch_in_the_order_renovate_reported() -> None:
    """One commit per Renovate branch, and the report's order is the order of the commits."""
    first = docker_update()
    second = docker_update(dep_name="postgres", replace_string="postgres:18-alpine@sha256:bbbb")
    groups = group([first, hook_update(), second])
    assert [one.branch for one in groups] == ["renovate/stack-images", "renovate/pre-commit-hooks"]
    assert groups[0].updates == (first, second)
    assert groups[0].package_files == ("stack/compose.yaml",)


def test_read_updates_rejects_a_report_with_no_repositories() -> None:
    """A report of another shape is a fault to report, not something to walk into."""
    with pytest.raises(ReportError, match="no repositories"):
        read_updates({})


def test_read_updates_rejects_a_report_about_another_repository() -> None:
    """The local platform always calls it 'local'; anything else means this was not a local run."""
    with pytest.raises(ReportError, match="rather than the expected"):
        read_updates({"repositories": {"github/thing": {}}})


def test_read_updates_rejects_a_report_with_no_package_files() -> None:
    """Without packageFiles there is nothing to apply and no way to know why."""
    with pytest.raises(ReportError, match="no packageFiles"):
        read_updates({"repositories": {"local": {}}})


def test_read_updates_rejects_a_field_of_the_wrong_type() -> None:
    """A list that is not a list stops the run instead of being iterated character by character."""
    report = {"repositories": {"local": {"packageFiles": {"docker-compose": "nope"}}}}
    with pytest.raises(ReportError, match="not a list"):
        read_updates(report)
