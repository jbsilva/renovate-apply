"""The replacement engine: rendering Renovate's templates and finding what to swap."""

import pytest
from helpers import docker_update, hook_update

from renovate_apply.errors import ReplaceError
from renovate_apply.replace import render, search_and_replacement, template_values


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
