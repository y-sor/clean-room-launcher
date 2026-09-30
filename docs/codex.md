---
layout: page
title: Codex and CLROOM
description: How Clean Room Launcher (CLROOM) relates to Codex global and project AGENTS.md, CODEX_HOME, profiles, skills, and session-specific clean launches.
permalink: /codex/
nav_title: Codex
---
CLROOM does not replace Codex. It launches the installed `codex` CLI.

The clean launch supports both interactive `clroom codex ...` and
non-interactive `clroom codex exec ...` through the existing CLROOM isolation
path. The native `--ignore-user-config` capability is specifically preflighted
and injected for `exec`; its absence on the TUI path is not an interactive
refusal reason.

## Codex can combine global instructions with project instructions

OpenAI documents a global instruction layer under `CODEX_HOME` and a project instruction chain discovered from the repository root toward the current working directory.

That persistent layering is useful for personal defaults.

It also creates the exact class of question CLROOM is designed to make easier to test: **is this behavior coming from the repository and task, or from personal-global instructions that normally join every Codex session?**

Current CLROOM blocks the known global Codex `AGENTS.md` / `AGENTS.override.md` inputs for its clean launch while leaving project context available.

## `CODEX_HOME` vs CLROOM

OpenAI documents `CODEX_HOME` as the way to point Codex at a different home/profile.

Use another `CODEX_HOME` when you want a persistent alternate Codex configuration.

CLROOM is useful when you want a repeatable per-launch clean/selective setup without maintaining a second normal Codex home or rewriting the one you already use.

## Codex profiles vs CLROOM

Codex profiles are useful for reusable configuration values.

That is not automatically the same problem as controlling which personal-global instructions and skill contents can participate in a session.

Use a profile when a profile solves the actual problem. Use CLROOM when the problem is per-launch composition of known personal-global inputs.

## Skills are separate from `AGENTS.md`

OpenAI documents Codex skills at repository, user, admin, and system locations.

For example, the documented user location is `$HOME/.agents/skills`, while admin skills can live under `/etc/codex/skills`.

CLROOM's selected-skill workflow is about personal-global skills admitted for one launch. It should not be described as controlling every admin/system skill or every managed Codex mechanism.

For practical workflows, see [Use cases](use-cases.md) and [Skill sets](skill-sets.md).

## Can I disable a Codex skill natively?

Yes. OpenAI documents skill configuration that can disable local skills persistently.

That may be the simpler answer when the desired change is permanent.

CLROOM is aimed at session-specific selection without editing the normal setup.

## What does `codex exec --ignore-user-config` do?

Codex provides `codex exec --ignore-user-config` as a native non-interactive
way to suppress user configuration for an exec task. Use it directly when
that broad suppression is exactly what you need.

CLROOM preflights this capability and injects the flag for its qualified
`codex exec` path, while preserving its selective filesystem restrictions and
selected-skill inventory. Interactive Codex uses the same existing isolation
path without that exec-only flag.

## v0.4.5: select one installed whole plugin

The v0.4.5 source adds one bounded Codex whole-plugin selector for the
interactive launch path:

```sh
codex plugin list --json
clroom codex --with=plugin:plugin-name@marketplace-name
```

The selector preserves Codex's provider-native plugin ID and admits at most one
already-installed bundle for that launch. CLROOM does not install, update,
remove, or refresh plugins or marketplaces.

For a selected launch, CLROOM revalidates the exact installed source bundle,
copies only that bundle into its existing private shadow `CODEX_HOME`
`PluginStore`, makes the projection non-writable, keeps sibling plugins absent,
and enables only that plugin through session-layer Codex configuration.
`features.apps`, `features.hooks`, and `features.remote_plugin` remain off.
The following ordinary clean launch removes only the verified CLROOM-owned
projection and does not inherit the selected plugin.

Raw Codex configuration/plugin controls such as `-c`, `--config`,
`--profile`, `--enable`, `--disable`, and `--plugin` are refused while a
CLROOM plugin selection is active, so there is only one activation authority.

The exact v0.4.5 qualification target is Codex CLI `0.159.2` on macOS Apple
Silicon. Release qualification uses a task-owned standalone MCP plugin fixture
with the real provider and requires provider startup, MCP `initialize`,
`tools/list` with at least one tool, and a real fixture tool call; `mcp list`
alone is not runtime evidence. A plugin exposing the app-owned `codex_app` MCP
surface is classified `HOST_REQUIRED` and fails closed in standalone CLROOM
rather than emulating the Codex Desktop host. Evidence remains bound to exact
candidate and provider bytes. The ordinary parser/runtime minimum remains
`0.147.0+`.

This whole-plugin path does not add multi-plugin selection, `--with=all`,
component-level plugin surgery, persistent Codex configuration mutation, or
marketplace installation/update behavior.

## v0.4.5: select one standalone stdio MCP server

v0.4.5 adds a separate bounded standalone MCP path:

```sh
clroom codex --with=mcp:my-server
clroom codex --with=mcp:my-server --pass-env=MY_TOKEN
```

The selector resolves exactly one root-user `mcp_servers.<id>` entry from the
ambient Codex `config.toml`. It accepts only stdio definitions with a command,
string arguments, an optional absolute `cwd`, and plain environment-variable
name references. Literal `env` values, structured/remote environment sources,
HTTP transports, OAuth/helper fields, interpolation in identity fields, extra
security-sensitive fields, multiple MCP selectors, and MCP/plugin mixing fail
closed.

Environment references are two-keyed: the MCP definition must name the variable,
and the same name must be explicitly admitted with `--pass-env=NAME`. CLROOM
never stores or prints the value.

The selected definition becomes only a session-layer Codex override; the
ambient file is not copied or rewritten. Immediately before provider birth,
CLROOM starts a no-model Codex app-server preflight with a private temporary
SQLite home and asks `config/read` for the active layers. The probe retains only
layer kind, disabled state, and MCP-key presence. It requires the selected MCP
to exist in `SessionFlags` and refuses any enabled non-session MCP layer. The
ambient selected source is digest-bound and re-read before the main provider
launch.

Release qualification for this path requires exact-candidate macOS real-provider
rehearsal against pinned Codex CLI `0.159.2`. Claude standalone MCP is not part
of this slice.

## Is CLROOM a way around managed Codex controls?

No.

Administrator-managed behavior belongs to a different control plane from the personal-global material CLROOM is designed to filter. CLROOM should never be marketed as a way around organization policy.

## Official OpenAI sources

- [Custom instructions with AGENTS.md](https://developers.openai.com/codex/guides/agents-md/)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
- [Build skills](https://developers.openai.com/codex/skills/)
- [OpenAI developer documentation index](https://developers.openai.com/llms.txt)

The `developers.openai.com` Codex URLs can redirect to their current ChatGPT Learn canonical pages.

Last verified against current OpenAI documentation: **2026-09-07**.