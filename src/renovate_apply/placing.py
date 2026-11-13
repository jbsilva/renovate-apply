"""
Decide which copy of a bare version belongs to a dependency.

npm, pep621, pre-commit and other managers report no ``replaceString``, only the version, and that
version can appear on many lines. A copy belongs to the dependency whose name is the closest name
before it, among every dependency the report lists for the file. Every rule below narrows which
names count, and when the answer is unclear, no copy belongs, so the edit stops instead of guessing.
"""

import re
from functools import cache
lazy from collections.abc import Sequence

lazy from renovate_apply.models import Update


# Renovate reports these managers' names normalized, as Python packaging compares them.
PYTHON_MANAGERS = frozenset(
    {"pep621", "poetry", "pip_requirements", "pip-compile", "pipenv", "pip_setup", "setup-cfg"},
)

# The prefix of an npm alias's value, "npm:react@^17", which an engines entry named npm would claim.
NPM_ALIAS = "npm:"

# A version runs on through these, so "==4.2" followed by one of them is the start of another.
_VERSION_CHARS = frozenset("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.+-")

_VERSION_DIGITS = frozenset("0123456789.")

# What an image or action name is made of, so a match right after one is the tail of another name.
_TOKEN_CHARS = frozenset("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ./_-@:")

# A bare number right after one of these is the bound of a range, not a version of its own.
_RANGE_OPERATORS = frozenset("^~<>=!")

# Characters a Python name is made of, so a match next to one is part of a longer word.
_NAME_CHARS = frozenset("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ._-")

# Managers whose files hold a dependency's settings in an inline table: { version = .. }.
_TABLE_MANAGERS = frozenset({"cargo", "pixi"})

# A Python extras group, "celery[redis]", whose names are not dependencies of their own here.
_EXTRAS = re.compile(r"\[[^\[\]\n]*\]")

_YAML = (".yaml", ".yml")

# The colon after a JSON key, up to where its value starts.
_MEMBER_VALUE = re.compile(r"\s*:\s*")

_WORD_CHARS = frozenset("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-")

# A TOML table header on a line of its own: [dependencies] or [dependencies.serde].
_TOML_HEADER = re.compile(
    r"^[ \t]*(?P<header>\[\[?[^\[\]\n]+\]\]?)[ \t]*(?:#[^\n]*)?$", re.MULTILINE
)

# A YAML list item: the indentation before its "- " marker.
_ITEM = re.compile(r"( *)- ")

_URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s\"'<>]+", re.IGNORECASE)

type _Span = tuple[int, int]


def copies(text: str, update: Update, search: str, start: int) -> list[int]:
    """Return every place from *start* where *search* is a whole version of this dependency."""
    found: list[int] = []
    for low, high in _sections(text, update):
        begin = max(start, low)
        at = text.find(search, begin, high)
        while at >= 0:
            if _whole_version(text, search, at) and _belongs_to(text, update, at, begin):
                found.append(at)
            at = text.find(search, at + 1, high)
    return found


def whole_copies(text: str, search: str, start: int) -> list[int]:
    """
    Return every place from *start* where *search* stands on its own, not inside a longer token.

    redis:7.2 inside bitnami/redis:7.2 belongs to another image, and image@v5 at the start of
    image@v5.1.0 is another version.
    """
    found: list[int] = []
    at = text.find(search, start)
    while at >= 0:
        after = at + len(search)
        joined_before = search[0].isalnum() and at > 0 and text[at - 1] in _TOKEN_CHARS
        joined_after = search[-1].isalnum() and after < len(text) and text[after] in _VERSION_CHARS
        if not (joined_before or joined_after):
            found.append(at)
        at = text.find(search, at + 1)
    return found


def section_key(text: str, update: Update) -> str | None:
    """Return the depType that narrows this update's search, or None when it searches the file."""
    return update.dep_type if _narrowed(text, update) else None


def _sections(text: str, update: Update) -> list[_Span]:
    """
    Return the parts of the file that can hold the dependency's entry, or all of it.

    Renovate's depType names them: for npm the package.json member, pnpm.overrides nested, and for
    Cargo the TOML tables, target tables included. A key appears once in each, so devDependencies
    and peerDependencies that pin one range are told apart, as are [dependencies] and [dev-
    dependencies].
    """
    return _narrowed(text, update) or [(0, len(text))]


def _narrowed(text: str, update: Update) -> list[_Span]:
    """Return the sections the depType names, or nothing when it names none."""
    if update.dep_type and update.manager == "npm":
        return _json_member(text, update.dep_type.split("."))
    if update.dep_type and update.manager in _TABLE_MANAGERS:
        return _toml_tables(text, update.dep_type, update.dep_name)
    return []


def _json_member(text: str, path: Sequence[str]) -> list[_Span]:
    """
    Return the value at *path* of the top-level JSON object: an object's body or a string's text.

    Each key is looked up among the direct members only, so devEngines.packageManager is never taken
    for packageManager.
    """
    opening = text.find("{")
    span: _Span | None = (opening + 1, _closing_brace(text, opening + 1)) if opening >= 0 else None
    for key in path:
        span = _member(text, span, key) if span else None
    return [span] if span else []


