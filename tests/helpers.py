"""
Builders the test modules share: sample package files, updates, and a report holding them.

Importable as ``helpers`` because ``[tool.pytest.ini_options].pythonpath`` puts ``tests`` on the
path. Fixtures stay in conftest.py; anything a test calls directly lives here, because under
``--import-mode=importlib`` conftest itself is not importable by name.
"""

import subprocess
from pathlib import Path
from typing import Any

from renovate_apply.main import main
from renovate_apply.models import Update


COMPOSE = """\
services:
  atuin:
    image: ghcr.io/atuinsh/atuin:v18.13.3@sha256:aaaa
  db:
    image: postgres:18-alpine@sha256:bbbb
"""

HOOKS = """\
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.5
    hooks:
      - id: ruff-check
  - repo: https://github.com/crate-ci/typos
    rev: v0.16.5
    hooks:
      - id: typos
"""


def run_cli(*args: str) -> int:
    """
    Run the command the way the console script does, and return the exit code.

    cyclopts ends every run with ``sys.exit``, success included, so a test that called ``main``
    directly would have to catch SystemExit around each one.
    """
    try:
        main(list(args))
    except SystemExit as stopped:
        return int(stopped.code or 0)
    return 0  # pragma: no cover - cyclopts always exits, this is here for the type checker


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in a test repository and fail the test when it does not work."""
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed


def docker_update(**overrides: object) -> Update:
    """Return an image update shaped the way the docker-compose manager reports one."""
    fields: dict[str, Any] = {
        "manager": "docker-compose",
        "package_file": "stack/compose.yaml",
        "dep_name": "ghcr.io/atuinsh/atuin",
        "update_type": "minor",
        "branch_name": "renovate/stack-images",
        "current_value": "v18.13.3",
        "new_value": "18.22.0",
        "current_digest": "sha256:aaaa",
        "new_digest": "sha256:cccc",
        "replace_string": "ghcr.io/atuinsh/atuin:v18.13.3@sha256:aaaa",
        "replace_template": (
            "{{depName}}{{#if newValue}}:{{newValue}}{{/if}}{{#if newDigest}}@{{newDigest}}{{/if}}"
        ),
    }
    fields.update(overrides)
    return Update(**fields)


def hook_update(**overrides: object) -> Update:
    """Return a hook rev update, which the pre-commit manager reports without a replace string."""
    fields: dict[str, Any] = {
        "manager": "pre-commit",
        "package_file": ".pre-commit-config.yaml",
        "dep_name": "crate-ci/typos",
        "update_type": "patch",
        "branch_name": "renovate/pre-commit-hooks",
        "current_value": "v0.16.5",
        "new_value": "v0.16.9",
    }
    fields.update(overrides)
    return Update(**fields)


def report_for(*updates: Update) -> dict[str, Any]:
    """Build a Renovate report holding *updates*, nested the way the real one is."""
    package_files: dict[str, list[dict[str, object]]] = {}
    for update in updates:
        entry: dict[str, object] = {
            "depName": update.dep_name,
            "currentValue": update.current_value,
            "currentDigest": update.current_digest,
            "replaceString": update.replace_string,
            "autoReplaceStringTemplate": update.replace_template,
            "updates": [
                {
                    "updateType": update.update_type,
                    "branchName": update.branch_name,
                    "newValue": update.new_value,
                    "newDigest": update.new_digest,
                    "newName": update.new_name,
                    "isVulnerabilityAlert": update.is_security,
                    "pendingChecks": update.pending,
                },
            ],
        }
        _add(package_files.setdefault(update.manager, []), update.package_file, entry)
    return {
        "problems": [],
        "repositories": {
            "local": {"problems": [], "branches": [], "packageFiles": package_files},
        },
    }


def _add(files: list[dict[str, object]], package_file: str, entry: dict[str, object]) -> None:
    """Put a dependency under its package file, adding the file the first time it is seen."""
    for existing in files:
        if existing["packageFile"] == package_file:
            deps = existing["deps"]
            assert isinstance(deps, list)
            deps.append(entry)
            return
    files.append({"packageFile": package_file, "deps": [entry]})
