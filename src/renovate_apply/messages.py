"""
Write the commit message for a group of updates.

The subject says what a person needs to see in ``git log --oneline``: one image and its new version,
or the directory whose images moved. The body lists every dependency in the group, aligned, so the
detail is one ``git show`` away without being in the subject line.

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


def moves(group: Group) -> list[tuple[str, str]]:
    """
    Return this group's "what moved" pairs, each once, in the order Renovate reported them.

    A dependency is reported once per use, so an action two jobs run and a base image two stages
    share are several updates all saying the same thing. Each is its own edit, but naming it more
    than once in a commit body tells the reader nothing, so the repeats are collapsed here.
    """
    return list(dict.fromkeys((update.dep_name, update.describe()) for update in group.updates))


def body(group: Group) -> str:
    """Return the aligned "what moved" list, one dependency per line."""
    lines = moves(group)
    width = max(len(name) for name, _ in lines)
    return "\n".join(f"{name.ljust(width)}  {moved}" for name, moved in lines)


def message(group: Group, prefix: str = DEFAULT_PREFIX) -> list[str]:
    """
    Return the commit message as the paragraphs git should be given.

    A group that moves one thing says everything in its subject already, so it gets no body.
    """
    paragraphs = [subject(group, prefix)]
    if len(moves(group)) > 1:
        paragraphs.append(body(group))
    return paragraphs


def _summary(group: Group) -> str:
    """Return the subject without its prefix."""
    if len(moves(group)) == 1:
        only = group.updates[0]
        if only.digest_only:
            return f"update the {only.dep_name} digest"
        return f"update {only.dep_name} to {only.new}"

    directories = group.directories
    if group.managers <= DOCKER_MANAGERS and len(directories) == 1:
        directory = next(iter(directories))
        return f"update the {directory} images" if directory else "update the images"
    if group.managers == PRE_COMMIT_MANAGERS:
        return "update the hook revs"
    if group.managers == ACTION_MANAGERS:
        return "update the action pins"
    return f"update {group.branch.removeprefix(BRANCH_PREFIX)}"
