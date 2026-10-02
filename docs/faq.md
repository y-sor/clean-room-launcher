---
layout: page
title: Clean Room Launcher (CLROOM) FAQ: Codex, Claude Code, Agent Skills, clean sessions
description: Direct answers about CLROOM, clean Codex and Claude Code sessions, global vs project instructions and skills, Agent Skills, Claude safe mode and bare mode, Codex AGENTS.md, CODEX_HOME, skill sets, and current limitations.
permalink: /faq/
nav_title: FAQ
---
New to the project? Start with [Why Clean Room Launcher (CLROOM) exists](why-clroom.md), or use the [problem index](problem-index.md) if you arrived with a symptom or half-remembered term.

## Can an app or CI job launch CLROOM?

Yes. For headless automation, the integrity-verified path in this release is
`clroom codex exec ...`. A runner that provides a terminal can also start the
interactive Codex or Claude Code path. Claude Code `-p` response
semantics are not independently qualified in this release.

## Can different workers get different skill sets?

Yes. Pass a different skill name or saved `@set` to each top-level launch.

## Does CLROOM configure Claude agent-team teammates individually?

No. Provider-owned teammates and subagents follow Claude Code's own inheritance
and scoping rules. Launch separate processes when workers need independent
CLROOM inputs.

## Can I keep skills in one git repo and symlink them?

Yes, for the supported individual-skill symlink forms. Selected links are
admitted once, unselected canonical targets stay denied, and protected targets
are refused. See [Skill sets](skill-sets.md#symlinked-global-skills).

## What problem does Clean Room Launcher (CLROOM) solve?

CLROOM is for cases where personal-global coding-agent configuration that is useful elsewhere should not silently participate in this particular launch. It gives you a repeatable cleaner starting point without deleting the normal setup.

## Why not just delete or rename my global configuration?

Because that changes the normal setup and creates manual cleanup. CLROOM is session-specific: the existing files remain in place for other work.

## Why can unrelated global instructions matter?

Because the cost can compound after the prompt: an irrelevant or conflicting instruction can affect a decision, tool choice, implementation path, review cycle, and rework.

## Does CLROOM guarantee lower token usage?

No fixed token saving should be promised. Skill systems can use progressive disclosure and provider behavior changes. CLROOM's stronger value is controlling which known personal-global inputs can participate and reducing avoidable conflict paths.

## I have many Agent Skills installed. Does that automatically mean they all fill the context window?

No. Do not assume every installed skill body is fully loaded into the model context. The useful question for CLROOM is which personal-global skills are eligible to participate in the launch, not a universal token count per installed skill.

## Can I test one Agent Skill without my other personal-global skills?

That is one of CLROOM's core use cases. Select the global skill or named skill set for the launch while unselected personal-global skill contents stay outside CLROOM's known clean-launch path. See [Use cases](use-cases.md) for the complete skill-author testing workflow.

## Why does Codex show more skills than the CLROOM `Global skills` count?

The CLROOM count is the number of **selected personal-global skills** for that launch. Provider-owned/system skills and project-local skills are separate scopes and can still appear by design.

For example, `Global skills: 1` can correctly coexist with one selected personal-global skill, Codex's own bundled skills, and a repository-local skill. If you need to distinguish a project skill from a global one, launch the same command from a sterile temporary directory: project-local skills should disappear there, while selected personal-global and provider-owned skills can remain. See [Codex skill scopes](problem-index.md#codex-built-in-and-project-skills).

## How can I tell whether a new skill actually improved the result?

Compare against a repeatable baseline. A clean/selective launch helps reduce the chance that another personal-global instruction or skill changed the comparison. It still does not turn model output into a perfectly deterministic experiment.

## Why does my coding agent behave differently in two repositories?

Many things can explain that: repository instructions, project configuration, local configuration, provider state, tools, models, or personal-global inputs. CLROOM is useful specifically for testing the contribution of the personal-global layer it controls.

## Can CLROOM tell me every instruction or influence the model saw?

No. Use provider-native status/diagnostic tools for provider configuration and CLROOM's own launch summary for controls it owns. No honest tool should claim to enumerate every influence on a model response.

## Can I use Claude Code `--safe-mode` instead?

Yes. If the goal is broad troubleshooting with customizations disabled, Anthropic's native `--safe-mode` is the simpler answer. CLROOM targets a more selective working session.

## What is the difference between Claude Code `--bare` and CLROOM?

Anthropic documents `--bare` as a minimal scripted mode that skips automatic discovery of several customization sources. CLROOM is aimed at repeatable selective work where relevant project/local configuration can remain useful.

## Why not call Claude with `--setting-sources project,local` myself?

Do that if it fully solves your need. CLROOM currently uses those sources itself and adds its own provider-specific launch controls and selected-skill workflow.

## Does CLROOM remove every Claude Code global setting?

No. In particular, current CLROOM does not blanket-block `~/.claude.json`, and it does not claim complete provider-global removal or complete home-directory isolation.

## Does CLROOM bypass managed Claude Code settings?

No. Organization-managed policy must remain authoritative. Any bypass would be a bug, not a feature.

## Does Codex normally load global and project `AGENTS.md` instructions?

OpenAI documents a global instruction layer under `CODEX_HOME` and a project instruction chain. CLROOM's Codex path blocks the known global instruction inputs for its clean launch.

## Why not use a separate `CODEX_HOME`?

Use one when you want a persistent alternate Codex home. CLROOM is aimed at a repeatable per-launch choice without maintaining another normal setup.

## Can I disable a Codex skill natively?

Yes. OpenAI documents persistent skill-disable configuration. That can be simpler for a permanent choice. CLROOM is aimed at per-launch selection.

## What about hooks, plugins, apps, and MCP servers?

Treat them separately by provider. They do not all share one universal scope model. CLROOM has provider-specific defaults; read the provider page and current limitations rather than assuming one generic rule.

## Can I keep different skill sets for planning, review, development, and fixes?

Yes. CLROOM supports reusable named skill sets so a chosen group of personal-global skills can be admitted for a launch. See [Skill sets](skill-sets.md) for practical examples.

## How do I create or edit a CLROOM skill set?

Run `clroom --help` to see the exact file path; it is normally `~/.config/clroom/skill-sets.yaml`. Create or edit that YAML directly, then use the group as `@set-name`. See [Skill sets](skill-sets.md) for examples of one set, multiple sets, and direct skills combined with sets.

## Is CLROOM useful across several projects or workflows?

It can be, especially when one permanent personal-global agent setup does not fit every kind of work. The goal is not to ban personalization; it is to make its participation deliberate for the launch.

## Is CLROOM a VM, container, or network sandbox for untrusted code?

No. Do not infer that from the product name. Read the existing threat model and limitations. The current release uses narrow macOS filesystem controls and is not a complete machine or network isolation product.

## What platforms are supported?

The current release documentation covers macOS on Apple Silicon and names exact
provider qualification targets. Linux, Windows, and Intel macOS are not
qualified by this release.

## Where should I verify provider behavior?

Use the official Anthropic and OpenAI links on the provider pages. Provider behavior changes, so consequential technical claims should be rechecked when upstream documentation or tested provider versions change.

## I do not know the right term for my problem. Where should I start?

Use the [coding-agent configuration problem index](problem-index.md). It starts from symptoms and common search language: old instructions, too many skills, project skills that still appear, context noise, safe mode, bare mode, restricted mode, CODEX_HOME, AGENTS.md, CLAUDE.md, hooks, MCP, runners, and reproducibility. From there, it routes to the relevant answer.
