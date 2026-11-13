"""
Turn Renovate's report into a flat list of updates, and say what is not going to be applied.

The report nests manager, package file, dependency and update. Everything here flattens that and
narrows the JSON into the typed objects in ``models``, so a shape Renovate changes later fails
loudly in this one module instead of halfway through an edit.
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase

from renovate_apply.errors import ReplaceError, ReportError
from renovate_apply.lockfiles import can_move_in_lock, lock_file_of
from renovate_apply.models import Group, Held, Update
from renovate_apply.replace import search_and_replacement


# The local platform always names the one repository it reads "local".
LOCAL_REPOSITORY = "local"

HELD_PENDING = "waiting out minimumReleaseAge"
HELD_MAJOR = "major, use --major to include it"
HELD_RENAME = "a rename, which this tool does not write"
HELD_SKIPPED = "skipped by configuration"
HELD_LOCKFILE = "a lock file update this tool cannot make, the manifest does not change"
HELD_NO_LOCK = "a lock file update, which --no-lock leaves to you"
HELD_UNTRACKED_LOCK = "a lock file update, and git does not track the lock file"
# Not decided from the report: main sets it when the lock file finds no solution for the edit.
HELD_NO_SOLUTION = "the lock file finds no solution for it, see above"


def held_repeat(first: Update) -> str:
    """Return why a repeat of *first* is held: the edit is already the other update's."""
    return f"the same edit as the {first.manager} update, in {first.branch_name}"


def held_collision(first: Update) -> str:
    """Return why a collision with *first* is held: Renovate's branch carries *first* instead."""
    return f"{first.branch_name} updates the same text to {first.target}"


def held_rebased(branch: str) -> str:
    """Return why an update rebased onto *branch* is held: the text it looks for was not written."""
    return f"rebased onto {branch}, which was not applied"


def problems(report: Mapping[str, object]) -> list[str]:
    """Return what Renovate complained about, both globally and for the repository."""
    found: list[str] = []
    for holder in (report, _repository(report)):
        for problem in _sequence(holder.get("problems"), "problems"):
            if isinstance(problem, Mapping):
                message = _text(problem.get("msg"))
                if message:
                    found.append(message)
    return found


def read_updates(report: Mapping[str, object]) -> list[Update]:
    """Return every update in the report, in the order Renovate found them."""
    return list(_iter_updates(report))


def split(
    updates: Sequence[Update],
    *,
    with_major: bool,
    skip: Sequence[str] = (),
    lock: bool = True,
    tracked: Callable[[str], bool] = lambda _path: True,
) -> tuple[list[Update], list[Held]]:
    """
    Split the updates into the ones to apply and the ones to hold back, with a reason each.

    A major is held unless asked for. Renovate can be configured to send some majors to the
    dependency dashboard for approval by hand, and the report does not say which ones carry that
    flag, so holding every major is the only reading that cannot contradict the configuration.

    *skip* holds a dependency by name, as a glob. That is the answer to the same blind spot on a
    non-major: a repository that keeps one dependency on the dashboard names it here.

    A lock file update is applied only when *lock* allows the package manager to run, that
    package manager can move one dependency in its lock file, and git *tracks* that lock file.
    """
    to_apply: list[Update] = []
    held: list[Held] = []
    for update in updates:
        reason = _hold_reason(update, with_major=with_major, skip=skip, lock=lock, tracked=tracked)
        if reason is None:
            to_apply.append(update)
        else:
            held.append(Held(update, reason))
    return to_apply, held


def split_collisions(
    updates: Sequence[Update],
) -> tuple[list[Update], list[tuple[Update, Update]]]:
    """
    Split off each update that a branch cannot carry, because an earlier one rewrites its text.

    One dependency can have two updates in one branch, a new version and a new digest of the old
    one. Made one after the other, the second finds its text gone. Renovate keeps the first and
    drops the rest ("Ignoring upgrade collision"), before any hold, and so does this.

    Returns the updates to keep, and each collision paired with the update it collides with.
    """
    kept: list[Update] = []
    collisions: list[tuple[Update, Update]] = []
    seen: dict[tuple[str, str, str, str | None], Update] = {}
    for update in updates:
        key = (update.branch_name, update.package_file, update.dep_name, update.current_value)
        first = seen.setdefault(key, update)
        if first.new_value == update.new_value:
            kept.append(update)
        else:
            collisions.append((update, first))
    return kept, collisions


