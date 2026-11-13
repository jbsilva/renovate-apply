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
    """
    Build a Renovate report holding *updates*, nested the way the real one is.

    Updates of one line (same dependency, same text, same ``dep_index``) share one dependency entry,
    as Renovate lists every update of a line under it. Set ``dep_index`` to make two lines.
    """
    package_files: dict[str, list[dict[str, object]]] = {}
    deps_of: dict[tuple[str, str], list[dict[str, object]]] = {}
    updates_of: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for update in updates:
        line: dict[str, object] = {
            "depName": update.dep_name,
            "packageName": update.package_name,
            "currentValue": update.current_value,
            "currentDigest": update.current_digest,
            "replaceString": update.replace_string,
            "autoReplaceStringTemplate": update.replace_template,
            "lockedVersion": update.locked_version,
            "depType": update.dep_type,
        }
        where = (update.manager, update.package_file)
        if where not in deps_of:
            deps_of[where] = []
            package_files.setdefault(update.manager, []).append(
                {
                    "packageFile": update.package_file,
                    "lockFiles": list(update.lock_files),
                    "deps": deps_of[where],
                },
            )
        key = (*where, *line.values(), update.dep_index)
        if key not in updates_of:
            updates_of[key] = []
            deps_of[where].append({**line, "updates": updates_of[key]})
        updates_of[key].append(
            {
                "updateType": update.update_type,
                "branchName": update.branch_name,
                "newValue": update.new_value,
                "newDigest": update.new_digest,
                "newName": update.new_name,
                "isVulnerabilityAlert": update.is_security,
                "pendingChecks": update.pending,
                "isLockfileUpdate": update.is_lockfile_update,
                "newVersion": update.new_version,
            },
        )
    return {
        "problems": [],
        "repositories": {
            "local": {"problems": [], "branches": [], "packageFiles": package_files},
        },
    }


WORKFLOW = """\
jobs:
  deploy:
    steps:
      - uses: cloudflare/wrangler-action@v4
        with:
          wranglerVersion: "4.139.0"
"""


def wrangler_updates(**overrides: object) -> tuple[Update, Update]:
    """
    Return one line found twice: by the github-actions manager and by a repository's regex manager.

    Renovate reports each on its own branch, with its own way of finding the text.
    """
    action = Update(
        manager="github-actions",
        package_file=".github/workflows/deploy.yml",
        dep_name="wrangler",
        update_type="minor",
        branch_name="renovate/github-actions",
        current_value="4.139.0",
        new_value="4.148.0",
    )
    fields: dict[str, Any] = {
        "manager": "regex",
        "package_file": action.package_file,
        "dep_name": "wrangler",
        "update_type": "minor",
        "branch_name": "renovate/tools",
        "current_value": "4.139.0",
        "new_value": "4.148.0",
        "replace_string": 'wranglerVersion: "4.139.0"',
    }
    fields.update(overrides)
    return action, Update(**fields)


def npm_lock_update(**overrides: object) -> Update:
    """Return an update that moves a dependency inside its range, in package-lock.json only."""
    fields: dict[str, Any] = {
        "manager": "npm",
        "package_file": "package.json",
        "dep_name": "osls",
        "update_type": "minor",
        "branch_name": "renovate/non-major",
        "current_value": "^4.0.0",
        "new_value": "^4.0.0",
        "new_digest": "sha512-abcd",
        "is_lockfile_update": True,
        "new_version": "4.5.0",
        "locked_version": "4.3.1",
        "lock_files": ("package-lock.json",),
    }
    fields.update(overrides)
    return Update(**fields)
