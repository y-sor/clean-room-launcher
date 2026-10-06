---
layout: page
title: When to use CLROOM — and when not to
description: Choose between CLROOM and native Codex or Claude Code controls for clean sessions, skills, settings, subagent tools, CODEX_HOME, plugins, and MCP.
permalink: /when-to-use-clroom/
nav_title: When to use
---
The simplest correct option should win.

If you want the short human explanation first, read [Why Clean Room Launcher (CLROOM) exists](why-clroom.md).

If you arrived with a symptom or half-remembered term rather than the product name, start with the [coding-agent configuration problem index](problem-index.md).

## Pick the narrowest control that solves the problem

| Need | Start with |
| --- | --- |
| Hide, narrow, or diagnose one or a few Claude skills | Claude `skillOverrides`, `disable-model-invocation`, `/skills`, and `/skill-doctor` |
| Broad Claude troubleshooting with customizations disabled | Claude `--safe-mode` |
| Minimal scripted Claude invocation | Claude `--bare` |
| Choose which normal Claude settings scopes participate | Claude `--setting-sources` |
| Inspect, edit, enable, or disable Claude auto-memory | Claude `/memory` and native memory controls |
| Compare behavior with Claude auto-memory absent from the launch while leaving stored memory untouched | CLROOM's qualified Claude clean path |
| Give a Claude subagent a narrower tool set or MCP servers of its own | Claude subagent `tools`, `disallowedTools`, and `mcpServers` |
| Suppress normal Codex user configuration for one non-interactive task | Native `codex exec --ignore-user-config` |
| Maintain a persistent alternate provider setup | `CODEX_HOME`, Claude configuration directory, or provider-native profiles/settings |
| Start a repeatable cleaner launch while preserving the project-side context CLROOM is designed to retain | CLROOM |
| Select and inspect the currently qualified one-plugin / one-stdio-MCP Codex launch without rewriting persistent Codex configuration | CLROOM's bounded Codex resource path |

The table is a routing aid, not a claim that the providers expose identical scope models. Use the provider-specific pages for exact behavior and version-qualified support.

## Use CLROOM when one launch should not inherit unrelated personal-global work

CLROOM is useful when:

- personal-global instructions written for other work should not participate in the current coding-agent session;
- only selected personal-global skills should be admitted for a particular launch;
- one persistent personal setup does not fit every repository, project, or workflow;
- you want to compare normal behavior with a repeatable cleaner baseline without deleting or renaming your normal configuration;
- you are testing whether a skill actually changed the result, rather than another installed skill or personal-global instruction changing it;
- you want reusable named skill sets for different kinds of work.

For a complete skill-author testing workflow, see [Use cases](use-cases.md). To create, edit, or combine reusable groups, see [Skill sets](skill-sets.md).

The normal setup remains on disk. CLROOM changes the launch, not the developer's permanent configuration.

## Use Claude Code native skill visibility controls when one skill is the whole problem

Current Claude Code provides native per-skill controls such as `skillOverrides`, `disable-model-invocation`, and `/skill-doctor`. If you only need to hide, narrow, or diagnose one or a few Claude skills, prefer those native controls.

CLROOM is useful when the requirement is broader and launch-specific: start without the ordinary personal-global instruction/skill layer participating by default, keep the project-side context CLROOM is designed to retain, and deliberately admit the personal-global skills needed for this run.

## Use Claude Code `--safe-mode` first when you want broad customization disabled

Claude Code has a native `--safe-mode` specifically for troubleshooting broken customizations. Anthropic documents that it disables a broad set of customizations for the session.

If that is exactly the goal, use the native feature.

CLROOM targets a different selective case: relevant project/local configuration can remain useful while ordinary personal-global inputs are kept out of the CLROOM launch and selected personal-global skills can be admitted deliberately.

See [Claude Code and CLROOM](claude-code.md).

## Use Claude Code `--bare` first for a minimal scripted Claude invocation

Anthropic documents `--bare` as a minimal mode that skips automatic discovery of hooks, skills, plugins, MCP servers, auto memory, and `CLAUDE.md`.

If a stripped-down scripted call is what you need, use the native feature.

CLROOM is aimed at repeatable selective composition for normal work, not at replacing every native minimal mode.

## Use native Claude `--setting-sources` when that alone solves the problem

Claude Code can choose filesystem settings sources for a session. A direct `--setting-sources` invocation may be enough when the only requirement is selecting which normal settings scopes participate.

CLROOM adds provider-specific clean defaults, known filesystem controls, a selected-global-skill workflow, and its own launch summary. Read the provider page and limitations before assuming those differences matter to your case.

## Use Claude subagent tool/MCP controls when the boundary is inside one Claude session

Current Claude Code can narrow inherited subagent tools with `tools` or `disallowedTools`, including MCP server-level patterns, and can define MCP servers in a subagent's `mcpServers` field. An inline subagent MCP can stay out of the parent conversation entirely.

Use those native controls when the actual requirement is **"this Claude subagent should get these tools or this MCP server."** They are provider-native controls rather than a CLROOM-qualified inner-session contract; current provider behavior can vary by Claude version, agent type, and execution mode, so verify the exact current Claude path when MCP inheritance itself is the problem.

CLROOM does not rewrite provider-owned subagent definitions. Use separate CLROOM top-level processes when an external runner owns the workers and each process needs its own CLROOM clean/selective boundary.

## Use another `CODEX_HOME`, Claude config directory, or provider profile when you want a persistent alternate setup

A second persistent provider configuration can be the right answer. For Claude Code, `CLAUDE_CONFIG_DIR` changes the configuration directory, but it should not be treated as a universal isolation guarantee; current provider behavior and known edge cases still matter.

CLROOM is more useful when you do **not** want to maintain another normal configuration and instead want a repeatable per-launch choice.

## If company policy already solves the problem, do not invent a second policy layer

CLROOM is not a company-policy bypass.

If organization-managed policy already prevents the personal customization you are trying to exclude, CLROOM may add little to ordinary daily work. Managed/admin policy must remain authoritative.

## Why unrelated instructions can cost more than their text size

The important cost is not necessarily the raw size of another instruction or skill description.

A conflict can compound:

`extra/conflicting instruction → wrong decision → wrong implementation path → rework → another review/fix cycle → more tokens + more engineering time`

A cleaner launch is useful when it reduces that avoidable source of variation.

## Exact provider mechanics

- [Claude Code and CLROOM](claude-code.md)
- [Codex and CLROOM](codex.md)
- [Configuration matrix](configuration-matrix.md)
- [Current limitations](limitations.md)
