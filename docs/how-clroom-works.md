---
layout: page
title: How CLROOM works — clean/selective launch architecture
description: How Clean Room Launcher (CLROOM) builds a clean/selective Codex or Claude Code launch, preserves project context, admits chosen inputs, fails closed, and keeps provider behavior separate.
permalink: /how-clroom-works/
nav_title: How it works
---

# How CLROOM works

**Short answer:** Clean Room Launcher (CLROOM) is a local launch layer in front of the installed Codex or Claude Code CLI. It keeps the project-side context the qualified path is designed to preserve, keeps known unrelated personal-global inputs out by default, admits only supported inputs selected for this run, then starts the real provider CLI.

CLROOM does **not** replace the provider, proxy model requests through a CLROOM backend, or turn the session into a VM/container/network sandbox.

## The launch flow

A supported launch follows this shape:

```text
your command
    ↓
CLROOM resolves the provider + current launch request
    ↓
provider/version/platform qualification + conflict checks
    ↓
clean launch restrictions + selected inputs
    ↓
provider-specific resolved launch
    ↓
optional sanitized inspection on supported paths
    ↓
the installed Codex or Claude Code process starts
```

The exact mechanics differ by provider. CLROOM shares one product idea across Codex and Claude Code, not one fake universal configuration model.

## 1. Resolve the installed provider

CLROOM starts the installed `codex` or `claude` executable. It does not install a private replacement provider or require a separate CLROOM account.

Provider authentication remains provider-owned. CLROOM does not ask you to paste a second copy of Codex or Claude credentials into a CLROOM service.

See [Privacy and data flow](privacy-data-flow.md) for the network/credential boundary.

## 2. Establish the clean launch boundary

On the qualified macOS Apple Silicon paths, CLROOM applies provider-specific launch controls plus a narrow macOS filesystem policy.

The goal is not an empty machine. The goal is narrower:

- known personal-global instructions covered by the qualified path stay out;
- unselected personal-global skill contents stay out;
- project/repository context that CLROOM is designed to retain stays available;
- managed/provider-owned behavior remains a separate scope and is not treated as something CLROOM can bypass.

The current protection is a focused filesystem boundary, not complete home-directory isolation.

See [Configuration matrix](configuration-matrix.md), [Threat model](threat-model.md), and [Current limitations](limitations.md).

## 3. Admit only supported inputs for this run

A clean launch can deliberately add supported inputs without rewriting the normal provider setup.

### Personal-global skills

Selected skills or named CLROOM skill sets are admitted only for the current launch. Project-local skills remain a separate project scope.

### Codex resources

On the exact qualified Codex path, CLROOM can admit:

- one already-installed whole plugin;
- one root-user standalone stdio MCP server;
- or the bounded pair together.

Those choices share one typed resolved launch. Unsupported cardinality, transport/auth forms, identity overlap, provider-version drift, or selected-source changes fail closed.

### Claude resources

Claude Code uses a different provider-native mechanism. Current CLROOM qualification can admit one supported installed whole plugin through Claude's session-only plugin path. This does not imply Claude standalone MCP support or generic cross-provider plugin equivalence.

See [Codex and CLROOM](codex.md) and [Claude Code and CLROOM](claude-code.md) for the exact supported surfaces.

## 4. Apply provider-specific clean defaults

CLROOM does not pretend Codex and Claude Code expose identical configuration systems.

For example, the current qualified paths use different mechanisms for:

- global vs project instructions;
- user/project/local settings;
- skills;
- plugins;
- MCP;
- auto-memory;
- provider-native clean/minimal controls.

That is why the public docs keep provider pages separate instead of inventing one generic "agent config" taxonomy.

## 5. Resolve before provider birth

For supported resource-selection paths, CLROOM resolves the launch before starting the real provider session.

The resolved launch owns the decisions CLROOM itself is responsible for: selected identities, qualification state, environment-name admission, provider-specific composition, and fail-closed conflicts.

