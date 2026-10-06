---
layout: page
title: Coding-agent configuration problem index — Codex, Claude Code, skills, and MCP
description: Find canonical answers for Codex and Claude Code clean sessions, skills, stale memory, MCP runtime/tool problems, plugins, runners, native controls, and CLROOM.
permalink: /problem-index/
nav_title: Problem index
---
People rarely start by searching for **Clean Room Launcher (CLROOM)**. They start with a symptom, a flag they half remember, or a configuration problem:

- “Why is Codex following old instructions?”
- “How do I test one Agent Skill without the others?”
- “What is Claude `--safe-mode`, `--bare`, or `--restricted`?”
- “Why do I still see project or built-in skills after selecting one global skill?”
- “Can I keep my normal setup but run one cleaner session?”

This page routes those problems to the shortest correct answer. It also says when a native Claude Code or Codex feature is the better tool.

> CLROOM is not a replacement for Claude Code or Codex. It launches the installed provider CLI with a session-specific clean/selective setup on supported macOS systems.

The wording lists are diagnostic aids: expand them when you recognize a phrase but do not know the provider's exact term. They route many ways of describing the same problem to one canonical answer instead of creating near-duplicate pages. A phrase in those lists is not a compatibility claim; use the linked provider page for current behavior.

If you want the human explanation before the provider details, read [Why Clean Room Launcher (CLROOM) exists](why-clroom.md).

## Start from the closest symptom

