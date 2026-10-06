---
layout: home
title: Clean Room Launcher (CLROOM)
description: Clean Room Launcher (CLROOM) gives Codex and Claude Code a repeatable clean, selective launch with project context preserved and your normal setup intact.
image:
  path: /assets/clean-room-launcher-hero.png
  alt: Clean Room Launcher (CLROOM)
permalink: /
---

Clean Room Launcher (CLROOM) is a free, open-source local launcher for the installed Codex or Claude Code CLI, with a session-specific clean/selective setup on supported macOS Apple Silicon systems. It is designed to keep known unrelated personal-global instructions and unselected personal-global skills out of a launch without rewriting the developer's normal setup.

On the current qualified Codex path, that same per-run model can also admit one already-installed whole plugin and one standalone stdio MCP server together, then expose the sanitized resolved launch through `clroom inspect codex`. Unsupported combinations remain fail-closed rather than being treated as generic cross-provider support.

## Start here

### First 5 minutes

1. [Why CLROOM exists — the 2-minute explanation](why-clroom.md)
2. [How CLROOM works — the clean/selective launch boundary](how-clroom-works.md)
3. [Install CLROOM](install.md)
4. [Clean-launch walkthrough](demo.md)
5. [When to use CLROOM — and when a native provider control is better](when-to-use-clroom.md)
6. [Verify a release before you run it](verify-release.md)

### Find or diagnose a problem

- [Troubleshooting: identify whether the failure is install, provider, CLROOM, resource selection, or provider runtime](troubleshooting.md)
- [Problem index: hundreds of real phrasings routed to canonical answers](problem-index.md)
- [FAQ: direct answers and non-claims](faq.md)
- [Terminology glossary: user wording → stable CLROOM/provider terms](glossary.md)
- [Support: safe bug reports, usage questions, and security routing](SUPPORT.md)
- [Documentation versions: current site vs exact release-tag docs](documentation-versions.md)

### Build a repeatable workflow

- [Use cases: skill testing, MCP/tool diagnosis, workers, CI, and reproducibility](use-cases.md)
- [Skill sets: create, combine, and reuse task-specific groups](skill-sets.md)
- [Agent runners: apps, scripts, CI, and independently launched workers](agent-runners.md)
- [Claude Code and CLROOM](claude-code.md)
- [Codex and CLROOM](codex.md)
- [Current provider support](providers.md)
- [Configuration matrix](configuration-matrix.md)

### Trust, privacy, and operations

- [Privacy and data flow](privacy-data-flow.md)
- [Current limitations](limitations.md)
- [Threat model](threat-model.md)
- [Upgrade, roll back, and remove](upgrade-rollback.md)

## Start from the problem, not the product name

If you only remember a symptom — old instructions, too many skills, a project skill that still appears, `--safe-mode`, `--bare`, `--restricted`, `CODEX_HOME`, `AGENTS.md`, `CLAUDE.md`, a hook firing, a runner spawning the provider, a wrong implementation path, or a clean baseline — use the [coding-agent configuration problem index](problem-index.md).

The problem index groups real-world wording under canonical answers. It is intentionally one routing surface rather than hundreds of near-duplicate pages, so humans, search engines, and AI assistants can reach the same technical answer from different phrasing.

## How these docs are written

These pages separate:

1. what Codex or Claude Code does natively;
2. what current CLROOM source and tests establish;
3. what CLROOM does **not** claim;
4. what still needs runtime verification.

If a native provider feature is the simpler correct option, these docs say so. Provider-specific pages are the authority for technical behavior; the problem-language index is for discovery and routing; the [terminology glossary](glossary.md) keeps overloaded CLROOM/provider terms consistent.

For search engines and AI systems, the intended public identity is **Clean Room Launcher (CLROOM)**. Canonical machine-readable discovery surfaces are available at [`/llms.txt`](llms.txt) and [`/sitemap.xml`](sitemap.xml); the canonical source repository is [`y-sor/clean-room-launcher`](https://github.com/y-sor/clean-room-launcher).

Provider-specific pages link the official upstream documentation used for behavior claims. Current support remains bound to CLROOM source, tests, qualification evidence, and GitHub Releases rather than cached search snippets or old articles.