def chain_branches(
    updates: Sequence[Update],
    repeats: Sequence[Update | None] = (),
) -> tuple[list[Update], list[tuple[Update, Update]], list[tuple[str, str]]]:
    """
    Rebase a version update onto the update of another branch that rewrites the same use before it.

    Renovate can open a pull request for each step of one dependency: the next patch, minor, and
    major, from the same line, in ascending order. Merge one and the next rebases, to move on from
    where the first left the line. Applied in one run, the groups are those merges in turn, so each
    later step is rebased the same way: it looks for the text the step before it writes.

    Anything else across two branches has no order to follow, and the later one is held. A lock file
    update writes no text in the manifest, so it takes no part in a chain.

    A repeat of another manager's update stands in for it in the line's chain. A repeat of an update
    held here is held too, since the edit it repeats is never made.

    Returns the updates to apply, rebased where needed, each held one paired with the update that
    rewrites its text first, and each rebase as a pair of branches, the one that must go first, then
    the one rebased onto it.
    """
    kept: list[Update] = []
    held: list[tuple[Update, Update]] = []
    order: list[tuple[str, str]] = []
    chains: dict[_Use, list[_Link]] = {}
    held_by: dict[int, Update] = {}
    for update, first in zip(updates, repeats or [None] * len(updates), strict=True):
        if first is not None and id(first) in held_by:
            held.append((update, held_by[id(first)]))
            continue
        if first is not None:
            stand_in = replace(update, branch_name=first.branch_name)
            chains.setdefault(_use(update), []).append(_Link(stand_in))
            continue
        if update.is_lockfile_update:
            kept.append(update)
            continue
        chain = chains.setdefault(_use(update), [])
        same = next((link for link in chain if link.update.branch_name == update.branch_name), None)
        if same is not None:
            # A second use of the line in one branch moves on from the same update as the first.
            kept.append(update if same.onto is None else _rebase(update, same.onto))
            continue
        link = _next_link(update, chain)
        if link is None:
            held.append((update, chain[0].update))
            held_by[id(update)] = chain[0].update
            continue
        kept.append(link.update)
        chain.append(link)
        if link.onto is not None:
            order.append((link.onto.branch_name, update.branch_name))
    return kept, held, order


@dataclass(frozen=True, slots=True)
class _Link:
    """One branch's update of a use, and the update it was rebased onto, if any."""

    update: Update
    onto: Update | None = None


type _Use = tuple[str, str, str, str | None, str | None, str | None, int | None]

# The update types that move to a new version, smallest step first. A step chains only onto a step
# no larger than itself, so a report out of order holds an update instead of writing a downgrade.
_STEP_RANK = {"patch": 1, "minor": 2, "major": 3}


def _use(update: Update) -> _Use:
    """Return what identifies one line of a dependency: where it is, and the text it holds."""
    return (
        update.manager,
        update.package_file,
        update.dep_name,
        update.current_value,
        update.current_digest,
        update.replace_string,
        update.dep_index,
    )


def _next_link(update: Update, chain: Sequence[_Link]) -> _Link | None:
    """Return *update* as the next link of its use's *chain*, or None when it is held."""
    if not chain:
        return _Link(update)
    onto = chain[-1].update
    rank = _STEP_RANK.get(update.update_type, 0)
    if rank < max(_STEP_RANK.get(onto.update_type, 0), 1) or update.target == onto.target:
        return None
    try:
        return _Link(_rebase(update, onto), onto)
    except ReplaceError:
        # The update before it cannot be rendered. Its own group fails, and says why.
        return None


def _rebase(update: Update, first: Update) -> Update:
    """Return *update* as it reads once *first* has rewritten its text."""
    return replace(
        update,
        current_value=first.new_value or update.current_value,
        current_digest=first.new_digest or update.current_digest,
        replace_string=(
            None if update.replace_string is None else search_and_replacement(first)[1]
        ),
    )


def group(updates: Sequence[Update], after: Sequence[tuple[str, str]] = ()) -> list[Group]:
    """
    Gather the updates by the branch Renovate would have opened, which is one commit each.

    The groups keep the order the report gives, except that for each pair in *after* the second
    branch goes after the first, which is what a rebased update needs to find its text.
    """
    branches: dict[str, list[Update]] = {}
    for update in updates:
        branches.setdefault(update.branch_name, []).append(update)
    waits: dict[str, tuple[str, ...]] = {}
    for before, later in after:
        waits[later] = (*waits.get(later, ()), before)
    return [
        Group(branch, tuple(branches[branch]), waits.get(branch, ()))
        for branch in _ordered(list(branches), waits)
    ]


def _ordered(branches: list[str], waits: Mapping[str, Sequence[str]]) -> list[str]:
    """
    Order *branches* so each one comes after the branches it waits for, and otherwise as given.

    A cycle has no right order, so the first branch left is taken. Its rebased update then fails
    with the file not holding its text, which names the dependency.
    """
    done: dict[str, None] = {}
    while branches:
        ready = next(
            (one for one in branches if all(before in done for before in waits.get(one, ()))),
            branches[0],
        )
        branches.remove(ready)
        done[ready] = None
    return list(done)


