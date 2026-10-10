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
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console

from renovate_apply import __version__
from renovate_apply.errors import RenovateApplyError
from renovate_apply.files import apply_group
from renovate_apply.git import commit, require_clean, require_repository
from renovate_apply.messages import message, moves
from renovate_apply.report import group, read_updates
from renovate_apply.scan import scan
lazy from renovate_apply.models import Group


app = App(
    name="renovate-apply",
    version=__version__,
    help=__doc__,
)

# markup off because an image tag or a version can hold square brackets, and rich would read those
# as style tags. soft_wrap off-loads wrapping to the terminal, so a long path or a long error stays
# one line and can be copied out of the scrollback whole.
out = Console(markup=False, highlight=False, soft_wrap=True)
err = Console(markup=False, highlight=False, soft_wrap=True, stderr=True)


@app.default
def apply_updates(
    directory: Path = Path(),
    *,
    dry_run: bool = False,
    # Named --commit so cyclopts derives the negative as --no-commit, which is what is typed.
    commit_each: Annotated[bool, Parameter(name="--commit")] = True,
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
    """
    root = directory.resolve()
    committing = commit_each and not dry_run
    try:
        groups = _plan(root, committing=committing)
    except RenovateApplyError as error:
        err.print(f"renovate-apply: {error}", style="red")
        raise SystemExit(1) from error
    failed = _perform(root, groups, dry_run=dry_run, committing=committing)
    _report_outcome(groups, failed, dry_run=dry_run, committing=committing)
    if failed:
        raise SystemExit(1)


def _plan(root: Path, *, committing: bool) -> list[Group]:
    """Check the working copy, run the scan, and return what to do with what came back."""
    require_repository(root)
    if committing:
        require_clean(root)

    err.print(f"renovate-apply: scanning {root} ...", style="dim")
    report = scan(root)
    return group(read_updates(report))


def _perform(root: Path, groups: list[Group], *, dry_run: bool, committing: bool) -> list[Group]:
    """
    Apply each group in turn, committing as it goes unless told not to.

    A group that cannot be applied is reported and passed over, and the groups after it are still
    applied. Each group is its own commit and its own set of files, so one of them failing says
    nothing about the rest, and losing the whole run to one stale dependency helps nobody. The
    groups that failed come back, for the caller to exit on.
    """
    failed: list[Group] = []
    for one in groups:
        try:
            _perform_group(root, one, dry_run=dry_run, committing=committing)
        except RenovateApplyError as error:
            err.print(f"renovate-apply: {error}", style="red")
            failed.append(one)
    return failed


def _perform_group(root: Path, one: Group, *, dry_run: bool, committing: bool) -> None:
    """Apply one group, and commit it when the run commits."""
    paragraphs = message(one)
    package_files = apply_group(root, one, write=not dry_run)
    out.print("would apply  " if dry_run else "applied  ", style="dim", end="")
    out.print(paragraphs[0], style="bold")
    for name, moved in moves(one):
        out.print(f"    {name}  {moved}")
    if committing:
        commit(root, package_files, paragraphs)


def _report_outcome(
    groups: list[Group],
    failed: list[Group],
    *,
    dry_run: bool,
    committing: bool,
) -> None:
    """Say what state the working copy is in now."""
    if failed:
        out.print(f"\n{len(failed)} of {len(groups)} groups could not be applied.", style="red")
    if not groups:
        out.print("Nothing to apply.")
        return
    if len(failed) == len(groups):
        return
    if dry_run:
        out.print("\nNothing was written.", style="dim")
    elif committing:
        out.print("\nCommitted. Nothing is pushed.", style="dim")
    else:
        out.print("\nWritten, not committed. `git diff` to read it.", style="dim")


def main(argv: list[str] | None = None) -> None:
    """Console entry point: run the CLI over the given arguments, or over the real ones."""
    app(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":  # pragma: no cover - module entry point, not exercised by tests
    main()
