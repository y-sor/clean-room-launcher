<p align="center">
  <img src="docs/assets/brand/clroom-logo.png" width="80" alt="CLROOM logo">
</p>

<h1 align="center">Clean Room Launcher (CLROOM)</h1>

<p align="center">
  <a href="https://github.com/y-sor/clean-room-launcher/actions/workflows/ci.yml"><img src="https://github.com/y-sor/clean-room-launcher/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://www.bestpractices.dev/en/projects/14692/passing"><img src="https://www.bestpractices.dev/projects/14692/badge" alt="OpenSSF Best Practices Passing"></a>
  <a href="https://www.bestpractices.dev/en/projects/14692/baseline-1"><img src="https://www.bestpractices.dev/projects/14692/baseline" alt="OpenSSF Baseline Level 1"></a>
  <a href="https://github.com/y-sor/clean-room-launcher/releases/latest"><img src="https://img.shields.io/github/v/release/y-sor/clean-room-launcher?display_name=tag&sort=semver" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/y-sor/clean-room-launcher" alt="License"></a>
  <a href="docs/install.md"><img src="https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-lightgrey?logo=apple" alt="macOS Apple Silicon"></a>
</p>

<p align="center">
  <a href="https://y-sor.github.io/clean-room-launcher/">Documentation →</a> ·
  <a href="docs/demo.md">Read the clean-launch walkthrough →</a>
</p>

<p align="center">
  <a
    href="#use-the-global-skills-you-need-without-loading-the-rest"
  >Choose skills</a> ·
  <a href="#see-the-clean-launch-as-codex-starts">See the clean launch</a> ·
  <a href="#install">Install</a> ·
  <a href="#launch">Launch</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#trust-and-limitations">Trust and limitations</a> ·
  <a href="#frequently-asked-questions">FAQ</a> ·
  <a href="#remove">Remove</a>
</p>

## What?

> **A clean-room launcher for Codex and Claude Code on macOS.**

## Why?

> **One word instead of many long parameters.**<br>
> **Bring only the skills you need into your empty place.**

## Launch your coding agent without unrelated instructions and skills.

Coding-agent CLIs can load global rules, skills from other work, and forgotten
instructions from outside the current project. `clroom` keeps them out of this
launch while your project context stays available.

Your existing setup stays untouched.

Use the automatic clean launch immediately.

## Use the global skills you need without loading the rest.

Project-local skills are available automatically.

Global skills stay outside unless you add them for this launch.

```sh
clroom codex --skill-set=my-skill,@my-skill-set
clroom codex exec --skill-set=my-skill,@my-skill-set --approve-for-me

clroom claude --skill-set=my-skill,@my-skill-set

# Provider drop-in entrypoints for external launchers
clroom-codex --skill-set=my-skill --pass-env=NAME
clroom-claude --skill-set=my-skill --pass-env=NAME
```

Use skill names installed in your own setup.

### Skill sets

For the full practical guide, see [Skill sets](docs/skill-sets.md).

Run `clroom help skill-set` for skill-name, namespace, and saved-set examples.

Run `clroom --help` to see the exact skill-set file path. It is normally
`~/.config/clroom/skill-sets.yaml`.

Open it and create skill groups you can reuse by name:

```yaml
my-skill-set:
  - my-first-skill
  - my-second-skill

feature-planning:
  - superpowers:brainstorming
  - superpowers:writing-plans
```

<details>
<summary>Exact skill-choice behavior</summary>

- A bare `name` admits the logical global skill with that name, or every skill
  in a namespace with that name.
- `namespace:skill` admits one specific skill from a namespace.
- `@set-name` admits a saved group from the YAML file.
- Invalid or unknown skill choices stop before the selected provider starts.
- Selections apply to this launch only.
- Repeated and overlapping skill choices admit each logical skill once.
- If the same logical skill exists in multiple discovered roots, the provider's
  documented root precedence chooses one.
- Saved groups cannot include other saved groups.
- `clroom` reads the YAML file only when you use an `@set` and never creates or
  rewrites it.

</details>

## See the clean launch as Codex starts

Run `clroom codex --skill-set=my-skill,@my-skill-set` from the directory where
you want to work.

Before Codex takes over the terminal, Clean Room Launcher shows a compact
summary of the active filesystem restrictions:

- global Codex `AGENTS.md` files are blocked;
- unselected global skill contents stay blocked;
- apps, hooks, and plugins are off by default;
- developer instructions and notifications are cleared by default.

