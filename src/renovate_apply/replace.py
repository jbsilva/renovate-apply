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
  version, and it is looked for after the dependency's name, so a version that two hooks happen to
  share cannot send the edit to the wrong one.

A dependency is reported once per use, so the updates of one file are made in order and each one
searches on from the last, which is what keeps a line used twice from being edited twice over.
"""

import re
lazy from collections.abc import Mapping, Sequence

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


def apply_to_text(text: str, update: Update) -> str:
    """Return *text* with this one update made, leaving everything else byte for byte."""
    return apply_all(text, [update])


def apply_all(text: str, updates: Sequence[Update]) -> str:
    """
    Return *text* with every one of *updates* made, in the order the report gave them.

    Renovate reports a dependency once per use, not once per line, so one line can come back more
    than once: a Dockerfile ``ARG`` that two ``FROM`` stages share is two dependencies carrying the
    same ``replaceString``. Each repeat therefore looks on from where the edit before it ended. A
    string that really is in the file twice is edited twice, and a repeat with nothing left to find
    is a line this run already updated, not a file that moved underneath the report.
    """
    resume: dict[tuple[str, str], int] = {}
    for update in updates:
        search, replacement = search_and_replacement(update)
        key = (search, replacement)
        at = _locate(text, update, search, resume.get(key))
        if at is None:
            continue
        text = text[:at] + replacement + text[at + len(search) :]
        resume[key] = at + len(replacement)
    return text


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


def _locate(text: str, update: Update, search: str, resume: int | None) -> int | None:
    """
    Return where the text to replace starts, refusing to guess when it is not there.

    *resume* is where the last edit of this same text ended, or None when this is the first of them.
    Once one edit has been made, the text being gone means the repeat has nothing left to do, which
    is None. Not finding it on the first try is a file the report no longer describes.
    """
    at = text.find(search, _anchor(text, update) if resume is None else resume)
    if at >= 0:
        return at
    if resume is not None:
        return None
    msg = f"{update.dep_name}: {search!r} is not in {update.package_file}. Was it already updated?"
    raise ReplaceError(msg)


def _anchor(text: str, update: Update) -> int:
    """
    Return where to start looking for the first edit of a dependency.

    With no ``replaceString`` the search text is a bare version, so the dependency's name anchors
    it: the version that belongs to this dependency is the first one after its name.
    """
    if update.replace_string is not None:
        return 0
    return max(text.find(update.dep_name), 0)


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
