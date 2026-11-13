"""Reading Renovate's report: what it holds, what is held back, and how it groups."""

from dataclasses import replace

import pytest
from helpers import docker_update, hook_update, npm_lock_update, report_for

from renovate_apply.errors import ReportError
from renovate_apply.models import Update
from renovate_apply.report import (
    HELD_LOCKFILE,
    HELD_MAJOR,
    HELD_NO_LOCK,
    HELD_PENDING,
    HELD_RENAME,
    HELD_SKIPPED,
    HELD_UNTRACKED_LOCK,
    chain_branches,
    group,
    held_collision,
    problems,
    read_updates,
    split,
    split_collisions,
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


def test_read_updates_names_the_other_dependencies_of_the_file() -> None:
    """A bare version is placed by the names around it, so each update carries its neighbors."""
    second = docker_update(dep_name="postgres", replace_string="postgres:18-alpine@sha256:bbbb")
    updates = read_updates(report_for(docker_update(), second, hook_update()))
    neighbors = [update.neighbors for update in updates]
    assert neighbors == [("postgres",), ("ghcr.io/atuinsh/atuin",), ()]


def test_read_updates_tells_a_package_which_aliases_name_it() -> None:
    """An alias's value holds the package's name, so the package must not take it for its own."""
    alias = docker_update(
        manager="npm",
        package_file="package.json",
        dep_name="react-17",
        package_name="react",
        replace_string=None,
    )
    real = replace(alias, dep_name="react", package_name=None)
    updates = read_updates(report_for(alias, real))
    assert [update.aliased_by for update in updates] == [(), ("react-17",)]


def test_read_updates_does_not_take_a_python_spelling_for_an_alias() -> None:
    """Renovate gives PyYAML the package name pyyaml, its normal form, not another package."""
    spelled = docker_update(
        manager="pep621",
        package_file="pyproject.toml",
        dep_name="PyYAML",
        package_name="pyyaml",
        replace_string=None,
    )
    normal = replace(spelled, dep_name="pyyaml", package_name="pyyaml")
    assert [update.aliased_by for update in read_updates(report_for(spelled, normal))] == [(), ()]


def test_read_updates_takes_a_custom_manager_template_from_its_file() -> None:
    """A regex manager sets its template on the package file, and each dependency of it uses it."""
    report = report_for(docker_update(manager="regex", replace_template=None))
    entry = report["repositories"]["local"]["packageFiles"]["regex"][0]
    entry["autoReplaceStringTemplate"] = "{{{depName}}}:{{{newValue}}}"
    assert read_updates(report)[0].replace_template == "{{{depName}}}:{{{newValue}}}"


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


def test_problems_collects_what_renovate_complained_about() -> None:
    """Renovate's own warnings are surfaced, from both places it files them."""
    report = report_for(docker_update())
    report["problems"] = [{"msg": "global trouble"}]
    report["repositories"]["local"]["problems"] = [{"msg": "repo trouble"}]
    assert problems(report) == ["global trouble", "repo trouble"]


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


def test_split_holds_a_dependency_named_in_skip() -> None:
    """A glob is how a repository keeps a dependency its dashboard is meant to approve."""
    _, held = split([docker_update()], with_major=False, skip=["ghcr.io/atuinsh/*"])
    assert held[0].reason == HELD_SKIPPED


def test_split_applies_a_dependency_no_pattern_matches() -> None:
    """A pattern that misses changes nothing about the rest of the run."""
    update = docker_update()
    to_apply, held = split([update], with_major=False, skip=["python", "postgres"])
    assert to_apply == [update]
    assert held == []


def test_split_collisions_keeps_the_first_of_two_updates_to_one_use() -> None:
    """Renovate keeps the first update of a branch and drops a later one to the same text."""
    minor = docker_update()
    digest = docker_update(update_type="digest", new_value="v18.13.3", new_digest="sha256:dddd")
    kept, collisions = split_collisions([minor, hook_update(), digest])
    assert kept == [minor, hook_update()]
    assert collisions == [(digest, minor)]


def test_held_collision_names_a_digest_as_a_digest() -> None:
    """The tag of a digest update is the one the file holds, so on its own it reads as no change."""
    digest = docker_update(update_type="digest", new_value="v18.13.3", new_digest="sha256:dddd")
    assert held_collision(digest) == (
        "renovate/stack-images updates the same text to v18.13.3, new digest"
    )


def test_split_collisions_keeps_two_uses_that_reach_the_same_value() -> None:
    """A dependency used twice is reported twice with one new value, and both uses are edited."""
    first = docker_update()
    assert split_collisions([first, first]) == ([first, first], [])


def test_split_collisions_keeps_updates_of_two_branches() -> None:
    """Each branch is its own pull request, so two of them can update the same text."""
    minor = docker_update()
    digest = docker_update(new_value="v18.13.3", branch_name="renovate/atuin-digest")
    assert split_collisions([minor, digest]) == ([minor, digest], [])


def test_read_updates_carries_what_a_lock_file_update_needs() -> None:
    """The version to lock is newVersion, since newValue is the range the manifest keeps."""
    update = read_updates(report_for(npm_lock_update(package_name="osls")))[0]
    assert (update.locked_version, update.new_version) == ("4.3.1", "4.5.0")
    assert update.package_name == "osls"
    assert update.lock_files == ("package-lock.json",)
    assert update.describe() == "4.3.1 -> 4.5.0"


@pytest.mark.parametrize("package_name", [None, "osls"])
def test_split_applies_an_npm_lock_file_update(package_name: str | None) -> None:
    """Npm can move one dependency in package-lock.json, so the update is not held."""
    update = npm_lock_update(package_name=package_name)
    assert split([update], with_major=False) == ([update], [])


def test_split_applies_a_uv_lock_file_update() -> None:
    """Uv can move one package in uv.lock, a transitive one included, so the update is not held."""
    update = npm_lock_update(
        manager="pep621",
        package_file="pyproject.toml",
        dep_name="PyJWT",
        package_name="pyjwt",
        lock_files=("uv.lock",),
    )
    assert split([update], with_major=False) == ([update], [])


def test_split_holds_a_lock_file_update_with_no_lock() -> None:
    """--no-lock means the package manager does not run, and nothing else can make the update."""
    _, held = split([npm_lock_update()], with_major=False, lock=False)
    assert held[0].reason == HELD_NO_LOCK


@pytest.mark.parametrize(
    "overrides",
    [
        {"lock_files": ("yarn.lock",)},
        {"lock_files": ("other/package-lock.json",)},
        {"new_version": None},
        {"package_name": "@serverless/osls"},
    ],
    ids=["yarn", "lock elsewhere", "no version", "alias"],
)
def test_split_holds_a_lock_file_update_npm_cannot_make(overrides: dict[str, object]) -> None:
    """Only a package-lock.json beside the manifest, with a version to lock, is moved here."""
    _, held = split([npm_lock_update(**overrides)], with_major=False)
    assert held[0].reason == HELD_LOCKFILE


def major_update(**overrides: object) -> Update:
    """Return the major of the image docker_update moves, on a branch of its own."""
    fields: dict[str, object] = {
        "update_type": "major",
        "branch_name": "renovate/major-atuin",
        "new_value": "19.0.0",
        "new_digest": "sha256:eeee",
    }
    fields.update(overrides)
    return docker_update(**fields)


def test_chain_branches_rebases_a_major_onto_the_minor_before_it() -> None:
    """The major looks for the text the minor writes, as its pull request would after a rebase."""
    minor = docker_update()
    kept, held, order = chain_branches([minor, major_update()])
    assert kept[0] == minor
    assert kept[1].replace_string == "ghcr.io/atuinsh/atuin:18.22.0@sha256:cccc"
    assert (kept[1].current_value, kept[1].current_digest) == ("18.22.0", "sha256:cccc")
    assert held == []
    assert order == [("renovate/stack-images", "renovate/major-atuin")]


def test_chain_branches_rebases_an_update_with_no_replace_string_by_its_version() -> None:
    """The pre-commit manager reports no text, so the bare version is what moves on."""
    minor = hook_update()
    major = hook_update(update_type="major", branch_name="renovate/major-typos", new_value="v1.0.0")
    kept, _, _ = chain_branches([minor, major])
    assert kept[1].current_value == "v0.16.9"
    assert kept[1].replace_string is None


def test_chain_branches_holds_a_minor_after_the_major_of_the_same_use() -> None:
    """The major already passes the minor, so the minor has nothing left to do."""
    major, minor = major_update(), docker_update()
    assert chain_branches([major, minor]) == ([major], [(minor, major)], [])


def test_chain_branches_holds_the_later_of_two_minors_on_two_branches() -> None:
    """Two non-majors of one use have no order to follow, so only the first is applied."""
    first, second = docker_update(), docker_update(branch_name="renovate/atuin")
    assert chain_branches([first, second]) == ([first], [(second, first)], [])


def test_chain_branches_keeps_two_uses_in_one_branch() -> None:
    """Two uses of one line in a branch are both edited, which apply_all already handles."""
    first = docker_update()
    assert chain_branches([first, first]) == ([first, first], [], [])


def test_chain_branches_chains_a_step_onto_the_branch_a_repeat_stands_for() -> None:
    """A repeat is held, but its line moves on its first's branch, so the next step waits for it."""
    minor = docker_update(manager="regex", branch_name="renovate/tools")
    elsewhere = docker_update(branch_name="renovate/github-actions")
    kept, held, order = chain_branches([minor, major_update(manager="regex")], [elsewhere, None])
    assert [update.replace_string for update in kept] == [
        "ghcr.io/atuinsh/atuin:18.22.0@sha256:cccc"
    ]
    assert held == []
    assert order == [("renovate/github-actions", "renovate/major-atuin")]


def test_chain_branches_holds_a_repeat_of_an_update_it_held() -> None:
    """A digest held behind the minor makes no edit, so its repeat neither stands in nor chains."""
    minor = docker_update()
    digest = docker_update(update_type="digest", new_value="v18.13.3", new_digest="sha256:dddd")
    digest = replace(digest, branch_name="renovate/atuin-digest")
    regex_minor, regex_digest = replace(minor, manager="regex"), replace(digest, manager="regex")
    updates = [minor, digest, regex_minor, regex_digest, major_update(manager="regex")]
    kept, held, order = chain_branches(updates, [None, None, minor, digest, None])
    assert held == [(digest, minor), (regex_digest, minor)]
    assert kept[1].replace_string == "ghcr.io/atuinsh/atuin:18.22.0@sha256:cccc"
    assert order == [("renovate/stack-images", "renovate/major-atuin")]


def test_chain_branches_keeps_two_lines_with_the_same_text_apart() -> None:
    """Two lines of one dependency are two dependencies in the report, each with its own steps."""
    dev = docker_update(dep_index=0, update_type="major", new_value="19.0.0")
    peer = docker_update(dep_index=1, branch_name="renovate/peer", new_value="18.22.0")
    assert chain_branches([dev, peer]) == ([dev, peer], [], [])


def test_chain_branches_rebases_each_major_onto_the_one_before_it() -> None:
    """With a branch per major, the next major moves on from the text the previous one writes."""
    major_20 = major_update(branch_name="renovate/major-20", new_value="20.0.0")
    kept, held, order = chain_branches([docker_update(), major_update(), major_20])
    assert kept[2].replace_string == "ghcr.io/atuinsh/atuin:19.0.0@sha256:eeee"
    assert held == []
    assert order == [
        ("renovate/stack-images", "renovate/major-atuin"),
        ("renovate/major-atuin", "renovate/major-20"),
    ]


def test_chain_branches_rebases_a_minor_onto_the_patch_before_it() -> None:
    """With separateMinorPatch, merging the patch rebases the minor, the same as for a major."""
    patch = docker_update(update_type="patch", branch_name="renovate/patch", new_value="v18.13.4")
    kept, held, order = chain_branches([patch, docker_update()])
    assert kept[1].replace_string == "ghcr.io/atuinsh/atuin:v18.13.4@sha256:cccc"
    assert held == []
    assert order == [("renovate/patch", "renovate/stack-images")]


def test_chain_branches_leaves_a_lock_file_update_out_of_the_chain() -> None:
    """The lock file update writes nothing in package.json, so the major has nothing to wait for."""
    lock = npm_lock_update()
    major = npm_lock_update(
        update_type="major",
        branch_name="renovate/major-osls",
        new_value="^5.0.0",
        is_lockfile_update=False,
        new_version="5.0.0",
    )
    assert chain_branches([lock, major]) == ([lock, major], [], [])


def test_chain_branches_rebases_a_second_use_of_the_line_the_same_way() -> None:
    """Both uses of the line in the major's branch look for the text the minor writes."""
    minor, major = docker_update(), major_update()
    kept, held, _ = chain_branches([minor, major, minor, major])
    assert kept[3] == kept[1]
    assert held == []


def test_chain_branches_holds_a_major_when_the_update_before_it_cannot_render() -> None:
    """The broken minor fails in its own group, and the run still plans every other group."""
    minor = docker_update(replace_template="{{#each depName}}{{/each}}")
    major = major_update(replace_template="{{#each depName}}{{/each}}")
    assert chain_branches([minor, major]) == ([minor], [(major, minor)], [])


def test_group_puts_a_branch_after_the_one_it_is_rebased_onto() -> None:
    """The major branch can come first in the report, through another dependency of its group."""
    other = hook_update(branch_name="renovate/major-atuin")
    minor = docker_update()
    groups = group([other, minor], after=[("renovate/stack-images", "renovate/major-atuin")])
    assert [(one.branch, one.after) for one in groups] == [
        ("renovate/stack-images", ()),
        ("renovate/major-atuin", ("renovate/stack-images",)),
    ]


def test_group_keeps_the_report_order_in_a_cycle() -> None:
    """Two branches that each wait for the other cannot both be first, so the report decides."""
    first, second = docker_update(), hook_update()
    pairs = [(first.branch_name, second.branch_name), (second.branch_name, first.branch_name)]
    assert [one.branch for one in group([first, second], pairs)] == [
        first.branch_name,
        second.branch_name,
    ]


def test_split_holds_a_lock_file_update_whose_lock_file_git_does_not_track() -> None:
    """Renovate reads an ignored lock file from disk, but this tool commits only tracked ones."""
    asked: list[str] = []

    def untracked(path: str) -> bool:
        asked.append(path)
        return False

    _, held = split([npm_lock_update()], with_major=False, tracked=untracked)
    assert asked == ["package-lock.json"]
    assert held[0].reason == HELD_UNTRACKED_LOCK
