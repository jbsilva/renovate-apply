"""
Builders the test modules share: sample updates.

Importable as ``helpers`` because ``[tool.pytest.ini_options].pythonpath`` puts ``tests`` on the
path. Fixtures stay in conftest.py; anything a test calls directly lives here, because under
``--import-mode=importlib`` conftest itself is not importable by name.
"""

from typing import Any

from renovate_apply.models import Update


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
