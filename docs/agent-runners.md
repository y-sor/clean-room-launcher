---
layout: page
title: CLROOM for coding-agent runners, scripts, and CI
description: Use CLROOM from runners, scripts, and CI to start Codex or Claude Code with per-run skills and qualified Codex plugin/MCP inputs while keeping project context.
permalink: /agent-runners/
nav_title: Agent runners
---

Clean Room Launcher (CLROOM) can sit between a tool that starts coding-agent processes and the installed Codex or Claude Code CLI.

Here, **runner** is a generic category for software that launches agent processes; this guide makes no compatibility claim for any named third-party launcher product.

```text
runner / script / CI
        ↓
      CLROOM
        ↓
Codex or Claude Code
```

Each CLROOM launch can keep the current repository context while leaving known unrelated personal-global instructions and unselected personal-global skills out of that worker. CLROOM is a CLI launch layer, not an orchestration framework, SDK, container runtime, credential broker, or replacement for a provider CLI.

<a id="clean-launches-from-tools"></a>
## Clean launches from tools

A runner can invoke the same commands a developer uses in a terminal:

```sh
clroom codex --skill-set=@review
clroom claude --skill-set=@review
clroom codex exec --skill-set=@review "Review the current change."
```

For a launcher with executable overrides, keep its runtime/provider set to
Codex or Claude Code and point the executable at `clroom-codex` or
`clroom-claude`. These are drop-in provider commands; no runner source change,
SDK, daemon, or fork is required. The equivalent direct forms are
`clroom codex ...` and `clroom claude ...`.

When an external launcher needs its own runtime context, pass only the exact
environment names it requires, for example:

```text
--pass-env=NAME
```

Names that are not explicitly passed remain unavailable, and unrelated parent
variables are not admitted.

For headless automation, this release qualifies `clroom codex exec`. Claude Code
`-p` can be passed through the launch path, but this release does not
independently qualify its response-output semantics. Verify that provider path
in your own harness before depending on its response contract.

The launch is session-specific. CLROOM does not rewrite ordinary Codex or Claude Code configuration. Use the provider directly when its native flags already provide the clean/minimal behavior you need.

<a id="different-capabilities-per-worker"></a>
## Different capabilities per worker

Different workers can receive different skill sets:

```sh
clroom codex --skill-set=@planning
clroom codex --skill-set=@review
clroom claude --skill-set=@debugging
```

On the current qualified Codex path, independently launched workers can also differ in the bounded provider resources admitted for that process. For example, one worker can start with a selected standalone stdio MCP while another uses the ordinary clean launch; a supported worker can also use the bounded one-plugin + one-MCP composition described in the Codex guide.

That per-process boundary matters when an external runner owns separate provider processes. It does **not** mean CLROOM rewrites provider-owned subagent definitions inside one already-running provider session.

Claude Code now has native subagent controls for that inner boundary: `tools` / `disallowedTools` can narrow a subagent's inherited tool pool, including MCP server-level patterns, and `mcpServers` can give a subagent servers that are not present in the parent conversation. Prefer those Claude-native controls when the requirement lives inside one Claude session; use separate CLROOM launches when the orchestration layer owns separate workers and needs an independent per-process CLROOM boundary.

Project-local skills remain part of the project. `--skill-set` controls the personal-global skills CLROOM deliberately adds for that launch.

<a id="fresh-vs-resumable-workers"></a>
## Fresh vs resumable workers

A fresh worker avoids inheriting assumptions from an earlier conversation. A resumed worker is useful when continuity is part of the job. CLROOM controls the launch inputs it owns; it does not turn provider conversation history into a universal stateless worker protocol. Qualify session history, authentication, working directory, project instructions, and the intended skill set separately when reusing a provider session.

<a id="claude-code-and-codex"></a>
## Claude Code and Codex

Codex and Claude Code expose different flags, configuration files, skill locations, MCP behavior, and session mechanisms. CLROOM provides one narrow shared idea: start the installed provider with a clean/selective session setup, then deliberately add the supported personal-global inputs this worker needs. Resource activation remains provider-specific; current Codex qualification is broader than Claude's and must not be generalized across providers.

<a id="subagents-and-agent-teams"></a>
## Separate worker processes vs provider-owned subagents

A separate `clroom codex ...` or `clroom claude ...` process gets its own CLROOM launch. Provider-owned subagents or agent-team teammates are created inside the provider session and follow that provider's own current inheritance and scoping rules. A top-level CLROOM skill choice does not automatically create a different skill set for every internal teammate.

For Claude Code specifically, native subagent definitions can narrow tools and MCP access or attach MCP servers to that subagent. Use that provider-native mechanism for inner-session specialization. Use independently launched CLROOM worker processes when the outer runner needs independently controlled launch boundaries, provider lifecycles, or CLROOM-selected top-level inputs.

<a id="symlinked-shared-skills"></a>
## Shared skill libraries and symlinks

Individual skill directories may be symlinked from a version-controlled shared library into a provider discovery location. CLROOM qualifies this as a filesystem-security case: a selected supported symlinked personal-global skill resolves to the intended skill, while unselected targets remain outside the clean launch. Protected provider, configuration, or credential targets are refused. Exact support differs by provider and source location; see [Skill sets](skill-sets.md#symlinked-global-skills).

## What CLROOM does not provide

CLROOM does not provide worker scheduling or queues, git worktree management, model routing, a cross-provider MCP catalog, a credential vault, VM/container/network isolation, universal control over provider-managed policy, or guaranteed identical behavior between Codex and Claude Code.

## Related pages

- [Problem index](problem-index.md)
- [Use cases](use-cases.md)
- [Skill sets](skill-sets.md)
- [Claude Code](claude-code.md)
- [Codex](codex.md)
- [Configuration matrix](configuration-matrix.md)
- [Current limitations](limitations.md)
