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
from renovate_apply.config import repository_defaults
from renovate_apply.errors import RenovateApplyError
from renovate_apply.files import apply_group, split_repeats
from renovate_apply.git import commit, require_clean, require_repository
from renovate_apply.lockfiles import refresh
from renovate_apply.messages import DEFAULT_PREFIX, message, moves
from renovate_apply.models import Held
from renovate_apply.report import group, held_repeat, problems, read_updates, split
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


@app.default
def apply_updates(  # noqa: PLR0913 - every argument is one switch of a single flat command
    directory: Path = Path(),
    *,
    dry_run: bool = False,
    # Named --commit so cyclopts derives the negative as --no-commit, which is what is typed.
    commit_each: Annotated[bool, Parameter(name="--commit")] = True,
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
    major
        Include major updates, which are held back by default.
    lock
        Run ``uv lock`` after editing a ``pyproject.toml`` that has a ``uv.lock`` beside it, and
        commit the two together. ``--no-lock`` leaves the lock file to you.
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
    committing = commit_each and not dry_run
    try:
        groups, held = _plan(
            root,
            major=major,
            committing=committing,
            skip=skip or [],
            renovate_version=renovate_version,
            token=token,
        )
    except RenovateApplyError as error:
        err.print(f"renovate-apply: {error}", style="red")
        raise SystemExit(1) from error
    failed = _perform(
        root,
        groups,
        prefix=prefix,
        dry_run=dry_run,
        committing=committing,
        lock=lock,
    )
    _report_held(held)
    _report_outcome(groups, failed, dry_run=dry_run, committing=committing)
    if failed:
        raise SystemExit(1)


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


def _perform(  # noqa: PLR0913 - one argument per switch the command was given
    root: Path,
    groups: list[Group],
    *,
    prefix: str,
    dry_run: bool,
    committing: bool,
    lock: bool,
) -> list[Group]:
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
            _perform_group(
                root,
                one,
                prefix=prefix,
                dry_run=dry_run,
                committing=committing,
                lock=lock,
            )
        except RenovateApplyError as error:
            err.print(f"renovate-apply: {error}", style="red")
            failed.append(one)
    return failed


def _perform_group(  # noqa: PLR0913 - one argument per switch the command was given
    root: Path,
    one: Group,
    *,
    prefix: str,
    dry_run: bool,
    committing: bool,
    lock: bool,
) -> None:
    """Apply one group, and commit it when the run commits."""
    paragraphs = message(one, prefix)
    package_files = apply_group(root, one, write=not dry_run)
    out.print("would apply  " if dry_run else "applied  ", style="dim", end="")
    out.print(paragraphs[0], style="bold")
    for name, moved in moves(one):
        out.print(f"    {name}  {moved}")
    if dry_run:
        return
    # The lock file is refreshed before the commit, so the manifest and the lock file that matches
    # it are one commit, which is how Renovate's own pull request carries them.
    locks = refresh(root, package_files) if lock else ()
    for refreshed in locks:
        out.print(f"    {refreshed}  refreshed", style="dim")
    if committing:
        commit(root, [*package_files, *locks], paragraphs)


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