On the current Codex path, `clroom inspect codex ...` and its JSON form expose the same sanitized launch-planning truth without starting the real provider session.

Inspection may show identities and admitted environment-variable **names**. It must not expose secret values, provider credentials, private source paths, or raw provider argument values.

## 6. Revalidate mutable selected sources

A selection is not trusted merely because it resolved once.

Where the qualified path depends on an installed plugin/MCP source, CLROOM binds and rechecks the selected source around launch. If a material selected source changes during that boundary, the launch fails instead of silently running a different resource than the one that was reviewed.

This is one reason CLROOM deliberately supports a bounded surface rather than claiming arbitrary plugin/MCP composition.

## 7. Start the original provider CLI

After CLROOM-owned checks and launch preparation pass, the real Codex or Claude Code process starts.

The provider still owns model requests, provider authentication, provider-native tools, service-side behavior, and any network activity it performs. A selected plugin or MCP server can also have its own behavior and data flow.

CLROOM is therefore a **launch-input control**, not a replacement provider and not a network-security product.

## What CLROOM changes vs what remains provider/project-owned

| CLROOM-owned launch decision | Remains separate / provider-owned |
| --- | --- |
| Known personal-global inputs covered by the qualified clean path | Project files and project-side context CLROOM is designed to retain |
| Selected personal-global skills for this run | Provider/system/admin scopes outside CLROOM's supported boundary |
| Qualified provider-resource selection | Provider authentication and model-service behavior |
| Fail-closed selector/config conflicts | Provider-native sandbox/approval/permission controls |
| Sanitized resolved-launch inspection on supported paths | Arbitrary model-response influences outside the CLROOM launch contract |
| Explicit environment-name admission where required | Secret values and resource/network behavior outside CLROOM's inspection contract |

## Why not just use a provider-native flag?

Sometimes you should.

Claude Code has native controls such as `--safe-mode`, `--bare`, `--setting-sources`, skill visibility controls, and subagent tool/MCP controls. Codex has native configuration, profiles, skill controls, `CODEX_HOME`, and `codex exec --ignore-user-config`.

Use the native feature when it is the smaller correct control.

CLROOM is useful when the requirement is a repeatable **per-launch** boundary across the supported provider paths, while keeping the normal setup on disk and deliberately admitting the supported personal-global inputs/resources needed for that run.

See [When to use CLROOM — and when not to](when-to-use-clroom.md).

## What "fail closed" means here

CLROOM should not silently fall back to an ordinary inherited launch when a claimed clean/selective boundary cannot be established.

Examples include:

- unsupported provider/version/platform tuples;
- invalid or unknown selected skills/resources;
- overlapping activation authorities;
- unsupported MCP transports/authentication fields;
- selected-source drift;
- inability to establish the required macOS restriction.

The exact refusal conditions are release- and provider-specific. Read the current [limitations](limitations.md) instead of assuming a future provider feature is already supported.

## What the release evidence adds

Runtime design and release trust are separate layers.

CLROOM's published release process also uses checksums, provenance attestations, a CycloneDX SBOM/SBOM attestation, exact provider qualification, immutable release identity, and post-public install verification.

Those mechanisms make the released bytes and claimed qualification easier to verify; they do not turn CLROOM into risk-free software or substitute for Apple signing/notarization.

See [Verify a CLROOM release](verify-release.md).

## Related canonical answers

- [Why CLROOM exists](why-clroom.md)
- [When to use CLROOM — and when not to](when-to-use-clroom.md)
- [Codex and CLROOM](codex.md)
- [Claude Code and CLROOM](claude-code.md)
- [Configuration matrix](configuration-matrix.md)
- [Privacy and data flow](privacy-data-flow.md)
- [Threat model](threat-model.md)
- [Current limitations](limitations.md)
- [Terminology glossary](glossary.md)
