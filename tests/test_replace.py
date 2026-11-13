"""The replacement engine: rendering Renovate's templates and finding what to swap."""

from dataclasses import replace

import pytest
from helpers import WORKFLOW, docker_update, hook_update, wrangler_updates

from renovate_apply.errors import ReplaceError
from renovate_apply.models import Update
from renovate_apply.replace import (
    apply_all,
    apply_to_text,
    render,
    same_edit,
    search_and_replacement,
    template_values,
)


ACTION_TEMPLATE = (
    "{{depName}}@{{#if newDigest}}{{newDigest}}{{#if newValue}} # {{newValue}}{{/if}}{{/if}}"
    "{{#unless newDigest}}{{newValue}}{{/unless}}"
)


def test_render_fills_a_plain_name() -> None:
    """A bare {{name}} is replaced by the value behind it."""
    assert render("{{depName}}:{{newValue}}", {"depName": "caddy", "newValue": "2.11.4"}) == (
        "caddy:2.11.4"
    )


def test_render_treats_a_null_field_as_empty() -> None:
    """A field the update does not carry a value for renders as nothing, as handlebars reads it."""
    assert render("a{{newValue}}b", {"newValue": None}) == "ab"


@pytest.mark.parametrize("template", ["a{{{datasource}}}b", "{{#if isPinDigest}}a{{/if}}"])
def test_render_refuses_a_field_it_does_not_know(template: str) -> None:
    """Renovate fills every field of the update, so an empty guess would write a broken line."""
    with pytest.raises(ReplaceError, match="does not know"):
        render(template, {"newValue": None})


def test_render_keeps_an_if_block_only_when_the_field_is_set() -> None:
    """The docker template drops the tag or the digest when the update does not carry one."""
    template = (
        "{{depName}}{{#if newValue}}:{{newValue}}{{/if}}{{#if newDigest}}@{{newDigest}}{{/if}}"
    )
    both = render(template, {"depName": "a", "newValue": "1", "newDigest": "sha256:x"})
    digest_only = render(template, {"depName": "a", "newValue": None, "newDigest": "sha256:x"})
    assert both == "a:1@sha256:x"
    assert digest_only == "a@sha256:x"


def test_render_handles_nested_blocks_and_unless() -> None:
    """The github-actions template nests an if inside an if, with an unless for the other case."""
    pinned = render(ACTION_TEMPLATE, {"depName": "a/b", "newDigest": "abc123", "newValue": "v2"})
    unpinned = render(ACTION_TEMPLATE, {"depName": "a/b", "newDigest": None, "newValue": "v2"})
    assert pinned == "a/b@abc123 # v2"
    assert unpinned == "a/b@v2"


def test_render_takes_the_else_branch_when_the_test_is_false() -> None:
    """
    An {{else}} is a second branch, not a field named "else".

    Read as a field it expands to nothing, which leaves both branches in the text and writes a
    reference that was never in the report: the one failure this module exists to prevent.
    """
    template = "{{depName}}{{#if newDigest}}@{{newDigest}}{{else}}:{{newValue}}{{/if}}"
    pinned = render(template, {"depName": "a/b", "newDigest": "abc123", "newValue": "v2"})
    unpinned = render(template, {"depName": "a/b", "newDigest": None, "newValue": "v2"})
    assert pinned == "a/b@abc123"
    assert unpinned == "a/b:v2"


def test_render_takes_the_else_branch_of_an_unless() -> None:
    """{{#unless}} inverts the test, so its {{else}} runs when the field is set."""
    template = "{{#unless newDigest}}{{newValue}}{{else}}{{newDigest}}{{/unless}}"
    assert render(template, {"newDigest": "abc123", "newValue": "v2"}) == "abc123"
    assert render(template, {"newDigest": None, "newValue": "v2"}) == "v2"


def test_render_handles_an_else_inside_a_nested_block() -> None:
    """The branch a nested block selects is the caller's text, else branch included."""
    template = "{{#if a}}{{#if b}}B{{else}}NOT-B{{/if}}{{else}}NOT-A{{/if}}"
    assert render(template, {"a": "1", "b": "1"}) == "B"
    assert render(template, {"a": "1", "b": None}) == "NOT-B"
    assert render(template, {"a": None, "b": "1"}) == "NOT-A"


