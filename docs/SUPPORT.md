---
layout: page
title: CLROOM support
description: CLROOM support guidance for non-sensitive bugs, version-specific docs, safe help requests, and security issues that belong in the private reporting process.
permalink: /support/
nav_title: Support
---

# Support

Clean Room Launcher (CLROOM) is a small open-source project. There is no paid support contract or guaranteed response-time SLA.

## Before asking for help

Start with the public documentation:

- [Install CLROOM](docs/install.md)
- [Clean-launch walkthrough](docs/demo.md)
- [Problem and search-language index](docs/problem-index.md)
- [When to use CLROOM — and when not to](docs/when-to-use-clroom.md)
- [Codex and CLROOM](docs/codex.md)
- [Claude Code and CLROOM](docs/claude-code.md)
- [Current limitations](docs/limitations.md)
- [Verify a CLROOM release](docs/verify-release.md)

If you do not know the provider's exact term, use the problem index first. It maps common symptoms and alternate wording to the canonical technical answer.

## Bug reports and usage questions

Use [GitHub Issues](https://github.com/y-sor/clean-room-launcher/issues) for non-sensitive bugs, documentation gaps, compatibility questions, and feature requests.

For a useful technical report, include only the minimum safe information needed to reproduce the problem:

- CLROOM version;
- macOS / architecture;
- Codex or Claude Code version;
- exact CLROOM command with secrets removed;
- expected behavior;
- observed behavior;
- a minimal reproduction if available.

Do not paste credentials, provider tokens, prompts, transcripts, private repository contents, unrestricted environment dumps, or home-directory listings.

## Security vulnerabilities

Do **not** put vulnerability details or sensitive reproductions in a public issue.

Use the process in [SECURITY.md](https://github.com/y-sor/clean-room-launcher/blob/main/SECURITY.md) and the repository [Security policy](https://github.com/y-sor/clean-room-launcher/security/policy).

## Provider behavior

CLROOM support claims are version-, platform-, and path-specific. Before reporting a provider difference, check the current provider page and [configuration matrix](docs/configuration-matrix.md).

A newly documented Codex or Claude Code capability does not automatically mean CLROOM has qualified that capability.

## Contributions

For code or documentation changes, use [CONTRIBUTING.md](https://github.com/y-sor/clean-room-launcher/blob/main/CONTRIBUTING.md). Substantial product, provider, platform, release-path, or security-boundary changes should start with an Issue so scope and evidence can be discussed before implementation.
