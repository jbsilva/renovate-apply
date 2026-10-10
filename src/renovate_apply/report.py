"""
Turn Renovate's report into a flat list of updates, and say what is not going to be applied.

The report nests manager, package file, dependency and update. Everything here flattens that and
narrows the JSON into the typed objects in ``models``, so a shape Renovate changes later fails
loudly in this one module instead of halfway through an edit.
"""

from collections.abc import Iterator, Mapping, Sequence
from fnmatch import fnmatchcase

from renovate_apply.errors import ReportError
from renovate_apply.models import Group, Held, Update


# The local platform always names the one repository it reads "local".
LOCAL_REPOSITORY = "local"

HELD_PENDING = "waiting out minimumReleaseAge"
HELD_MAJOR = "major, use --major to include it"
HELD_RENAME = "a rename, which this tool does not write"
HELD_SKIPPED = "skipped by configuration"
HELD_LOCKFILE = "a lock file update, the manifest does not change"
# Not decided from the report: main sets it when uv lock finds no solution for the edit.
HELD_NO_SOLUTION = "uv lock finds no solution for it, see above"


def held_repeat(first: Update) -> str:
    """Return why a repeat of *first* is held: the edit is already the other update's."""
    return f"the same edit as the {first.manager} update, in {first.branch_name}"


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
) -> tuple[list[Update], list[Held]]:
    """
    Split the updates into the ones to apply and the ones to hold back, with a reason each.

    A major is held unless asked for. Renovate can be configured to send some majors to the
    dependency dashboard for approval by hand, and the report does not say which ones carry that
    flag, so holding every major is the only reading that cannot contradict the configuration.

    *skip* holds a dependency by name, as a glob. That is the answer to the same blind spot on a
    non-major: a repository that keeps one dependency on the dashboard names it here.
    """
    to_apply: list[Update] = []
    held: list[Held] = []
    for update in updates:
        reason = _hold_reason(update, with_major=with_major, skip=skip)
        if reason is None:
            to_apply.append(update)
        else:
            held.append(Held(update, reason))
    return to_apply, held


def group(updates: Sequence[Update]) -> list[Group]:
    """Gather the updates by the branch Renovate would have opened, which is one commit each."""
    branches: dict[str, list[Update]] = {}
    for update in updates:
        branches.setdefault(update.branch_name, []).append(update)
    return [Group(branch, tuple(members)) for branch, members in branches.items()]


def _hold_reason(update: Update, *, with_major: bool, skip: Sequence[str]) -> str | None:
    """Return why this update is not applied, or None when it is."""
    if any(fnmatchcase(update.dep_name, pattern) for pattern in skip):
        return HELD_SKIPPED
    if update.new_name is not None and update.new_name != update.dep_name:
        return HELD_RENAME
    if update.is_lockfile_update:
        return HELD_LOCKFILE
    # A security fix bypasses Renovate's own holds, so it bypasses this one too.
    if update.pending and not update.is_security:
        return HELD_PENDING
    if update.update_type == "major" and not with_major:
        return HELD_MAJOR
    return None


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
    for dep in _sequence(entry.get("deps"), f"{package_file} deps"):
        if isinstance(dep, Mapping):
            yield from _iter_dep_updates(manager, package_file, dep)


def _iter_dep_updates(
    manager: str,
    package_file: str,
    dep: Mapping[str, object],
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
