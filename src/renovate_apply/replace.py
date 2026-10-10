"""
Make the edit Renovate would have made, from what its report says about the dependency.

Renovate calls this auto-replace, and the report carries both halves of it. ``replaceString`` is the
exact text the manager found in the file. ``autoReplaceStringTemplate`` is how to write that text
again with the new version or digest in it. Rendering the second and swapping it for the first is
the whole edit, and it is what Renovate itself commits.

Two managers give less than that:

- Some give a ``replaceString`` and no template. The new text is then the old text with the version
  and the digest substituted, which is Renovate's own fallback.
- Some give neither, the pre-commit manager among them. The text to look for is then the bare
  version.
"""

import re
lazy from collections.abc import Mapping

from renovate_apply.errors import ReplaceError
lazy from renovate_apply.models import Update


# The templates are handlebars, but a replacement template only ever uses these forms. Anything
# else is a manager this tool has not seen, and it stops rather than write a guess.
_TOKEN = re.compile(
    r"\{\{\{\s*(?P<raw>[\w.]+)\s*\}\}\}"
    r"|\{\{#\s*(?P<block>if|unless)\s+(?P<test>[\w.]+)\s*\}\}"
    r"|\{\{/\s*(?P<close>if|unless)\s*\}\}"
    r"|\{\{\s*(?P<name>[\w.]+)\s*\}\}"
    r"|\{\{(?P<other>[^}]*)\}\}",
)


def render(template: str, values: Mapping[str, str | None]) -> str:
    """
    Expand a replacement template against the fields of an update.

    Supports ``{{name}}``, ``{{{name}}}``, ``{{#if name}}`` and ``{{#unless name}}``, nested. A name
    that is missing or empty counts as false, the way handlebars reads it.
    """
    text, end = _render(template, values, 0, None)
    if end != len(template):  # pragma: no cover - _render only stops early on a close tag
        msg = f"template has a stray closing tag: {template!r}"
        raise ReplaceError(msg)
    return text


def template_values(update: Update) -> dict[str, str | None]:
    """Return the fields a replacement template can name, as Renovate names them."""
    return {
        "depName": update.dep_name,
        "packageName": update.dep_name,
        "currentValue": update.current_value,
        "currentDigest": update.current_digest,
        "newValue": update.new_value,
        "newDigest": update.new_digest,
        "newName": update.new_name,
    }


def search_and_replacement(update: Update) -> tuple[str, str]:
    """
    Return the text to find in the package file and the text to put in its place.

    Raises ReplaceError when the report does not say enough to make an edit, or when the two come
    out the same, which would mean writing the file for nothing.
    """
    search = _search_string(update)
    replacement = _replacement_string(update, search)
    if search == replacement:
        msg = f"{update.dep_name}: the replacement is the text it replaces"
        raise ReplaceError(msg)
    return search, replacement


def _search_string(update: Update) -> str:
    """Return the text the manager found, or the bare version when it reported none."""
    if update.replace_string is not None:
        return update.replace_string
    digest_moves = _moves(update.current_digest, update.new_digest)
    value_moves = _moves(update.current_value, update.new_value)
    fallback = update.current_digest if digest_moves and not value_moves else update.current_value
    if not fallback:
        msg = f"{update.dep_name}: the report does not say what text to replace"
        raise ReplaceError(msg)
    return fallback


def _replacement_string(update: Update, search: str) -> str:
    """Render the template, or substitute the version and the digest into the text found."""
    if update.replace_template:
        return render(update.replace_template, template_values(update))
    replacement = search
    if _moves(update.current_value, update.new_value):
        replacement = replacement.replace(str(update.current_value), str(update.new_value), 1)
    if _moves(update.current_digest, update.new_digest):
        replacement = replacement.replace(str(update.current_digest), str(update.new_digest), 1)
    return replacement


def _moves(current: str | None, new: str | None) -> bool:
    """Say whether both sides are there and they differ."""
    return bool(current and new and current != new)


def _render(
    template: str,
    values: Mapping[str, str | None],
    start: int,
    until: str | None,
) -> tuple[str, int]:
    """Expand from *start* until the close tag *until*, returning the text and where it stopped."""
    out: list[str] = []
    position = start
    for match in _TOKEN.finditer(template, start):
        if match.start() < position:
            continue  # inside a block that was already expanded by the recursive call below
        out.append(template[position : match.start()])
        position = match.end()
        name = match.group("raw") or match.group("name")
        block = match.group("block")
        close = match.group("close")
        if name is not None:
            out.append(values.get(name) or "")
        elif block is not None:
            body, position = _render(template, values, position, block)
            if bool(values.get(match.group("test"))) is (block == "if"):
                out.append(body)
        elif close is not None:
            if close != until:
                msg = f"template closes {{{{/{close}}}}} that was never opened: {template!r}"
                raise ReplaceError(msg)
            return "".join(out), position
        else:
            msg = f"unsupported template expression {match.group(0)!r} in {template!r}"
            raise ReplaceError(msg)
    if until is not None:
        msg = f"template never closes {{{{#{until}}}}}: {template!r}"
        raise ReplaceError(msg)
    out.append(template[position:])
    return "".join(out), len(template)
