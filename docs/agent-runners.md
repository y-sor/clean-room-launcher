---
layout: page
title: Use CLROOM from coding-agent runners, orchestrators, scripts, and CI
description: Launch Codex and Claude Code workers with a clean/selective per-run setup and task-specific global skills while keeping project context and the developer's normal setup intact.
permalink: /agent-runners/
nav_title: Agent runners
---

Clean Room Launcher (CLROOM) can sit between a tool that starts coding-agent processes and the installed Codex or Claude Code CLI.

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

Project-local skills remain part of the project. `--skill-set` controls the personal-global skills CLROOM deliberately adds for that launch.

<a id="fresh-vs-resumable-workers"></a>
## Fresh vs resumable workers

A fresh worker avoids inheriting assumptions from an earlier conversation. A resumed worker is useful when continuity is part of the job. CLROOM controls the launch inputs it owns; it does not turn provider conversation history into a universal stateless worker protocol. Qualify session history, authentication, working directory, project instructions, and the intended skill set separately when reusing a provider session.

<a id="claude-code-and-codex"></a>
## Claude Code and Codex

Codex and Claude Code expose different flags, configuration files, skill locations, MCP behavior, and session mechanisms. CLROOM provides one narrow shared idea: start the installed provider with a clean/selective session setup, then add only the personal-global skills this worker needs.

<a id="subagents-and-agent-teams"></a>
## Separate worker processes vs provider-owned subagents

A separate `clroom codex ...` or `clroom claude ...` process gets its own CLROOM launch. Provider-owned subagents or agent-team teammates are created inside the provider session and follow that provider's inheritance and scoping rules. A top-level CLROOM skill choice does not automatically create a different skill set for every internal teammate. Use independently launched worker processes when you need independently controlled inputs.

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
