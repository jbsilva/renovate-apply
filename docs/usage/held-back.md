---
icon: lucide/pause
---

# What is held back

Nothing is applied quietly past a hold, and nothing is dropped quietly either. Whatever is held is
listed at the end of the run with its reason:

```console
Held back:
  ghcr.io/atuinsh/atuin -> 19.0.0 (major, use --major to include it)
  python -> 3.15 (skipped by configuration)
```

The reasons follow.

## Majors

An update Renovate calls `major` waits until you pass `--major`.

This is about a blind spot, not about majors being scary. Renovate can be configured to send some
updates to the dependency dashboard for approval by hand, with `dependencyDashboardApproval`. It
resolves that per package, and the report does not carry the answer. Holding every major is the only
reading that cannot contradict your configuration.

```bash
rnv --major
```

## Updates Renovate would not open yet

An update still waiting out `minimumReleaseAge` carries `pendingChecks` in the report. Renovate
would not open a pull request for it yet, so this does not apply it yet either.

A security fix bypasses that hold in Renovate, so it bypasses this one too. An update flagged
`isVulnerabilityAlert` is applied even while it is pending.

## Renames

When Renovate wants to replace a dependency with a different one, the report carries a `newName`.
That is not a version bump, and this tool does not write it. Do it by hand.

## Lock file updates

Sometimes the range in the manifest already allows the new version. An npm `^2.49.0` covers
`2.49.1`, so nothing in `package.json` changes and only the lock file beside it moves. Renovate
marks these `isLockfileUpdate`.

There is no text to replace, so moving the lock file takes the package manager. For a
`package-lock.json` beside the `package.json`, this tool runs npm and applies the update. See
[Lock file updates with npm](../how-it-works/commits.md#lock-file-updates-with-npm).

An npm alias, such as `"foo": "npm:bar@^1.0.0"`, is also held. To move an alias, npm needs a command
that names both the alias and the package. This tool does not run that form.

Any other lock file update is held, with this reason:

```console
Held back:
  pydantic -> 2.13.1 (a lock file update this tool cannot make, the manifest does not change)
```

If git does not track the lock file, for example because `.gitignore` lists it, the update is held.
A commit cannot carry that lock file:

```console
Held back:
  osls -> 4.5.0 (a lock file update, and git does not track the lock file)
```

`--no-lock` holds every lock file update, because npm does not run. The reason then names the flag:

```console
Held back:
  osls -> 4.5.0 (a lock file update, which --no-lock leaves to you)
```

## Updates that do not lock

Sometimes the new floor in `pyproject.toml` conflicts with another dependency. For example, a
package you depend on caps `opentelemetry-sdk` below the version Renovate proposes. Then `uv lock`
finds no solution, and Renovate's own pull request would fail its lock file update. For npm, the
same case is a peer dependency conflict, which npm reports as `ERESOLVE`.

The group is undone: every file it edited is put back as it was, the lock file included. The package
manager's explanation is printed, and the updates are listed with this reason:

```console
renovate-apply: deps: update opentelemetry-python-monorepo does not lock, undone. uv lock failed in .:
error: No solution found when resolving dependencies
...

Held back:
  opentelemetry-sdk -> >=1.45.0 (the lock file finds no solution for it, see above)
```

The run goes on with the other groups and does not fail because of this one. Run it again when the
dependency that blocks the update releases a version that allows it.

A dry run does not refresh lock files, so it lists such a group as one it would apply. Any other
failure of the package manager, for example a network error, fails the group instead. The group is
still undone.

## One line that two managers found

A custom regex manager in your Renovate configuration can match a line that a built-in manager also
reads. For example, a regex manager and the `github-actions` manager can both read the
`wranglerVersion` input of `cloudflare/wrangler-action`. Renovate then reports the line twice, on
two branches.

If both updates write the same new text, the first one is applied and the second one is held:

```console
Held back:
  wrangler -> 4.148.0 (the same edit as the github-actions update, in renovate/github-actions-(minor+patch))
```

If the two updates write different text, both are kept. The second one then fails, because the first
one changed the line.

## A new version and a new digest in one branch

A dependency pinned to a digest can have two updates on the same branch: a new version, and a new
digest of the version it has now. Both rewrite the same text, so only one of them can be applied.

Renovate keeps the first update of the branch and drops the other ("Ignoring upgrade collision").
This tool does the same, and lists the dropped one:

```console
Held back:
  docker -> 29.8.2-cli, new digest (renovate/stack-images updates the same text to 29.9.0-cli)
```

## One line that two branches update

With `--major`, one line can have two updates on two branches: the next minor and the next major.
For example, `serverless-domain-manager` at `10.3.1` can go to `10.5.1` and to `11.0.1`. Renovate
opens two pull requests. After you merge the minor one, Renovate rebases the major one onto it.

This tool does the same. The minor is committed first. Then the major is applied to the line that
the minor wrote, and it is committed as a second step:

```console
applied  deps: update non-major
    serverless-domain-manager  10.3.1 -> 10.5.1
applied  deps: update serverless-domain-manager to 11.0.1
    serverless-domain-manager  10.5.1 -> 11.0.1
```

The other steps of one line follow each other in the same way. For example, Renovate opens one
branch for each major with `separateMultipleMajor`, and a patch branch before the minor branch with
`separateMinorPatch`. Each step is applied to the line that the step before it wrote.

A lock file update does not change the line in `package.json`, so it is not part of these steps.

If the group of the minor fails or is held, the major has no line to apply to. The major is then
held too:

```console
Held back:
  serverless-domain-manager -> 11.0.1 (rebased onto renovate/non-major, which was not applied)
```

Any other pair of updates to one line on two branches has no order to follow. For example, the major
comes before the minor in the report, or the second update is a new digest of the current version.
The first update is applied, and the second is held:

```console
Held back:
  serverless-domain-manager -> 10.5.1 (renovate/major-serverless-domain-manager updates the same text to 11.0.1)
```

## Anything named in `--skip`

Your answer to the same blind spot as majors, for updates that are not majors:

```bash
rnv --skip python
```

A repository that keeps `requires-python` on the dependency dashboard writes this once in
`pyproject.toml` and stops being asked:

```toml
[tool.renovate-apply]
skip = ["python"]
```

!!! note

    `--skip` is matched here, against the report. It does not reach Renovate, so a skipped dependency is
    still looked up. It is held at the last moment, and listed.