def test_render_rejects_an_else_outside_a_block() -> None:
    """An {{else}} with no block around it is a template this tool has misread."""
    with pytest.raises(ReplaceError, match="outside a block"):
        render("x{{else}}y", {})


def test_render_rejects_two_else_branches_in_one_block() -> None:
    """Which of the three branches wins is a guess, so it is not made."""
    with pytest.raises(ReplaceError, match="two"):
        render("{{#if a}}x{{else}}y{{else}}z{{/if}}", {"a": "1"})


def test_render_rejects_an_else_if_chain() -> None:
    """{{else if}} is a third branch this tool does not render; it stops rather than drop one."""
    with pytest.raises(ReplaceError, match="unsupported template expression"):
        render("{{#if a}}x{{else if b}}y{{/if}}", {"a": None, "b": "1"})


def test_render_rejects_an_expression_it_does_not_implement() -> None:
    """A template feature this tool cannot render stops it, rather than writing a guess."""
    with pytest.raises(ReplaceError, match="unsupported template expression"):
        render("{{#each deps}}{{/each}}", {})


def test_render_rejects_an_unclosed_block() -> None:
    """A block that never closes is a template this tool has misread; say so."""
    with pytest.raises(ReplaceError, match="never closes"):
        render("{{#if newValue}}x", {"newValue": "1"})


def test_render_rejects_a_stray_closing_tag() -> None:
    """A close with no open is the same kind of fault, from the other side."""
    with pytest.raises(ReplaceError, match="never opened"):
        render("x{{/if}}", {})


def test_template_values_names_the_fields_renovate_names() -> None:
    """The names in a template are Renovate's, not this package's."""
    values = template_values(docker_update())
    assert values["depName"] == "ghcr.io/atuinsh/atuin"
    assert values["newValue"] == "18.22.0"
    assert values["currentDigest"] == "sha256:aaaa"


def test_search_and_replacement_uses_the_template_when_there_is_one() -> None:
    """An image reference is rebuilt from the template, tag and digest together."""
    search, replacement = search_and_replacement(docker_update())
    assert search == "ghcr.io/atuinsh/atuin:v18.13.3@sha256:aaaa"
    assert replacement == "ghcr.io/atuinsh/atuin:18.22.0@sha256:cccc"


def test_search_and_replacement_substitutes_when_there_is_no_template() -> None:
    """The regex manager reports the text it matched and no template, so the version is swapped."""
    update = docker_update(
        manager="regex",
        replace_string="# renovate: depName=zizmor\n    ZIZMOR_VERSION: 1.30.0",
        replace_template=None,
        current_value="1.30.0",
        new_value="1.30.1",
        current_digest=None,
        new_digest=None,
    )
    search, replacement = search_and_replacement(update)
    assert search.endswith("1.30.0")
    assert replacement.endswith("1.30.1")
    assert replacement.startswith("# renovate: depName=zizmor")


def test_search_and_replacement_falls_back_to_the_bare_version() -> None:
    """A hook rev has no replace string at all, so the version itself is what gets replaced."""
    assert search_and_replacement(hook_update()) == ("v0.16.5", "v0.16.9")


def test_search_and_replacement_prefers_the_digest_when_only_it_moves() -> None:
    """A digest-only update with no replace string looks for the digest, not the unchanged tag."""
    update = hook_update(
        current_value="latest",
        new_value="latest",
        current_digest="sha256:old",
        new_digest="sha256:new",
        update_type="digest",
    )
    assert search_and_replacement(update) == ("sha256:old", "sha256:new")


def test_search_and_replacement_refuses_an_update_that_changes_nothing() -> None:
    """Renovate sometimes reports an update whose new text equals the old; never write that."""
    update = hook_update(new_value="v0.16.5")
    with pytest.raises(ReplaceError, match="replaces"):
        search_and_replacement(update)


