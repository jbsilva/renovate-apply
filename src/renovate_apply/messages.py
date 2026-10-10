"""
Write the commit message for a group of updates.

The subject says what a person needs to see in ``git log --oneline``: one image and its new version,
or the directory whose images moved.

The prefix is a setting because Renovate's own is: ``commitMessagePrefix: "deps:"`` and
``semanticCommits`` produce different first words, and a repository has one of them, not both.
"""

lazy from renovate_apply.models import Group


DEFAULT_PREFIX = "deps:"

DOCKER_MANAGERS = frozenset({"docker-compose", "dockerfile", "docker"})
PRE_COMMIT_MANAGERS = frozenset({"pre-commit"})
ACTION_MANAGERS = frozenset({"github-actions"})
BRANCH_PREFIX = "renovate/"


def subject(group: Group, prefix: str = DEFAULT_PREFIX) -> str:
    """Return the summary line for this group's commit."""
    return f"{prefix} {_summary(group)}".strip()


def _summary(group: Group) -> str:
    """Return the subject without its prefix."""
    if len(group.updates) == 1:
        only = group.updates[0]
        if only.digest_only:
            return f"update the {only.dep_name} digest"
        return f"update {only.dep_name} to {only.new}"

    directories = group.directories
    if group.managers <= DOCKER_MANAGERS and len(directories) == 1:
        directory = next(iter(directories))
        if directory:
            return f"update the {directory} images"
    if group.managers == PRE_COMMIT_MANAGERS:
        return "update the hook revs"
    if group.managers == ACTION_MANAGERS:
        return "update the action pins"
    return f"update {group.branch.removeprefix(BRANCH_PREFIX)}"
