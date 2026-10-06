---
layout: page
title: CLROOM privacy and data flow
description: How CLROOM handles telemetry, credentials, provider-owned network behavior, MCP environment values, release downloads, and website analytics.
permalink: /privacy-data-flow/
nav_title: Privacy & data flow
---

# Privacy and data flow

**Short answer:** Clean Room Launcher (CLROOM) is a local launch layer. It does not require a CLROOM account, CLROOM API key, or CLROOM-hosted backend to start Codex or Claude Code. Provider authentication stays with the installed provider CLI.

That does **not** mean the whole session is offline or that no data can leave the machine. Codex, Claude Code, a selected plugin, or a selected MCP server can use the network according to their own behavior and configuration. CLROOM is not a network sandbox.

## Separate the surfaces

| Surface | What CLROOM claims |
| --- | --- |
| **CLROOM launcher** | Prepares the qualified clean/selective launch locally, resolves supported inputs, applies its launch restrictions, prints the local launch summary, and starts the installed provider CLI. |
| **Provider authentication** | Remains provider-owned. CLROOM does not ask for a separate provider credential or store a second copy of provider login state. |
| **Selected skills / plugins / MCP** | Selected resources can become readable or executable by the provider for that launch according to the qualified path. Their own behavior can include provider/tool network activity; CLROOM does not turn them into offline resources. |
| **MCP environment variables** | On the qualified Codex standalone-MCP path, referenced environment-variable **names** must be explicitly admitted with `--pass-env=NAME`. Literal MCP secret values are refused by that selector. CLROOM inspection/evidence may show admitted names, not secret values. |
| **Installer / release verification** | Installation and verification fetch release assets or attestations from GitHub. That download traffic is distinct from normal CLROOM launch preparation. |
| **Documentation website** | The public site is hosted on GitHub Pages and currently includes a Cloudflare Web Analytics beacon. GitHub documents host-level visitor IP logging for Pages security; the Cloudflare beacon is an additional website analytics surface. Both are separate from the CLROOM CLI runtime. |

## Does CLROOM collect product telemetry or phone home?

The current CLROOM launcher does not require a CLROOM telemetry service or CLROOM-hosted control plane to perform a launch.

The public documentation site is a different surface: it currently loads Cloudflare Web Analytics from `static.cloudflareinsights.com`. Do not infer website analytics behavior from the CLI, or CLI behavior from the website. GitHub also documents that GitHub Pages logs visitor IP addresses for security purposes. See [GitHub Pages data collection](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages#data-collection) and [Cloudflare Web Analytics](https://developers.cloudflare.com/web-analytics/) for the current hosting/analytics provider documentation.

If a future CLROOM release adds any launcher-side telemetry, hosted service, account requirement, update check, or new network client, that would be a material data-flow change and the documentation and release review must change with it.

## Does CLROOM read or copy my Codex / Claude credentials?

CLROOM does not ask you to paste provider credentials and does not create a separate CLROOM credential store. The launched Codex or Claude Code process continues to own its normal authentication/session behavior.

CLROOM's clean/selective controls are intentionally narrower than complete home-directory isolation. Read the [threat model](threat-model.md) and [current limitations](limitations.md) for the exact filesystem and provider-state boundaries.

## Does CLROOM upload my prompts, source code, or repository?

CLROOM itself is not a hosted coding service or proxy for model requests. It starts the installed provider CLI.

The provider process can still send prompts, tool results, repository context, or other data according to that provider's own product behavior, account settings, permissions, and tools. A selected MCP server or plugin can also have its own data flow. CLROOM does not claim to inspect or prevent every such transmission.

Use provider-native privacy, sandbox, permission, network, and enterprise-policy controls for those provider-owned questions.

## What does `clroom inspect` expose?

`clroom inspect ...` is designed to show the sanitized launch plan CLROOM owns. On supported paths it can expose selected identities, qualification decisions, boundary controls, and admitted environment-variable **names**.

It must not expose secret environment-variable values, provider credentials, or private source paths as part of the public inspection contract. Inspection is still not a universal inventory of everything the provider may later read or send.

## Is CLROOM offline?

Do not treat **offline** as a CLROOM support claim.

Some launch preparation is local, but:

- the provider may require authentication and network access;
- selected plugins or MCP servers can have their own network behavior;
- installation/update and release verification use GitHub-hosted assets/services;
- the documentation website is online and has its own analytics surface.

If you need a network-isolated environment, use an operating-system/container/network control designed for that purpose. CLROOM is not that control.

## Does CLROOM make MCP or plugin data safe?

No. Selecting one resource instead of inheriting a larger ambient set can make a launch easier to reason about, but it does not make the selected resource trustworthy.

MCP/tool output, plugin content, repository text, fetched web content, and other provider-visible data can still be malicious or sensitive. CLROOM is not a prompt-injection defense and does not replace provider permission/sandbox controls.

## What should I include in a support report?

Do not paste credentials, tokens, unrestricted environment dumps, private repository contents, prompts, transcripts, or home-directory listings into a public issue.

See [Support](SUPPORT.md) for the minimum useful report and [Security policy](https://github.com/y-sor/clean-room-launcher/security/policy) for sensitive vulnerability reports.

## Related trust pages

- [Threat model](threat-model.md)
- [Current limitations](limitations.md)
- [Verify a CLROOM release](verify-release.md)
- [Support](SUPPORT.md)
- [Configuration matrix](configuration-matrix.md)
