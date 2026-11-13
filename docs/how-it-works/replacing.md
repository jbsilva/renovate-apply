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
`currentDigest`, `newValue`, `newDigest`, `newName` and `newVersion`. A field that is empty counts
as false, the way handlebars reads it.

A built-in manager sets its template on each dependency. A custom `regex` or `jsonata` manager sets
its `autoReplaceStringTemplate` on the package file, and every dependency of that file uses it.

Anything else stops the run, another field name included:

```console
renovate-apply: unsupported template expression '{{#each deps}}' in ...
renovate-apply: template names 'datasource', a field this tool does not know: ...
```

That is on purpose. A template feature rendered wrong writes a broken version string into a file,
and the commit looks fine. Stopping is the only safe answer.

## Managers that give less

Two cases give less than a template and a string.

**A string and no template.** Some managers report `replaceString` alone. The new text is then the
old text with the version and the digest substituted into it, which is Renovate's own fallback. A
custom regex manager with no `autoReplaceStringTemplate` lands here:

```text
found       # renovate: depName=zizmor
            ZIZMOR_VERSION: 1.30.0
written     # renovate: depName=zizmor
            ZIZMOR_VERSION: 1.30.1
```

**Neither.** The pre-commit, npm and pep621 managers are some of these. The text to look for is then
the bare version. The tool edits the first copy of it whose closest dependency name before it is
this dependency's name. The report lists every dependency of the file, so the tool knows all the
names. This rule tells apart two hooks pinned to the same rev:

```yaml
- repo: https://github.com/astral-sh/ruff-pre-commit
  rev: v0.16.5    # not this one
- repo: https://github.com/crate-ci/typos
  rev: v0.16.5    # this one, because it follows crate-ci/typos
```

The same rule keeps an edit of `eslint` away from the range of `@typescript-eslint/parser`, and from
a script that runs `eslint`. A Python name matches in any case, with `-`, `_` and `.` alike, because
Renovate reports it in its normal form: `Sphinx` in the file is `sphinx` in the report. Other names
match exactly, because two Go modules can differ only in case. An npm alias such as
`"react-17": "npm:react@^17.0.0"`, or a Cargo rename, names its package in its value. That name
belongs to the alias, not to the package. Some names do not count as another dependency's name: an
extra such as `redis` in `celery[redis]`, and a name in a URL after a dependency that is not itself
named by a URL. Keys inside the dependency's own inline table, such as `python` in
`tomli = { python = "<3.11", version = "^2.0" }`, do not count either. A copy of the version must be
a whole version: `==4.2` is not the start of `==4.2.11`, and `1.0` is not the end of `0.1.0`.

In a YAML file, the name and the version must be in one list item. In a chart entry that lists
`- version: 18.1.0` before its `name:`, the version belongs to that entry, not to the entry above.

For npm and Cargo, the copy must also sit in the part of the file that Renovate reports as the
dependency's `depType`. For npm, that is a key such as `devDependencies` or `pnpm.overrides`. For
Cargo, it is a table such as `[dev-dependencies]`, `[dependencies.serde]` or
`[target.'cfg(unix)'.dependencies]`. A key appears once in each part, so this copy is certain,
whatever order the report lists the parts in. In a `[dependencies.serde]` table, the names in its
`features` belong to serde.

If the name of the dependency is not in the file, the run stops for that group. Some managers name a
dependency in a way the file never spells out:

- Maven: `org.slf4j:slf4j-api` is a `groupId` and an `artifactId` in two elements.
- Gradle: the `kotlin("jvm")` plugin is `org.jetbrains.kotlin.jvm`, and a version catalog entry that
    uses `version.ref` holds its version under another key.
- Argo CD: a chart from an OCI `repoURL` is named by the registry and the chart together.

The run also stops if the number of copies that qualify differs from the number the group edits.
Renovate's report does not follow the file's order, so the tool cannot know which copy is this
update's. For example, a chart named `redis` at `19.0.1` with a `redis` dependency at `19.0.1` has
two copies and one update. A version mentioned in a script or a comment after the name can stop an
update in the same way.

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
