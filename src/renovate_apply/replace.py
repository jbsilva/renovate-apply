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
  version, and only a copy whose closest dependency name is this one's counts, so a version that
  two dependencies share cannot send the edit to the wrong one.

A dependency is reported once per use, so the updates of one file are made in order and each one
searches on from the last, which is what keeps a line used twice from being edited twice over.
"""

import re
from collections import Counter
lazy from collections.abc import Mapping, Sequence

from renovate_apply.errors import ReplaceError
from renovate_apply.placing import copies, name_key, section_key, whole_copies
lazy from renovate_apply.models import Update


# The templates are handlebars, but a replacement template only ever uses these forms. Anything
# else is a manager this tool has not seen, and it stops rather than write a guess.
_TOKEN = re.compile(
    r"\{\{\{\s*(?P<raw>[\w.]+)\s*\}\}\}"
    r"|\{\{#\s*(?P<block>if|unless)\s+(?P<test>[\w.]+)\s*\}\}"
    r"|\{\{/\s*(?P<close>if|unless)\s*\}\}"
    # Must precede the plain-name branch, which would otherwise read {{else}} as a field of that
    # name, expand it to nothing, and leave both branches of the block in the output.
    r"|\{\{\s*(?P<alt>else)\s*\}\}"
    r"|\{\{\s*(?P<name>[\w.]+)\s*\}\}"
    r"|\{\{(?P<other>[^}]*)\}\}",
)


def render(template: str, values: Mapping[str, str | None]) -> str:
    """
    Expand a replacement template against the fields of an update.

    Supports ``{{name}}``, ``{{{name}}}``, ``{{#if name}}`` and ``{{#unless name}}``, nested, each
    with an optional ``{{else}}``. A field that is null or empty counts as false, the way handlebars
    reads it. A name that is not in *values* raises, because Renovate would have filled it.
    """
    text, end, _ = _render(template, values, 0, None)
    if end != len(template):  # pragma: no cover - _render only stops early on a close tag
        msg = f"template has a stray closing tag: {template!r}"
        raise ReplaceError(msg)
    return text


def template_values(update: Update) -> dict[str, str | None]:
    """Return the fields a replacement template can name, as Renovate names them."""
    return {
        "depName": update.dep_name,
        "packageName": update.package_name or update.dep_name,
        "currentValue": update.current_value,
        "currentDigest": update.current_digest,
        "newValue": update.new_value,
        "newDigest": update.new_digest,
        "newName": update.new_name,
        "newVersion": update.new_version,
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


def same_edit(
    text: str,
    first: Update,
    second: Update,
    *,
    uses: tuple[int, int] = (1, 1),
) -> bool:
    """
    Say whether two managers found the same use of a dependency and agree on its new text.

    A repository's regex manager can find a line a built-in manager also finds, and Renovate then
    reports it twice, on two branches. Made once, the line no longer holds what the second expects.
    Within one manager two equal edits are two uses, which ``apply_all`` makes one after the other.
    *uses* says which use of its text each update is, so a second use is compared at its own line.
    """
    if first.manager == second.manager or first.package_file != second.package_file:
        return False
    try:
        one = apply_all(text, [first] * uses[0], count=False)
        return one == apply_all(text, [second] * uses[1], count=False)
    except ReplaceError:
        return False


def apply_all(text: str, updates: Sequence[Update], *, count: bool = True) -> str:
    """
    Return *text* with every one of *updates* made, in the order the report gave them.

    Renovate reports a dependency once per use, not once per line, so one line can come back more
    than once: a Dockerfile ``ARG`` that two ``FROM`` stages share is two dependencies carrying the
    same ``replaceString``. Each repeat therefore looks on from where the edit before it ended. A
    string that really is in the file twice is edited twice, and a repeat with nothing left to find
    is a line this run already updated, not a file that moved underneath the report.

    Without *count*, the copies are not counted against the edits, for a caller that asks what one
    use of a text would become.
    """
    planned = [(update, *search_and_replacement(update)) for update in updates]
    # One key per section, so a search in devDependencies never resumes into peerDependencies.
    keys = [
        (name_key(one.dep_name, one.manager), section_key(text, one), search, new)
        for one, search, new in planned
    ]
    edits = Counter(keys)
    resume: dict[tuple[str, str | None, str, str], int] = {}
    for (update, search, replacement), key in zip(planned, keys, strict=True):
        at = _locate(text, update, search, resume.get(key), edits=edits[key] if count else None)
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
    # Every copy, as Renovate's autoReplaceGlobalMatch does by default: a URL can hold the version
    # twice. A repository that turns it off says so only in its configuration, not in the report.
    replacement = search
    if _moves(update.current_value, update.new_value):
        replacement = replacement.replace(str(update.current_value), str(update.new_value))
    if _moves(update.current_digest, update.new_digest):
        replacement = replacement.replace(str(update.current_digest), str(update.new_digest))
    return replacement


def _locate(
    text: str,
    update: Update,
    search: str,
    resume: int | None,
    *,
    edits: int | None = 1,
) -> int | None:
    """
    Return where the text to replace starts, refusing to guess when it is not there.

    *resume* is where the last edit of this same text ended, or None when this is the first of them.
    Once one edit has been made, the text being gone means the repeat has nothing left to do, which
    is None. Not finding it on the first try is a file the report no longer describes.

    Text found in more places than *edits*, the updates making this same edit, stops: the report's
    order is not the file's, so which copy is this update's is a guess. A bare version also stops
    when it is found in fewer places.
    """
    start = 0 if resume is None else resume
    if update.replace_string is None:
        found = copies(text, update, search, start)
        if resume is None and edits is not None and found and len(found) != edits:
            msg = (
                f"{update.dep_name}: {search!r} follows the name {update.dep_name!r} {len(found)} "
                f"times in {update.package_file}, and this group edits {edits} of them, so it is "
                "not clear which ones to edit."
            )
            raise ReplaceError(msg)
        at = found[0] if found else -1
    else:
        found = whole_copies(text, search, start)
        if resume is None and edits is not None and len(found) > edits:
            msg = (
                f"{update.dep_name}: {search!r} is in {update.package_file} {len(found)} times, "
                f"and this group edits {edits} of them, so it is not clear which ones to edit."
            )
            raise ReplaceError(msg)
        at = found[0] if found else -1
    if at >= 0:
        return at
    if resume is not None:
        return None
    where = update.package_file
    if update.replace_string is None:
        where = f"{where} after the name {update.dep_name!r}"
    msg = f"{update.dep_name}: {search!r} is not in {where}. Was it already updated?"
    raise ReplaceError(msg)


def _moves(current: str | None, new: str | None) -> bool:
    """Say whether both sides are there and they differ."""
    return bool(current and new and current != new)


def _render(
    template: str,
    values: Mapping[str, str | None],
    start: int,
    until: str | None,
) -> tuple[str, int, bool]:
    """
    Expand from *start* to the close tag *until*, or to this block's ``{{else}}``.

    Returns the text, where it stopped, and whether it stopped on an ``{{else}}`` rather than on the
    close tag, which is what tells the caller another branch follows.
    """
    out: list[str] = []
    position = start
    for match in _TOKEN.finditer(template, start):
        if match.start() < position:
            continue  # inside a block that was already expanded by the recursive call below
        out.append(template[position : match.start()])
        position = match.end()
        if _terminates(match, template, until):
            return "".join(out), position, match.group("alt") is not None
        body, position = _expand(match, template, values, position)
        out.append(body)
    if until is not None:
        msg = f"template never closes {{{{#{until}}}}}: {template!r}"
        raise ReplaceError(msg)
    out.append(template[position:])
    return "".join(out), len(template), False


def _terminates(match: re.Match[str], template: str, until: str | None) -> bool:
    """Say whether this token ends the block being expanded, refusing one that closes nothing."""
    close = match.group("close")
    if close is not None:
        if close != until:
            msg = f"template closes {{{{/{close}}}}} that was never opened: {template!r}"
            raise ReplaceError(msg)
        return True
    if match.group("alt") is None:
        return False
    if until is None:
        msg = f"template has an {{{{else}}}} outside a block: {template!r}"
        raise ReplaceError(msg)
    return True


def _expand(
    match: re.Match[str],
    template: str,
    values: Mapping[str, str | None],
    position: int,
) -> tuple[str, int]:
    """Expand one token that is not a terminator, returning its text and where to carry on."""
    name = match.group("raw") or match.group("name")
    if name is not None:
        return _value(values, name, template) or "", position
    block = match.group("block")
    if block is not None:
        return _render_block(template, values, position, block, match.group("test"))
    msg = f"unsupported template expression {match.group(0)!r} in {template!r}"
    raise ReplaceError(msg)


def _render_block(
    template: str,
    values: Mapping[str, str | None],
    start: int,
    block: str,
    test: str,
) -> tuple[str, int]:
    """Expand one ``{{#if}}`` or ``{{#unless}}``, returning the branch its test selects."""
    body, position, had_else = _render(template, values, start, block)
    alternative = ""
    if had_else:
        alternative, position, again = _render(template, values, position, block)
        if again:
            msg = f"template has two {{{{else}}}} in one block: {template!r}"
            raise ReplaceError(msg)
    taken = bool(_value(values, test, template)) is (block == "if")
    return (body if taken else alternative), position


def _value(values: Mapping[str, str | None], name: str, template: str) -> str | None:
    """Return a field's value, refusing a field this tool does not carry."""
    if name not in values:
        msg = f"template names {name!r}, a field this tool does not know: {template!r}"
        raise ReplaceError(msg)
    return values[name]
