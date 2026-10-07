---
layout: page
title: CLROOM limitations — platforms, provider scope, isolation, MCP, and plugins
description: Current CLROOM limits for macOS qualification, provider versions, filesystem isolation, plugins, MCP, subagents, signing, and unsupported platforms.
permalink: /limitations.html
---

CLROOM deliberately supports a **bounded, qualified launch surface**. The limits below are part of the product contract: unsupported provider combinations fail closed rather than silently inheriting a broader configuration.

## Platform and distribution limits

- Distributed macOS release artifacts are unsigned and unnotarized; qualification is limited to the documented macOS Apple Silicon release path.
- Only macOS on Apple Silicon is supported. The minimum accepted versions are Codex CLI `0.147.0` and Claude Code CLI `2.1.223`. Exact qualification targets are Codex `0.161.0` and Claude Code `2.1.292`. Release qualification fails closed if either stable provider version moves before tagging.
- Linux and Windows are `NOT_QUALIFIED`. Intel macOS, Homebrew, crates.io, signing and notarization are not claimed.
- The launcher depends on the undocumented longevity of macOS `sandbox-exec`; it fails closed if the protection cannot be created.

## Plugin and MCP limits

- The whole-plugin selector admits at most one already-installed provider-native plugin per launch. Codex `0.161.0` uses an exact private shadow-PluginStore projection for the interactive path; Claude Code `2.1.292` uses its separately qualified session-only plugin-directory path. Other provider tuples fail closed for activation. Codex plugins whose effective MCP surface includes the app-owned `codex_app` server are `HOST_REQUIRED`; CLROOM does not emulate the Codex Desktop host.
- The initial Claude whole-plugin qualification is narrower than Claude's full plugin discovery semantics. Activation requires a matching `.claude-plugin/plugin.json` identity and only default one-level `skills/<name>/SKILL.md` components. Manifestless plugins, root `SKILL.md` single-skill plugins, custom skill paths, slash commands, hooks, MCP servers, agents, LSP servers, background monitors, plugin executables, or plugin settings may still be observed by inventory but fail closed for activation.
- Codex admits at most one exact root-user standalone stdio MCP server per interactive launch. The current source can compose that server with at most one qualified whole Codex plugin in the same typed resolved launch.
- Reusable presets do **not** expand that qualified surface. A preset can only reuse the provider/resource/skill/environment forms the same source already accepts directly; unsupported provider combinations still fail closed.
- Multiple plugins or MCP servers, HTTP/SSE/WebSocket, OAuth/helpers, relative MCP working directories, project/local restore, Claude standalone MCP, component-level filtering, project/team/remote preset registries, preset scripts/interpolation, and `--with=all` remain outside the current source scope.
- The standalone Codex MCP path refuses literal environment values and identity-field interpolation. Every referenced environment-variable name also requires explicit `--pass-env=NAME`. It fails closed if an active non-session Codex config layer contributes MCP servers rather than attempting to override or bypass that layer.

## Isolation and provider-state limits

- The protection is a narrow macOS filesystem denylist, not a VM, container, network sandbox or complete home-directory isolation.
- The project directory and other host paths remain available unless macOS or the selected provider applies an additional restriction.
- A provider may visibly warn that reading a blocked global instruction is not permitted. This is expected and does not mean the provider itself failed.
- User arguments are intentionally last for ordinary clean launches. During CLROOM resource selection, overlapping provider config/plugin/MCP activation controls are refused so they cannot override the exact selection claim.
- Ordinary project, user, or other ambient MCP configurations are not loaded by default in the current Claude launch. CLROOM passes `--strict-mcp-config` and does not synthesize an `--mcp-config`; MCP servers are considered only when you explicitly supply Claude's own `--mcp-config` argument for that launch.
- CLROOM controls each top-level launch. Provider-owned Claude Code teammates and subagents follow Claude's own inheritance and scoping rules. Claude provides native subagent tool/MCP controls; CLROOM does not claim inner-session subagent surgery.
- Claude Code `-p` reached the provider and exited successfully in the current release qualification canary, but response-output semantics are not independently qualified by this release.
- Claude cleanup preserves live, unknown, corrupt, and legacy projection state; only a recognized session whose recorded owner is proven dead is reaped.

## Security and trust non-claims

- CLROOM is not a prompt-injection defense.
- CLROOM does not make a selected skill, plugin, MCP server, repository, or provider trustworthy merely by selecting or isolating it.
- CLROOM does not bypass managed/admin/organization policy.
- No bounty program exists.
- Release provenance/SBOM attestations are not substitutes for Apple code signing/notarization or an independent security audit.

For exact scope-by-scope behavior, see the [Configuration matrix](configuration-matrix.md). For security assumptions, see the [Threat model](threat-model.md). For artifact evidence, see [Verify a CLROOM release](verify-release.md).
