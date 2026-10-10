"""The replacement engine: rendering Renovate's templates and finding what to swap."""

import pytest

from renovate_apply.errors import ReplaceError
from renovate_apply.replace import render


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
