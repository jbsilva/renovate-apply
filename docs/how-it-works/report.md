---
icon: lucide/file-json
---

# Reading the report

## Running the scan

The scan is a normal Renovate run with two settings forced:

| Setting                     | Why                                                                                                        |
| --------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `--platform=local`          | Read the working copy. No server, no clone.                                                                |
| `RENOVATE_REPORT_TYPE=file` | Write a JSON report instead of only logging.                                                               |
| `LOG_LEVEL=warn`            | Renovate takes bunyan's level names. A shell exporting `warning` for something else would make it exit 60. |

The report goes to a temporary file, is read back, and the temporary directory is removed. The
report is a supported machine-readable output, not the debug log, so it stays small and stable.

If Renovate exits non-zero, or exits zero without writing a report, the run stops and prints the
last 15 lines of Renovate's own output. That is where Renovate says what went wrong.

## The shape of it

The report nests four levels deep:

```json
{
  "repositories": {
    "local": {
      "packageFiles": {
        "docker-compose": [
          {
            "packageFile": "stack/compose.yaml",
            "deps": [
              {
                "depName": "ghcr.io/atuinsh/atuin",
                "currentValue": "v18.13.3",
                "replaceString": "ghcr.io/atuinsh/atuin:v18.13.3@sha256:aaaa",
                "autoReplaceStringTemplate": "{{depName}}{{#if newValue}}:{{newValue}}{{/if}}",
                "updates": [
                  { "updateType": "minor", "newValue": "18.22.0", "branchName": "renovate/atuin" }
                ]
            }]
        }]
      }
    }
  }
}
```

Manager, then package file, then dependency, then the updates found for it. Flattening that gives
one `Update` per thing to change, carrying both what to change and where.

Note which fields sit where. `replaceString` and `currentValue` belong to the dependency, because
they describe the file as it is now. `newValue` and `branchName` belong to the update, because one
dependency can have several.

## Narrowing it

Everything is read through helpers that refuse a surprise rather than walk into it. A missing key
reads as empty. A key holding the wrong type stops the run:

```console
renovate-apply: renovate reported: packageFiles.docker-compose is a str, not a list
```

This is deliberately all in one module. When Renovate changes the shape of its report, it fails
loudly in one place instead of halfway through editing somebody's Dockerfile.

The local platform always calls the one repository it reads `local`. A report naming anything else
means the run was not a local one, and that is an error too.

## Problems Renovate reported

Renovate files its own complaints in the report, both globally and per repository. They are printed
as warnings and do not stop the run:

```console
renovate-apply: renovate reported: GitHub rate limit reached
```

That one is worth reading. A rate-limited lookup can come back empty, which looks exactly like a
dependency that is already up to date.

## Grouping

Each update carries the `branchName` Renovate would have opened. Updates are gathered by that name,
in the order the report listed them, and each group becomes one commit. A grouped pull request on
the server and a local run therefore produce the same commits.

An update with no branch name lands in `renovate/ungrouped`.