def _member(text: str, body: _Span, key: str) -> _Span | None:
    """Return the value of *key* among the direct members of the object whose *body* is given."""
    index, depth = body[0], 0
    while index < body[1]:
        char = text[index]
        if char == '"':
            end = _string_end(text, index)
            value = _MEMBER_VALUE.match(text, end + 1)
            if depth == 0 and text[index + 1 : end] == key and value is not None:
                return _value_span(text, value.end())
            index = end
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        index += 1
    return None


def _value_span(text: str, start: int) -> _Span | None:
    """Return the body of the object or the text of the string that starts at *start*."""
    if text.startswith("{", start):
        return start + 1, _closing_brace(text, start + 1)
    if text.startswith('"', start):
        return start + 1, _string_end(text, start)
    return None


def _string_end(text: str, start: int) -> int:
    """Return where the JSON string that opens at *start* closes."""
    index = start + 1
    while index < len(text) and text[index] != '"':
        index += 2 if text[index] == "\\" else 1
    return index


def _toml_tables(text: str, table: str, name: str) -> list[_Span]:
    """
    Return the [table] and [table.name] tables of a TOML file, each from its header on.

    A target table, [target.'cfg(unix)'.dependencies], has the same depType as [dependencies].
    """
    target = r"(?:target\.(?:'[^']*'|\"(?:[^\"\\]|\\.)*\"|[^.\]\s]+)\.)?"
    own = rf'(?:\.{re.escape(name)}|\."{re.escape(name)}")?'
    header = re.compile(rf"\[{target}{re.escape(table)}{own}\]")
    found: list[_Span] = []
    for line in _TOML_HEADER.finditer(text):
        if header.fullmatch(line.group("header")):
            following = _TOML_HEADER.search(text, line.end())
            found.append((line.start(), following.start() if following else len(text)))
    return found


def _closing_brace(text: str, start: int) -> int:
    """Return where the JSON object opened just before *start* closes, skipping strings."""
    depth, quoted, escaped = 1, False, False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
        elif quoted:
            escaped = char == "\\"
            quoted = char != '"'
        elif char == '"':
            quoted = True
        elif char in "{}":
            depth += 1 if char == "{" else -1
            if depth == 0:
                return index
    return len(text)


def name_key(name: str, manager: str) -> str:
    """Return the name as the manager compares it: normalized for Python, as written elsewhere."""
    if manager not in PYTHON_MANAGERS:
        return name
    return re.sub(r"[-_.]+", "-", name).lower()


def _whole_version(text: str, search: str, at: int) -> bool:
    """
    Say whether the text at *at* is a whole version, not part of a longer one or of a range.

    Only a version that starts with a digit checks what comes before it: 1.0 inside 0.1.0, or 9.1.0
    inside >=9.1.0. One that starts with ==, ^ or v follows a name, as in boto3==1.34.
    """
    after = at + len(search)
    if after < len(text) and text[after] in _VERSION_CHARS:
        return False
    if at == 0 or search[0] not in _VERSION_DIGITS:
        return True
    return text[at - 1] not in _VERSION_DIGITS and text[at - 1] not in _RANGE_OPERATORS


def _belongs_to(text: str, update: Update, at: int, start: int) -> bool:
    """Say whether this dependency's name is closer to the version at *at* than any other."""
    loose = update.manager in PYTHON_MANAGERS
    alias = _aliased_span(text, update, start, at, loose=loose)
    mine = _last_whole(text, update.dep_name, start, at if alias is None else alias[0], loose=loose)
    if mine is None or _named_by_an_alias(text, update, mine, loose=loose):
        return False
    if update.package_file.endswith(_YAML) and _new_item_between(text, mine, at):
        return False
    ignored = [*_own_extras(text, mine, at, loose=loose), *([alias] if alias else [])]
    if loose or update.manager in _TABLE_MANAGERS:
        ignored += _own_table(text, mine, at)
    if not _inside_any(mine, list(_urls(text, 0, mine[1]))):
        ignored += _urls(text, mine[1], at)
    return not any(
        _closer(found, mine)
        for other in update.neighbors
        if not (loose and same_python_name(other, update.dep_name))
        for found in _all(text, other, at, loose=loose)
        if not _inside_any(found, ignored) and not (loose and _inside_a_word(text, found))
    )


def same_python_name(name: str, other: str) -> bool:
    """Say whether two names are one Python package, as ``Sphinx`` and ``sphinx`` are."""
    return _pattern(name, loose=True).fullmatch(other) is not None


def _closer(found: _Span, mine: _Span) -> bool:
    """Say whether a name *found* sits closer to the version than this dependency's own."""
    return found[1] > mine[1] or (found[1] == mine[1] and found[0] <= mine[0])


def _named_by_an_alias(text: str, update: Update, mine: _Span, *, loose: bool) -> bool:
    """Say whether *mine* is inside an alias's value: "react-17": "npm:react@^17" is not react."""
    for alias in update.aliased_by:
        found = _last(text, alias, 0, mine[0], loose=loose)
        if found is not None and "\n" not in text[found[1] : mine[0]]:
            return True
    return False


