"""
Turn Renovate's report into a flat list of updates, and say what is not going to be applied.

The report nests manager, package file, dependency and update. Everything here flattens that and
narrows the JSON into the typed objects in ``models``, so a shape Renovate changes later fails
loudly in this one module instead of halfway through an edit.
"""

from collections.abc import Iterator, Mapping, Sequence

from renovate_apply.errors import ReportError
from renovate_apply.models import Group, Held, Update


# The local platform always names the one repository it reads "local".
LOCAL_REPOSITORY = "local"

HELD_MAJOR = "major, use --major to include it"


def read_updates(report: Mapping[str, object]) -> list[Update]:
    """Return every update in the report, in the order Renovate found them."""
    return list(_iter_updates(report))


def split(
    updates: Sequence[Update],
    *,
    with_major: bool,
) -> tuple[list[Update], list[Held]]:
    """
    Split the updates into the ones to apply and the ones to hold back, with a reason each.

    A major is held unless asked for. Renovate can be configured to send some majors to the
    dependency dashboard for approval by hand, and the report does not say which ones carry that
    flag, so holding every major is the only reading that cannot contradict the configuration.
    """
    to_apply: list[Update] = []
    held: list[Held] = []
    for update in updates:
        reason = _hold_reason(update, with_major=with_major)
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


def _hold_reason(update: Update, *, with_major: bool) -> str | None:
    """Return why this update is not applied, or None when it is."""
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