- **Launch/integration:** [apps, runners, scripts, and CI](#apps-runners-and-ci), [different inputs per worker](#subagents-inherit-mcp-tools)
- **Skills:** [selected global skills](#only-selected-skills), [saved skill sets](#create-edit-and-combine-skill-sets), [shared symlinked skills](#symlinked-shared-skills), [Codex global vs repository skills](#codex-global-skills-keep-project-skills), [Claude plugin skill controls](#claude-plugin-skill-controls)
- **Claude Code:** [`--safe-mode`](#claude-safe-mode), [`--bare`](#claude-bare-mode), [`--restricted`](#claude-restricted), [`--setting-sources`](#claude-setting-sources), [`CLAUDE_CONFIG_DIR`](#claude-config-dir), [stale/auto memory](#claude-auto-memory), [subagent MCP/tools](#subagents-inherit-mcp-tools)
- **Codex:** [global `AGENTS.md`](#codex-agents-md), [`--ignore-user-config`](#codex-ignore-user-config), [`CODEX_HOME`/profiles](#codex-home-and-profiles), [skill scopes](#codex-skill-scopes), [plugin + MCP](#codex-plugin-mcp-composition), [inspect launch](#inspect-resolved-launch)
- **MCP/tools:** [tool/context overload](#mcp-tool-context-overload), [runtime environment/auth](#mcp-env-var-not-in-process), [configured but tools unavailable](#mcp-configured-tools-unavailable), [per-worker/subagent scope](#subagents-inherit-mcp-tools), [subagent cannot see MCP tools](#subagent-mcp-tools-missing)
- **Diagnosis:** [wrong-path/rework](#wrong-path-or-rework), [context noise](#context-noise-or-contamination), [stale Claude memory](#claude-auto-memory), [configuration drift/sync](#configuration-sync-vs-clean-launch), [prompt injection vs configuration contamination](#prompt-injection-vs-configuration-contamination), [testing/reproducibility](#testing-and-reproducibility), [what loaded](#what-loaded-into-the-session)
- **Trust/privacy/install:** [first-run/install failures](#install-first-run-failures), [what CLROOM sends, stores, or leaves provider-owned](#privacy-data-flow), [license and work/commercial use](#license-commercial-use), [verify release checksum, provenance, and SBOM](#verify-release-evidence), [prompt injection boundary](#prompt-injection-vs-configuration-contamination)
- **Version/freshness:** [current docs do not match an older release](#docs-vs-installed-release)

<a id="apps-runners-and-ci"></a>
## Is an app, runner, script, or CI job launching the coding agent?

**Common ways people ask this:**

- `spawn Codex without user config`
- `run Claude Code programmatically with clean config`
- `agent runner per-worker skills`
- `one runner for Claude Code and Codex`
- `clean Codex worker from CI`
- `different skills per agent worker`
- `drop-in Codex launcher`
- `drop-in Claude Code launcher`

Use [Agent runners](agent-runners.md) for the integration pattern and the provider pages for exact behavior. CLROOM supplies `clroom-codex` and `clroom-claude` as provider-facing entrypoints; qualification remains version- and path-specific.

<a id="symlinked-shared-skills"></a>
## Do you keep shared skills in a central repo and expose them with symlinks?

**Common ways people ask this:**

- `Codex symlink skills not discovered`
- `Claude Code symlink skills not discovered`
- `shared skills directory Claude Code Codex symlink`
- `share one Agent Skills repo with Codex and Claude Code`
- `central skills repo symlink`
- `selected symlinked skill clean launch`

See [Skill sets](skill-sets.md#symlinked-global-skills) and the provider-specific pages. CLROOM qualifies supported individual personal-global skill symlinks as both a discovery and filesystem-security case.

<a id="codex-built-in-and-project-skills"></a>
## Why does Codex still show built-in or project skills after I select one global skill?

**Common ways people ask this:**

- `CLROOM Global skills 1 but Codex shows more skills`
- `Codex built-in skills still visible`
- `project skill still visible with --skill-set`
- `Codex system skills vs global skills`
- `Codex project skills vs user skills`
- `why does job-flow still show with --skill-set=arrow`
- `provider skills visible in clean Codex`

CLROOM's **Global skills** count refers to the personal-global skills deliberately selected for that launch. Provider-owned/system skills and project-local skills are separate scopes and can remain visible by design. A useful falsifier is to launch from a sterile temporary directory: project-local skills should disappear there, while selected personal-global and provider-owned skills can remain.

**Go deeper:** [Codex](codex.md) · [Skill sets](skill-sets.md) · [FAQ](faq.md)

<a id="codex-ignore-user-config"></a>
## Do you need `codex exec --ignore-user-config` or a clean Codex `config.toml`?

**Common ways people ask this:**

- `codex --ignore-user-config`
- `codex exec --ignore-user-config`
- `clean codex config.toml`
- `Codex without user config`
- `Codex ignore config.toml for one run`
- `Codex exec clean user settings`

Use native `codex exec --ignore-user-config` for broad non-interactive user-config suppression. Use CLROOM when you also need its qualified selective project-preserving filesystem restrictions and selected-skill workflow; the same CLROOM isolation path also supports interactive Codex.

**Go deeper:** [Codex](codex.md) · [Limitations](limitations.md)

<a id="claude-restricted"></a>
## Should you use `claude --restricted` or CLROOM?

**Common ways people ask this:**

- `claude --restricted`
- `Claude restricted mode`
- `restricted vs CLROOM`
- `Claude Code eval harness shared machine`
- `Claude Code no project settings shared machine`
- `Claude Code restricted evaluation mode`

Claude Code `--restricted` is the native strong restriction for evaluation or shared-machine use from version `2.1.248+`. CLROOM is for selective launches that preserve project/local configuration while admitting chosen skills.

**Go deeper:** [Claude Code](claude-code.md) · [When to use CLROOM](when-to-use-clroom.md)

<a id="clean-or-fresh-session"></a>

## Need a clean or fresh coding-agent session?

**Common ways people ask this:**

- `clean coding agent session`
- `clean agent session`
- `fresh coding agent session`
- `fresh Codex session`
- `fresh Claude Code session`

<details>
<summary>More related wording and searches</summary>

- `start Codex clean`
- `start Claude clean`
- `clean room for coding agent`
- `minimal coding agent session`
- `vanilla coding agent session`
- `coding agent without my normal setup`
- `start coding agent without global config`
- `temporary clean agent setup`
- `isolated agent session`
- `reproducible coding agent session`
- `known clean agent environment`
- `clean baseline coding agent`
- `agent clean slate`
- `how do I start fresh without deleting my setup`
- `how do I test with a clean agent setup`

</details>

Use a native provider clean/minimal mode when you truly want broad customization off. Use Clean Room Launcher (CLROOM) when you want a repeatable clean/selective launch without deleting the setup you normally use.

**Go deeper:** [When to use CLROOM](when-to-use-clroom.md) · [Claude Code](claude-code.md) · [Codex](codex.md)

<a id="global-instructions-vs-current-work"></a>

## Are global instructions affecting the work in front of you?

**Common ways people ask this:**

- `disable global instructions for one session`
- `ignore global instructions temporarily`
- `coding agent using old instructions`
- `agent follows rules from another project`
- `why is my coding agent following unrelated instructions`

<details>
<summary>More related wording and searches</summary>

- `global instructions interfering with project`
- `global instructions leaking into another project`
- `personal instructions affecting repository`
- `remove global instructions without deleting them`
- `turn off global AGENTS.md temporarily`
- `turn off global CLAUDE.md temporarily`
- `Claude without global CLAUDE.md`
- `ignore ~/.codex AGENTS.md`
- `ignore ~/.claude CLAUDE.md`
- `global vs project instructions coding agent`
- `conflicting coding agent instructions`
- `agent instruction conflict`
- `wrong instructions loaded coding agent`
- `unrelated instructions loaded by Claude`
- `unrelated instructions loaded by Codex`

</details>

Claude Code and Codex both have persistent instruction/configuration layers. CLROOM is designed to keep known unrelated personal-global instruction inputs out of its launch while retaining the project-side context it is designed to keep. Use the provider pages for the exact scope.

**Go deeper:** [Claude Code](claude-code.md) · [Codex](codex.md) · [Configuration matrix](configuration-matrix.md)

<a id="only-selected-skills"></a>

## Do you want only selected global skills for this launch?

**Common ways people ask this:**

- `run with only selected skills`
- `choose skills per session`
- `only these skills for Codex`
- `only these skills for Claude Code`
- `disable all other skills temporarily`

<details>
<summary>More related wording and searches</summary>

- `test one skill without other skills`
- `skill isolation coding agent`
- `isolated skill test`
- `test Agent Skill cleanly`
- `test Claude skill in isolation`
- `test Codex skill in isolation`
- `skill set per task`
- `different skills for different projects`
- `many skills installed but use only a few`
- `too many skills coding agent`
- `skill bloat`
- `skills from other projects interfering`
- `temporary skill selection`
- `reusable skill groups Codex`
- `reusable skill groups Claude`
- `select global skills per launch`
- `global skills only when needed`
- `prevent unrelated skills from being discovered`
- `how to know which skill influenced the result`
- `test whether a skill actually improved output`
- `test skill alone vs skill set`

</details>

That is a core CLROOM use case. Select a personal-global skill or reusable skill set for one launch instead of letting every personal-global skill remain eligible by default. Project-local and provider-owned skills follow their own scopes.

**Go deeper:** [Use cases](use-cases.md) · [Skill sets](skill-sets.md) · [Claude Code](claude-code.md) · [Codex](codex.md) · [FAQ](faq.md)

<a id="create-edit-and-combine-skill-sets"></a>

## Do you want to create, edit, or combine reusable skill sets?

**Common ways people ask this:**

- `how do I create a skill set`
- `create CLROOM skill set`
- `create reusable skill group`
- `how to group Agent Skills`
- `where is CLROOM skill-sets.yaml`

<details>
<summary>More related wording and searches</summary>

- `where is skill-sets.yaml`
- `edit a CLROOM skill set`
- `add skill to CLROOM skill set`
- `remove skill from CLROOM skill set`
- `use multiple skill sets in one launch`
- `combine skill sets CLROOM`
- `combine a skill and skill set`
- `reusable skill sets Codex`
- `reusable skill sets Claude Code`

</details>

CLROOM supports named user-created skill sets so a repeatable group of personal-global skills can be selected per launch. The groups live in `~/.config/clroom/skill-sets.yaml`; CLROOM reads them when referenced and does not install the skills for you.

**Go deeper:** [Skill sets](skill-sets.md) · [Use cases](use-cases.md) · [FAQ](faq.md)

<a id="many-skills-and-token-concerns"></a>

## Do many installed skills mean too many tokens or too much context?

**Common ways people ask this:**

- `many skills tokens`
- `too many skills tokens`
- `do skills use context tokens`
- `skills context window`
- `skills context overhead`

<details>
<summary>More related wording and searches</summary>

- `skill descriptions context cost`
- `many Agent Skills context`
- `does installing more skills slow Claude`
- `does installing more skills slow Codex`
- `agent skills token cost`
- `skill metadata token cost`
- `too many skills overwhelming agent`
- `skill catalog bloat`
- `reduce skills context`
- `keep only relevant skills`
- `skills noise coding agent`
- `skill discovery overhead`
- `Claude skillOverrides`
- `Claude /skill-doctor`
- `disable-model-invocation`
- `hide Claude skill from context`

</details>

Not necessarily, and the answer is provider-specific. Current Claude Code documentation says full skill bodies load when invoked, while skills listed to Claude contribute their name/description to context on each turn. Claude now provides native controls such as `skillOverrides`, `disable-model-invocation`, and `/skill-doctor` for visibility and usage diagnosis. Codex has its own skill scopes and controls. CLROOM does not promise a fixed token saving; its stronger value is a repeatable launch boundary for which supported personal-global inputs can participate.

**Go deeper:** [FAQ](faq.md) · [When to use CLROOM](when-to-use-clroom.md)

<a id="wrong-path-or-rework"></a>

## Did the agent go down the wrong implementation path?

**Common ways people ask this:**

- `coding agent went down wrong path`
- `agent chose wrong implementation path`
- `Claude keeps implementing the wrong thing`
- `Codex keeps using wrong approach`
- `agent ignores project conventions`

<details>
<summary>More related wording and searches</summary>

- `agent behaves differently between projects`
- `agent made decision from old instructions`
- `why does my agent keep doing this`
- `coding agent unpredictable behavior`
- `coding agent inconsistent setup`
- `same prompt different result because config`
- `debug agent behavior caused by configuration`
- `configuration causing wrong tool call`
- `instructions causing rework`
- `agent setup causes rework`

</details>

Many causes are possible: repository instructions, local configuration, provider state, tools, models, or personal-global inputs. CLROOM gives you a cleaner comparison point for testing whether personal-global instructions or skills were part of the problem.

**Go deeper:** [FAQ](faq.md) · [When to use CLROOM](when-to-use-clroom.md)

<a id="context-noise-or-contamination"></a>

## Are you searching for “context pollution”, “prompt pollution”, or “agent context noise”?

**Common ways people ask this:**

- `context pollution coding agent`
- `context contamination coding agent`
- `context noise Claude Code`
- `context noise Codex`
- `prompt pollution coding agent`

<details>
<summary>More related wording and searches</summary>

- `instruction pollution`
- `irrelevant context coding agent`
- `agent context clutter`
- `too much agent context`
- `remove unrelated context`
- `reduce coding agent context noise`
- `clean context Claude Code`
- `clean context Codex`
- `global config contamination`
- `configuration contamination coding agent`

</details>

Those phrases are useful symptoms, but CLROOM makes a narrower technical claim. It controls known personal-global instruction and skill inputs for its launch; it does not claim that every kind of model context or provider state disappears.

**Go deeper:** [Configuration matrix](configuration-matrix.md) · [FAQ](faq.md) · [Limitations](limitations.md)

<a id="claude-safe-mode"></a>

## Should you use Claude Code `--safe-mode` instead?

**Common ways people ask this:**

- `claude --safe-mode`
- `Claude Code safe mode`
- `Claude safe mode vs normal`
- `safe mode vs CLROOM`
- `Claude disable all customizations`

<details>
<summary>More related wording and searches</summary>

- `Claude no config mode`
- `Claude clean config`
- `Claude vanilla mode`
- `Claude troubleshooting config`
- `Claude Code broken config`
- `Claude without skills hooks MCP`
- `Claude disable CLAUDE.md for one session`
- `CLAUDE_CODE_SAFE_MODE`
- `what does Claude safe mode disable`

</details>

Often, yes. If you want broad customization disabled for troubleshooting, Claude Code's native safe mode is the simpler answer. CLROOM targets the selective case where relevant project/local configuration can remain while ordinary personal-global inputs stay out and chosen global skills can be admitted.

**Go deeper:** [Claude Code](claude-code.md) · [When to use CLROOM](when-to-use-clroom.md)

<a id="claude-bare-mode"></a>

## Should you use Claude Code `--bare` instead?

**Common ways people ask this:**

- `claude --bare`
- `Claude Code bare mode`
- `bare vs safe mode Claude`
- `bare vs CLROOM`
- `Claude minimal mode`

<details>
<summary>More related wording and searches</summary>

- `CLAUDE_CODE_SIMPLE`
- `Claude skip auto discovery`
- `Claude scripted minimal mode`
- `Claude no hooks skills plugins MCP`
- `what does --bare do`
- `when to use --bare Claude`

</details>

Use native `--bare` when its minimal/script-oriented behavior matches the job. CLROOM is not the only clean-launch option; it is for repeatable selective composition without rewriting the normal setup.

**Go deeper:** [Claude Code](claude-code.md) · [When to use CLROOM](when-to-use-clroom.md)

<a id="claude-setting-sources"></a>

## Can Claude Code `--setting-sources` solve this natively?

**Common ways people ask this:**

- `Claude --setting-sources`
- `setting-sources project local`
- `Claude ignore user settings keep project`
- `Claude project settings without user settings`
- `Claude user project local settings`

<details>
<summary>More related wording and searches</summary>

- `Claude settings precedence`
- `Claude setting sources meaning`
- `Claude ~/.claude settings ignore`
- `keep CLAUDE.md project but ignore global CLAUDE.md`
- `Claude project only config`
- `Claude local settings vs project settings`
- `Claude Code configuration layers`

</details>

Sometimes. Claude Code can choose user/project/local filesystem setting sources directly. CLROOM uses provider-native controls plus its own launch behavior; if `--setting-sources` alone solves the problem, prefer the native flag.

**Go deeper:** [Claude Code](claude-code.md) · [Configuration matrix](configuration-matrix.md) · [When to use CLROOM](when-to-use-clroom.md)

<a id="claude-config-dir"></a>

## Would `CLAUDE_CONFIG_DIR` be simpler?

**Common ways people ask this:**

- `CLAUDE_CONFIG_DIR clean config`
- `temporary CLAUDE_CONFIG_DIR`
- `empty Claude config directory`
- `separate Claude config profile`
- `multiple Claude configurations`

<details>
<summary>More related wording and searches</summary>

- `Claude alternate config directory`
- `Claude different setup per project`
- `Claude config home`

</details>

Use an alternate Claude config directory when you want a persistent alternate configuration, but do not assume `CLAUDE_CONFIG_DIR` alone isolates every Claude input. CLROOM is aimed at session-specific clean/selective launches while the normal configuration remains in place.

**Go deeper:** [Claude Code](claude-code.md) · [When to use CLROOM](when-to-use-clroom.md)

<a id="claude-project-and-local-configuration"></a>

## What happens to Claude project and local configuration?

**Common ways people ask this:**

- `CLAUDE.md vs CLAUDE.local.md`
- `Claude project vs local instructions`
- `Claude settings.json vs settings.local.json`
- `Claude local config personal project`
- `Claude shared project configuration`

<details>
<summary>More related wording and searches</summary>

- `Claude project hooks vs user hooks`
- `does CLROOM keep CLAUDE.local.md`
- `does CLROOM keep project CLAUDE.md`

</details>

Current CLROOM intentionally retains Claude project and project-local setting sources. Read the provider page and limitations before assuming every customization behaves identically.

**Go deeper:** [Claude Code](claude-code.md) · [Configuration matrix](configuration-matrix.md) · [Limitations](limitations.md)

<a id="claude-auto-memory"></a>

## Is Claude Code carrying stale auto-memory or old `MEMORY.md` state into a fresh session?

**Common ways people ask this:**

- `Claude stale auto memory`
- `Claude Code MEMORY.md stale`
- `disable Claude auto memory one session`
- `Claude remembers old project state`
- `fresh Claude session without auto memory`

<details>
<summary>More related wording and searches</summary>

- `Claude memory from another session interfering`
- `Claude MEMORY.md wrong instructions`
- `Claude auto memory context`
- `Claude project memory stale`
- `Claude Code old memory loaded`
- `Claude memory across worktrees`
- `Claude memory shared between sessions`
- `Claude Code memory race`
- `test Claude without MEMORY.md`
- `Claude memory contaminating new session`
- `Claude auto memory disable temporarily`
- `why does Claude remember old repository state`
- `Claude memory stale after project changed`
- `Claude concurrent sessions memory conflict`
- `Claude worktree memory shared`

</details>

Claude Code auto-memory is provider-owned persistent state and has its own native controls and diagnostics. Use those when you want to inspect, edit, retain, or manage memory itself.

The current qualified CLROOM Claude path disables auto-memory for the clean launch. That makes CLROOM useful as a diagnostic comparison when the question is **"does this behavior disappear without auto-memory participating in this launch?"** It does not delete, rewrite, repair, expire, or synchronize Claude's stored memory files, and it does not make a claim about every other provider-owned state surface.

**Go deeper:** [Claude Code](claude-code.md) · [FAQ](faq.md) · [Configuration matrix](configuration-matrix.md) · [When to use CLROOM](when-to-use-clroom.md)

<a id="codex-agents-md"></a>

## Why is Codex reading global `AGENTS.md`?

**Common ways people ask this:**

- `Codex without global AGENTS.md`
- `Codex AGENTS.md global project`
- `global AGENTS.md vs project AGENTS.md`
- `Codex AGENTS.override.md`
- `Codex instruction hierarchy`

<details>
<summary>More related wording and searches</summary>

- `Codex instruction precedence`
- `why Codex reads ~/.codex/AGENTS.md`
- `ignore global AGENTS.md Codex`
- `temporary disable AGENTS.md`
- `project AGENTS.md plus global AGENTS.md`
- `Codex old global instructions`
- `Codex user instructions project instructions`
- `Codex global AGENTS.md relative links wrong path`
- `global AGENTS.md links resolve in project cwd`
- `Codex global instructions wrong working directory`

</details>

Codex has global instruction files under `CODEX_HOME` plus project instruction discovery. CLROOM's Codex path is designed to block the known global `AGENTS.md` / `AGENTS.override.md` inputs for its clean launch while retaining project instruction context.

**Go deeper:** [Codex](codex.md) · [Configuration matrix](configuration-matrix.md) · [When to use CLROOM](when-to-use-clroom.md)

<a id="codex-home-and-profiles"></a>

## Should you use `CODEX_HOME` or a Codex profile instead?

**Common ways people ask this:**

- `CODEX_HOME`
- `temporary CODEX_HOME`
- `different Codex home`
- `separate Codex configuration`
- `multiple Codex configs`

<details>
<summary>More related wording and searches</summary>

- `Codex profiles`
- `Codex profile per project`
- `Codex clean profile`
- `Codex alternate config`
- `Codex config.toml profile`
- `Codex profiles vs CLROOM`
- `CODEX_HOME vs CLROOM`
- `Codex without default config`
- `Codex profile disable global AGENTS.md`
- `Codex profile different global instructions`

</details>

Use native homes/profiles when you want a persistent alternate Codex setup or reusable configuration values. CLROOM is useful when the problem is per-launch control over known personal-global instructions and skills without maintaining another normal home.

**Go deeper:** [Codex](codex.md) · [When to use CLROOM](when-to-use-clroom.md)

<a id="codex-skill-scopes"></a>

## How do Codex user, repository, admin, and system skills relate to CLROOM?

**Common ways people ask this:**

- `Codex global skills`
- `Codex user skills`
- `Codex repo skills`
- `Codex admin skills`
- `Codex skill locations`

<details>
<summary>More related wording and searches</summary>

- `disable Codex skill temporarily`
- `Codex skills.config enabled false`
- `Codex only selected skills`
- `Codex .agents/skills`
- `~/.agents/skills Codex`
- `~/.codex/skills Codex`
- `Codex skills from other projects`
- `Codex skill precedence`

</details>

Codex skill scopes are separate from `AGENTS.md`. CLROOM's selected-skill workflow concerns personal-global skills admitted for one launch. Provider-owned/system skills and project-local skills remain separate concepts, and CLROOM should not be described as controlling every administrator or system skill mechanism.

**Go deeper:** [Codex](codex.md) · [Configuration matrix](configuration-matrix.md) · [Limitations](limitations.md)

<a id="hooks-plugins-mcp-and-apps"></a>

## Are hooks, plugins, MCP servers, or apps changing agent behavior?

**Common ways people ask this:**

- `disable coding agent hooks temporarily`
- `disable plugins one session`
- `disable MCP servers one session`
- `Codex apps hooks plugins off`
- `Claude hooks interfering`

<details>
<summary>More related wording and searches</summary>

- `Claude MCP conflict`
- `Codex hook conflict`
- `plugin changes agent behavior`
- `MCP changes coding agent behavior`
- `debug hooks plugins skills together`
- `clean launch without hooks`
- `clean launch without plugins`
- `clean launch without MCP`
- `why is this hook firing`
- `which plugin is affecting my agent`

</details>

They can, but Claude Code and Codex do not expose one universal scope model for all of them. CLROOM has provider-specific clean defaults and only makes activation claims for exact qualified paths. The current Codex path can admit one qualified whole plugin, one standalone stdio MCP, or the bounded pair together; that does not imply generic support for every upstream plugin/MCP package or transport. Use the provider pages for exact behavior and current non-claims.

**Go deeper:** [Claude Code](claude-code.md) · [Codex](codex.md) · [Configuration matrix](configuration-matrix.md)

<a id="claude-plugin-skill-controls"></a>

## Do you want to disable or evaluate one skill that came from a Claude plugin?

**Common ways people ask this:**

- `disable one Claude plugin skill`
- `Claude plugin skill individually disable`
- `skillOverrides plugin skill`
- `turn off skill from Claude plugin`
- `test Claude plugin skill without plugin`

<details>
<summary>More related wording and searches</summary>

- `Claude plugin skill off`
- `Claude /plugin manage skills`
- `Claude plugin eval skill`
- `evaluate plugin skill with and without plugin`
- `Claude skillOverrides does not affect plugin skill`
- `disable plugin skill keep plugin`

</details>

Current Claude Code documentation draws a real boundary here: `skillOverrides` applies to ordinary personal/project skills but does **not** control plugin-provided skills. Claude routes plugin management through `/plugin`, and `claude plugin eval` can compare a plugin skill with and without the plugin in isolated runs.

CLROOM's current Claude plugin path is whole-plugin and atomic. It does not promise component-level surgery that disables one skill while keeping the rest of the selected plugin active.

**Go deeper:** [Claude Code](claude-code.md) · [When to use CLROOM](when-to-use-clroom.md) · [Current limitations](limitations.md)

<a id="mcp-tool-context-overload"></a>

## Are too many MCP servers or tool definitions consuming context or slowing startup?

**Common ways people ask this:**

- `too many MCP tools context`
- `MCP context bloat`
- `MCP tool definitions context window`
- `MCP tools prompt too long`
- `too many MCP servers coding agent`

<details>
<summary>More related wording and searches</summary>

- `MCP servers slow startup`
- `Codex MCP startup slow`
- `Codex first turn blocked by MCP`
- `Claude MCP context warning`
- `Claude MCP tools context overhead`
- `reduce MCP tool context`
- `load only one MCP server for a task`
- `disable unused MCP servers for one run`
- `coding agent tool overload`
- `MCP tool schema overload`
- `MCP tool noise`
- `large MCP tools context`
- `MCP tools use too many tokens`
- `Claude /context MCP tools`
- `MCP tool schemas counted as messages`
- `global MCP starts every thread`
- `too many Codex MCP processes`

</details>

This is a real provider-scale problem, but the mitigation is provider-specific. Current Claude Code has native MCP Tool Search that defers tool definitions on supported paths and can use threshold modes such as `auto`; use that first when the problem is Claude tool-definition context overhead. OpenAI documents tool search in its API/agent runtimes too, but that must not be assumed to describe the qualified Codex CLI path.

CLROOM's narrower role is to provide its qualified clean/selective launch boundary and, on the current Codex path, deliberately admit one supported standalone stdio MCP when that is the resource the task needs. It does not claim universal lazy MCP loading, repair provider process-lifecycle bugs, or replace provider-owned subagent tool controls.

**Go deeper:** [Codex](codex.md) · [Claude Code](claude-code.md) · [Use cases](use-cases.md) · [Limitations](limitations.md)

<a id="mcp-env-var-not-in-process"></a>

## Is an MCP server configured but its token or environment variable missing from the active process?

**Common ways people ask this:**

- `Codex MCP bearer token env var missing`
- `MCP configured but env var missing`
- `MCP enabled but auth missing`
- `MCP server configured but token not in process`
- `MCP env var not inherited`

<details>
<summary>More related wording and searches</summary>

- `pass MCP env var to Codex`
- `Codex MCP config says bearer token but request unauthorized`
- `MCP works in config but not active session`
- `MCP server missing environment variable`
- `MCP auth environment not visible to process`
- `restart coding agent after setting MCP token`
- `MCP configured but tools unavailable`

</details>

A configuration file can name an environment variable without proving that the active provider process actually has a usable value. Treat configuration presence, process environment, authentication, and tool availability as separate states.

On CLROOM's qualified standalone Codex MCP path, referenced plain environment-variable **names** must also be explicitly admitted with `--pass-env=NAME`; CLROOM never stores or prints their secret values. That explicit admission does not turn unsupported remote/OAuth MCP forms into supported ones.

**Go deeper:** [Codex](codex.md) · [Use cases](use-cases.md) · [Current limitations](limitations.md)

<a id="mcp-configured-tools-unavailable"></a>

## Is an MCP server configured or connected, but its tools are still unavailable to the model?

**Common ways people ask this:**

- `MCP configured but tools missing`
- `MCP server connected but tools unavailable`
- `Codex MCP configured but tool_search missing`
- `Codex MCP visible in settings but not chat`
- `MCP client running but model cannot use tools`

<details>
<summary>More related wording and searches</summary>

- `MCP settings vs runtime tools`
- `MCP initialized but tools not callable`
- `MCP server healthy but tools absent`
- `Codex MCP connected no tool namespace`
- `Codex MCP tools disappeared`
- `MCP tool namespace missing`
- `tool_search missing MCP`
- `MCP works in TUI but not desktop`
- `MCP listed but model cannot call it`
- `configured MCP not exposed to model`
- `MCP connection ok tool discovery failed`
- `MCP runtime exposure failure`
- `MCP tools missing after model change`
- `MCP tools unavailable after provider update`
- `MCP config valid but session tools missing`

</details>

Configuration presence, server initialization, and model-visible tool availability are separate states. A provider can successfully read an MCP configuration or keep a connection alive while the active session still lacks the tool namespace or discovery mechanism needed to call those tools.

Use the provider's current MCP/status/tool-discovery diagnostics to establish the runtime state. CLROOM's qualified Codex resource path can prove the selected configuration and launch plan it owns, and `clroom inspect codex ...` can show that sanitized resolved plan before provider birth. Neither is a universal guarantee that every provider surface, model mode, desktop host, or later runtime state will expose the tool successfully.

**Go deeper:** [Codex](codex.md) · [FAQ](faq.md) · [Configuration matrix](configuration-matrix.md) · [Current limitations](limitations.md)

<a id="codex-plugin-mcp-composition"></a>

## Do you want one Codex plugin and one MCP server together for only this launch?

**Common ways people ask this:**

- `Codex plugin and MCP same session`
- `use one plugin and one MCP Codex`
- `temporary Codex plugin plus MCP`
- `Codex plugin MCP composition`
- `one run plugin MCP without editing config`

<details>
<summary>More related wording and searches</summary>

- `select Codex plugin per run`
- `select MCP server per run Codex`
- `Codex plugin MCP conflict`
- `Codex plugin includes MCP plus standalone MCP`
- `plugin MCP identity conflict Codex`
- `Codex plugin mcpServers`
- `Codex plugin .mcp.json`
- `Codex plugin.json mcp.json`
- `Codex plugin bundled MCP server`
- `inspect Codex plugin MCP launch`
- `Codex plugin MCP without changing config.toml`
- `Codex per session plugin and MCP`

</details>

On the exact qualified v0.5 Codex path, CLROOM can compose one already-installed whole plugin with one root-user standalone stdio MCP through the same typed resolved launch. Identity overlap, unsupported transports/fields, unqualified provider tuples, and source drift fail closed. This is deliberately not generic multi-plugin or multi-MCP support.

**Go deeper:** [Codex](codex.md) · [Use cases](use-cases.md) · [Configuration matrix](configuration-matrix.md) · [Limitations](limitations.md)

<a id="codex-global-skills-keep-project-skills"></a>

## Do you want Codex user/global skills out while keeping repository skills?

**Common ways people ask this:**

- `disable global Codex skills keep project skills`
- `Codex user skills off repo skills on`
- `project skills without user skills Codex`
- `ignore ~/.agents/skills keep repo skills`
- `Codex global skills context budget`

<details>
<summary>More related wording and searches</summary>

- `Codex disable user skills for one repo`
- `Codex keep .codex/skills but hide global skills`
- `Codex ~/.agents/skills vs .agents/skills`
- `Codex user skills interfering with project skills`
- `Codex only repository skills`
- `temporary disable Codex global skills`
- `Codex personal skills off for one run`
- `Codex project skill still available clean launch`

</details>

That scope distinction is central to CLROOM. Selected personal-global skills are launch inputs CLROOM can deliberately control on qualified paths, while repository/project and provider-owned skill scopes remain separate. Do not describe the result as “only one skill exists” when project or system skills can still be visible by design.

**Go deeper:** [Codex](codex.md) · [Skill sets](skill-sets.md) · [FAQ](faq.md)

<a id="subagents-inherit-mcp-tools"></a>

## Are subagents or agent-team workers inheriting MCP tools they do not need?

**Common ways people ask this:**

- `Claude subagent inherits MCP tools`
- `subagent prompt too long MCP`
- `per subagent MCP tools`
- `different MCP servers per worker`
- `coding agent worker tool isolation`

<details>
<summary>More related wording and searches</summary>

- `subagent inherits all MCP servers`
- `agent team MCP context bloat`
- `per agent MCP selection`
- `different tools per coding agent worker`
- `agent runner per-worker MCP`
- `agent runner per-worker plugin`
- `separate worker different skills and MCP`
- `coding agent subagent tool context overflow`
- `independent agent process tool isolation`
- `provider subagent inherited tools`

</details>

Provider-owned subagents and teammates follow the provider's own rules; CLROOM does not surgically rewrite them.

For current Claude Code, use native subagent controls first when the problem is inside one Claude session: `tools` / `disallowedTools` can narrow inherited tools, including MCP server-level patterns, and `mcpServers` can attach servers to the subagent. An inline subagent MCP can stay out of the parent conversation entirely.

If an external runner owns separate provider processes, each top-level process can instead get its own CLROOM launch. On the current Codex path, those separate launches can differ in the supported skill/plugin/MCP selections CLROOM qualifies.

**Go deeper:** [Agent runners](agent-runners.md) · [Use cases](use-cases.md) · [Limitations](limitations.md)

<a id="subagent-mcp-tools-missing"></a>

## Why can a Claude subagent fail to see MCP tools that work in the parent session?

**Common ways people ask this:**

- `Claude subagent MCP tools missing`
- `subagent cannot access MCP tools`
- `Claude Agent tool no MCP tools`
- `MCP works in parent not subagent`
- `custom subagent ToolSearch missing`

<details>
<summary>More related wording and searches</summary>

- `Claude custom agent MCP unavailable`
- `subagent mcpServers not working`
- `MCP tools missing in background subagent`
- `Claude subagent inherits tools inconsistently`
- `ToolSearch missing from custom subagent`
- `plugin subagent cannot use MCP`
- `Claude AgentDefinition MCP tools`
- `subagent tools frontmatter ignored MCP`
- `MCP available in main thread not child agent`
- `Claude subagent MCP inheritance bug`

</details>

This is provider-owned behavior, not something CLROOM can make universal from outside the running Claude session. Current Claude documentation exposes subagent `tools`, `disallowedTools`, and `mcpServers` controls, but real provider behavior has changed across versions and execution modes. If MCP works in the parent and disappears in a provider-owned subagent, reproduce it against the current Claude version and provider docs before treating it as a CLROOM launch failure.

Use separate top-level CLROOM processes when an external runner needs independently controlled workers. That gives each process its own CLROOM launch boundary; it does not patch Claude's internal subagent implementation.

**Go deeper:** [Claude Code](claude-code.md) · [Agent runners](agent-runners.md) · [When to use CLROOM](when-to-use-clroom.md) · [Current limitations](limitations.md)

<a id="inspect-resolved-launch"></a>

## Do you want to inspect what CLROOM will launch before the provider starts?

**Common ways people ask this:**

- `inspect Codex resolved launch`
- `show selected plugin MCP before launch`
- `what MCP will Codex start`
- `what plugin will Codex load`
- `dry run Codex plugin MCP`

<details>
<summary>More related wording and searches</summary>

- `machine readable coding agent launch plan`
- `JSON launch plan Codex`
- `inspect qualified Codex launch`
- `why did CLROOM reject plugin MCP`
- `show admitted env names without secrets`
- `verify Codex launch configuration before start`
- `inspect one run coding agent configuration`
- `resolved launch plugin MCP conflict`
- `Codex launch plan JSON`
- `preview coding agent launch without model call`

</details>

Use `clroom inspect codex ...` or its JSON form. Inspection resolves through the same typed launch-planning truth used by execution and exposes bounded identities, qualification decisions and admitted environment-variable names while redacting secret values, private source paths and provider argument values.

**Go deeper:** [Codex](codex.md) · [Use cases](use-cases.md) · [FAQ](faq.md)

<a id="different-projects-and-workflows"></a>

## Does one personal agent setup fit every project or workflow?

**Common ways people ask this:**

- `different coding agent rules per project`
- `global agent setup doesn't fit every project`
- `enterprise repo vs MVP agent rules`
- `coding agent config for multiple projects`
- `different skills per project`

<details>
<summary>More related wording and searches</summary>

- `different workflows per project`
- `switch coding agent setup by task`
- `frontend skills vs backend skills coding agent`
- `planning skills vs debugging skills`
- `task specific agent configuration`
- `reusable coding agent skill sets`
- `agent setup per workflow`
- `personal global rules conflict with repository rules`
- `thread level plugin MCP profile`
- `plugin profile per workflow`
- `MCP profile per workflow`
- `different plugins for coding design research`
- `choose tools before first model request`

</details>

Often it does not. CLROOM is useful when instructions or skills that help one kind of work should not automatically participate in another, while reusable selected skill sets can still be brought in for the launch that needs them.

**Go deeper:** [Skill sets](skill-sets.md) · [When to use CLROOM](when-to-use-clroom.md) · [FAQ](faq.md)

<a id="configuration-sync-vs-clean-launch"></a>

## Do you want one source of truth that keeps agent skills, MCP, or configuration synchronized?

**Common ways people ask this:**

- `sync coding agent config across tools`
- `one config for Codex and Claude Code`
- `sync MCP servers across agents`
- `sync Agent Skills between Codex and Claude`
- `coding agent configuration drift`

<details>
<summary>More related wording and searches</summary>

- `single source of truth coding agent config`
- `keep MCP config in sync across agents`
- `same skills on every coding agent`
- `manage agent config across machines`
- `Codex Claude config synchronization`
- `agent environment config drift`
- `central MCP configuration`

</details>

That is a **persistent configuration-management/synchronization** problem. CLROOM deliberately does not rewrite normal Codex or Claude Code configuration to make both providers share one persistent source of truth.

Use a configuration-management or provider-native synchronization approach when persistence and cross-machine convergence are the goal. Use CLROOM when the problem is narrower: keep the normal setup intact and choose the supported inputs for this **particular launch**.

**Go deeper:** [Why CLROOM exists](why-clroom.md) · [When to use CLROOM](when-to-use-clroom.md) · [Configuration matrix](configuration-matrix.md)

<a id="prompt-injection-vs-configuration-contamination"></a>

## Is this configuration contamination or prompt injection?

**Common ways people ask this:**

- `coding agent prompt injection vs bad config`
- `AGENTS.md prompt injection or configuration`
- `CLAUDE.md prompt injection`
- `MCP output prompt injection coding agent`
- `untrusted repository instructions coding agent`

<details>
<summary>More related wording and searches</summary>

- `clean session protect against prompt injection`
- `does CLROOM stop prompt injection`
- `malicious Agent Skill instructions`
- `malicious MCP tool output instructions`
- `repository prompt injection coding agent`
- `coding agent untrusted README instructions`
- `context contamination security vs configuration`

</details>

They are different threat classes.

CLROOM can help test whether **known personal-global configuration it controls** influenced a launch. It does **not** make repository files, project instructions, fetched pages, skills you deliberately admit, MCP/tool output, or other provider-visible data trustworthy. A malicious instruction in one of those channels can still be prompt injection.

Use the [Threat model](threat-model.md) for the security boundary. Keep provider sandbox/permissions, credential scope, network controls, source review, and normal prompt-injection defenses in place.

**Go deeper:** [Threat model](threat-model.md) · [Current limitations](limitations.md)

<a id="testing-and-reproducibility"></a>

## Are you trying to reproduce a bug or test whether a skill changed the result?

**Common ways people ask this:**

- `reproduce Claude Code bug clean environment`
- `reproduce Codex bug clean environment`
- `minimal repro coding agent`
- `test coding agent configuration`
- `test prompt without my config`

<details>
<summary>More related wording and searches</summary>

- `A/B test Agent Skill`
- `compare with and without skill`
- `verify skill changes result`
- `known baseline agent session`
- `reproducible skill testing`
- `coding agent regression test configuration`
- `is this provider bug or my setup`
- `configuration bisect coding agent`
- `debug coding agent customizations`
- `compare two Agent Skills on the same task`
- `compare same Agent Skill in Codex and Claude Code`
- `compare Agent Skill results token use and time`
- `coding agent eval clean baseline`
- `Claude Code eval clean environment`
- `Codex eval clean environment`
- `benchmark coding agent configuration`
- `benchmark Agent Skill`
- `agent eval configuration contamination`
- `reproducible coding agent benchmark`
- `A/B test coding agent setup`
- `evaluate skill without global config`

</details>

A clean/selective launch can provide a more repeatable baseline without destructive renaming or editing of the normal setup. It does not make model output deterministic, but it can remove known personal-global variables from the comparison.

**Go deeper:** [Use cases](use-cases.md) · [When to use CLROOM](when-to-use-clroom.md) · [FAQ](faq.md) · [Configuration matrix](configuration-matrix.md)

<a id="install-first-run-failures"></a>

## Did CLROOM install, but the first command still fails on macOS?

**Common ways people ask this:**

- `clroom command not found`
- `CLROOM installed but command not found`
- `~/.local/bin not in PATH macOS`
- `Apple cannot verify clroom`
- `CLROOM unidentified developer`

<details>
<summary>More related wording and searches</summary>

- `CLROOM Gatekeeper blocked`
- `CLROOM unsigned app macOS`
- `CLROOM unnotarized macOS`
- `macOS cannot check CLROOM for malicious software`
- `CLROOM wrong architecture`
- `CLROOM Apple Silicon only`
- `CLROOM arm64 required`
- `clroom codex command not found`
- `clroom claude command not found`
- `Codex not installed CLROOM`
- `Claude Code not installed CLROOM`
- `where did CLROOM install`
- `CLROOM ~/.local/bin`
- `CLROOM first run fails`
- `CLROOM install troubleshooting`
- `verify CLROOM after install`

</details>

Start with the exact installation contract:

1. the current release is qualified for **macOS on Apple Silicon**;
2. the one-line installer places `clroom`, `clroom-codex`, and `clroom-claude` in `~/.local/bin`;
3. if that directory is not in `PATH`, add it before treating the install as missing;
4. the Codex or Claude Code CLI you intend to launch must already work on its own;
5. the current archive is unsigned and unnotarized, so macOS policy can warn or refuse it.

Do not disable Gatekeeper globally to make CLROOM run. Verify the release identity/checksum/provenance first, follow local macOS or organization policy, and use Apple's normal per-app security flow only if you have independently decided to trust the exact downloaded release.

**Go deeper:** [Install](install.md) · [Verify a release](verify-release.md) · [Support](SUPPORT.md) · [Current limitations](limitations.md)

<a id="privacy-data-flow"></a>

## Does CLROOM send my code, collect telemetry, or need my API keys?

**Common ways people ask this:**

- `does CLROOM collect telemetry`
- `does CLROOM phone home`
- `does CLROOM send my code`
- `does CLROOM upload prompts`
- `does CLROOM need an API key`

<details>
<summary>More related wording and searches</summary>

- `does CLROOM read credentials`
- `does CLROOM copy Claude credentials`
- `does CLROOM copy Codex credentials`
- `does CLROOM store tokens`
- `does CLROOM have a backend`
- `does CLROOM require an account`
- `is CLROOM local only`
- `what network requests does CLROOM make`
- `does CLROOM track users`
- `CLROOM privacy`
- `CLROOM data collection`
- `CLROOM analytics`
- `CLROOM Cloudflare analytics`
- `does CLROOM upload repository files`
- `does CLROOM send prompts to its own server`
- `does CLROOM work offline`
- `CLROOM offline mode`
- `does CLROOM block provider network access`
- `does CLROOM expose MCP environment variables`
- `does clroom inspect show secrets`
- `CLROOM plugin data privacy`
- `CLROOM MCP data privacy`
- `coding agent launcher telemetry`
- `coding agent launcher privacy`

</details>

CLROOM is a local launch layer, not a hosted coding service. It does not require a CLROOM account, CLROOM API key, or CLROOM-hosted backend to start the installed provider. Provider authentication remains provider-owned.

That is **not** a promise that the whole session is offline or that no data leaves the machine. Codex, Claude Code, a selected plugin, or a selected MCP server can use the network according to their own behavior and configuration. The documentation website also has its own analytics surface, separate from CLI runtime behavior.

Use the canonical privacy/data-flow page for the exact separation between launcher behavior, provider authentication, selected-resource environment admission, installer/release downloads, and website analytics.

**Go deeper:** [Privacy and data flow](privacy-data-flow.md) · [Threat model](threat-model.md) · [Current limitations](limitations.md) · [Support](SUPPORT.md)

<a id="license-commercial-use"></a>

## Can I use CLROOM at work, and what license applies?

**Common ways people ask this:**

- `CLROOM license`
- `Clean Room Launcher license`
- `CLROOM MPL 2.0`
- `CLROOM open source license`
- `can I use CLROOM at work`

<details>
<summary>More related wording and searches</summary>

- `CLROOM commercial use`
- `CLROOM enterprise use`
- `does CLROOM require paid license`
- `CLROOM company use`
- `CLROOM commercial license`
- `CLROOM open source`
- `is CLROOM free software`
- `MPL 2.0 CLROOM`

</details>

CLROOM is distributed under the **Mozilla Public License 2.0 (MPL-2.0)**. The license text controls the rights and obligations for using, modifying, and distributing the software; this documentation is not legal advice.

The current project does not require a separate paid CLROOM account or commercial-edition license to run the CLI. That is separate from your organization's provider subscriptions, internal software policy, support requirements, or legal review.

**Go deeper:** [LICENSE](https://github.com/y-sor/clean-room-launcher/blob/main/LICENSE) · [Governance](https://github.com/y-sor/clean-room-launcher/blob/main/GOVERNANCE.md) · [Support](SUPPORT.md)

<a id="managed-enterprise-policy"></a>

## Can CLROOM override company-managed Claude Code or Codex policy?

**Common ways people ask this:**

- `Claude managed settings vs CLROOM`
- `Codex managed configuration vs CLROOM`
- `enterprise coding agent policy`
- `organization managed Claude settings`
- `organization managed Codex config`

<details>
<summary>More related wording and searches</summary>

- `can CLROOM bypass company policy`
- `does CLROOM override managed settings`
- `coding agent MDM settings`
- `enterprise skill restrictions Claude`
- `admin skills Codex`
- `managed hooks MCP Claude`

</details>

No. CLROOM must never be positioned as a policy bypass. If organization policy already removes personal customization, CLROOM may add little to ordinary daily work. Managed-policy interactions should remain explicit and conservative.

**Go deeper:** [Claude Code](claude-code.md) · [Codex](codex.md) · [Configuration matrix](configuration-matrix.md) · [Limitations](limitations.md)

<a id="keep-normal-setup-untouched"></a>

## Can you test a cleaner session without deleting or renaming your normal config?

**Common ways people ask this:**

- `test coding agent without changing config`
- `clean session without deleting config`
- `temporarily disable config without editing files`
- `don't rename ~/.claude`
- `don't rename ~/.codex`

<details>
<summary>More related wording and searches</summary>

- `keep my existing setup untouched`
- `one session different config`
- `temporary agent configuration`
- `session only agent settings`
- `try clean mode without breaking setup`
- `switch agent setup without reconfiguring`

</details>

Yes. That is a core CLROOM property: the change is launch-specific. The normal configuration remains on disk for other work.

**Go deeper:** [When to use CLROOM](when-to-use-clroom.md) · [FAQ](faq.md)

<a id="development-cost-tokens-and-rework"></a>

## Can configuration conflict increase development cost?

**Common ways people ask this:**

- `coding agent wasting tokens because instructions`
- `conflicting instructions token cost`
- `agent rework token cost`
- `reduce coding agent wasted tokens`
- `wrong tool call more tokens`

<details>
<summary>More related wording and searches</summary>

- `agent wrong path costs time`
- `coding agent instruction conflicts cost`
- `context cost vs rework`
- `many global instructions slow agent`
- `coding agent configuration overhead`

</details>

Yes, through the work it causes rather than through a guaranteed fixed context bill: an irrelevant or conflicting instruction can influence a decision, tool call, implementation path, rework, and another review/fix cycle. CLROOM's value claim stays on that mechanism, not a universal token-saving number.

**Go deeper:** [FAQ](faq.md) · [When to use CLROOM](when-to-use-clroom.md)

<a id="what-loaded-into-the-session"></a>

## How do you know what configuration or skills were active?

**Common ways people ask this:**

- `what config did Claude load`
- `what settings sources Claude loaded`
- `what instructions did Codex load`
- `show active Claude settings`
- `show active Codex instructions`

<details>
<summary>More related wording and searches</summary>

- `why is this skill active`
- `which skills are loaded`
- `which CLAUDE.md loaded`
- `which AGENTS.md loaded`
- `inspect coding agent configuration`
- `debug active coding agent config`
- `what influenced this agent session`

</details>

Use provider-native status or inspection tools where they exist, and CLROOM's launch summary for the controls CLROOM owns. For a selected Codex plugin/MCP launch, `clroom inspect codex ...` and the JSON output show the sanitized resolved launch that CLROOM itself would execute. No tool should claim it can enumerate every influence on a model response.

**Go deeper:** [Claude Code](claude-code.md) · [Codex](codex.md) · [FAQ](faq.md)

<a id="agent-skills-basics-and-testing"></a>

## Are you learning or authoring Agent Skills?

**Common ways people ask this:**

- `what are Agent Skills`
- `how do Agent Skills work`
- `Agent Skills progressive disclosure`
- `skill discovery activation execution`
- `where should I install Agent Skills`

<details>
<summary>More related wording and searches</summary>

- `global vs project skills`
- `personal vs project Agent Skills`
- `test my new Agent Skill`
- `skill creator testing`
- `skill author isolation`
- `skill compatibility Claude Codex`
- `skill author clean launch`

</details>

Start with the provider/Agent Skills documentation for the skill model itself. CLROOM becomes relevant when the next question is how to test a skill cleanly, compare with/without it, or keep unrelated personal-global skills out of the test launch.

**Go deeper:** [Use cases](use-cases.md) · [Skill sets](skill-sets.md) · [FAQ](faq.md) · [Claude Code](claude-code.md) · [Codex](codex.md)

<a id="docs-vs-installed-release"></a>

## Why do the current CLROOM docs describe something my installed release does not have?

**Common ways people ask this:**

- `CLROOM docs don't match installed version`
- `CLROOM feature missing in old release`
- `current docs vs CLROOM v0.5`
- `which CLROOM docs match my version`
- `old CLROOM release documentation`

<details>
<summary>More related wording and searches</summary>

- `CLROOM historical docs`
- `docs for exact CLROOM tag`
- `CLROOM version specific documentation`
- `provider docs changed since CLROOM release`
- `CLROOM current site newer than installed version`
- `what features were in CLROOM v0.4`
- `use docs from Git tag CLROOM`
- `AI answer mixed CLROOM versions`
- `search result shows old CLROOM docs`
- `CLROOM cached documentation stale`
- `CLROOM old GitHub Pages URL`
- `CLROOM repository moved`
- `CLROOM old namespace`
- `why does CLROOM search result use old URL`
- `CLROOM canonical repository`

</details>

The canonical website follows the current project state, and the canonical source repository is `y-sor/clean-room-launcher`. Historical Pages URLs can remain visible in search caches after a repository transfer because GitHub does not automatically redirect repository-associated Pages sites. A published Git tag preserves the documentation for that exact source snapshot. If the question names an older CLROOM version, use the README, provider pages, limitations, threat model, and configuration matrix from that exact tag instead of projecting current-site behavior backward.

**Go deeper:** [Documentation versions](documentation-versions.md) · [GitHub Releases](https://github.com/y-sor/clean-room-launcher/releases) · [Current provider support](providers.md)

<a id="verify-release-evidence"></a>

## Can you verify a CLROOM release before you run it?

**Common ways people ask this:**

- `verify CLROOM release`
- `verify CLROOM download`
- `CLROOM release checksum`
- `CLROOM provenance attestation`
- `CLROOM SBOM`

<details>
<summary>More related wording and searches</summary>

- `gh attestation verify CLROOM`
- `verify CLROOM GitHub release provenance`
- `CLROOM artifact attestation`
- `verify CLROOM install.sh`
- `CLROOM immutable release`
- `CLROOM checksum vs provenance`
- `CLROOM SBOM attestation`
- `is CLROOM release signed`
- `is CLROOM notarized`
- `CLROOM unsigned unnotarized`
- `is CLROOM safe to install`
- `verify coding agent launcher download`
- `software supply chain verify CLROOM`
- `verify release before curl pipe sh`
- `verify GitHub release Sigstore bundle`
- `has CLROOM been security audited`
- `CLROOM independent security audit`
- `CLROOM security certification`
- `CLROOM SOC 2`

</details>

Yes. The published release exposes separate evidence for separate trust questions: `SHA256SUMS` for byte equality, a tag-bound build-provenance bundle, a CycloneDX SBOM and SBOM attestation, plus GitHub's published release identity. The current macOS archive is still unsigned and unnotarized at the Apple code-signing layer, and none of these checks means the software is vulnerability-free. The current threat model also records that no independent security audit has been completed; provenance, OpenSSF badges, CI, or attestations must not be presented as an audit or certification.

Use the canonical [release verification guide](verify-release.md) for exercised commands and for the exact distinction between checksum, provenance, SBOM, immutable release state, provider qualification, and runtime/security non-claims.

**Go deeper:** [Verify a release](verify-release.md) · [Install](install.md) · [Security policy](https://github.com/y-sor/clean-room-launcher/security/policy) · [Threat model](threat-model.md)

## If your wording is different

You do not need to know the provider's exact terminology before using these docs. Start with the symptom: old rules, too many skills, a wrong implementation path, a clean baseline, a profile, a hook, MCP, a runner, or a setting you cannot place.

Search engines and AI systems can connect synonyms and related meanings. The related-wording lists above are there for recognition and routing; the technical answer stays singular and canonical. If the ambiguity is about terminology rather than a symptom, use the [CLROOM terminology glossary](glossary.md).

If the problem is still not answered, open an issue in the [CLROOM repository](https://github.com/y-sor/clean-room-launcher). A real unanswered question is more useful than another synthetic keyword page.

---

## Want the product explanation instead of another configuration detail?

Read [Why Clean Room Launcher (CLROOM) exists](why-clroom.md), then use [When to use CLROOM — and when not to](when-to-use-clroom.md) for the decision against native alternatives.
