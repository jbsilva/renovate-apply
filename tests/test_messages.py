"""The commit messages: one subject a person can read, one body listing what moved."""

from helpers import docker_update, hook_update

from renovate_apply.messages import subject
from renovate_apply.models import Group, Update


def group_of(*updates: Update) -> Group:
    """Wrap updates into the group they would have arrived in."""
    return Group(updates[0].branch_name, updates)


def test_subject_names_the_dependency_when_the_group_holds_one() -> None:
    """A single update says what moved and where to, which is all the commit is."""
    assert subject(group_of(docker_update())) == "deps: update ghcr.io/atuinsh/atuin to 18.22.0"


def test_subject_says_digest_when_only_the_digest_moved() -> None:
    """A tag that stays put would make "to latest" read as a change; it is not one."""
    update = docker_update(update_type="digest", new_value="v18.13.3")
    assert subject(group_of(update)) == "deps: update the ghcr.io/atuinsh/atuin digest"


def test_subject_names_the_directory_when_a_stack_moved() -> None:
    """Several images in one directory are that directory's update, not a list in a subject."""
    group = group_of(docker_update(), docker_update(dep_name="postgres"))
    assert subject(group) == "deps: update the stack images"


def test_subject_names_the_hooks_and_the_actions_by_what_they_are() -> None:
    """Files at the repository root have no directory to name, so the manager names them."""
    hooks = group_of(hook_update(), hook_update(dep_name="astral-sh/ruff-pre-commit"))
    actions = group_of(
        docker_update(manager="github-actions", package_file=".github/workflows/ci.yml"),
        docker_update(
            manager="github-actions",
            package_file=".github/workflows/ci.yml",
            dep_name="astral-sh/setup-uv",
        ),
    )
    assert subject(hooks) == "deps: update the hook revs"
    assert subject(actions) == "deps: update the action pins"


def test_subject_falls_back_to_the_group_name_renovate_chose() -> None:
    """A group spanning managers is whatever the Renovate config called it."""
    group = group_of(
        hook_update(branch_name="renovate/zizmor", dep_name="zizmorcore/zizmor-pre-commit"),
        hook_update(
            branch_name="renovate/zizmor",
            manager="regex",
            package_file=".github/workflows/ci.yml",
            dep_name="zizmor",
        ),
    )
    assert subject(group) == "deps: update zizmor"


def test_subject_takes_the_prefix_the_repository_uses() -> None:
    """A project on semantic commits writes build(deps):, and Renovate's own commits would too."""
    assert subject(group_of(docker_update()), "build(deps):").startswith("build(deps): update ")
