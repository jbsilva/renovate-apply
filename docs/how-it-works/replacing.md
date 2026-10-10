---
icon: lucide/replace
---

# Making the edit

Renovate calls this auto-replace, and the report carries both halves of it.

`replaceString` is the exact text the manager found in the file. `autoReplaceStringTemplate` says
how to write that text again with the new version in it. Render the second, find the first, swap
them. That is the whole edit.

```text
replaceString  ghcr.io/atuinsh/atuin:v18.13.3@sha256:aaaa
template       {{depName}}{{#if newValue}}:{{newValue}}{{/if}}{{#if newDigest}}@{{newDigest}}{{/if}}
rendered       ghcr.io/atuinsh/atuin:18.22.0@sha256:cccc
```

## Templates

The templates are handlebars. A replacement template only ever uses a few forms, and those are the
ones supported:

| Form                           | Meaning                                       |
| ------------------------------ | --------------------------------------------- |
| `{{name}}`                     | The field's value, or nothing if it is unset. |
| `{{{name}}}`                   | The same. Renovate does not HTML-escape here. |
| `{{#if name}}…{{/if}}`         | Keep the body when the field is set.          |
| `{{#unless name}}…{{/unless}}` | Keep the body when it is not.                 |
| `{{else}}`                     | The other branch of an `if` or `unless`.      |

Blocks nest. The fields a template can name are `depName`, `packageName`, `currentValue`,
`currentDigest`, `newValue`, `newDigest` and `newName`. A field that is missing or empty counts as
false, the way handlebars reads it.

Anything else stops the run:

```console
renovate-apply: unsupported template expression '{{#each deps}}' in ...
```

That is on purpose. A template feature rendered wrong writes a broken version string into a file,
and the commit looks fine. Stopping is the only safe answer.

## Managers that give less

Two cases give less than a template and a string.

**A string and no template.** Some managers report `replaceString` alone. The new text is then the
old text with the version and the digest substituted into it, which is Renovate's own fallback. A
custom regex manager usually lands here:

```text
found       # renovate: depName=zizmor
            ZIZMOR_VERSION: 1.30.0
written     # renovate: depName=zizmor
            ZIZMOR_VERSION: 1.30.1
```

**Neither.** The pre-commit manager is one of these. The text to look for is then the bare version,
and it is looked for *after* the dependency's name in the file. Two hooks pinned to the same rev
would otherwise be indistinguishable:

```yaml
- repo: https://github.com/astral-sh/ruff-pre-commit
  rev: v0.16.5    # not this one
- repo: https://github.com/crate-ci/typos
  rev: v0.16.5    # this one, because it follows crate-ci/typos
```

## When the text is not there

If the search text is not in the file, the run stops for that group:

```console
renovate-apply: postgres: 'postgres:18-alpine' is not in stack/compose.yaml. Was it already updated?
```

No fallback, no fuzzy match, no second guess. A file that no longer matches the report is a file the
report no longer describes, and widening the search to "probably this line" is how a wrong version
gets written into somebody's infrastructure.

## One dependency, used twice

Renovate reports a dependency once per use, not once per line. An action two jobs run comes back as
two updates carrying the same `replaceString`.

The edits of one file are made in order, and each repeat starts looking from where the previous edit
ended. So:

- A reference that really is in the file twice gets edited twice.
- A repeat with nothing left to find is a line this run already updated, not an error. A Dockerfile
    `ARG` that two `FROM` stages share is two dependencies over one line.

## All or nothing, per group

Every edit of a group is computed before any of them is written. A group that fails on its second
file leaves the first one alone.

This matters because of what would otherwise happen. The group is reported as failed and passed
over, but its first file would still be sitting there edited. The next group to touch that file
would stage it and commit the edit under its own message, and `git status` would come back clean, so
nothing would tell you.

## Line endings

Files are read and written with newlines untranslated. A CRLF file stays CRLF. Otherwise the
one-line diff Renovate promises would be the whole file rewritten.
