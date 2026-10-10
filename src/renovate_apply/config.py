"""
Read the ``[tool.renovate-apply]`` defaults of the repository being updated.

cyclopts resolves a ``Toml`` source against the working directory of the process, which is the wrong
file as soon as a run is pointed somewhere else: ``rnv ~/infra`` would take the prefix and the skip
list of whatever project the shell happened to be sitting in, and write them into another
repository's commits without saying so.

The settings belong to the repository being updated, so the path is taken from the ``directory``
argument instead. Configuration sources run after the arguments are parsed, so it is already known.
"""

from pathlib import Path

# Not ``from cyclopts import config``: the stub re-exports its own submodules, and pycroscope's
# typeshed reader recurses forever on that self-reference.
from cyclopts.config import Toml
lazy from cyclopts import App
lazy from cyclopts.argument import ArgumentCollection


MANIFEST = "pyproject.toml"
SECTION = ("tool", "renovate-apply")


class TargetToml(Toml):
    """The ``pyproject.toml`` of the directory being updated, rather than of the current one."""

    def __call__(
        self,
        app: App,
        commands: tuple[str, ...],
        arguments: ArgumentCollection,
    ) -> None:
        """Point the source at the target's manifest, then read it the way cyclopts would."""
        # Assigned every call, never only when a directory was given: one App serves every run in a
        # process, and a path kept from the last one would answer for the next.
        self.path = _target(arguments) / MANIFEST
        super().__call__(app, commands, arguments)


def repository_defaults() -> TargetToml:
    """Return the configuration source cyclopts reads a run's defaults from."""
    return TargetToml(MANIFEST, root_keys=SECTION, use_commands_as_keys=False)


def _target(arguments: ArgumentCollection) -> Path:
    """Return the directory the run was pointed at, or where it was started when it was not."""
    tokens = arguments.match("--directory")[0].tokens
    return Path(tokens[-1].value) if tokens else Path()