def _hold_reason(
    update: Update,
    *,
    with_major: bool,
    skip: Sequence[str],
    lock: bool,
    tracked: Callable[[str], bool],
) -> str | None:
    """Return why this update is not applied, or None when it is."""
    if any(fnmatchcase(update.dep_name, pattern) for pattern in skip):
        return HELD_SKIPPED
    if update.new_name is not None and update.new_name != update.dep_name:
        return HELD_RENAME
    held_lock = _lock_reason(update, lock=lock, tracked=tracked)
    if held_lock is not None:
        return held_lock
    # A security fix bypasses Renovate's own holds, so it bypasses this one too.
    if update.pending and not update.is_security:
        return HELD_PENDING
    if update.update_type == "major" and not with_major:
        return HELD_MAJOR
    return None


def _lock_reason(update: Update, *, lock: bool, tracked: Callable[[str], bool]) -> str | None:
    """Return why a lock file update is not applied, or None when it is (or is not one)."""
    if not update.is_lockfile_update:
        return None
    if not can_move_in_lock(update):
        return HELD_LOCKFILE
    if not lock:
        return HELD_NO_LOCK
    lock_file = lock_file_of(update)
    return None if lock_file is None or tracked(lock_file) else HELD_UNTRACKED_LOCK


def _iter_updates(report: Mapping[str, object]) -> Iterator[Update]:
    """Walk manager, package file, dependency and update, yielding one Update per update."""
    package_files = _repository(report).get("packageFiles")
    if not isinstance(package_files, Mapping):
        msg = "the report holds no packageFiles; renovate found nothing to read"
        raise ReportError(msg)
    for manager, files in package_files.items():
        for entry in _sequence(files, f"packageFiles.{manager}"):
            if isinstance(entry, Mapping):
                yield from _iter_file_updates(str(manager), entry)


def _iter_file_updates(manager: str, entry: Mapping[str, object]) -> Iterator[Update]:
    """Yield one Update per update found in a single package file."""
    package_file = _text(entry.get("packageFile"))
    if package_file is None:
        return
    lock_files = tuple(
        found
        for found in map(_text, _sequence(entry.get("lockFiles"), f"{package_file} lockFiles"))
        if found
    )
    for dep_index, dep in enumerate(_sequence(entry.get("deps"), f"{package_file} deps")):
        if isinstance(dep, Mapping):
            yield from _iter_dep_updates(manager, package_file, dep, lock_files, dep_index)


def _iter_dep_updates(
    manager: str,
    package_file: str,
    dep: Mapping[str, object],
    lock_files: tuple[str, ...] = (),
    dep_index: int | None = None,
) -> Iterator[Update]:
    """Yield one Update per update found for a single dependency."""
    name = _text(dep.get("depName")) or _text(dep.get("packageName"))
    if name is None:
        return
    for raw in _sequence(dep.get("updates"), f"{name} updates"):
        if not isinstance(raw, Mapping):
            continue
        yield Update(
            manager=manager,
            package_file=package_file,
            dep_name=name,
            package_name=_text(dep.get("packageName")),
            update_type=_text(raw.get("updateType")) or "unknown",
            branch_name=_text(raw.get("branchName")) or "renovate/ungrouped",
            current_value=_text(dep.get("currentValue")),
            new_value=_text(raw.get("newValue")),
            current_digest=_text(dep.get("currentDigest")),
            new_digest=_text(raw.get("newDigest")),
            replace_string=_text(dep.get("replaceString")),
            replace_template=_text(dep.get("autoReplaceStringTemplate")),
            new_name=_text(raw.get("newName")),
            is_security=_flag(raw.get("isVulnerabilityAlert")),
            pending=_flag(raw.get("pendingChecks")),
            is_lockfile_update=_flag(raw.get("isLockfileUpdate")),
            new_version=_text(raw.get("newVersion")),
            locked_version=_text(dep.get("lockedVersion")),
            lock_files=lock_files,
            dep_index=dep_index,
        )


def _repository(report: Mapping[str, object]) -> Mapping[str, object]:
    """Return the one repository the local platform reports on."""
    repositories = report.get("repositories")
    if not isinstance(repositories, Mapping):
        msg = "the report has no repositories in it"
        raise ReportError(msg)
    repository = repositories.get(LOCAL_REPOSITORY)
    if not isinstance(repository, Mapping):
        named = ", ".join(str(key) for key in repositories) or "nothing"
        msg = f"the report names {named} rather than the expected '{LOCAL_REPOSITORY}' repository"
        raise ReportError(msg)
    return repository


def _sequence(value: object, what: str) -> Sequence[object]:
    """Return a list, reading a missing key as empty and a wrong type as a fault."""
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"{what} is a {type(value).__name__}, not a list"
        raise ReportError(msg)
    return value


def _text(value: object) -> str | None:
    """Return a string field, or None when it is absent or null."""
    return value if isinstance(value, str) else None


def _flag(value: object) -> bool:
    """Return a boolean field, treating anything absent or odd as false."""
    return value is True
