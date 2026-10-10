"""
Domain exceptions raised by library modules.

These replace ``SystemExit`` in non-CLI code so that callers (tests, future library consumers) can
handle failures without catching ``SystemExit``. The CLI boundary in ``main.py`` turns them into
exit codes.
"""


class RenovateApplyError(Exception):
    """Base for all renovate-apply domain errors."""


class ScanError(RenovateApplyError):
    """Renovate could not be run, or it finished without writing a report."""


class ReportError(RenovateApplyError):
    """The report Renovate wrote is not the shape this tool can read."""


class ReplaceError(RenovateApplyError):
    """
    An update cannot be turned into an edit.

    Raised when the string Renovate reported is no longer in the file, when the replacement would
    change nothing, or when the update uses a template feature this tool does not implement. Every
    one of these means the file must not be touched.
    """


class GitError(RenovateApplyError):
    """A git command failed, most often a commit a hook refused."""


class WorkingCopyError(RenovateApplyError):
    """The directory is not a git repository, or it has changes that a commit would swallow."""
