---
layout: page
title: CLROOM terminology glossary
description: Canonical CLROOM terms for clean/selective launches, Agent Skills, plugins, MCP, workers, subagents, configuration scope, and qualified support.
permalink: /glossary/
nav_title: Glossary
---

CLROOM documentation uses a small set of precise terms because Codex, Claude Code, users, and integrators often use different words for similar-looking concepts.

Use this page when a search phrase, provider term, or CLROOM term seems ambiguous. The [problem index](problem-index.md) maps symptoms and alternate wording to canonical answers; this glossary maps terminology to the meaning used in CLROOM documentation.

## Launch terms

| Term | Meaning in CLROOM docs |
| --- | --- |
| **Clean launch** | A CLROOM launch in which the known personal-global inputs covered by the qualified path do not participate by default. It does **not** mean an empty home directory, no provider-owned state, or a security sandbox. |
| **Selective launch** | A clean launch plus explicit supported inputs for that run, such as selected personal-global skills or a qualified provider resource. |
| **Normal setup** | The provider configuration and personal setup you ordinarily use outside CLROOM. CLROOM aims to change the launch rather than rewrite that setup. |
| **Resolved launch** | The typed, sanitized CLROOM plan produced before provider birth for supported resource selection. On the current Codex path it can describe selected skills, one qualified plugin, one qualified standalone stdio MCP, environment-name admission, and relevant decisions. |
| **Inspect** | `clroom inspect ...` resolves the supported launch plan without starting the real provider session. It is for launch-plan review, not a claim that every possible influence on model behavior has been enumerated. |
| **Info** | `clroom info ...` reports provider/CLROOM capability and observation information. It is distinct from the resolved plan for a specific launch. |

## Configuration and scope terms

| Term | Meaning in CLROOM docs |
| --- | --- |
| **Personal-global / user-global** | User-level instructions, skills, or other supported inputs that normally apply across repositories or projects. CLROOM generally uses **personal-global** when discussing the scope it selectively controls. |
| **Project / repository-local** | Inputs that belong to the repository or project being worked on. These are intentionally distinct from personal-global inputs and can remain available in a clean launch when the qualified provider path is designed to retain them. |
| **Provider-owned / system** | Inputs or capabilities supplied by the provider itself rather than by the user's personal-global setup. A CLROOM global-skill count does not imply these disappear. |
| **Admin / managed / organization policy** | Provider or machine policy controlled by an administrator or organization. CLROOM does not claim to bypass it. |
| **Ambient state** | State that would normally be inherited or discovered from the surrounding user/provider environment. CLROOM only makes claims about the ambient inputs its qualified path explicitly controls. |

## Skills, plugins, and MCP

| Term | Meaning in CLROOM docs |
| --- | --- |
| **Agent Skill / skill** | A provider-recognized skill package or skill directory. Exact locations, discovery, and activation semantics differ by provider. |
| **Selected personal-global skill** | A supported personal-global skill deliberately admitted for one CLROOM launch. |
| **Skill set** | A CLROOM user-created named group of personal-global skills that can be selected together. It is not a provider-native plugin or MCP profile. |
| **Plugin** | A provider-native installed bundle. A plugin can contain provider-specific components; CLROOM support is narrower than every component a provider might understand. |
| **Whole-plugin selection** | CLROOM activates one supported installed plugin as an atomic provider-native bundle on a qualified path. It does not mean component-level plugin surgery. |
| **MCP server** | A Model Context Protocol server exposed to a provider. Transport, authentication, environment, scope, and lifecycle matter; "MCP enabled" is not one universal state. |
| **Standalone MCP** | An MCP definition selected independently rather than only as a component of a selected plugin. Current CLROOM qualification is provider-specific. |
| **Plugin-bundled MCP** | An MCP surface contributed by a plugin. It is distinct from CLROOM's standalone MCP selector even if both ultimately expose MCP tools. |
| **Tool context / tool overload** | User language for the cost or complexity created by large tool inventories or schemas. Provider-native tool search/lazy loading and CLROOM resource selection solve different parts of this problem. |

## Workers and subagents

| Term | Meaning in CLROOM docs |
| --- | --- |
| **Worker** | A separately launched top-level provider process. Different workers can have different CLROOM launch inputs because each process gets its own launch boundary. |
| **Provider-owned subagent / teammate** | An agent created inside an already-running provider session. Its tool/config inheritance follows that provider's own rules; CLROOM does not claim per-subagent surgery from outside the provider. |
| **Runner / orchestrator** | Software that starts or coordinates provider processes. CLROOM can sit underneath a runner as a launch layer; it is not itself the scheduler or orchestrator. |

## Evidence and support terms

| Term | Meaning in CLROOM docs |
| --- | --- |
| **Observed** | CLROOM or its tests can see that a provider object or behavior exists. Observation alone does not mean activation is supported. |
| **Qualified** | The exact provider/version/platform/path has passed the evidence required for the stated CLROOM support claim. |
| **Supported** | Publicly claimed behavior backed by the current CLROOM contract and corresponding qualification/evidence. |
| **Not qualified** | CLROOM does not make a support claim for that provider/path/combination in the current release, even if the upstream provider may support it natively. |
| **Provider tuple** | The exact provider version, platform, architecture, launch path, and other material dimensions to which qualification evidence is bound. |
| **Fail closed** | Refuse the launch or feature when CLROOM cannot prove the supported invariant instead of silently falling back to a broader inherited configuration. |

## Similar phrases that are not the same claim

### Context pollution vs configuration contamination

People use **context pollution**, **prompt pollution**, **context noise**, and similar phrases for many problems. CLROOM makes a narrower claim: it can control specific qualified personal-global launch inputs. It does not claim to remove every kind of model context.

### Configuration contamination vs prompt injection

A stale or unrelated instruction/configuration source can change agent behavior. Prompt injection is different: untrusted content attempts to manipulate the model through repository text, web pages, MCP/tool output, or another visible channel. CLROOM is not a prompt-injection defense.

### Clean launch vs sandbox

A CLROOM clean launch is a configuration/input boundary. The macOS isolation path protects specific filesystem inputs, but CLROOM is not a VM, container, network sandbox, or complete home-directory isolation product.

### Search phrase vs product term

The [problem index](problem-index.md) deliberately keeps many human search formulations such as "skill bloat", "MCP context bloat", or "why is this skill active". Canonical answer pages then use stable CLROOM/provider terminology so the same concept is not renamed from page to page.

## Go deeper

- [Why CLROOM exists](why-clroom.md)
- [When to use CLROOM — and when not to](when-to-use-clroom.md)
- [Configuration matrix](configuration-matrix.md)
- [Problem and search-language index](problem-index.md)
- [Codex and CLROOM](codex.md)
- [Claude Code and CLROOM](claude-code.md)
- [Current limitations](limitations.md)
- [Threat model](threat-model.md)
