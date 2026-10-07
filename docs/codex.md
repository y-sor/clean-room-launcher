---
layout: page
title: Codex and CLROOM
description: Use CLROOM with Codex for clean/selective launches, global vs project AGENTS.md, skills, bounded plugin/MCP selection, CODEX_HOME alternatives, and inspection.
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

Current Codex supports reusable configuration profiles selected with `--profile profile-name`. The profile is a provider-native configuration layer (for example `$CODEX_HOME/profile-name.config.toml`) and participates in Codex's own configuration precedence together with project, user, cloud-managed, system, and CLI layers.

Use a Codex profile when the problem is **reusing Codex configuration values**. Project-level `.codex/config.toml` and managed configuration can also be the right native answer when the desired settings belong to a repository or organization.

That is not the same contract as CLROOM's current clean/selective launch boundary. CLROOM's shipped skill/resource selectors are aimed at deciding which supported personal-global inputs participate in this run without turning a provider profile into a second CLROOM configuration authority.

CLROOM v0.6 keeps that distinction explicit. A CLROOM preset saves top-level CLROOM launch intent—supported skill/resource selectors, admitted environment-variable names, and literal provider argv—and compiles it into the same qualified launch path. It does not define typed copies of Codex model/reasoning/approval/sandbox/agent-role settings. Use [Presets](presets.md) for the exact schema and precedence.

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

## Select one installed whole plugin

CLROOM admits at most one provider-native installed Codex plugin for an
interactive launch:

```sh
codex plugin list --json
clroom codex --with=plugin:plugin-name@marketplace-name
```

The selected bundle is source-bound, revalidated, projected alone into the
private shadow `CODEX_HOME` `PluginStore`, made non-writable, and enabled only
for that process. Sibling plugins remain absent. CLROOM does not install, update,
remove, or refresh plugins or marketplaces. App-owned `codex_app` surfaces
remain `HOST_REQUIRED` rather than being emulated outside the Codex Desktop
host.

OpenAI's current plugin documentation also describes a portable package format with root `plugin.json`, optional `skills/` and `mcp.json`, plus `.codex-plugin/plugin.json` as a compatibility fallback. That upstream packaging evolution does not automatically widen CLROOM support: the current activation claim remains bound to the exact installed provider-native surface and provider tuple that CLROOM qualified.

## Select one standalone stdio MCP server

CLROOM also admits exactly one root-user `mcp_servers.<id>` entry:

```sh
clroom codex --with=mcp:my-server
clroom codex --with=mcp:my-server --pass-env=MY_TOKEN
```

Only bounded stdio definitions are qualified. Literal environment values,
structured/remote environment sources, HTTP transports, OAuth/helper fields,
identity-field interpolation, extra security-sensitive fields, and relative MCP
working directories fail closed. Each plain environment-variable name referenced
by the MCP must also be explicitly admitted with `--pass-env=NAME`; values are
never stored or printed.

The selected definition is a session-layer override. The ambient file is not
rewritten. Before provider birth CLROOM performs a no-model Codex
`config/read` preflight and refuses active non-session MCP layers. The selected
source remains digest-bound and is re-read before the real launch.

If your problem is a large ambient MCP/tool inventory, start with Codex's own current MCP configuration/status surfaces, such as `codex mcp list`, and the provider documentation for the installed Codex version. OpenAI also documents deferred tool search in its API/agent runtimes, but that is a separate product surface and must not be projected onto the qualified Codex CLI path without evidence.

CLROOM's narrower value is per-launch selection: the clean path does not rewrite the normal user configuration, and the qualified resource path can deliberately admit one supported standalone stdio MCP for this run. That can reduce configuration ambiguity, but it is not a claim of universal lazy MCP loading or control over every provider-owned tool surface.

## Configuration presence vs runtime MCP tool availability

A configured or initialized MCP server is not automatically the same thing as tools being visible and callable in the active Codex session. Provider runtime mode, model/tool-discovery behavior, host surface, authentication, and upstream regressions can affect the final tool-exposure step.

CLROOM's selected-MCP preflight and `clroom inspect codex ...` prove only the bounded launch/configuration facts they own. They do not claim that every provider host or later runtime state will expose a configured tool successfully. When the symptom is **"the MCP is configured but the model cannot call its tools,"** use current Codex MCP/status/tool-discovery diagnostics as well as the CLROOM launch evidence.

## Compose one plugin with one standalone MCP

v0.5.0 can resolve both bounded selectors in one interactive launch:

```sh
clroom codex \
  --with=plugin:plugin-name@marketplace-name \
  --with=mcp:my-server \
  --pass-env=MY_TOKEN
```

One typed resolved launch owns the plugin plan, MCP plan, environment-name
admissions, deterministic provider-argument composition and final source
revalidation. A source change on either side invalidates the whole launch.
Plugin/MCP identity overlap fails closed. Raw Codex configuration/plugin/MCP
activation controls are refused while CLROOM selection is active so there is
only one activation authority.

The exact qualification target for these Codex resource paths is Codex CLI `0.160.0` on macOS Apple Silicon. Multiple plugins, multiple standalone MCP
servers, `--with=all`, component-level plugin surgery, persistent provider
configuration mutation, remote/OAuth MCP and marketplace installation/update
remain outside this bounded slice. Claude standalone MCP is not qualified.

## Inspect the effective Codex launch

`clroom inspect codex ...` uses the same resolved-launch planning truth as the
real launch. Use `clroom --output json inspect codex ...` for the machine
representation. Both surfaces expose bounded resource identities, decisions,
qualification state, admitted environment-variable names and boundary controls
while provider argument values, secret values and private source paths remain
redacted.


## Is CLROOM a way around managed Codex controls?

No.

Administrator-managed behavior belongs to a different control plane from the personal-global material CLROOM is designed to filter. CLROOM should never be marketed as a way around organization policy.

## Official OpenAI sources

- [Custom instructions with AGENTS.md](https://developers.openai.com/codex/guides/agents-md/)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
- [Build skills](https://developers.openai.com/codex/skills/)
- [Package plugins](https://developers.openai.com/plugins/build/plugins)
- [OpenAI developer documentation index](https://developers.openai.com/llms.txt)

The `developers.openai.com` Codex URLs can redirect to their current ChatGPT Learn canonical pages.

Last verified against current OpenAI documentation: **2026-10-06**.