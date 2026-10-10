"""
``renovate-apply``: make the updates Renovate finds, in the working copy, without a pull request.

The version is read from the installed distribution metadata so there is a single source of truth
(``[project].version`` in ``pyproject.toml``). No module hardcodes the version string.
"""

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("renovate-apply")
except PackageNotFoundError:  # pragma: no cover - only when run from a non-installed tree
    # Source checkout that was never installed (some bare CI shells). The real
    # version is unknowable here, so flag it rather than guess.
    __version__ = "0.0.0+unknown"


__all__ = ["__version__"]
