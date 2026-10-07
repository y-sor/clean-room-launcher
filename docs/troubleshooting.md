---
layout: page
title: Troubleshoot CLROOM — clean launches, skills, MCP, plugins, and provider failures
description: Diagnose CLROOM install, provider, clean-launch, skill, plugin, MCP, and resolved-launch failures without deleting config or exposing secrets.
permalink: /troubleshooting/
nav_title: Troubleshooting
---

# Troubleshoot CLROOM

**Start by locating the failing layer.** CLROOM sits in front of the installed Codex or Claude Code CLI, so a failure can belong to installation, the provider, CLROOM's clean/selective boundary, a selected skill/resource, or the provider runtime after launch.

Do not start by deleting your normal configuration. Do not disable Gatekeeper globally. Do not paste credentials, provider tokens, prompts, transcripts, unrestricted environment dumps, or your whole home directory into a bug report.

## 1. Is CLROOM installed and on PATH?

Check the executable first:

```sh
command -v clroom
clroom --help
```

The supported one-line installer writes `clroom`, `clroom-codex`, and `clroom-claude` to `~/.local/bin`.

If `command -v clroom` prints nothing, check whether `$HOME/.local/bin` is in `PATH`. For the current shell only, this is sufficient to test the installation:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

If macOS refuses the binary because the developer cannot be verified, remember that the current CLROOM archive is unsigned and unnotarized. Verify the exact release first and use the normal per-app macOS approval flow only if your local or organization policy permits it. Do **not** weaken machine-wide security.

**Canonical answer:** [Install CLROOM](install.md) · [Verify a CLROOM release](verify-release.md)

## 2. Is the platform supported?

The current release is qualified on **macOS Apple Silicon**.

```sh
uname -m
```

The expected architecture is `arm64`. Linux, Windows, Intel macOS, Homebrew, crates.io distribution, Apple signing, and notarization are not current qualified support.

A failure on an unsupported platform is not evidence that a supported CLROOM path regressed.

**Canonical answer:** [Current provider support](providers.md) · [Current limitations](limitations.md)

## 3. Does the provider work before CLROOM is involved?

CLROOM starts the installed provider; it does not install Codex or Claude Code or own provider authentication.

Check the provider executable and version:

```sh
command -v codex
codex --version

command -v claude
claude --version
```

Then check the provider through CLROOM:

```sh
clroom codex --version
clroom claude --version
```

If the provider itself cannot authenticate, reach its service, or start correctly outside CLROOM, fix the provider problem first. CLROOM is not a credential broker and does not maintain a second provider login.

**Canonical answer:** [Provider support](providers.md) · [Privacy and data flow](privacy-data-flow.md)

## 4. Did CLROOM refuse the launch before the provider started?

A refusal can be the correct fail-closed behavior.

Examples include:

- unsupported provider/version/platform state;
- unknown or unsupported selected resources;
- unsupported MCP transport/authentication fields;
- missing required environment-name admission;
- conflicting provider arguments or multiple activation authorities;
- plugin/MCP identity overlap;
- selected-source drift;
- inability to establish the required clean-launch restriction.

Do not work around a refusal by re-admitting ambient configuration or bypassing a check until you know which contract failed.

For a supported Codex resource selection, inspect the resolved launch **without starting the provider**:

```sh
clroom inspect codex \
  --with=plugin:plugin-name@marketplace-name \
  --with=mcp:my-server \
  --pass-env=MY_TOKEN
```

For machine-readable output:

```sh
clroom --output json inspect codex \
  --with=plugin:plugin-name@marketplace-name \
  --with=mcp:my-server \
  --pass-env=MY_TOKEN
```

Inspection exposes the bounded launch decisions CLROOM owns while keeping secret values and private source paths out of the output.

**Canonical answer:** [How CLROOM works](how-clroom-works.md) · [Codex and CLROOM](codex.md) · [Configuration matrix](configuration-matrix.md)

## 5. Does Codex still show more skills than you selected?

Do not equate **visible skill count** with **selected personal-global skill count**.

CLROOM's `Global skills` count is about the personal-global skills deliberately admitted for this launch. Provider-owned/system skills and repository/project-local skills are separate scopes and can remain visible by design.

A useful diagnostic is to repeat the relevant launch from a sterile temporary directory. Repository-local skills should disappear there; selected personal-global and provider-owned skills can remain.

If the problem is specifically “disable user/global Codex skills but keep repository skills,” use the scope distinction in the Codex docs rather than trying to make every visible skill disappear.

