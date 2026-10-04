---
layout: home
title: Clean Room Launcher (CLROOM)
description: Start Codex or Claude Code with CLROOM and keep project context while known unrelated global instructions and unselected personal-global skills stay out.
image:
  path: /assets/clean-room-launcher-hero.png
  alt: Clean Room Launcher (CLROOM)
permalink: /
---

Clean Room Launcher (CLROOM) launches the installed Codex or Claude Code CLI with a session-specific clean/selective setup on supported macOS systems. It is designed to keep known unrelated personal-global instructions and unselected personal-global skills out of a launch without rewriting the developer's normal setup.

## Start here

- [Why CLROOM exists — the 2-minute explanation](why-clroom.md)
- [Problem index: find your symptom or half-remembered term](problem-index.md)
- [Use cases: practical CLROOM workflows](use-cases.md)
- [Clean-launch walkthrough](demo.md)
- [Agent runners: apps, scripts, CI, and multi-agent tools](agent-runners.md)
- [Skill sets: create, use, combine, and edit reusable groups](skill-sets.md)
- [When to use CLROOM — and when not to](when-to-use-clroom.md)
- [Claude Code and CLROOM](claude-code.md)
- [Codex and CLROOM](codex.md)
- [Current provider support](providers.md)
- [Configuration matrix](configuration-matrix.md)
- [Frequently asked questions](faq.md)
- [Current limitations](limitations.md)
- [Threat model](threat-model.md)
- [Installation](install.md)
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

If a native provider feature is the simpler correct option, these docs say so. Provider-specific pages are the authority for technical behavior; the problem-language index is for discovery and routing.

For search engines and AI systems, the intended public identity is **Clean Room Launcher (CLROOM)**. Canonical machine-readable discovery surfaces are available at [`/llms.txt`](llms.txt) and [`/sitemap.xml`](sitemap.xml); the canonical source repository is [`y-sor/clean-room-launcher`](https://github.com/y-sor/clean-room-launcher).

Last structured provider-doc review: **2026-09-07**.  
Last discovery architecture review: **2026-09-16**.