def test_search_and_replacement_refuses_an_update_with_nothing_to_find() -> None:
    """No replace string and no current version means the report cannot place the edit."""
    update = hook_update(current_value=None, current_digest=None)
    with pytest.raises(ReplaceError, match="does not say what text to replace"):
        search_and_replacement(update)


def test_search_and_replacement_substitutes_every_copy_of_the_version() -> None:
    """With no template, Renovate replaces the version wherever the found text holds it."""
    update = docker_update(
        manager="regex",
        dep_name="tool",
        replace_string="https://e.com/v1.2.3/tool-1.2.3.tgz",
        replace_template=None,
        current_value="1.2.3",
        new_value="1.2.4",
        current_digest=None,
        new_digest=None,
    )
    assert search_and_replacement(update)[1] == "https://e.com/v1.2.4/tool-1.2.4.tgz"


def test_search_and_replacement_writes_the_package_name_the_template_asks_for() -> None:
    """A regex manager can name a dependency apart from the image it pulls."""
    update = docker_update(
        manager="regex",
        dep_name="bar",
        package_name="ghcr.io/foo/bar",
        replace_string="image: ghcr.io/foo/bar:1.0",
        replace_template="image: {{{packageName}}}:{{{newValue}}}",
        current_value="1.0",
        new_value="1.1",
        current_digest=None,
        new_digest=None,
    )
    assert search_and_replacement(update)[1] == "image: ghcr.io/foo/bar:1.1"


def test_apply_to_text_refuses_one_update_for_two_copies() -> None:
    """Two identical references are two dependencies, so one update for them is a guess."""
    text = "a: x:1@sha256:aaaa\nb: x:1@sha256:aaaa\n"
    update = docker_update(
        dep_name="x",
        replace_string="x:1@sha256:aaaa",
        current_value="1",
        new_value="2",
        new_digest="sha256:cccc",
    )
    with pytest.raises(ReplaceError, match="not clear which ones"):
        apply_to_text(text, update)
    assert apply_all(text, [update, update]) == "a: x:2@sha256:cccc\nb: x:2@sha256:cccc\n"


@pytest.mark.parametrize(
    ("text", "search", "expected"),
    [
        pytest.param(
            "a: bitnami/redis:7.2\nb: redis:7.2\n",
            "redis:7.2",
            "a: bitnami/redis:7.2\nb: redis:7.4\n",
            id="tail-of-another-image",
        ),
        pytest.param(
            "- uses: a/b@v5.1.0\n- uses: a/b@v5\n",
            "a/b@v5",
            "- uses: a/b@v5.1.0\n- uses: a/b@v7.4\n",
            id="start-of-a-longer-version",
        ),
    ],
)
def test_apply_to_text_edits_text_that_stands_on_its_own(
    text: str, search: str, expected: str
) -> None:
    """A replaceString inside a longer name or version is not this dependency's line."""
    old = search.rsplit(":", 1)[-1].rsplit("@", 1)[-1]
    update = docker_update(
        dep_name=search,
        replace_string=search,
        replace_template=None,
        current_value=old,
        new_value="7.4" if old == "7.2" else "v7.4",
        current_digest=None,
        new_digest=None,
    )
    assert apply_to_text(text, update) == expected


def test_apply_to_text_keeps_a_short_go_digest_short() -> None:
    """Renovate cuts the 40-character hash to the length the pseudo-version holds."""
    text = "require example.com/x v0.0.0-20230101120000-abcdef123456\n"
    update = Update(
        manager="gomod",
        package_file="go.mod",
        dep_name="example.com/x",
        update_type="digest",
        branch_name="renovate/x",
        current_value="v0.0.0-20230101120000-abcdef123456",
        new_value="v0.0.0-20230101120000-abcdef123456",
        current_digest="abcdef123456",
        new_digest="0123456789abcdef0123456789abcdef01234567",
    )
    assert (
        apply_to_text(text, update) == "require example.com/x v0.0.0-20230101120000-0123456789ab\n"
    )