def _aliased_span(text: str, update: Update, start: int, at: int, *, loose: bool) -> _Span | None:
    """Return where an alias names its package on the version's line: "react-17": "npm:react@"."""
    package = update.package_name
    if package is None or package == update.dep_name:
        return None
    if loose and same_python_name(package, update.dep_name):
        return None
    line = max(start, text.rfind("\n", 0, at) + 1)
    span = _last(text, package, line, at, loose=loose)
    # A git URL whose last segment is the name is the dependency itself, not an alias of it.
    if span is None or _last(text, update.dep_name, line, span[0], loose=loose) is None:
        return None
    if text.startswith(NPM_ALIAS, span[0] - len(NPM_ALIAS)):
        return span[0] - len(NPM_ALIAS), span[1]
    return span


def _own_extras(text: str, mine: _Span, at: int, *, loose: bool) -> list[_Span]:
    """Return the extras groups between a Python name and its version: "celery[redis]>=5"."""
    return [match.span() for match in _EXTRAS.finditer(text, mine[1], at)] if loose else []


def _new_item_between(text: str, mine: _Span, at: int) -> bool:
    """
    Say whether a YAML list item starts after the name's line, at its depth or out, up to *at*.

    In "- version: 18.1.0" after "- name: redis", the version is the next chart's, not redis's. A
    deeper item, such as a pre-commit hook under its repo, is still part of the name's entry.
    """
    line_start = text.rfind("\n", 0, mine[0]) + 1
    depth = _item_depth(text[line_start : mine[0]])
    next_line = text.find("\n", mine[1], at)
    if next_line < 0:
        return False
    return any(
        (item := _ITEM.match(line)) is not None and len(item.group(1)) <= depth
        for line in text[next_line + 1 : at].split("\n")
    )


def _item_depth(prefix: str) -> int:
    """Return the column of the list marker that opens *prefix*, or its indentation without one."""
    item = _ITEM.match(prefix)
    return len(item.group(1)) if item else len(prefix) - len(prefix.lstrip(" "))


def _own_table(text: str, mine: _Span, at: int) -> list[_Span]:
    """
    Return this dependency's own table: python and features there are its keys and values.

    That is an inline table on the name's line, or the body of a [dependencies.name] table.
    """
    line_start = text.rfind("\n", 0, mine[0]) + 1
    if text.startswith("[", line_start):
        return [(mine[1], at)]
    opening = text.find("{", mine[1], at)
    if opening < 0 or "\n" in text[mine[1] : at]:
        return []
    return [(opening, at)]


def _inside_a_word(text: str, span: _Span) -> bool:
    """Say whether a Python name is part of a longer word, as python is in python_version."""
    before = text[span[0] - 1] if span[0] else " "
    after = text[span[1]] if span[1] < len(text) else " "
    return before in _NAME_CHARS or after in _NAME_CHARS


def _urls(text: str, start: int, end: int) -> list[_Span]:
    """Return the URLs between *start* and *end*, whose path can hold any dependency's name."""
    return [match.span() for match in _URL.finditer(text, start, end)]


def _inside_any(span: _Span, spans: Sequence[_Span]) -> bool:
    """Say whether *span* lies wholly inside one of *spans*."""
    return any(outer[0] <= span[0] and span[1] <= outer[1] for outer in spans)


def _last_whole(text: str, name: str, start: int, end: int, *, loose: bool) -> _Span | None:
    """
    Return where *name* last appears as a name of its own, not inside another word.

    "uuid" at the end of a "with-uuid" feature is no uuid, but wrangler in wranglerVersion is. A
    Python name keeps the looser rule: python in requires-python is the Python dependency.
    """
    found = [
        span
        for span in _all(text, name, end, loose=loose, start=start)
        if loose or not span[0] or text[span[0] - 1] not in _WORD_CHARS
    ]
    return found[-1] if found else None


def _last(text: str, name: str, start: int, end: int, *, loose: bool) -> _Span | None:
    """Return where *name* last appears between *start* and *end*."""
    found = _all(text, name, end, loose=loose, start=start)
    return found[-1] if found else None


def _all(text: str, name: str, end: int, *, loose: bool, start: int = 0) -> list[_Span]:
    """Return every place *name* appears between *start* and *end*."""
    return [match.span() for match in _pattern(name, loose=loose).finditer(text, start, end)]


@cache
def _pattern(name: str, *, loose: bool) -> re.Pattern[str]:
    """
    Match a name exactly, or *loose*ly as Python packaging compares names.

    Loose is any case, with ``-``, ``_`` and ``.`` alike: Renovate reports ``Sphinx`` as ``sphinx``.
    Elsewhere case matters, because two Go modules can differ by it alone.
    """
    if not loose:
        return re.compile(re.escape(name))
    parts = (r"[-_.]+" if char in "-_." else re.escape(char) for char in name)
    return re.compile("".join(parts), re.IGNORECASE)
