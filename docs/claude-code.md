---
layout: page
title: Claude Code and CLROOM
description: How Clean Room Launcher (CLROOM) relates to Claude Code user, project, local and managed settings, CLAUDE.md, skills, safe mode, bare mode, and setting sources.
permalink: /claude-code/
nav_title: Claude Code
---
CLROOM does not replace Claude Code. It launches the installed `claude` CLI.

This page focuses on one question: **which Claude Code configuration sources are relevant to a CLROOM launch, and what should you use natively instead when CLROOM is unnecessary?**

## Claude Code has multiple configuration scopes

Anthropic documents user, project, project-local, and managed organization settings. Those scopes are not interchangeable.

A simplified view:

| Claude Code scope | Examples | Current CLROOM direction |
| --- | --- | --- |
| User | `~/.claude/settings.json`, user `CLAUDE.md`, user rules/skills | Ordinary user settings source omitted; known personal-global instruction/skill roots restricted |
| Project | project `CLAUDE.md`, `.claude/settings.json`, project rules/skills | Retained |
| Project local | `CLAUDE.local.md`, `.claude/settings.local.json` | Retained |
| Managed / organization | managed settings delivered through supported admin mechanisms | Must remain authoritative |

Current CLROOM source launches Claude with `--setting-sources project,local`, `--strict-mcp-config`, fail-closed sandbox settings, disabled auto-memory, and additional filesystem controls for known personal-global roots.

The `--strict-mcp-config` flag is intentionally stricter than the project-settings row above. For the current CLROOM launch, ordinary project, user, and other ambient MCP configurations are not loaded. CLROOM does not synthesize an `--mcp-config`; Claude considers MCP servers only when you explicitly supply its own `--mcp-config` argument for that launch. This is an explicit current limitation, not a claim that project MCP configuration is preserved.

Selected personal-global skills are exposed through a private temporary projection and `--add-dir`.

Individual symlinked skill entries from a shared library are supported when
their canonical target is a valid, non-protected skill directory. Unselected
targets remain denied, duplicate names follow source precedence, and links
into provider configuration or credential paths are refused. A root symlink is
not treated as authority for an entire arbitrary tree.

Provider-owned subagents and agent-team teammates follow Claude Code's own
inheritance rules; a top-level CLROOM skill selection does not configure every
internal teammate independently.

For practical workflows, see [Use cases](use-cases.md) and [Skill sets](skill-sets.md).

## v0.4.0: select one installed whole plugin

The v0.4.0 source adds one bounded whole-plugin selector:

```sh
claude plugin list
clroom claude --with=plugin:plugin-name@marketplace-name
```

The selector takes the provider-native qualified plugin ID. It admits exactly one
already-installed Claude plugin for this launch. CLROOM does not install or
update the plugin, and it does not change persistent provider enablement or
configuration.

For this path CLROOM resolves the active installed plugin root, requires the
exact qualified provider tuple, revalidates the root immediately around launch,
reopens only that selected root read-only in the outer macOS isolation policy,
and delegates activation to Claude's session-only `--plugin-dir` interface.
Claude documents `--plugin-dir` as loading a plugin for the current session
only.

Whole-plugin still means the provider-native bundle is atomic: CLROOM either
admits the qualified bundle root or refuses the plugin; it does not extract
individual files or components.

The initial v0.4.0 qualification is intentionally narrower than Claude's full
plugin format. Inventory follows Claude provider semantics broadly enough to
observe provider-visible plugin surfaces, but activation requires a matching
`.claude-plugin/plugin.json` identity and only the default one-level
`skills/<name>/SKILL.md` layout. Manifestless plugins, root `SKILL.md`
single-skill plugins, custom skill paths, slash commands, hooks, MCP servers,
agents, LSP servers, background monitors, plugin executables, or plugin settings
remain observable but fail closed for activation. Real-provider testing
showed why this boundary is necessary: a hook-bearing plugin can load through
`--plugin-dir` while its hook still depends on provider-global runtime state
under `~/.claude`, which the clean launch intentionally keeps unavailable.
CLROOM does not reopen that ambient provider directory merely to make such a
plugin run.

