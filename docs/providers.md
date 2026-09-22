---
layout: page
title: Provider support
description: Current CLROOM provider support on macOS Apple Silicon for Codex and Claude Code, including minimum accepted versions and exact qualification targets.
permalink: /providers.html
---

The current source has two supported provider families on macOS Apple Silicon.
Minimum accepted parser/runtime ranges are broader than the exact versions used
for release qualification:

| Coding-agent CLI | Minimum accepted range | Exact release qualification |
| --- | --- | --- |
| Codex CLI | 0.147.0+ | 0.156.0 |
| Claude Code CLI | 2.1.223+ | 2.1.280 |

The exact qualified launch paths for this source tree are:

| Provider path | Exact version | Qualification |
| --- | --- | --- |
| `clroom codex` | Codex CLI 0.156.0 | Interactive clean launch |
| `clroom codex exec ...` | Codex CLI 0.156.0 | Non-interactive clean launch |
| `clroom codex --with=plugin:<id>` | Codex CLI 0.156.0 | One installed standalone-capable whole plugin |
| `clroom claude` | Claude Code CLI 2.1.280 | Interactive clean launch |
| `clroom claude --with=plugin:<id>` | Claude Code CLI 2.1.280 | One installed skill-only whole plugin |
| Claude Code `-p` response-output semantics | Claude Code CLI 2.1.280 | Launch path exercised; response-output contract is not independently qualified |

For provider diagnostics, use the top-level forms:

```sh
clroom codex --help
clroom codex --version
clroom claude --version
```

Clean Room Launcher resolves the installed provider from `PATH`; it does not
install, replace, log in to, or copy credentials from either provider.

Codex runs inside the CLROOM macOS isolation path. The `exec` path additionally
injects native `--ignore-user-config`. The v0.4.2 Codex whole-plugin path
projects exactly one qualified installed bundle into a private shadow
`CODEX_HOME` and fails closed on host-required app-owned MCP surfaces.

Claude runs with project/local settings retained, known personal-global inputs
restricted, and selected global skills admitted only for that launch. The
v0.4.2 whole-plugin path admits exactly one installed plugin whose observed
effective surface is skill-only; hooks, commands, agents, MCP/LSP, monitors,
executables, settings, custom skill paths, and other broader plugin surfaces
remain unqualified for activation.

Linux and Windows are `NOT_QUALIFIED`; Intel macOS is not supported by this
release. The macOS archive is unsigned and unnotarized.
