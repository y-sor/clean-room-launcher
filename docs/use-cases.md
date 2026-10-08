---
layout: page
title: CLROOM use cases — skills, workers, Codex plugin + MCP, scripts, and CI
description: Practical CLROOM workflows for clean Agent Skill tests, per-worker skill sets, bounded Codex plugin plus MCP launches, MCP-overload diagnosis, scripts, and CI.
permalink: /use-cases/
nav_title: Use cases
---
## For skill authors: test your skills in clean launches with CLROOM

You built a skill. Test it without unrelated global instructions or skills. Alone, with a skill set you created, or both together:

```sh
clroom codex exec --skill-set=my-skill,@my-skill-set
```

Then test other skills on the same task to compare the results, token use, and time:

```sh
clroom codex exec --skill-set=superpowers
```

Then repeat the test with the other supported coding agent in the same simple way:

```sh
clroom claude --skill-set=@skill-set
```

Your project context stays available. Your normal setup stays untouched.

You configure only this launch.

## Different skills for different workers

Use separate saved groups when a planning, review, or debugging worker needs a
different personal-global skill set:

```sh
clroom codex --skill-set=@planning
clroom codex exec --skill-set=@review "Review the staged diff."
clroom claude --skill-set=@debugging
```

## Reuse a complete CLROOM launch intent

When a task repeatedly needs the same CLROOM-owned launch choices, save them as a preset instead of repeating the flags:

```sh
clroom codex --preset=review
clroom claude --preset=review
```

An external runner can give different independently launched workers different preset names. Presets remain top-level launch inputs; they do not configure provider-owned subagents inside one session.

Use a native Codex profile or Claude settings when the reusable object is provider configuration itself. Use [Presets](presets.md) when the reusable object is the CLROOM clean/selective launch intent.

## Compose one Codex plugin with one standalone MCP for a launch

When one task needs both an already-installed Codex plugin and one qualified root-user stdio MCP server, CLROOM can resolve both through the same bounded interactive launch without rewriting persistent Codex configuration:

```sh
clroom codex \\
  --with=plugin:plugin-name@marketplace-name \\
  --with=mcp:my-server \\
  --pass-env=MY_TOKEN
```

Inspect the same plan before provider birth when you need a machine-readable or human review surface:

```sh
clroom inspect codex --with=plugin:plugin-name@marketplace-name --with=mcp:my-server
clroom --output json inspect codex --with=plugin:plugin-name@marketplace-name --with=mcp:my-server
```

This is intentionally narrow: one whole plugin plus one standalone stdio MCP on the exact qualified Codex path. Multiple plugins/MCP servers, remote/OAuth MCP, `--with=all`, and Claude standalone MCP are not implied.

## Investigate MCP/tool overload from a cleaner launch

Large MCP/tool inventories can create startup latency, tool-discovery noise, context pressure, or simply an unnecessarily broad tool surface.

For Claude Code, use native MCP Tool Search first when the problem is tool-definition context overhead; current Claude can defer MCP tool definitions and also scope MCP servers/tools inside subagent definitions. For Codex CLI, use the current Codex MCP configuration/status surfaces for the installed version rather than assuming OpenAI API tool-search behavior is identical to the CLI.

Use CLROOM when the problem is the top-level **per-launch boundary** itself. On the current qualified Codex path, a clean launch can deliberately admit one supported standalone stdio MCP:

```sh
clroom codex --with=mcp:my-server --pass-env=MY_TOKEN
```

That can help distinguish an ambient configuration problem from the one MCP resource the task actually needs. It is not universal lazy MCP loading, and it does not rewrite the tool inheritance of provider-owned subagents.

For independent worker processes owned by an external runner, launch each worker separately when different tasks need different CLROOM-supported resources. For subagents inside one Claude session, prefer Claude's native `tools`, `disallowedTools`, and `mcpServers` controls.

## Cross-provider review workflow

The same runner can exercise one task through both supported interactive provider
paths while keeping each provider's native environment and lifecycle rules.

## Clean worker launched from a script or CI

For headless automation, the integrity-verified path in this release is `clroom codex
exec ...`. A runner that provides a terminal can also start the interactive
Codex or Claude Code path. Keep provider authentication, queues,
worktrees, and session reuse in the system that owns those responsibilities;
CLROOM supplies the per-launch clean/selective layer.
