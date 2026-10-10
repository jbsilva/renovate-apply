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

There is no text to replace, so there is nothing for this tool to do. Moving the lock file takes
that package manager. The one exception is `uv.lock`, which is refreshed after an edit to its own
`pyproject.toml`. See [Commits and lock files](../how-it-works/commits.md#lock-files).

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
