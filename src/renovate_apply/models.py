"""
The typed value objects the rest of the package passes around.

Renovate's report is nested JSON: manager, then package file, then dependency, then the updates
found for it. Everything below flattens that into one ``Update`` per thing to change, so no module
after ``report`` has to know the report's shape.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Update:
    """One dependency Renovate would move, and everything needed to move it."""

    manager: str
    """The Renovate manager that found it: docker-compose, pre-commit, github-actions, regex."""

    package_file: str
    """Path to the file holding it, relative to the repository root, with forward slashes."""

    dep_name: str
    """The image, action or hook, as Renovate names it."""

    update_type: str
    """Major, minor, patch, digest, pin, or whatever else Renovate decided this is."""

    branch_name: str
    """
    The branch Renovate would have opened.

    This is what groups updates into one commit.
    """

    current_value: str | None = None
    new_value: str | None = None
    current_digest: str | None = None
    new_digest: str | None = None

    replace_string: str | None = None
    """
    The exact text the manager found in the file.

    Absent for managers that have no such text.
    """

    replace_template: str | None = None
    """Renovate's ``autoReplaceStringTemplate``: how to write ``replace_string`` again, updated."""

    new_name: str | None = None
    """Set only when Renovate wants to replace the dependency with a different one."""
