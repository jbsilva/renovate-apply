"""The replacement engine: rendering Renovate's templates and finding what to swap."""

import pytest
from helpers import WORKFLOW, docker_update, hook_update, wrangler_updates

from renovate_apply.errors import ReplaceError
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


def test_render_treats_a_missing_name_as_empty() -> None:
    """An unknown or null field renders as nothing, the way handlebars reads it."""
    assert render("a{{missing}}b", {"newValue": None}) == "ab"


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


def test_apply_to_text_replaces_the_first_match_only() -> None:
    """Two identical references are two updates; each run moves one of them."""
    text = "a: x:1@sha256:aaaa\nb: x:1@sha256:aaaa\n"
    update = docker_update(
        dep_name="x",
        replace_string="x:1@sha256:aaaa",
        current_value="1",
        new_value="2",
        new_digest="sha256:cccc",
    )
    assert apply_to_text(text, update) == "a: x:2@sha256:cccc\nb: x:1@sha256:aaaa\n"


def test_apply_to_text_anchors_a_bare_version_on_the_dependency_name() -> None:
    """Two hooks on the same rev: the one being updated is the one after its own repository."""
    text = (
        "  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.16.5\n"
        "  - repo: https://github.com/crate-ci/typos\n    rev: v0.16.5\n"
    )
    updated = apply_to_text(text, hook_update())
    assert "ruff-pre-commit\n    rev: v0.16.5" in updated
    assert "typos\n    rev: v0.16.9" in updated


def test_apply_to_text_says_so_when_the_text_has_already_moved() -> None:
    """A file that no longer holds what the report described is never rewritten on a guess."""
    with pytest.raises(ReplaceError, match="is not in"):
        apply_to_text("nothing here\n", docker_update())


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
    with pytest.raises(ReplaceError, match="is not in"):
        apply_all("nothing here\n", [docker_update(), docker_update()])


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
        dep_name="astral-sh/ruff-pre-commit", current_value="v0.16.5", new_value="v0.16.9"
    )
    updated = apply_all(text, [ruff, ruff])
    assert "typos\n    rev: v0.16.5" in updated
    assert updated.count("rev: v0.16.9") == 2
