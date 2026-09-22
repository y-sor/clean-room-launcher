---
layout: page
title: Limitations
description: "Current CLROOM support boundaries: macOS Apple Silicon qualification, filesystem isolation limits, provider configuration caveats, and unsupported platforms."
permalink: /limitations.html
---

- Distributed macOS release artifacts are unsigned and unnotarized;
  qualification is limited to the documented macOS Apple Silicon release path.
- Only macOS on Apple Silicon is supported. The minimum accepted versions are
  Codex CLI `0.147.0` and Claude Code CLI `2.1.223`. v0.4.2 exact
  qualification targets are Codex `0.155.1` and Claude Code `2.1.280`.
  Release qualification fails closed if either stable provider version moves
  before tagging.
- The v0.4.2 whole-plugin selector admits at most one already-installed
  provider-native plugin per launch. Codex `0.155.1` uses an exact private
  shadow-PluginStore projection for the interactive path; Claude Code `2.1.280`
  uses its separately qualified session-only plugin-directory path. Other
  provider tuples fail closed for activation. Codex plugins whose effective MCP
  surface includes the app-owned `codex_app` server are `HOST_REQUIRED` and
  are not standalone-qualified; CLROOM does not emulate the Codex Desktop host.
- The initial v0.4 whole-plugin qualification is narrower than Claude's full
  plugin discovery semantics. Activation requires a matching
  `.claude-plugin/plugin.json` identity and only default one-level
  `skills/<name>/SKILL.md` components. Manifestless plugins, root `SKILL.md`
  single-skill plugins, custom skill paths, slash commands, hooks, MCP servers,
  agents, LSP servers, background monitors, plugin executables, or plugin
  settings may still be observed by inventory but fail closed for activation.
  This avoids reopening broader ambient provider state.
- Multi-plugin selection, component-level filtering, standalone MCP resource
  selection, presets, and `--with=all` are not qualified by this slice.
- The protection is a narrow macOS filesystem denylist, not a VM, container,
  network sandbox or complete home-directory isolation.
- A provider may visibly warn that reading a blocked global instruction is not
  permitted. This is expected and does not mean the provider itself failed.
- User arguments are intentionally last for ordinary clean launches. During a
  CLROOM whole-plugin selection, overlapping provider plugin/config activation
  controls are refused so they cannot override the exact selection claim.
- The project directory and other host paths remain available unless macOS or
  the selected provider applies an additional restriction.
- Ordinary project, user, or other ambient MCP configurations are not loaded by
  default in the current Claude launch. CLROOM passes `--strict-mcp-config` and
  does not synthesize an `--mcp-config`; MCP servers are considered only when
  you explicitly supply Claude's own `--mcp-config` argument for that launch.
- CLROOM controls each top-level launch. Provider-owned Claude Code teammates
  and subagents follow Claude's own inheritance and scoping rules.
- Claude Code `-p` reached the provider and exited successfully in the current
  release qualification canary, but response-output semantics are not independently
  qualified by this release.
- The launcher depends on the undocumented longevity of macOS `sandbox-exec`;
  it fails closed if the protection cannot be created.
- No bounty program exists.
- Claude cleanup preserves live, unknown, corrupt, and legacy projection state;
  only a recognized session whose recorded owner is proven dead is reaped.
- Linux and Windows are `NOT_QUALIFIED`. Intel macOS, Homebrew, crates.io,
  signing and notarization are not claimed.