def test_apply_to_text_refuses_text_also_in_a_comment() -> None:
    """A comment that names the image is a second copy the report does not list."""
    text = "# based on node:20\nFROM node:20\n"
    update = docker_update(
        dep_name="node",
        replace_string="node:20",
        replace_template=None,
        current_value="20",
        new_value="22",
        current_digest=None,
        new_digest=None,
    )
    with pytest.raises(ReplaceError, match="not clear which ones"):
        apply_to_text(text, update)


def test_apply_to_text_anchors_a_bare_version_on_the_dependency_name() -> None:
    """Two hooks on the same rev: the one being updated is the one after its own repository."""
    text = (
        "  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.16.5\n"
        "  - repo: https://github.com/crate-ci/typos\n    rev: v0.16.5\n"
    )
    updated = apply_to_text(text, hook_update())
    assert "ruff-pre-commit\n    rev: v0.16.5" in updated
    assert "typos\n    rev: v0.16.9" in updated


def _npm_update(name: str, neighbors: tuple[str, ...]) -> Update:
    """Return a package.json range update, which the npm manager reports without a string."""
    return Update(
        manager="npm",
        package_file="package.json",
        dep_name=name,
        update_type="major",
        branch_name=f"renovate/major-{name}",
        current_value="^8.0.0",
        new_value="^9.0.0",
        neighbors=neighbors,
    )


@pytest.mark.parametrize(
    ("text", "name", "neighbors", "expected"),
    [
        pytest.param(
            '"lint": "eslint ."\n"@typescript-eslint/parser": "^8.0.0",\n"eslint": "^8.0.0"\n',
            "eslint",
            ("@typescript-eslint/parser",),
            '"lint": "eslint ."\n"@typescript-eslint/parser": "^8.0.0",\n"eslint": "^9.0.0"\n',
            id="name-in-a-script",
        ),
        pytest.param(
            '"@types/react": "^8.0.0",\n"react": "^8.0.0"\n',
            "react",
            ("@types/react",),
            '"@types/react": "^8.0.0",\n"react": "^9.0.0"\n',
            id="name-inside-a-longer-name",
        ),
    ],
)
def test_apply_to_text_places_a_bare_version_by_the_closest_dependency_name(
    text: str,
    name: str,
    neighbors: tuple[str, ...],
    expected: str,
) -> None:
    """A version that follows another dependency's name is that dependency's, not this one's."""
    assert apply_to_text(text, _npm_update(name, neighbors)) == expected


def test_apply_to_text_finds_a_python_name_written_apart_from_its_normal_form() -> None:
    """Renovate reports Sphinx as sphinx and pytest_cov as pytest-cov, as pip compares them."""
    text = 'docs = ["Sphinx>=7.2"]\ndev = ["pytest_cov>=7.2"]\n'
    update = replace(
        _npm_update("pytest-cov", ("sphinx",)),
        manager="pep621",
        package_file="pyproject.toml",
        current_value=">=7.2",
        new_value=">=8.1",
    )
    assert apply_to_text(text, update) == 'docs = ["Sphinx>=7.2"]\ndev = ["pytest_cov>=8.1"]\n'


def test_apply_to_text_lets_an_alias_keep_the_package_it_names() -> None:
    """In "react-17": "npm:react@^8.0.0", the react inside the value is the alias's own."""
    text = '"react": "^18.2.0",\n"react-17": "npm:react@^8.0.0"\n'
    update = replace(_npm_update("react-17", ("react",)), package_name="react")
    assert apply_to_text(text, update) == '"react": "^18.2.0",\n"react-17": "npm:react@^9.0.0"\n'


def test_apply_to_text_keeps_case_apart_outside_python_names() -> None:
    """Two Go modules that differ only in case are two dependencies, each with its own line."""
    text = (
        "require github.com/Sirupsen/logrus v1.9.0\n"
        "replace github.com/Sirupsen/logrus => github.com/sirupsen/logrus v1.9.0\n"
    )
    update = replace(
        _npm_update("github.com/sirupsen/logrus", ("github.com/Sirupsen/logrus",)),
        manager="gomod",
        package_file="go.mod",
        current_value="v1.9.0",
        new_value="v1.9.3",
    )
    assert apply_to_text(text, update) == (
        "require github.com/Sirupsen/logrus v1.9.0\n"
        "replace github.com/Sirupsen/logrus => github.com/sirupsen/logrus v1.9.3\n"
    )


