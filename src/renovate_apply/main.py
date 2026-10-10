"""
``renovate-apply``: make the updates Renovate finds, here, without a pull request.

Renovate can read a working copy. ``renovate --platform=local`` finds every pending update and
reports it. It cannot write one: the local platform turns the run into a lookup-only dry run as it
starts, so the run ends after the lookup, before the step that edits a file. No flag turns that off.

This is the other half. It runs that scan, reads the JSON report, and makes the replacement the
report describes for each update, which is the same text and the same template Renovate's own
managers use. Then it commits, one commit per group, grouped the way the repository's Renovate
configuration groups a pull request.

Nothing is pushed and nothing is deployed. Read the diff, then push.
"""

import sys
from enum import Enum
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console

from renovate_apply import __version__
from renovate_apply.config import repository_defaults
from renovate_apply.errors import LockError, NoSolutionError, RenovateApplyError
from renovate_apply.files import apply_group, restore, snapshot, split_repeats
from renovate_apply.git import commit, require_clean, require_repository, stage
from renovate_apply.lockfiles import refresh
from renovate_apply.messages import DEFAULT_PREFIX, message, moves
from renovate_apply.models import Held
from renovate_apply.report import (
    HELD_NO_SOLUTION,
    group,
    held_repeat,
    problems,
    read_updates,
    split,
)
from renovate_apply.scan import scan
lazy from renovate_apply.models import Group


app = App(
    name="renovate-apply",
    version=__version__,
    help=__doc__,
    # Per-repository defaults live under [tool.renovate-apply] in the pyproject.toml of the
    # repository being updated, so a project that writes "build(deps):" never has to say so twice.
    config=repository_defaults(),
)

# markup off because an image tag or a version can hold square brackets, and rich would read those
# as style tags. soft_wrap off-loads wrapping to the terminal, so a long path or a long error stays
# one line and can be copied out of the scrollback whole.
out = Console(markup=False, highlight=False, soft_wrap=True)
err = Console(markup=False, highlight=False, soft_wrap=True, stderr=True)


class Mode(Enum):
    """How far each group goes once its edits are computed; each value is the run's last line."""

    DRY_RUN = "Nothing was written."
    WRITE = "Written, not committed. `git diff` to read it."
    STAGE = "Staged, not committed. `git diff --cached` to read it."
    COMMIT = "Committed. Nothing is pushed."


@app.default
def apply_updates(  # noqa: PLR0913 - every argument is one switch of a single flat command
    directory: Path = Path(),
    *,
    dry_run: bool = False,
    # Named --commit so cyclopts derives the negative as --no-commit, which is what is typed.
    commit_each: Annotated[bool, Parameter(name="--commit")] = True,
    stage_each: Annotated[bool, Parameter(name="--stage")] = False,
    major: bool = False,
    lock: bool = True,
    skip: list[str] | None = None,
    prefix: str = DEFAULT_PREFIX,
    renovate_version: str | None = None,
    # An env var so there is a way in that is not argv, which every process on the machine can read.
    token: Annotated[str | None, Parameter(env_var="GITHUB_TOKEN")] = None,
) -> None:
    """
    Apply the updates Renovate finds, one commit per group.

    Parameters
    ----------
    directory
        The repository to update. Defaults to the current directory.
    dry_run
        Say what would change and write nothing.
    commit_each
        Commit each group as it is applied. ``--no-commit`` writes the files and stops, for one
        review of everything at once.
    stage_each
        Stage each group as it is applied, and commit nothing. Implies ``--no-commit``, and leaves
        the run's own edits in ``git diff --cached``, apart from anything else in the tree.
    major
        Include major updates, which are held back by default.
    lock
        Run ``uv lock`` after editing a ``pyproject.toml`` that has a ``uv.lock`` beside it, and
        commit the two together. A group uv finds no solution for is undone and held back.
        ``--no-lock`` leaves the lock file to you.
    skip
        Hold a dependency back by name, as a glob, repeatable. This is how a repository keeps a
        dependency that its Renovate configuration sends to the dependency dashboard, which the
        report gives no way to see.
    prefix
        The first word of every commit subject. Match it to the repository's Renovate
        configuration: ``deps:`` for commitMessagePrefix, ``build(deps):`` for semantic commits.
    renovate_version
        The npm version of Renovate to run. Without this, a ``renovate`` already on PATH is used,
        and otherwise npx fetches the latest.
    token
        A GitHub token. ``GITHUB_TOKEN`` in the environment says the same thing without putting the
        token in argv or in the shell history. Without either, ``gh auth token`` is asked, and a run
        with no token at all is rate limited on everything it looks up on GitHub.
    """
    root = directory.resolve()
    mode = _mode(dry_run=dry_run, commit_each=commit_each, stage_each=stage_each)
    try:
        groups, held = _plan(
            root,
            major=major,
            committing=mode is Mode.COMMIT,
            skip=skip or [],
            renovate_version=renovate_version,
            token=token,
        )
    except RenovateApplyError as error:
        err.print(f"renovate-apply: {error}", style="red")
        raise SystemExit(1) from error
    failed, unsolved = _perform(root, groups, prefix=prefix, mode=mode, lock=lock)
    held += [Held(update, HELD_NO_SOLUTION) for one in unsolved for update in one.updates]
    _report_held(held)
    _report_outcome(
        total=len(groups),
        failed=len(failed),
        applied=len(groups) - len(failed) - len(unsolved),
        mode=mode,
    )
    if failed:
        raise SystemExit(1)


