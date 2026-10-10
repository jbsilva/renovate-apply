"""
Make the edit Renovate would have made, from what its report says about the dependency.

Renovate calls this auto-replace, and the report carries both halves of it. ``replaceString`` is the
exact text the manager found in the file. ``autoReplaceStringTemplate`` is how to write that text
again with the new version or digest in it. Rendering the second and swapping it for the first is
the whole edit, and it is what Renovate itself commits.
"""

import re
lazy from collections.abc import Mapping

from renovate_apply.errors import ReplaceError


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