def test_apply_to_text_lets_an_alias_keep_a_package_name_that_holds_another() -> None:
    """In "react-dom-17": "npm:react-dom@...", neither react nor react-dom claims the version."""
    text = '"react": "^18.2.0",\n"react-dom": "^18.2.0",\n"react-dom-17": "npm:react-dom@^8.0.0"\n'
    update = replace(_npm_update("react-dom-17", ("react", "react-dom")), package_name="react-dom")
    assert apply_to_text(text, update).endswith('"react-dom-17": "npm:react-dom@^9.0.0"\n')


def test_apply_to_text_leaves_an_alias_that_names_the_package_alone() -> None:
    """An alias earlier in the file holds the package's name in its value, not the package."""
    text = '"types-react-17": "npm:@types/react@^8.0.0",\n"@types/react": "^8.0.0"\n'
    update = replace(
        _npm_update("@types/react", ("types-react-17",)), aliased_by=("types-react-17",)
    )
    assert apply_to_text(text, update) == (
        '"types-react-17": "npm:@types/react@^8.0.0",\n"@types/react": "^9.0.0"\n'
    )


def test_apply_to_text_lets_an_alias_keep_its_npm_prefix() -> None:
    """An engines entry named npm is a dependency too, and the npm: of an alias is not it."""
    text = '"react-17": "npm:react@^8.0.0",\n"engines": {"npm": ">=9"}\n'
    update = replace(_npm_update("react-17", ("npm",)), package_name="react")
    assert apply_to_text(text, update).startswith('"react-17": "npm:react@^9.0.0"')


def test_apply_to_text_lets_a_cargo_rename_keep_the_package_it_names() -> None:
    """A rename's value names its package after the key, and that name is the rename's own."""
    text = 'rand07 = { package = "rand", version = "0.7.3" }\n'
    update = replace(
        _npm_update("rand07", ("rand",)),
        manager="cargo",
        package_file="Cargo.toml",
        package_name="rand",
        current_value="0.7.3",
        new_value="0.7.4",
    )
    assert apply_to_text(text, update) == 'rand07 = { package = "rand", version = "0.7.4" }\n'


def test_apply_to_text_takes_two_spellings_of_one_python_package_as_one_name() -> None:
    """typing_extensions and typing-extensions are one package, so neither blocks the other."""
    text = 'a = ["typing_extensions>=4.5"]\nb = ["typing-extensions>=4.12"]\n'
    update = replace(
        _npm_update("typing_extensions", ("typing-extensions",)),
        manager="pep621",
        package_file="pyproject.toml",
        current_value=">=4.5",
        new_value=">=4.6",
    )
    assert apply_to_text(text, update).startswith('a = ["typing_extensions>=4.6"]')


def test_apply_to_text_refuses_a_bare_version_when_the_name_is_not_in_the_file() -> None:
    """With no name to place it by, the first copy of the version could be anyone's."""
    with pytest.raises(ReplaceError, match="after the name 'eslint'"):
        apply_to_text('"prettier": "^8.0.0"\n', _npm_update("eslint", ("prettier",)))


def test_apply_to_text_says_so_when_the_text_has_already_moved() -> None:
    """A file that no longer holds what the report described is never rewritten on a guess."""
    update = docker_update()
    with pytest.raises(ReplaceError, match="is not in"):
        apply_to_text("nothing here\n", update)


def test_apply_all_edits_a_reference_that_is_really_in_the_file_twice() -> None:
    """An action used by two jobs is two updates and two lines, one edit each."""
    text = "  uses: a/b@aaa # v1\n  run: x\n  uses: a/b@aaa # v1\n"
    update = docker_update(
        manager="github-actions",
        dep_name="a/b",
        current_value="v1",
        new_value="v2",
        current_digest="aaa",
        new_digest="ccc",
        replace_string="a/b@aaa # v1",
        replace_template=ACTION_TEMPLATE,
    )
    assert apply_all(text, [update, update]) == (
        "  uses: a/b@ccc # v2\n  run: x\n  uses: a/b@ccc # v2\n"
    )


