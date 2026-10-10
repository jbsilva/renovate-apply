"""
The typed value objects the rest of the package passes around.

Renovate's report is nested JSON: manager, then package file, then dependency, then the updates
found for it. Everything below flattens that into one ``Update`` per thing to change, so no module
after ``report`` has to know the report's shape.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath


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

    @property
    def current(self) -> str:
        """Return what the file says now, for display."""
        return self.current_value or self.current_digest or "?"

    @property
    def new(self) -> str:
        """Return what the file will say, for display."""
        return self.new_value or self.new_digest or "?"

    @property
    def digest_only(self) -> bool:
        """Say whether the tag stays and only the digest behind it moved."""
        return self.update_type == "digest"

    @property
    def directory(self) -> str:
        """Return the directory of the package file, empty for a file at the repository root."""
        parent = PurePosixPath(self.package_file).parent
        return "" if parent == PurePosixPath(".") else str(parent)

    def describe(self) -> str:
        """Return the one-line "what moved" text used in commit bodies and in the terminal."""
        if self.digest_only:
            return f"{self.current}, new digest"
        return f"{self.current} -> {self.new}"


@dataclass(frozen=True, slots=True)
class Group:
    """The updates that share a Renovate branch, which is to say the updates of one commit."""

    branch: str
    updates: tuple[Update, ...]

    @property
    def package_files(self) -> tuple[str, ...]:
        """Return the files this group touches, each once, in the order Renovate reported them."""
        return tuple(dict.fromkeys(update.package_file for update in self.updates))

    @property
    def managers(self) -> frozenset[str]:
        """Return the set of managers that contributed to this group."""
        return frozenset(update.manager for update in self.updates)

    @property
    def directories(self) -> frozenset[str]:
        """Return the set of directories this group touches."""
        return frozenset(update.directory for update in self.updates)


@dataclass(frozen=True, slots=True)
class Held:
    """An update that was found and deliberately not applied, with the reason to report."""

    update: Update
    reason: str
