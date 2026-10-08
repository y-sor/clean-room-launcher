---
layout: page
title: Clean-launch walkthrough
description: First-run CLROOM walkthrough for clean Codex and Claude Code launches, selected skills, Codex exec, and inspecting bounded plugin/MCP composition.
permalink: /demo.html
---

Start from a project on a supported macOS Apple Silicon system after [installing CLROOM](install.md).

## 1. Start the provider from a cleaner baseline

For Codex:

```sh
cd your-project
clroom codex
```

For Claude Code:

```sh
cd your-project
clroom claude
```

Before the provider takes over the terminal, CLROOM prints its launch summary. The useful check is not "everything is gone": project files, project instructions, project-local skills, provider-owned behavior, and managed policy can still exist. CLROOM reports the launch controls it actually owns.

**First-run success check:** after the CLROOM launch summary, the supported
provider should start its normal interactive session. Verify that the project
context you intended to keep is available, then exit through the provider's
normal exit method. A successful `clroom --help` or `--version` alone does not
prove this full interactive path. If CLROOM refuses the launch or the provider
does not start, use [Troubleshooting](troubleshooting.md); do not bypass the
launch restrictions as a workaround. This is a repeatable user check, not a
claim of independently observed unassisted onboarding.

## 2. Admit only the personal-global skills this run needs

Choose one skill or a saved set without rewriting the normal provider setup:

```sh
clroom codex --skill-set=my-skill,@review
clroom claude --skill-set=my-skill,@review
```

Project-local skills remain a separate scope. If Codex still shows provider-owned or repository skills, that does not mean every personal-global skill was re-admitted. See the [problem index](problem-index.md#codex-built-in-and-project-skills) for that distinction.

## 3. Use Codex exec for a headless task

The qualified non-interactive Codex path is:

```sh
clroom codex exec "summarize the staged changes"
```

CLROOM applies the same clean-launch boundary and also uses Codex's native exec-only user-config suppression on the qualified path. Scripts and CI can use the provider-facing `clroom-codex` executable when an existing runner supports an executable override.

## 4. Inspect a bounded Codex resource launch before provider birth

On the current qualified Codex path, CLROOM can select one already-installed whole plugin, one supported root-user stdio MCP server, or the bounded pair together.

Inspect the resolved launch without starting the real provider session:

```sh
clroom inspect codex \
  --with=plugin:plugin-name@marketplace-name \
  --with=mcp:my-server \
  --pass-env=MY_TOKEN
```

For a machine-readable view:

```sh
clroom --output json inspect codex \
  --with=plugin:plugin-name@marketplace-name \
  --with=mcp:my-server \
  --pass-env=MY_TOKEN
```

Inspection reports selected identities, qualification decisions, boundary controls, and admitted environment-variable **names** while keeping secret values and private source paths out of the output.

## 5. Know when the provider's native control is simpler

CLROOM is not the right answer to every configuration problem. Claude Code has native clean/minimal modes, skill visibility controls, MCP tool search, and subagent tool/MCP scoping. Codex has native homes/profiles, skill controls, MCP configuration, and an exec-only user-config suppression path.

Use [When to use CLROOM — and when not to](when-to-use-clroom.md) to choose the narrowest correct control.

## What this walkthrough proves — and what it does not

It demonstrates the supported launch model. It does **not** claim complete home-directory isolation, network isolation, universal plugin/MCP support, control over organization policy, or identical behavior between Codex and Claude Code.

For exact support boundaries, continue with:

- [Use cases](use-cases.md)
- [Codex and CLROOM](codex.md)
- [Claude Code and CLROOM](claude-code.md)
- [Configuration matrix](configuration-matrix.md)
- [Current limitations](limitations.md)
- [Threat model](threat-model.md)