**Canonical answer:** [Codex skill scopes](problem-index.md#codex-built-in-and-project-skills) · [Skill sets](skill-sets.md) · [FAQ](faq.md)

## 6. Is a Claude customization or memory source still affecting behavior?

Claude Code has several native controls that may be the narrower answer:

- `--safe-mode` for broad troubleshooting;
- `--bare` for a minimal scripted invocation;
- `--setting-sources` for settings-scope selection;
- `skillOverrides`, `disable-model-invocation`, `/skills`, and `/skill-doctor` for skill visibility/diagnosis;
- native memory controls for `MEMORY.md` / auto-memory;
- subagent `tools`, `disallowedTools`, and `mcpServers` for inner-session tool/MCP scope.

Current qualified CLROOM Claude launches disable auto-memory for the launch but do not delete or repair stored memory. CLROOM also does not rewrite provider-owned subagents from outside the provider.

**Canonical answer:** [Claude Code and CLROOM](claude-code.md) · [When to use CLROOM](when-to-use-clroom.md)

## 7. Is the MCP configured but the model still cannot use its tools?

Treat these as different states:

1. the MCP definition exists in provider configuration;
2. CLROOM resolved the selected MCP for the launch;
3. the provider started or connected to the server;
4. the provider exposed the expected tools to the active model/session.

Passing an earlier state does not prove the later one.

For the current supported Codex selection, use `clroom inspect codex ...` to prove the bounded CLROOM launch plan. Then use the provider's current MCP/tool-discovery diagnostics for runtime visibility. Provider regressions can make configured or initialized MCP servers differ from model-visible tools.

If many MCP servers are the actual problem, provider-native tool search/lazy-loading can be the simpler answer. CLROOM's role is narrower: a qualified clean launch and deliberate per-run admission of the supported resource surface.

**Canonical answer:** [Codex and CLROOM](codex.md) · [MCP configured but tools unavailable](problem-index.md#mcp-configured-tools-unavailable) · [MCP/tool overload](problem-index.md#mcp-tool-context-overload)

## 8. Did an independently launched worker behave differently from a provider-owned subagent?

A CLROOM **worker** is a separately launched top-level provider process. Each such process can get its own supported CLROOM launch inputs.

A provider-owned subagent or teammate is created **inside** an already-running provider session. Its configuration/tool inheritance follows the provider's own rules.

If the question is “why did this subagent inherit too many tools?” or the opposite “why did the subagent lose MCP/ToolSearch?”, reproduce that provider-native subagent path. Do not infer that top-level CLROOM selection controls the provider's internal agent tree.

**Canonical answer:** [Agent runners](agent-runners.md) · [When to use CLROOM](when-to-use-clroom.md)

## 9. Does behavior differ between repositories?

Repository instructions, project configuration, project-local skills, local settings, provider state, models, and selected tools can all change behavior.

Use CLROOM for the part it actually controls: compare the ordinary launch with a repeatable clean/selective launch while keeping the project-side context the qualified path is designed to retain.

If a repository-local skill or instruction is the suspected variable, repeat the comparison in a sterile temporary directory. If the problem disappears there, that is evidence for project-local rather than personal-global influence.

CLROOM does not make model output deterministic; it removes a bounded set of known launch variables so the comparison is easier to reason about.

**Canonical answer:** [Use cases](use-cases.md) · [Why CLROOM exists](why-clroom.md)

## 10. Are you reading documentation for the same CLROOM release?

The canonical documentation site follows the current project state. An older immutable release can have a different provider tuple, limitation, CLI surface, or qualification boundary.

For historical behavior, read the documentation from that exact Git tag rather than projecting current-main docs backward.

**Canonical answer:** [Documentation versions](documentation-versions.md)

## 11. Build a safe minimal reproduction

Before opening an Issue, reduce the problem to the smallest reproducible boundary.

Record:

- CLROOM version;
- macOS version and architecture;
- Codex or Claude Code version;
- sanitized CLROOM command;
- whether the provider works directly;
- whether the failure happens before or after provider start;
- whether it reproduces without selected skills/plugins/MCP;
- whether it reproduces outside the repository in a sterile temporary directory when that distinction matters;
- expected behavior;
- observed error or behavior.

Do **not** include credentials, provider tokens, prompts, transcripts, private repository contents, unrestricted environment dumps, or home-directory listings.

Use a public Issue for non-sensitive bugs and compatibility questions. Use the private security-reporting path for vulnerabilities or sensitive reproductions.

**Canonical answer:** [Support](SUPPORT.md) · [Security policy](https://github.com/y-sor/clean-room-launcher/security/policy)

## Fast decision table

| Symptom | First useful boundary |
| --- | --- |
| `clroom: command not found` | Install/PATH |
| provider executable missing | Provider installation |
| provider auth/network error | Provider-owned state |
| CLROOM refuses before provider start | CLROOM qualification/conflict/fail-closed boundary |
| extra project/provider skills visible | Skill-scope distinction |
| Claude old memory appears relevant | Native memory controls / CLROOM no-auto-memory comparison |
| MCP configured but tools absent | Provider runtime/tool discovery after CLROOM launch-plan inspection |
| too many MCP/tool definitions | Provider-native tool search/lazy loading vs deliberate CLROOM per-run resource selection |
| subagent has too many or too few tools | Provider-owned subagent scoping |
| behavior differs by repository | Project-local vs personal-global comparison |
| docs do not match an installed old release | Exact-tag documentation |

## What troubleshooting should never prove

A successful troubleshooting step does not mean:

- CLROOM is a VM/container/network sandbox;
- every provider-owned input disappeared;
- a selected plugin, MCP server, skill, or repository is trustworthy;
- managed organization policy can be bypassed;
- provider runtime/tool visibility is guaranteed merely because CLROOM resolved a launch plan;
- current website documentation describes every older release.

Those boundaries are deliberate. See [Current limitations](limitations.md), [Threat model](threat-model.md), and [Privacy and data flow](privacy-data-flow.md).