def test_apply_all_skips_a_repeat_of_a_line_that_is_in_the_file_once() -> None:
    """
    A Dockerfile ARG two FROM stages share is two dependencies over one line.

    Renovate reports the dependency once per use, so the second update has nothing left to do. It is
    the same edit already made, not a file that moved: make it once and carry on.
    """
    text = "ARG BASE=img:latest@sha256:aaaa\nFROM ${BASE} AS build\nFROM ${BASE} AS final\n"
    update = docker_update(
        manager="dockerfile",
        dep_name="img",
        current_value="latest",
        new_value="latest",
        replace_string="ARG BASE=img:latest@sha256:aaaa",
        replace_template="ARG BASE=img:latest@{{newDigest}}",
    )
    assert apply_all(text, [update, update]) == (
        "ARG BASE=img:latest@sha256:cccc\nFROM ${BASE} AS build\nFROM ${BASE} AS final\n"
    )


def test_apply_all_still_refuses_a_first_edit_it_cannot_place() -> None:
    """Skipping a repeat never becomes skipping the edit itself: the first miss is still a fault."""
    updates = [docker_update(), docker_update()]
    with pytest.raises(ReplaceError, match="is not in"):
        apply_all("nothing here\n", updates)


def test_same_edit_is_one_line_two_managers_found() -> None:
    """A regex manager and a built-in one on the same line make one edit, not two."""
    action, regex = wrangler_updates()
    assert same_edit(WORKFLOW, action, regex)


def test_same_edit_needs_both_to_write_the_same_version() -> None:
    """Two managers that disagree on the new version are not one edit; the second still fails."""
    action, regex = wrangler_updates(new_value="5.0.0")
    assert not same_edit(WORKFLOW, action, regex)


def test_same_edit_leaves_two_uses_from_one_manager_alone() -> None:
    """One manager reporting the same text twice is two uses, which apply_all edits one by one."""
    _, regex = wrangler_updates()
    assert not same_edit(WORKFLOW, regex, regex)


def test_same_edit_is_not_an_edit_that_cannot_be_placed() -> None:
    """When either edit misses the file, nothing is shown to be the same, and nothing is dropped."""
    action, regex = wrangler_updates(replace_string='wranglerVersion: "4.0.0"')
    assert not same_edit(WORKFLOW, action, regex)


def test_apply_all_two_hooks_sharing_a_version_are_both_updated() -> None:
    """Two hooks on the same rev are both updated regardless of order in the update list."""
    text = (
        "  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.16.5\n"
        "  - repo: https://github.com/crate-ci/typos\n    rev: v0.16.5\n"
    )
    typos = hook_update(dep_name="crate-ci/typos", current_value="v0.16.5", new_value="v0.16.9")
    ruff = hook_update(
        dep_name="astral-sh/ruff-pre-commit", current_value="v0.16.5", new_value="v0.16.9"
    )
    updated = apply_all(text, [typos, ruff])
    assert "ruff-pre-commit\n    rev: v0.16.9" in updated
    assert "typos\n    rev: v0.16.9" in updated


def test_apply_all_repeated_hook_anchors_past_other_hooks_on_the_same_rev() -> None:
    """A repeated hook searches for its own name past previous edits, not just any match."""
    text = (
        "  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.16.5\n"
        "  - repo: https://github.com/crate-ci/typos\n    rev: v0.16.5\n"
        "  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.16.5\n"
    )
    ruff = hook_update(
        dep_name="astral-sh/ruff-pre-commit",
        current_value="v0.16.5",
        new_value="v0.16.9",
        neighbors=("crate-ci/typos",),
    )
    updated = apply_all(text, [ruff, ruff])
    assert "typos\n    rev: v0.16.5" in updated
    assert updated.count("rev: v0.16.9") == 2
