---
layout: page
title: Reusable CLROOM launch presets for Codex and Claude Code
description: Save and compose provider-bounded CLROOM launch intent for skills, qualified resources, admitted environment names, and literal provider arguments without replacing native provider profiles.
permalink: /presets/
nav_title: Presets
---

CLROOM presets save **CLROOM-owned launch intent** for reuse. A preset can select the same personal-global skills, qualified plugin/MCP resources, admitted environment-variable names, and literal provider arguments that you could supply to a supported CLROOM launch directly.

A preset is **not** a second Codex/Claude settings system. Codex profiles, Claude settings, provider-owned agent/subagent controls, authentication, models, and managed policy remain provider-owned.

## Preset file

Run:

```sh
clroom --help
```

The normal path is:

```text
~/.config/clroom/presets.yaml
```

When `XDG_CONFIG_HOME` is set to an absolute path, CLROOM uses:

```text
$XDG_CONFIG_HOME/clroom/presets.yaml
```

CLROOM reads this user-owned file. It does not create, rewrite, sync, or upload it.

## Minimal schema

```yaml
schema: clroom.presets.v1

presets:
  default:
    default-provider: codex
    providers:
      codex: {}
      claude: {}

  review:
    providers:
      codex:
        args: []
      claude:
        args: []
    skill-set:
      - "@review"
    with: []
    without: []
    pass-env:
      - REVIEW_TOKEN
```

Every preset declares the provider or providers it permits. Empty provider objects are intentional: they say the preset may be used with that provider without adding provider-native arguments.

This explicit provider set prevents a preset from silently beginning to support a new provider merely because a future CLROOM release adds one.

## Use presets

If a `default` preset exists, an ordinary supported launch applies it implicitly:

```sh
clroom codex
clroom claude
```

Choose additional presets with one `--preset=` option:

```sh
clroom codex --preset=review
clroom codex --preset=review,debug
clroom claude --preset=review
```

Use `none` to reset preset layers:

```sh
clroom codex --preset=none
clroom codex --preset=none,review
```

The reset token is the only preset-layer reset mechanism. v0.6 does not add per-field reset flags or a mini-language.

## Provider inference

An explicit provider always wins:

```sh
clroom claude --preset=review
```

Without an explicit provider, CLROOM can infer one only when the selected preset set is unambiguous:

```sh
clroom --preset=review
```

Resolution is:

1. explicit CLI provider, when present;
2. one unambiguous `default-provider` declared by the selected presets;
3. otherwise, the one provider permitted by **all** selected presets;
4. otherwise fail before provider birth and require an explicit provider.

Conflicting default providers or a selected preset combination with no shared provider fail closed.

## Composition and precedence

Presets compile into the same launch path used by direct CLI options. They do not create another launcher or another resource resolver.

The conceptual order is:

```text
CLROOM clean safety defaults
  -> implicit default preset
  -> explicit presets, in order
  -> explicit CLI CLROOM options
  -> literal provider argv
  -> qualification / managed policy / hard safety constraints
```

Field behavior:

- `skill-set`: preset skill selectors are composed in preset order; an explicit CLI `--skill-set=...` replaces all preset-derived skill selection for that launch.
- `with` / `without`: compile to the existing qualified CLROOM resource selector. Existing provider/cardinality/conflict rules still apply. A preset cannot make an unsupported resource combination supported.
- `pass-env`: contains **environment-variable names only**. Names are composed and deduplicated by the existing launch path. Values are never stored in the preset.
- `providers.<provider>.args`: literal argv elements for that provider. Preset argv is added in preset order, followed by explicit invocation argv.

If the same target is explicitly included and excluded through the existing resource selector, the existing fail-closed selection rules remain authoritative.

## Provider-native profiles are different

Use native provider configuration when it solves the narrower problem directly.

For Codex, named `--profile` files and project/user/managed/system configuration are native reusable configuration layers. CLROOM presets do not reimplement their typed settings. A Codex profile can still be passed as provider argv on a launch that does not conflict with CLROOM's active resource-selection safety rules.

For Claude Code, settings, skills, plugins, subagent tool/MCP scope, and other provider-native controls remain Claude-owned. CLROOM presets do not become an inner-session subagent or orchestration system.

Use a CLROOM preset when the reusable object is the **top-level clean/selective launch intent** itself.

## Security and failure behavior

Preset resolution is intentionally local, bounded, and fail-closed:

- schema must be exactly `clroom.presets.v1`;
- unknown schema fields and unknown providers are refused;
- preset names and list sizes are bounded;
- the file is bounded in size;
- no shell expansion, command substitution, scripts, recursive includes, remote registry, network fetch, or implicit interpolation exists;
- provider arguments are argv elements, never shell strings;
- credential-shaped/sensitive provider arguments are refused;
- provider argv cannot smuggle CLROOM-owned `--preset`, `--with`, `--without`, `--skill-set`, or `--pass-env` controls;
- provider argv cannot insert a `--` terminator that would bypass later CLROOM option precedence;
- malformed or incompatible presets fail before the selected provider starts;
- managed/admin/provider policy and CLROOM qualification remain authoritative.

A preset may contain provider-native flags that change provider behavior. Those flags remain user-owned provider configuration; CLROOM does not turn them into safe recommendations or bypass hard CLROOM/provider policy.

## Inspect the resolved launch

On the qualified Codex inspection path:

```sh
clroom inspect codex --preset=review
clroom --output json inspect codex --preset=review
```

Inspection reports the effective preset names alongside the same sanitized resolved launch used by execution. Provider argument **values** remain redacted in the launch summary.

## Runners and independent workers

Apps, scripts, CI jobs, and agent runners can give different top-level workers different preset names while still launching the provider through CLROOM.

That does not configure provider-owned subagents inside one Codex or Claude session. If an external orchestrator starts separate provider processes, each process can receive its own CLROOM preset.

See [Agent runners](agent-runners.md), [Skill sets](skill-sets.md), [Codex](codex.md), [Claude Code](claude-code.md), and the [Configuration matrix](configuration-matrix.md).
