---
layout: page
title: Claude Code and CLROOM
description: Compare CLROOM with Claude Code settings, CLAUDE.md, skills, auto-memory, MCP/tool controls, safe/bare modes, subagents, and native alternatives.
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
| External ancestor | `AGENTS.md` / `.claude/AGENTS.md` above the nearest Git worktree root, or above the launch directory outside Git | Restricted for this launch |
| Project | `CLAUDE.md` / `AGENTS.md` at or below that project boundary, including repo-root instructions when launched from a nested directory | Retained |
| Project local | `CLAUDE.local.md`, `.claude/settings.local.json` | Retained |
| Managed / organization | managed settings delivered through supported admin mechanisms | Must remain authoritative |

Current CLROOM source launches Claude with `--setting-sources project,local`, `--strict-mcp-config`, fail-closed sandbox settings, disabled auto-memory, and additional filesystem controls for known personal-global roots. Claude Code 2.1.289 also ships a built-in `agents-md` instruction surface. For this launch, CLROOM treats the nearest real Git `.git` marker as the project instruction boundary (or the launch directory when no such marker exists): `AGENTS.md` and `.claude/AGENTS.md` above that boundary are blocked, while repo-root and nested project instructions remain available.

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

## Auto-memory vs a CLROOM clean launch

Claude Code auto-memory is persistent provider-owned state. It can be useful, but it is a different scope from project instructions, user settings, skills, plugins, and MCP configuration.

The current qualified CLROOM Claude path disables auto-memory for the launch. Use that as a diagnostic boundary when you want to ask whether old or shared memory is contributing to the current behavior while leaving the provider's stored memory files untouched.

CLROOM does **not** delete, edit, expire, synchronize, or repair Claude's `MEMORY.md` state. If the goal is to inspect or manage Claude memory itself, prefer Claude's native memory controls. If the goal is a comparison launch where auto-memory does not participate, CLROOM provides that narrower qualified boundary.

## Native Claude skill controls vs CLROOM

Claude Code now exposes useful native controls for individual skills. Anthropic documents `skillOverrides` states such as `name-only`, `user-invocable-only`, and `off`; `disable-model-invocation: true` prevents Claude from auto-invoking a skill and removes its description from the normal skill listing context; and `/skill-doctor` reports skill context cost and usage. Plugin-provided skills are managed separately rather than through `skillOverrides`.

Use those native controls when they solve the actual problem. CLROOM is aimed at a different launch-level boundary: start a session without the ordinary personal-global instruction/skill set participating by default, then admit selected personal-global skills for that launch without rewriting the normal provider setup.

Plugin-provided skills are a distinct case: current Claude Code documentation says `skillOverrides` does not apply to them. Use Claude's plugin manager/evaluation path for plugin-skill questions rather than assuming personal/project skill controls apply inside a plugin.

## Native Claude MCP tool search vs CLROOM

Claude Code now defers MCP tool definitions through native Tool Search on supported provider/model paths. Only tool names and server instructions need to load at session start, and threshold modes such as `ENABLE_TOOL_SEARCH=auto` can switch to deferral when tool definitions consume enough of the context window.

Use that native mechanism when the problem is **tool-definition context overhead inside Claude Code**. CLROOM does not replace Claude's MCP discovery engine and does not claim that selecting fewer CLROOM inputs is a universal substitute for provider-native Tool Search.

CLROOM remains relevant when the boundary is different: which supported personal-global launch inputs participate at all, without rewriting the developer's ordinary setup.

## Native Claude subagent MCP scoping vs CLROOM

Claude Code subagent definitions can narrow inherited tools with `tools` or `disallowedTools`, including MCP server-level patterns. They can also declare `mcpServers`; inline servers can be connected for that subagent and kept out of the parent conversation.

Use those native controls when the problem is **per-subagent tool or MCP scope inside one Claude session**. CLROOM controls top-level launches it owns; it does not rewrite provider-owned subagent definitions. An external runner can still start separate top-level CLROOM processes when each worker needs an independent CLROOM launch boundary.

## Select one installed whole plugin

CLROOM includes one bounded whole-plugin selector:

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

The qualified activation path is intentionally narrower than Claude's full
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

The ordinary clean launch and this whole-plugin path are exactly qualified on
the current stable Claude Code `2.1.289` for macOS Apple Silicon. Release
qualification includes the provider's built-in `agents-md` behavior: AGENTS
instructions above the Git project boundary must stay outside the launch while
repo-root and nested project AGENTS remain available even when Claude starts
from a subdirectory. Qualification fails closed if the npm stable tag moves before
the candidate is tagged. The ordinary parser/runtime minimum remains `2.1.223+`.

This Claude slice still does not add standalone MCP resource activation,
`--with=all`, installation/update/removal, or component-level selection.
CLROOM presets can reuse already-supported top-level Claude launch inputs, but they do not add Claude subagent/inner-session controls or widen plugin qualification. Codex whole-plugin activation is a separate provider-specific
path; it does not reuse Claude's `--plugin-dir` mechanism.

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
- [Claude Code commands (`/memory`, `/mcp`, `/context`, and diagnostics)](https://code.claude.com/docs/en/commands)
- [Claude Code settings](https://code.claude.com/docs/en/settings)
- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code documentation index](https://code.claude.com/docs/llms.txt)

Last verified against current Anthropic documentation: **2026-10-06**.