def _mode(*, dry_run: bool, commit_each: bool, stage_each: bool) -> Mode:
    """Turn the three flags into one mode; the flag that does less wins."""
    if dry_run:
        return Mode.DRY_RUN
    if stage_each:
        return Mode.STAGE
    return Mode.COMMIT if commit_each else Mode.WRITE


def _plan(  # noqa: PLR0913 - one argument per switch the command was given
    root: Path,
    *,
    major: bool,
    committing: bool,
    skip: list[str],
    renovate_version: str | None,
    token: str | None,
) -> tuple[list[Group], list[Held]]:
    """Check the working copy, run the scan, and return what to do with what came back."""
    require_repository(root)
    if committing:
        require_clean(root)

    err.print(f"renovate-apply: scanning {root} ...", style="dim")
    report = scan(root, version=renovate_version, token=token)
    for problem in problems(report):
        err.print(f"renovate-apply: renovate reported: {problem}", style="yellow")

    to_apply, held = split(read_updates(report), with_major=major, skip=skip)
    to_apply, repeats = split_repeats(root, to_apply)
    held += [Held(update, held_repeat(first)) for update, first in repeats]
    return group(to_apply), held


def _perform(
    root: Path,
    groups: list[Group],
    *,
    prefix: str,
    mode: Mode,
    lock: bool,
) -> tuple[list[Group], list[Group]]:
    """
    Apply each group in turn, as far as *mode* says.

    A group that cannot be applied is reported and passed over, and the groups after it are still
    applied. Each group is its own commit and its own set of files, so one of them failing says
    nothing about the rest, and losing the whole run to one stale dependency helps nobody.

    Returns the groups that failed, for the caller to exit on, and the groups uv could not lock,
    which are held back rather than failed: the edit is sound, the dependency tree is not ready.
    """
    failed: list[Group] = []
    unsolved: list[Group] = []
    for one in groups:
        try:
            _perform_group(root, one, prefix=prefix, mode=mode, lock=lock)
        except NoSolutionError as error:
            subject = message(one, prefix)[0]
            err.print(f"renovate-apply: {subject} does not lock, undone. {error}", style="yellow")
            unsolved.append(one)
        except RenovateApplyError as error:
            err.print(f"renovate-apply: {error}", style="red")
            failed.append(one)
    return failed, unsolved


def _perform_group(root: Path, one: Group, *, prefix: str, mode: Mode, lock: bool) -> None:
    """Apply one group, then lock, stage, or commit it as *mode* says."""
    paragraphs = message(one, prefix)
    originals = snapshot(root, one.package_files)
    package_files = apply_group(root, one, write=mode is not Mode.DRY_RUN)
    # The lock file is refreshed before the commit, so the manifest and the lock file that matches
    # it are one commit, which is how Renovate's own pull request carries them.
    locks = _relock(root, package_files, originals) if lock and mode is not Mode.DRY_RUN else ()
    out.print("would apply  " if mode is Mode.DRY_RUN else "applied  ", style="dim", end="")
    out.print(paragraphs[0], style="bold")
    for name, moved in moves(one):
        out.print(f"    {name}  {moved}")
    for refreshed in locks:
        out.print(f"    {refreshed}  refreshed", style="dim")
    if mode is Mode.STAGE:
        stage(root, [*package_files, *locks])
    elif mode is Mode.COMMIT:
        commit(root, [*package_files, *locks], paragraphs)


def _relock(
    root: Path,
    package_files: tuple[str, ...],
    originals: dict[str, str],
) -> tuple[str, ...]:
    """
    Refresh the lock files beside the edited manifests, or put the manifests back.

    A manifest left edited after its lock failed is one the next ``git commit`` refuses, through the
    repository's own uv-lock hook, long after this run has ended.
    """
    try:
        return refresh(root, package_files)
    except LockError:
        restore(root, originals)
        raise


def _report_held(held: list[Held]) -> None:
    """List what was found and deliberately left alone, each thing once."""
    if not held:
        return
    lines = dict.fromkeys(
        f"  {one.update.dep_name} -> {one.update.new} ({one.reason})" for one in held
    )
    out.print("\nHeld back:", style="bold")
    for line in lines:
        out.print(line)


def _report_outcome(*, total: int, failed: int, applied: int, mode: Mode) -> None:
    """Say what state the working copy is in now."""
    if failed:
        out.print(f"\n{failed} of {total} groups could not be applied.", style="red")
    if not applied:
        if not failed:
            out.print("Nothing to apply.")
        return
    out.print(f"\n{mode.value}", style="dim")


def main(argv: list[str] | None = None) -> None:
    """Console entry point: run the CLI over the given arguments, or over the real ones."""
    app(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":  # pragma: no cover - module entry point, not exercised by tests
    main()