While a CLROOM resource selection is active, raw `--plugin-dir` and
`--plugin-url` arguments are refused to avoid two competing activation
authorities. More than one selected whole plugin is also refused.

The exact qualification target for this activation path is Claude Code
`2.1.273` on macOS Apple Silicon. Other provider tuples fail closed for plugin
activation. The baseline interactive clean-launch exact qualification remains
Claude Code `2.1.272`; the ordinary parser/runtime minimum remains
`2.1.223+`.

This slice does not add Codex plugin activation, MCP resource activation,
`--with=all`, presets, installation/update/removal, or component-level
selection.

## Does CLROOM remove every Claude global or provider-owned input?

**No.**

Anthropic documents some global configuration/state outside the ordinary filesystem settings-source model, including keys in `~/.claude.json`. Current CLROOM does not blanket-block that sibling file.

Do not translate “ordinary user settings are omitted” into “all Claude global configuration is gone.”

CLROOM also does not claim complete home-directory isolation.

## Does CLROOM bypass organization-managed Claude Code policy?

**No. It must not.**

Anthropic documents managed settings as the highest normal settings tier, with specific exceptions that can only make security-sensitive values stricter.

CLROOM's product invariant is that organization-managed policy remains authoritative.

There is still a runtime-verification gap around every possible interaction between managed customization restrictions and a selected skill exposed through an additional directory. Until that matrix is proven, do not claim universal enterprise-policy compatibility.

## `claude --safe-mode` vs CLROOM

Anthropic documents `--safe-mode` as a troubleshooting mode that disables a broad set of customizations, including `CLAUDE.md`, skills, plugins, hooks, MCP servers, commands/agents, styles/workflows, and auto-memory. Managed settings policy still applies, with provider-documented exceptions for which managed customizations do or do not load.

Use it when broad clean troubleshooting is what you want.

CLROOM targets a narrower selective workflow: keep relevant project/local work, omit ordinary personal-global sources, and deliberately admit selected personal-global skills.

## `claude --bare` vs CLROOM

Anthropic documents `--bare` as a minimal mode for faster scripted calls. It skips auto-discovery of hooks, skills, plugins, MCP servers, auto memory, and `CLAUDE.md`.

That is a strong native option for minimal invocation.

CLROOM is intended for a different workflow: a repeatable selective session that does not require rewriting the developer's normal setup.

## `--setting-sources project,local` vs CLROOM

This native Claude flag is part of CLROOM's current implementation, but you can use it directly yourself.

Use the native flag alone if it completely solves the problem.

CLROOM additionally applies its provider-specific launch controls and selected-skill workflow. Those are implementation details, not a reason to use CLROOM when the native flag is already sufficient.

## `claude --restricted` vs CLROOM

Claude Code `--restricted` is available from Claude Code `2.1.248+`. It is a
stronger evaluation and shared-machine restriction mode. Use it when you need
that broad native restriction.

CLROOM serves a different purpose: a selective project/local-preserving
workflow that omits ordinary personal-global sources and admits explicitly
selected skills. This documentation addition does not raise CLROOM's
qualified minimum Claude Code version.

## Why `--add-dir` matters for selected skills

Anthropic documents skills and commands as an exception to the usual additional-directory rule: `.claude/skills/` and `.claude/commands/` in an added directory can be discovered automatically.

CLROOM uses that provider behavior for its private selected-skill projection.

This is also why managed-policy interactions around selected skills require careful runtime testing rather than assumptions.

## Official Anthropic sources

- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Claude Code settings](https://code.claude.com/docs/en/settings)
- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Claude Code documentation index](https://code.claude.com/docs/llms.txt)

Last verified against current Anthropic documentation: **2026-09-18**.