```text
╓──○──╖ ╭─ CLEAN ROOM ─ v0.4.0 ─────────╮
║░░░░░║⠒│                               │
║░░░░░║⠒│     Global AGENTS.md  off     │
║░░░░░║⠒│     Global skills    3 on     │
║░░░░░║⠒│     Apps              off     │
║░░░░░║⠒│     Hooks/plugins     off     │
║░░░░░║⠒│     Dev prompt        off     │
║░░░░░║⠒│     Notifications     off     │
║░░░░░║⠒│                               │
╙──○──╜ ╰───────────╥───────╥───────────╯
        ╭───────────╨───────╨───────────╮
        │     Project skills   2 on     │
        ╰───────────────────────────────╯
```

The main plaque reports the global restrictions and admitted global-skill count.
When project-local skills are present in `.agents/skills`, the separate card
shows how many remain available; with none, the card is omitted. Project
context and explicit Codex arguments remain available.

Interactive `clroom codex` starts the normal Codex TUI through the qualified
CLROOM isolation path. The non-interactive `clroom codex exec ...` path uses the
same CLROOM restrictions and also injects Codex's native
`--ignore-user-config` enhancement, which is exec-only.

## Install

Current release: macOS on Apple Silicon. Minimum accepted provider runtime:
Codex CLI `0.147.0+` or Claude Code CLI `2.1.223+`.

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/y-sor/clean-room-launcher/releases/latest/download/install.sh | sh
```

The installer verifies the downloaded release archive against `SHA256SUMS` and
installs `clroom`, `clroom-codex`, and `clroom-claude` to `~/.local/bin`. It does
not use `sudo`, edit shell startup files, install a service, or modify provider
state.

If `~/.local/bin` is not in `PATH`, the installer tells you what to add.

The macOS release archive is unsigned and unnotarized. Do not disable Gatekeeper
globally to run it.

See the [install guide](docs/install.md) for manual archive verification, Cargo
installation, removal, and provider checks.

## Launch

### Codex

Start Codex normally:

```sh
cd your-project
clroom codex
```

Add selected global skills for the same interactive launch:

```sh
clroom codex --skill-set=my-skill,@my-skill-set
```

Interactive Codex is the default path. Codex options you supply are forwarded
to the installed Codex CLI after CLROOM applies its clean launch defaults:

```sh
clroom codex --approve-for-me
clroom codex --enable apps --enable hooks --enable plugins
```

`--approve-for-me` is a Codex option. It keeps the Codex workspace sandbox and
routes eligible approval requests through its automatic reviewer. Availability
and reviewer behavior are controlled by the installed Codex version and
account.

Use `exec` when you specifically want Codex's non-interactive automation path,
for example from a script or CI job:

```sh
clroom codex exec
clroom codex exec --approve-for-me
```

The interactive and `exec` forms use the same CLROOM isolation path. CLROOM
additionally preflights and injects Codex's native `--ignore-user-config`
enhancement for `exec`; that flag is exec-only.

For provider diagnostics, use the top-level forms:

```sh
clroom codex --help
clroom codex --version
```

### Claude Code

Start Claude Code with the same clean launch:

```sh
cd your-project
clroom claude
```

Project-local Claude skills remain available automatically. Add selected
global skills for this launch with the same skill choice:

```sh
clroom claude --skill-set=my-skill,@my-skill-set
```

The v0.4.0 source can also admit exactly one already-installed whole Claude
plugin for one launch:

```sh
claude plugin list
clroom claude --with=plugin:plugin-name@marketplace-name
```

Use the provider-native qualified ID reported by Claude. CLROOM does not install
or update the plugin, and it does not change persistent provider enablement or
configuration. It resolves the
installed plugin root, reopens only that root read-only inside the Claude clean
launch, and asks Claude to load it for this session. Raw Claude
`--plugin-dir`/`--plugin-url` activation cannot be combined with a CLROOM
resource selection.

This whole-plugin path is currently an exact macOS Apple Silicon qualification
for Claude Code `2.1.273`. v0.4.0 deliberately qualifies a narrower subset of
Claude's plugin format: the installed provider-native ID must have a matching
`.claude-plugin/plugin.json` identity, and the observed effective components
must come only from the default one-level `skills/<name>/SKILL.md` layout.
Manifestless plugins, root `SKILL.md` single-skill plugins, custom skill paths,
slash commands, hooks, MCP servers, agents, LSP servers, background monitors,
plugin executables, or plugin settings may be observed by inventory but are not
activation-qualified in v0.4.0. They fail closed instead of receiving a broader
filesystem seam. The qualified bundle is still passed to Claude atomically;
CLROOM does not extract individual components.

Baseline clean-launch exact qualification remains Claude Code `2.1.272`; the
whole-plugin activation path is separately qualified on Claude Code `2.1.273`.
v0.4.0 does not add Codex plugin selection, standalone MCP selection,
`--with=all`, or component-level plugin surgery.

## How it works

1. **Resolve the provider locally.** Clean Room Launcher finds the installed
   `codex` or `claude` executable through `PATH`. It does not install or replace
   either CLI.

2. **Apply filesystem restrictions.** It creates a narrow macOS Seatbelt policy that
   denies reads of the provider's global instruction files and unselected
   ambient skill contents.

3. **Admit your selected skills.** Direct global skill names and named
   `@sets` composed with `--skill-set=` are readable for this launch only.
   Project-local skills remain available automatically.

4. **Apply clean defaults.** Codex starts with apps, hooks, and plugins off,
   empty developer instructions, and no notifications. Claude starts without
   global `CLAUDE.md`, user settings, or auto memory.

5. **Show the restrictions.** The launcher prints the compact `CLEAN ROOM` status
   plaque, admitted global-skill count, and a project-skill card when local
   skills are present.

6. **Launch the original CLI.** Codex retains native foreground terminal
   behavior. Claude is supervised only long enough to bind its private skill
   projection to the real consumer process and clean it safely on exit.

<details>
<summary><strong>Crash-safe Claude skill cleanup</strong></summary>

Each Claude launch gets a private, session-scoped skill projection. On a normal
exit, `clroom` moves that projection to quarantine and removes it.
If cleanup is interrupted, a later Claude launch retries only recognized
`clroom` state whose recorded consumer process is confirmed dead. Live,
unknown, malformed, and legacy state is left untouched. Cleanup removes
projection links, not your installed skill sources.

</details>

Clean Room Launcher makes no model request and performs no provider login before
the selected CLI starts.

## What it changes and what it leaves alone

| For this launch | Left unchanged |
|---|---|
| Global provider instruction files are unavailable | Those files remain untouched on disk |
| Unselected global skill contents are unavailable | Existing skills remain untouched on disk |
| Selected global skills are readable for one launch | No skill is copied, installed, or enabled permanently |
| Apps, hooks, and plugins are off by default | Explicit user arguments can re-enable them |
| Codex developer instructions and notifications are cleared by default; Claude global user settings and auto memory are not loaded | Provider configuration is not rewritten |
| The selected project remains available | Project files, Git history, and project instructions remain untouched |
| The provider starts with the launcher's filesystem restrictions | Installation, login, and provider state remain provider-owned |

Clean Room Launcher does not perform a separate provider login. Authentication
remains provider-owned.

## Trust and limitations

Clean Room Launcher provides focused context restrictions. It is not a virtual
machine, container, network sandbox, complete home-directory sandbox,
permission broker, coding-agent proxy, or hosted coding service.

Its macOS Seatbelt policy blocks the documented global instruction files and
the contents of known global skill roots, while allowing the root listing the
provider needs for discovery. It then admits only the resolved skill directories
you selected. Other project and host paths remain available unless macOS or the
provider applies another restriction.

The launcher does not make unsafe commands safe and does not replace provider
sandbox or approval controls.

Codex may display `Operation not permitted` when it probes a blocked global
`AGENTS.md` file. That warning is expected: the clean-room restrictions denied the
read. It does not mean Codex failed to start.

If the required macOS filesystem restrictions cannot be created, Clean Room Launcher
fails instead of silently starting a normal inherited Codex session.

See [the current limitations](docs/limitations.md) and
[security policy](SECURITY.md).

<details>
<summary><strong>Why not just use provider flags or profiles?</strong></summary>

Native provider controls may be the better fit when you only need one
provider's own configuration. `clroom` gives Codex and Claude Code one
repeatable way to launch: project-local context stays available, the documented
global inputs stay outside, and only the global skills you select are admitted
for that launch. It does not replace either provider or rewrite its saved
configuration.

See the official [Claude Code CLI reference][claude-cli-reference] and
[Codex configuration reference][codex-config-reference].

</details>

## Coding-agent support

The qualified macOS provider paths for this source tree are:

| Coding agent and launch path | Platform | Status |
|---|---|---|
| Codex CLI 0.154.0 — interactive `clroom codex` | macOS / Apple Silicon | Exact qualification target |
| Codex CLI 0.154.0 — `clroom codex exec` | macOS / Apple Silicon | Exact qualification target |
| Claude Code CLI 2.1.272 — interactive `clroom claude` | macOS / Apple Silicon | Exact clean-launch qualification target |
| Claude Code CLI 2.1.273 — `clroom claude --with=plugin:<id>` | macOS / Apple Silicon | Exact skill-only plugin-activation qualification target |
| Claude Code CLI `-p` response-output semantics | macOS / Apple Silicon | Not independently qualified |

Linux and Windows are `NOT_QUALIFIED`. Intel macOS, Homebrew, crates.io,
signing, and notarization are not qualified by the current release.

Additional coding agents and platforms may be considered later, but this README
makes no support claim for them.

## Documentation

For exact provider behavior, native alternatives, current limitations, and common problem wording:

- [Why CLROOM exists](docs/why-clroom.md)
- [Coding-agent configuration problem index](docs/problem-index.md)
- [When to use Clean Room Launcher (CLROOM) — and when not to](docs/when-to-use-clroom.md)
- [Use cases](docs/use-cases.md)
- [Skill sets](docs/skill-sets.md)
- [Claude Code and CLROOM](docs/claude-code.md)
- [Codex and CLROOM](docs/codex.md)
- [Configuration matrix](docs/configuration-matrix.md)
- [FAQ](docs/faq.md)
- [Limitations](docs/limitations.md)
- [Threat model](docs/threat-model.md)

The documentation intentionally recommends native provider features when they are the simpler correct option.

## Frequently asked questions

### Does it delete or rewrite my existing setup?

No. Existing instructions, skills, provider settings, and other projects stay where
they are. The filesystem restrictions apply only to the launched process.

### Does it remove all context from Codex?

No. Your selected project, project-local skills, and any global skills you
explicitly selected remain available. The provider also keeps its own built-in
behavior. Clean Room Launcher keeps the other specified ambient global inputs
outside this launch.

### Do I need another account or subscription?

No. Clean Room Launcher starts your existing CLI. Codex or Claude continues to
own its account, subscription, authentication, and provider connection.

### Does Clean Room Launcher read or copy my credentials?

No. Clean Room Launcher does not ask for provider credentials or store a
separate credential copy. The selected CLI continues to use its existing
provider authentication.

### Is this a complete operating-system sandbox?

No. It uses macOS Seatbelt to enforce a narrow filesystem denylist. It does not
block the network, isolate every home-directory file, or replace a VM or
container.

### Can I see what was cleaned?

Yes. The launch plaque shows the active restriction categories, admitted global
skills, and—when present—the project-local skill count before the provider starts.

This release does not provide a per-file review interface or compiled-context
manifest.

### Can I override the clean defaults?

Yes. Explicit Codex arguments can re-enable apps, hooks, and plugins or replace
the cleared Codex configuration values.

They do not disable the launcher's filesystem restrictions around global
instructions and unselected skill roots. Use `--skill-set=` with direct skill
names or named `@sets` for one launch.

### Why does Codex show `Operation not permitted`?

Codex may probe a global `AGENTS.md` file during startup. The warning proves
that the clean-room restrictions blocked the read. Review other errors normally.

## Remove

For an archive or one-line installation:

```sh
rm "$HOME/.local/bin/clroom" "$HOME/.local/bin/clroom-codex" "$HOME/.local/bin/clroom-claude"
```

For a Cargo installation:

```sh
cargo uninstall clean-room-launcher
```

These commands remove the installed binaries. They do not remove CLROOM-owned
provider support state such as Codex's `.clroom-clean-state-v1` directory.
There is no daemon, service, account, or system-wide configuration to remove.
Removing the binaries does not modify provider authentication.

## Project status

This source tree is prepared for `v0.4.0` on macOS Apple Silicon. See the
[latest GitHub release](https://github.com/y-sor/clean-room-launcher/releases/latest)
for publication status and downloadable artifacts. Real-provider qualification
is bound to the exact behavior-specific provider versions above. The macOS
archive is unsigned and unnotarized.

It supports the documented Codex interactive and exec paths, the ordinary
interactive Claude Code clean launch, and the bounded v0.4.0 Claude skill-only
whole-plugin activation path. Qualification is limited to the documented macOS
Apple Silicon paths.

External launchers can use `clroom-codex` or `clroom-claude` as their provider
executable override. See the [agent runner guide](docs/agent-runners.md).

## Help improve Clean Room Launcher

If Clean Room Launcher makes your coding-agent sessions easier to trust,
[star the repository](https://github.com/y-sor/clean-room-launcher).
It helps other Codex and Claude Code users find it.

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution process, acceptance
requirements, and local verification steps.

Report bugs or request features in
[GitHub Issues](https://github.com/y-sor/clean-room-launcher/issues).
For vulnerability reports, follow the private-reporting instructions below.

## Support CLROOM

If CLROOM belongs in your workflow, you can support continued development and testing:

- [Patreon](https://www.patreon.com/CLROOM)
- [Direct support](https://send.monobank.ua/jar/9UUyaEo717)


## Security

Please do not put credentials, private instructions, prompts, transcripts,
private paths, or exploit details in a public issue.

Use **Security → Report a vulnerability** in the GitHub repository. If private
reporting is unavailable, open a minimal public issue asking the maintainer to
provide a private channel.

This project does not offer a vulnerability bounty.

## License

Clean Room Launcher is open-source software under the
[Mozilla Public License 2.0](LICENSE).

Clean Room Launcher is an independent project and is not affiliated with or
endorsed by OpenAI or Anthropic.

[claude-cli-reference]: https://code.claude.com/docs/en/cli-reference
[codex-config-reference]: https://developers.openai.com/codex/config-reference
