"""
Domain exceptions raised by library modules.

These replace ``SystemExit`` in non-CLI code so that callers (tests, future library consumers) can
handle failures without catching ``SystemExit``. The CLI boundary in ``main.py`` turns them into
exit codes.
"""


class RenovateApplyError(Exception):
    """Base for all renovate-apply domain errors."""
