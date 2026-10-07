---
layout: page
title: CLROOM configuration scope matrix — what stays, changes, or remains provider-owned
description: Compare Codex and Claude Code configuration scopes to see what CLROOM retains, excludes, selects, leaves provider-owned, or does not qualify.
permalink: /configuration-matrix/
---

This matrix answers a narrow question: **for each provider/configuration scope, what does the current qualified CLROOM launch intentionally retain, exclude, select, or leave provider-owned?** It is not a claim that CLROOM can enumerate or remove every influence on a coding-agent session.

## How to read the matrix

- **Retained** means the qualified CLROOM path intentionally leaves that project/provider scope available.
- **Excluded/restricted** means CLROOM has a specific mechanism for the named input on that qualified path; it does **not** imply complete home-directory or provider-state isolation.
- **Selected/admitted** means the input participates only through the documented CLROOM selection contract.
- **Provider-owned / not qualified** means CLROOM does not claim control merely because the upstream provider supports the feature.

| Provider | Input / scope | Current CLROOM direction | Confidence |
| --- | --- | --- | --- |
| Claude Code | interactive top-level launch | Isolated; exact qualification target is 2.1.289 | Current-release qualification canary |
| Claude Code | `-p` non-interactive launch | Launch path exercised; response-output semantics not claimed as qualified | Provider exited 0, but the expected textual canary was not observed |
| Claude Code | ordinary user settings source | Omitted through `--setting-sources project,local`, with additional controls for known personal-global roots | Confirmed from current CLROOM source |
| Claude Code | project settings source | Retained | Confirmed from current CLROOM source |
| Claude Code | project-local settings source | Retained | Confirmed from current CLROOM source |
| Claude Code | project/user/ambient MCP configuration | Not loaded by default; current release uses `--strict-mcp-config` and supplies no default `--mcp-config` | Confirmed from current CLROOM source and Claude Code CLI contract |
| Claude Code | explicit `--mcp-config` provider argument | Passed through for that launch; Claude's own strict MCP rules apply | Confirmed from current CLROOM source and Claude Code CLI contract |
| Claude Code | `~/.claude.json` | Not blanket-blocked | Known limitation |
| Claude Code | managed / organization policy | Must remain authoritative | Product invariant; detailed combinations continue to require tests |
| Claude Code | selected personal-global skill | Admitted through a private temporary projection | Confirmed from current CLROOM source |
| Claude Code | whole-plugin selector | `--with=plugin:<provider-native-id>` admits exactly one already-installed plugin whose observed effective surface is skill-only | Exact real-provider E2E on Claude Code 2.1.289 / macOS Apple Silicon |
| Claude Code | selected plugin root | Exact active install root is revalidated and reopened read-only; persistent provider configuration is not rewritten | Focused negative tests plus exact real-provider E2E |
| Claude Code | raw plugin activation overlap | `--plugin-dir` and `--plugin-url` are refused while CLROOM resource selection is active | CLI conflict tests |
| Codex | global `AGENTS.md` / `AGENTS.override.md` | Known global instruction inputs blocked for the CLROOM launch | Confirmed from current CLROOM source |
| Codex | interactive top-level launch | Existing isolation path retained; exact qualification target is 0.160.0 | Current-release qualification canary |
| Codex | `exec` non-interactive launch | Existing isolation plus exec-only `--ignore-user-config`; exact qualification target is 0.160.0 | Current-release qualification canary |
| Codex | whole-plugin selector | `--with=plugin:<provider-native-id>` admits exactly one installed standalone-capable bundle into a private shadow PluginStore | Exact real-provider E2E on Codex CLI 0.160.0 / macOS Apple Silicon |
| Codex | host-required plugin surface | App-owned `codex_app` MCP is classified `PLUGIN_HOST_REQUIRED` instead of being treated as standalone-capable | Negative qualification plus real standalone MCP fixture evidence |
| Codex | standalone MCP selector | One exact root-user `mcp:<id>`, stdio only, interactive launch only | Exact real-provider E2E on Codex CLI 0.160.0 / macOS Apple Silicon |
| Codex | standalone MCP environment | Literal values refused; each plain `env_vars` name also requires explicit `--pass-env=NAME` | Focused negatives plus exact-provider rehearsal |
| Codex | bounded plugin + MCP composition | At most one qualified whole plugin and one qualified standalone stdio MCP share one typed resolved launch; overlap or drift on either side fails closed | Exact-candidate real-provider composition rehearsal |
| Codex | effective launch inspection | `inspect codex` human/JSON output comes from the resolved launch and exposes identities/reasons but not provider argv values, secrets or private source paths | CLI/unit privacy regressions |
| Codex | ambient MCP siblings | Preflight requires selected `SessionFlags` MCP and refuses enabled non-session MCP layers before provider birth | Fail-closed source tests plus exact-provider negative rehearsal |
| Claude Code | standalone MCP selector | Not qualified; fails closed | Not qualified; no release qualification evidence |
| Codex | project instruction chain | Retained | Confirmed from current CLROOM source |
| Codex | unselected personal-global skill contents | Known personal-global skill roots restricted | Confirmed from current CLROOM source |
| Codex | selected personal-global skills | Admitted for the launch | Confirmed from current CLROOM source |
| Both | selected symlinked personal-global skill | Admitted once when supported; canonical target is explicitly bounded | Focused security tests plus macOS sandbox enforcement tests |
| Codex | apps, hooks, plugins | Clean defaults off; explicit supported user arguments can re-enable them | Version-qualified |
| Both | complete home directory | **Not** claimed to be completely isolated | Explicit non-claim |
| Both | reusable CLROOM launch preset | User-level `presets.yaml` compiles provider-bounded skills/resources/env names/literal argv into the existing launch pipeline; native provider settings remain provider-owned | Source/unit/CLI contract; exact-provider release rehearsal required |
| Both | provider authentication | Existing provider authentication remains provider-owned | Confirmed product direction |

## Qualified skill source maps

CLROOM inventories only provider-qualified local sources. For Codex this is
the repository `.agents/skills` chain, personal `$HOME/.agents/skills` and
`$CODEX_HOME/skills`, and provider-owned admin/system behavior. Codex plugin
activation remains provider-owned: CLROOM does not infer activation from
cached package residue or invent an `installed_plugins.json` authority. For
Claude Code this is project/enterprise/personal skill locations and an active
cached plugin version gated by its provider-supported `installed_plugins.json`
contract.

Provider-managed synced/remote state is not guessed from filesystem residue.
Cached package directories without an active install record are stale and
remain unavailable. Selecting a package skill through `--skill-set=` admits only that skill
directory and its supporting files; package hooks, MCP, agents, executables,
settings, and notifications are not activated. By contrast, the bounded
whole-plugin selectors deliberately pass one qualified provider-native plugin
bundle as an atomic unit; it does not perform component-level surgery. The
initial activation qualification is narrower than provider inventory: a matching
plugin manifest identity plus only the default one-level `skills/<name>/SKILL.md`
layout is required. Manifestless/root-single-skill/custom-skill-path bundles and
observed command, hook, MCP, agent, LSP, monitor, executable, or settings
components make activation fail closed.

## What this matrix does not prove

The matrix is a public support map, not a runtime trace of every provider-owned influence. Use `clroom inspect ...` for the sanitized CLROOM launch plan on supported paths, provider-native diagnostics for provider state, and the [Threat model](threat-model.md) / [Limitations](limitations.md) for security non-claims.
