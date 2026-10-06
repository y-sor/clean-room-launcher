---
layout: page
title: Why Clean Room Launcher (CLROOM) exists
description: Why coding-agent sessions become harder to reason about as global instructions, skills, plugins, and tools grow, and where CLROOM's clean/selective launch helps.
permalink: /why-clroom/
nav_title: Why CLROOM
---
As a coding-agent setup gets more powerful, it gets harder to know what actually influenced a session.

You add global instructions because they help. You install skills because they help. Different work starts needing different rules, tools, and skill sets.

Then one day the question changes from:

**“Can my agent do this?”**

to:

**“Why did my agent do that?”**

Was it the project instructions? A global instruction written for different work? Another installed skill? A hook, plugin, or provider setting?

CLROOM started with a simple testing problem: **run the real coding agent from a cleaner baseline, then add back only what this session actually needs.**

## Start clean. Add back only what this session needs.

With Clean Room Launcher (CLROOM), you can launch the installed Codex or Claude Code CLI and explicitly choose the personal-global skills you want for that launch.

For example:

```sh
clroom codex exec --skill-set=@my-skills
```

or:

```sh
clroom claude --skill-set=@my-skills
```

The normal provider setup is not rewritten just to get that cleaner launch.

On the current supported path, CLROOM is designed to keep known unrelated personal-global instructions and unselected personal-global skills out of the launch while preserving the project-side configuration it is designed to retain.

The exact mechanics differ between Codex and Claude Code, so the provider pages document them separately:

- [Claude Code and CLROOM](claude-code.md)
- [Codex and CLROOM](codex.md)

## Why this matters beyond skill testing

Testing one skill was the first use case.

The broader problem is that one persistent personal setup rarely fits every kind of work.

A rule that helps on one repository can be wrong for another. A skill useful for planning does not need to participate in every bug fix. An MVP workflow should not automatically inherit every rule used for enterprise work, and enterprise work should not silently inherit shortcuts written for an MVP.

When global instructions conflict with project instructions, development costs can multiply:

`extra/conflicting instruction → wrong decision → wrong implementation path → rework → another review/fix cycle → more tokens + more engineering time`

CLROOM turns those personal-global inputs from **automatic** into **deliberate** for the launch.

Nothing has to be deleted or permanently reconfigured. The developer keeps the normal setup and can bring in the global skills that actually belong in that session.

## Inspectable per-run composition, not only skill filtering

On the current qualified Codex path, CLROOM can also admit one already-installed whole plugin and one root-user standalone stdio MCP server in the same interactive launch. Both selections resolve through one typed launch plan, overlapping identities fail closed, and a source change on either side invalidates the whole launch.

Use `clroom inspect codex ...` to inspect the same resolved launch truth without starting the real provider session. The human and JSON views expose selected identities, decisions, qualification state, and admitted environment-variable names while keeping secret values, private source paths, and provider argument values out of the output.

This is deliberately bounded rather than a promise of universal plugin/MCP composition. See [Codex and CLROOM](codex.md) and [Current limitations](limitations.md) for the exact supported surface.

## Reusable skill sets instead of rebuilding the setup

Selected skills do not have to be chosen one by one every time.

CLROOM supports reusable named skill sets, so different working modes can have different combinations, for example:

```text
@dev-mvp
@dev-full
@bugfix
@brainstorming
@content
```

That makes the same clean/selective model useful for repeated day-to-day work, not only one-off tests.

## CLROOM is not the only answer

Sometimes the provider already has the simpler native option.

Claude Code has native modes and settings controls such as `--safe-mode`, `--bare`, `--setting-sources`, and alternate configuration directories. Codex has its own configuration, profiles, `CODEX_HOME`, and instruction/skill scopes.

If one of those solves your problem cleanly, use it.

CLROOM is useful in the middle: **you want a repeatable cleaner launch, you still want the relevant project-side setup, and you want personal-global inputs to be deliberate rather than automatic.**

See [When to use CLROOM — and when not to](when-to-use-clroom.md).

## What CLROOM does not claim

CLROOM is not a VM or container sandbox. It does not claim complete home-directory isolation, removal of every provider-owned global input, or a way around organization-managed policy.

Those limits are documented openly:

- [Current limitations](limitations.md)
- [Threat model](threat-model.md)
- [Configuration matrix](configuration-matrix.md)

## Current scope

CLROOM is open source under MPL-2.0.

The current release supports Codex and Claude Code on macOS / Apple
Silicon. For current provider/version details, use the repository and
installation/limitations pages rather than copying a version number from an
old article.

- [GitHub repository](https://github.com/y-sor/clean-room-launcher)
- [Installation](install.md)
- [Find your problem in the configuration problem index](problem-index.md)
