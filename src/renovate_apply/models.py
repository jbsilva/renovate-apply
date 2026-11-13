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

    package_name: str | None = None
    """Renovate's ``packageName``: the package to look up, which an npm alias names apart."""

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

    is_security: bool = False
    """Renovate's ``isVulnerabilityAlert``: this one bypasses every hold it has."""

    pending: bool = False
    """Renovate's ``pendingChecks``: it found this one but would not open a pull request yet."""

    is_lockfile_update: bool = False
    """
    Renovate's ``isLockfileUpdate``: the range in the manifest already allows the new version.

    Nothing in the package file changes, so there is no edit to make. Only the lock file beside it
    moves, and that takes the package manager, not a string replacement.
    """

    new_version: str | None = None
    """
    Renovate's ``newVersion``: the exact version to lock.

    Differs from ``new_value`` when the manifest holds a range.
    """

    locked_version: str | None = None
    """Renovate's ``lockedVersion``: the version the lock file holds now."""

    lock_files: tuple[str, ...] = ()
    """The lock files Renovate found for the package file, relative to the repository root."""

    @property
    def current(self) -> str:
        """Return what the file says now, for display; the locked version for a lock update."""
        if self.is_lockfile_update and self.locked_version:
            return self.locked_version
        return self.current_value or self.current_digest or "?"

    @property
    def new(self) -> str:
        """Return what the file will say, for display; the version to lock for a lock update."""
        if self.is_lockfile_update and self.new_version:
            return self.new_version
        return self.new_value or self.new_digest or "?"

    @property
    def target(self) -> str:
        """Return where the update goes, for display: the new version, or a new digest of it."""
        return f"{self.new}, new digest" if self.digest_only else self.new

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
