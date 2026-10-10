# Security Policy

`renovate-apply` is a local command-line tool maintained by one person in their spare time. It runs
Renovate over a working copy, edits the files Renovate's report describes, and commits them. This
document explains how to report a security problem, what I can promise in return, and where the line
sits between bugs in this tool and choices you make when you run it.

This is a solo, unpaid, hobby project under the MIT license. There is no company, no security team,
no service-level agreement, and no bug bounty. I will still take security reports seriously and do
my best to fix real problems quickly.

## Supported Versions

`renovate-apply` is pre-1.0 software and follows Semantic Versioning. Security fixes ship for the
latest released line only. Upgrading is how you get the fix.

| Version        | Supported          |
| -------------- | ------------------ |
| 0.1.0 (latest) | :white_check_mark: |
| < 0.1.0        | :x:                |

## Reporting a Vulnerability

Report privately through GitHub's
[security advisories](https://github.com/jbsilva/renovate-apply/security/advisories/new). Please do
not open a public issue for a vulnerability.

Tell me what you did, what happened, and what you expected. A reproduction is worth more than a
scanner finding. I will confirm receipt within a week and tell you what I intend to do about it.

## What is in scope

This tool writes files and makes commits on the machine that runs it. In scope:

- An edit that lands somewhere the Renovate report did not describe, or that writes a version other
  than the one reported.
- A commit that includes files the run did not write.
- The GitHub token leaking anywhere: into argv, into a log line, into an error message, into a
  commit.
- Anything in this package that executes a string as a shell command.

## What is not in scope

- **What Renovate itself resolves.** This tool applies what Renovate reports. A compromised
  registry, a malicious tag, or a Renovate configuration that points at an untrusted source is
  upstream of it. Review the diff before you push, exactly as you would review a Renovate pull
  request.
- **Running it against a repository you do not trust.** Renovate executes that repository's
  configuration. This tool is no safer than running `renovate --platform=local` there yourself.
- **Your git hooks.** They run on every commit, by design, with whatever they do.
- **A token you put on the command line yourself.** `--token` is argv, which every process on the
  machine can read, and it lands in your shell history. Set `GITHUB_TOKEN` in the environment, or
  log in with `gh` and pass nothing, and neither happens.
