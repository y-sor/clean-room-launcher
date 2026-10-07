---
layout: page
title: CLROOM provider support — Codex and Claude Code qualification
description: Current CLROOM support for Codex and Claude Code on macOS Apple Silicon, including qualified launch paths, provider versions, MCP, plugins, and non-claims.
permalink: /providers.html
---

CLROOM supports **specific provider/version/platform/launch-path combinations**, not an abstract promise that every Codex or Claude Code feature works through CLROOM. The current release qualification is macOS on Apple Silicon, with exact paths listed below.

## Provider versions

Minimum accepted parser/runtime ranges are broader than the exact versions used for release qualification:

| Coding-agent CLI | Minimum accepted range | Exact release qualification |
| --- | --- | --- |
| Codex CLI | 0.147.0+ | 0.161.0 |
| Claude Code CLI | 2.1.223+ | 2.1.293 |

A newer installed provider can still require fresh qualification if upstream behavior changes. Public support claims remain bound to the exact release evidence rather than inferred from semver alone.

## Qualified launch paths

| Provider path | Exact version | Qualification |
| --- | --- | --- |
| `clroom codex` | Codex CLI 0.161.0 | Interactive clean launch |
| `clroom codex exec ...` | Codex CLI 0.161.0 | Non-interactive clean launch |
| `clroom codex --with=plugin:<id>` | Codex CLI 0.161.0 | One installed standalone-capable whole plugin |
| `clroom codex --with=mcp:<id>` | Codex CLI 0.161.0 | One exact root-user stdio standalone MCP server |
| `clroom codex --with=plugin:<id> --with=mcp:<id>` | Codex CLI 0.161.0 | Bounded one-plugin + one-stdio-MCP composition |
| `clroom claude` | Claude Code CLI 2.1.293 | Interactive clean launch |
| `clroom claude --with=plugin:<id>` | Claude Code CLI 2.1.293 | One installed skill-only whole plugin |
| Claude Code `-p` response-output semantics | Claude Code CLI 2.1.293 | Launch path exercised; response-output contract is not independently qualified |

For provider diagnostics:

```sh
clroom codex --help
clroom codex --version
clroom claude --version
```

## What CLROOM owns vs what the provider owns

Clean Room Launcher resolves the installed provider from `PATH`; it does not install, replace, log in to, or copy credentials from either provider.

Codex runs inside the CLROOM macOS isolation path. The `exec` path additionally injects native `--ignore-user-config`. The Codex whole-plugin path projects exactly one qualified installed bundle into a private shadow `CODEX_HOME` and fails closed on host-required app-owned MCP surfaces. Its standalone MCP path admits one exact root-user stdio server through a session-layer override with explicit environment-name admission and active-layer preflight. The current source composes one qualified plugin with one qualified standalone MCP through the same typed resolved launch; either-side drift invalidates the whole launch. Reusable presets do not widen that resource surface.

Claude runs with project/local settings retained, known personal-global inputs restricted, and selected global skills admitted only for that launch. The whole-plugin path admits exactly one installed plugin whose observed effective surface is skill-only; hooks, commands, agents, MCP/LSP, monitors, executables, settings, custom skill paths, and broader plugin surfaces remain unqualified for CLROOM activation.

Provider-native features outside these qualified paths remain provider-owned. A feature appearing in current Codex or Claude documentation does not automatically become a CLROOM-supported surface.

## Other coding-agent providers

The current CLROOM release is qualified only for the installed Codex and Claude Code CLIs on the paths above. Gemini CLI, Cursor, Aider, OpenCode, and other coding-agent products are not implicitly supported because they expose similar concepts. Adding another provider requires separate process/configuration/security/platform qualification.

## Not qualified in this release

- Linux and Windows;
- Intel macOS;
- Homebrew or crates.io distribution;
- Apple code signing or notarization;
- arbitrary multi-plugin or multi-MCP composition;
- remote/OAuth MCP through the CLROOM standalone selector;
- Claude standalone MCP selection through CLROOM;
- generic provider-owned subagent/orchestration control.

The distributed macOS archive is unsigned and unnotarized. See [Current limitations](limitations.md), [Configuration matrix](configuration-matrix.md), and [Verify a CLROOM release](verify-release.md) for the exact boundaries.
