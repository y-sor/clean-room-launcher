# Changelog

All notable changes to Clean Room Launcher will be documented in this file.

The format is based on Keep a Changelog, and this project intends to use
Semantic Versioning after the first public release.

## [Unreleased]

## [0.4.2] - 2026-09-20

### Added

- Added `clroom codex --with=plugin:<provider-native-id>` for one exact
  already-installed Codex whole plugin per interactive launch. The selected
  bundle is projected into CLROOM's private shadow `PluginStore`, siblings stay
  absent, and activation is session-only.

### Changed

- Development/release stabilization now binds semantic release review to exact
  tracked content instead of commit ancestry, deduplicates branch CI against PR
  CI, cancels superseded runs, and runs release readiness automatically on
  accepted `main` pushes.
- Codex real-provider qualification now distinguishes configuration visibility
  from runtime capability and requires a standalone MCP `initialize` +
  `tools/list` boundary with a real fixture tool call.
- Advanced exact macOS Apple Silicon release qualification to current stable
  Codex `0.155.1` and Claude Code `2.1.278`.
- Release provider pins fail closed against live npm `latest` and registry
  integrity before canary provisioning and again at the protected tag boundary.
- Codex release qualification now proves provider-state lifecycle continuity:
  the generic real-provider canary starts Codex twice against the same synthetic
  home, and accepted-main pre-tag qualification performs a final clean launch
  after a real-provider MCP runtime probe on the same persistent CLROOM shadow.
- Pre-publish verification now reconciles the exact tag/SHA, Draft identity and
  asset set, checksums and attestations, provider pins, local pre-tag/Draft
  evidence, and every exact-tag GitHub Actions run before a publish gate.

### Fixed

- Make changelog/tag date validation monotonic: the candidate-declared release date may precede the real annotated tagger day, while future-dated entries still fail closed. This removes cross-midnight bookkeeping PRs without backdating the tag or weakening action-time checks.
- Make the canonical release contract, not only readiness CI, reject candidate versions that are not strictly newer than the latest published stable release and reject changelog dates earlier than that published baseline.
- Classify the app-owned `codex_app` MCP surface as host-required for
  standalone CLROOM instead of treating a visible server with zero tools as a
  qualified whole-plugin runtime.
- Remove ancestry-bound release-review resealing that created bookkeeping-only
  correction PRs after squash; release-review v2 carries explicit N−1 migration
  coverage and remains content-addressed across equivalent trees.
- Accept Codex `0.155.1` provider-owned `$CODEX_HOME/.tmp` lifecycle state,
  including `plugin-share-local-paths-v1.json` and
  `rollout-maintenance.lock`, after the CLROOM shadow is initialized while
  preserving fail-closed rejection of preexisting or unknown shadow state.
- Close the release-gate gap that allowed provider-written state created during
  the pre-tag Codex runtime probe to escape revalidation until the Draft artifact
  smoke.
- Block Claude Code 2.1.278 built-in `agents-md` from importing `AGENTS.md`
  or `.claude/AGENTS.md` above the nearest Git worktree boundary (or launch
  directory outside Git) while retaining repo-root and nested project AGENTS
  instructions when Claude starts from a subdirectory.

### Compatibility

- Codex whole-plugin activation remains limited to one provider-native plugin ID
  and the interactive CLROOM Codex path. Existing clean Codex and Claude launch
  behavior remains the default when no resource selection is requested.
- Standalone MCP restore, `--with=all`, multi-plugin selection, component-level
  plugin surgery, Linux, Windows, and Intel macOS remain outside this release.
- No runtime dependency was added or replaced.

### Security

- Codex activation revalidates provider/source identity around launch, projects
  exact captured bundle bytes only, rejects symlink/path/drift/sibling states,
  makes the projected bundle non-writable, and refuses overlapping raw Codex
  plugin/config activation controls.
- Protected tag creation requires lifecycle-aware Codex pre-tag evidence,
  including the post-runtime clean relaunch. Deleting provider-written state
  merely to make qualification pass is not accepted evidence.
- Claude pre-tag evidence now requires a real pinned-provider TUI confirmation
  that no external ancestor `AGENTS.md` was loaded; provider pin changes
  require fresh ambient-instruction-surface qualification.
- This release supersedes the unpublished v0.4.1 Draft candidate. v0.4.1 was
  never published and is not the installable latest release.

## [0.4.1] - 2026-09-20

### Added

- Added `clroom codex --with=plugin:<provider-native-id>` for one exact
  already-installed Codex whole plugin per interactive launch. The selected
  bundle is projected into CLROOM's private shadow `PluginStore`, siblings stay
  absent, and activation is session-only.

### Changed

- Advanced exact macOS Apple Silicon release qualification to current stable
  Codex `0.155.1` and Claude Code `2.1.278`.
- Release provider pins now fail closed against live npm `latest` and registry
  integrity before canary provisioning and again at the protected tag boundary.

### Compatibility

- Codex whole-plugin activation is limited to one provider-native plugin ID and
  the interactive CLROOM Codex path. Existing clean Codex and Claude launch
  behavior remains the default when no resource selection is requested.
- Standalone MCP restore, `--with=all`, multi-plugin selection, component-level
  plugin surgery, Linux, Windows, and Intel macOS remain outside this release.
- No runtime dependency was added or replaced.

### Security

- Codex activation revalidates provider/source identity around launch, projects
  exact captured bundle bytes only, rejects symlink/path/drift/sibling states,
  makes the projected bundle non-writable, and refuses overlapping raw Codex
  plugin/config activation controls.
- Release qualification requires clean → selected → clean Codex evidence,
  unchanged ambient provider/plugin state, current-stable provider bytes, and
  action-time provider revalidation before tag push.

## [0.4.0] - 2026-09-19

### Added

- Added `clroom claude --with=plugin:<provider-native-id>` for one exact
  already-installed Claude whole plugin per launch, using Claude's session-only
  plugin loading path without installing, updating, or persistently rewriting
  provider state.

### Changed

- Clarified interactive `clroom codex` as the primary Codex path while keeping
  `codex exec` for non-interactive automation; this is a documentation change,
  not a new Codex runtime path.
- Updated pinned CI checkout usage to `actions/checkout` v7.0.1 and added
  OpenSSF Best Practices status badges; these do not change shipped runtime
  behavior.
- Hardened public search/discovery metadata: the Limitations front matter is
  valid YAML, the site exposes a shorter SEO tagline, and project crawler/sitemap
  metadata is aligned with the host-root policy without changing the canonical
  URL set.
- Added Release Contract v1: every stable release is checked against the full
  delta from the latest published stable release, with fail-closed change
  classification, explicit contract-evolution review, exact tracked-content
  review sealing, and a local whole-release audit command.

### Compatibility

- Whole-plugin activation is exactly qualified for Claude Code `2.1.273` on
  macOS Apple Silicon. Baseline clean-launch exact qualification remains Codex
  `0.154.0` and Claude Code `2.1.272`; documented minimum accepted ranges
  remain Codex `0.147.0+` and Claude Code `2.1.223+`.
- Codex plugin activation, MCP resource selection, `--with=all`, presets, and
  component-level plugin selection remain outside this release.

### Security

- Selected plugin activation reuses provider inventory/selection truth,
  revalidates the exact active install root around launch, reopens only that
  root read-only, refuses overlapping raw `--plugin-dir`/`--plugin-url`
  activation, and leaves persistent Claude configuration unchanged.
- Activation inventory follows Claude provider-visible plugin surfaces, while
  v0.4.0 activation remains deliberately narrower: a matching plugin manifest
  identity plus only the default one-level `skills/<name>/SKILL.md` layout is
  qualified. Manifestless/root-single-skill/custom-skill-path bundles and
  slash-command, hook, MCP, agent, LSP, monitor, executable, or settings
  surfaces remain unqualified. Nested non-skill paths and identity are included
  in the fail-closed check, and qualification is revalidated immediately around
  launch.
- Updated the shipped `cap-std` / `cap-primitives` dependency from `4.0.2`
  to `4.0.3`, incorporating the upstream fix for
  `GHSA-hp8f-xmx4-4qrg` affecting trailing-slash symlink containment on
  platforms including macOS.
- Release qualification executes provider canaries against binaries extracted
  from the exact release archive and explicitly verifies both exported
  provenance and SBOM attestation bundles before Draft Release creation.

## [0.3.1] - 2026-09-17

### Added

- Added a pull-request Dependency Review lane that blocks newly introduced
  high/critical known-vulnerable dependencies while leaving existing
  `cargo-deny` advisory/license policy authoritative.
- Added dev/test-only `cargo-fuzz` harnesses and bounded PR smoke fuzzing for
  deterministic schema-admission and manifest-framing boundaries.
- Added release-visible Sigstore attestation bundles for build provenance and
  the CycloneDX SBOM, with verification bound to the release workflow and source
  identity.

### Changed

- Removed generic `Boundary`, `Boundary controls`, `Managed`, and `Model` launch
  diagnostics from normal interactive Codex/Claude presentation while
  preserving internal launch-contract classification and fail-closed behavior.
- Refreshed vulnerability-reporting guidance without claiming a private route
  when repository configuration cannot be verified from the public policy.
- Replaced GitHub CodeQL Default Setup with a repository-local Advanced Setup
  workflow covering GitHub Actions, Python, and Rust.

### Compatibility

- macOS on Apple Silicon remains the qualified release platform.
- Exact real-provider qualification targets remain Codex `0.154.0` and Claude
  Code `2.1.272`; documented minimum accepted ranges remain Codex `0.147.0+`
  and Claude Code `2.1.223+`.
- This patch does not expand Browser, operating-system, provider, credential,
  signing, or notarization support.

### Security

- Release readiness now carries the v0.3.1 version contract while preserving
  locked tests, dependency SCA, public-boundary checks, installer self-test,
  exact real-provider qualification, SBOM/provenance checks, and fail-closed
  artifact metadata validation.
- Release provenance is exported as verifier-consumable Sigstore bundles for
  the exact archive/SBOM/installer subjects; no long-lived signing secret is
  introduced.
- Fuzzing and Dependency Review are CI/test-only controls and add no shipped
  runtime dependency. The distributed macOS archive remains unsigned and
  unnotarized at the Apple platform-signing layer.

## [0.3.0] - 2026-09-17

### Added

- Added provider-state inspection through `clroom info codex`, backed by explicit
  catalog, resource, plugin-surface, selection, and selection-receipt handling.
- Added repository discovery checks plus OpenSSF Scorecard and Dependabot
  configuration for the public repository.

### Changed

- Moved the canonical public namespace and documentation/discovery URLs to
  `y-sor/clean-room-launcher` and `y-sor.github.io/clean-room-launcher`.
- Updated exact Claude Code release qualification to `2.1.272` while retaining
  Codex `0.154.0` as the exact Codex qualification target.
- Hardened release-candidate and tag-release provider provisioning so the
  verified npm tarball bytes are the exact local tarballs installed for real
  provider qualification.

### Fixed

- Added explicit Codex and Claude plugin-state handling and provider-state
  inspection coverage without weakening fail-closed launch behavior.
- Removed stale public control/execution-map residue and tightened the public
  repository boundary checks after the namespace transfer.

### Compatibility

- macOS on Apple Silicon remains the qualified release platform.
- Exact real-provider qualification targets are Codex `0.154.0` and Claude Code
  `2.1.272`; documented minimum accepted ranges remain Codex `0.147.0+` and
  Claude Code `2.1.223+`.
- Linux, Windows, Intel macOS, Homebrew, crates.io distribution, Apple signing,
  and notarization remain outside the qualified release surface.

### Security

- Release readiness continues to run locked tests, dependency SCA review,
  installer self-test, public-boundary checks, exact artifact metadata checks,
  real-provider qualification evidence verification, SBOM generation, and
  provenance verification before release gating.
- Apps, hooks, and plugins remain disabled by default. The distributed macOS
  archive remains unsigned and unnotarized.

## [0.2.1] - 2026-09-15

### Changed

- Updated the README, demo, and install guidance to present interactive
  `clroom codex` as the primary Codex launch path and the published GitHub
  installer as the normal installation path.

### Fixed

- Repeated Codex launches no longer fail with `CLROOM_CODEX_STATE_DIRTY` after
  supported Codex `0.154.0` creates legitimate provider-owned `cache` or
  `plugins` state inside an initialized CLROOM shadow home.

### Compatibility

- Exact real-provider qualification remains Codex `0.154.0` and Claude Code
  `2.1.263`; documented minimum accepted ranges remain Codex `0.147.0+` and
  Claude Code `2.1.223+`.
- This patch adds no platform expansion: macOS on Apple Silicon remains the
  qualified release platform.

### Security

- Capability-owned Codex state is accepted only inside a valid initialized
  CLROOM shadow home and only as real top-level directories; unknown roots,
  symlinks, and invalid entry types remain fail-closed.
- Apps, hooks, and plugins remain disabled by default. The distributed macOS
  archive remains unsigned and unnotarized.

## [0.2.0] - 2026-09-14

### Added

- Added a persistent clean configuration view for interactive `clroom codex`;
  native `--ignore-user-config` remains an exec-only enhancement.
- Selected symlinked global skills preserve canonical-target isolation and
  duplicate-source safety across the qualified provider paths.
- Codex exec launches with clean user configuration, provider-aware
  selected-skill inventory, and fail-closed filesystem restrictions.
- Drop-in `clroom-codex` and `clroom-claude` provider executables preserve native
  provider arguments, interactive process behavior, and exact `--pass-env=NAME`
  admission, with Claude parity and duplicate/invalid-name refusal.
- The release process binds sanitized real-provider startup evidence to Codex
  `0.154.0` and Claude Code `2.1.263`, alongside canonical release readiness,
  SCA verification, `SHA256SUMS`, a CycloneDX SBOM, provenance, and GitHub
  attestations.
- Added checksum-verified one-line macOS Apple Silicon installation from GitHub
  Releases without `sudo` or shell-configuration mutation.
- Strengthened documentation discovery assets for search engines and AI-facing
  documentation discovery without changing the supported runtime surface.

### Fixed

- Claude Code `2.1.257+` no longer rejects CLROOM's local selected-skill
  projection as a network path when the outer macOS Seatbelt policy is active.
  The fix preserves denial of sibling projection contents, unselected skills,
  provider state, credential roots, and writes to protected skill sources.

### Compatibility

- macOS on Apple Silicon is the qualified platform for `v0.2.0`.
- The exact real-provider qualification targets are Codex `0.154.0` and Claude
  Code `2.1.263`. The documented minimum accepted parser/runtime ranges remain
  Codex `0.147.0+` and Claude Code `2.1.223+`.
- Claude Code project and other ambient MCP configurations are not loaded by the
  default `v0.2.0` Claude launch. CLROOM starts Claude with
  `--strict-mcp-config`; MCP servers are considered only when explicitly
  supplied through Claude's own `--mcp-config` argument.
- Claude Code `-p` response-output semantics are not independently qualified by
  this release.

### Security

- The distributed macOS archive is unsigned and unnotarized.
- The archive records `qualification=CANDIDATE`; runtime qualification is kept
  as separately verified evidence bound to the exact candidate bytes rather
  than being self-asserted by the archive itself.
- Linux, Windows, Intel macOS, Homebrew, crates.io distribution, signing, and
  notarization are not claimed by `v0.2.0`.

## [0.1.0-alpha.4.2] - 2026-08-24

### Fixed

- Tag CI exposed a concurrent reaper/owner cleanup race; cleanup is idempotent
  only for an absent generated session leaf beneath the exact validated private
  layout, while unsafe ancestors and leaves remain fail-closed.

## [0.1.0-alpha.4.1] - 2026-08-24

### Changed

- Revalidated provider executable identity and version immediately before each
  launch, with a closed allowlisted parent environment and truthful launch
  status when the clean filesystem restrictions cannot be established.
- Hardened path, symlink, and selected-skill filesystem checks for the qualified
  macOS provider paths.

### Fixed

- Hardened Claude session projection ownership, stale cleanup, process exit,
  and signal handling; concurrent cleanup is idempotent only for a missing
  residue and remains fail-closed for other errors.

### Security

- This patch release adds no new operating-system or provider qualification:
  the supported claim remains macOS on Apple Silicon with Codex and Claude.

## [0.1.0-alpha.4] - 2026-08-23

### Added

- A `clroom claude` launch path with the same explicit one-launch skill
  selection used by Codex.
- Private, session-scoped Claude skill projections with normal-exit cleanup,
  proven-dead crash reaping, and parallel-session isolation.
- A Claude-specific launch plaque covering global instructions, selected global
  skills, user settings, auto memory, and project-local skills.

### Changed

- The project-skills card supports are centered beneath both provider plaques.
- Help, install guidance, provider support, and limitations now describe both
  qualified macOS provider paths.

### Fixed

- Abrupt terminal closure no longer creates indefinitely accumulating Claude
  projections: the next launch removes only residues whose owner is proven dead.

### Security

- Claude projections and owner markers use private modes, selected source skills
  remain read-only, and live, unknown, corrupt, or legacy state is never reaped.
- Linux and Windows remain explicitly `NOT_QUALIFIED`; this release makes no
  cross-platform isolation claim beyond macOS on Apple Silicon.

## [0.1.0-alpha.3] - 2026-08-22

### Added

- `clroom --version` and `clroom -V`, with the package version also visible in
  help and on the launch plaque.
- A conditional plaque card reporting valid project-local skills that remain
  available to Codex.

### Changed

- Help and the pre-launch review use a concise, adaptive presentation.
- The plaque reflects explicit user overrides for apps, hooks and plugins.

### Fixed

- Native Codex skill discovery can enumerate known roots while unselected skill
  contents remain outside the launch restrictions.
- Duplicate selected global skills resolve once using Codex root precedence.

### Security

- Discovery access is limited to root metadata and listing; unselected skill
  bodies remain unreadable.

## [0.1.0-alpha.2] - 2026-08-22

### Added

- One `--skill-set=` option for exact global skills, whole namespaces, exact
  `namespace:skill` skill names, reusable named `@sets`, and mixed selections.
- User-owned skill sets from `$XDG_CONFIG_HOME/clroom/skill-sets.yaml` or
  `~/.config/clroom/skill-sets.yaml`; Clean Room Launcher reads this file only
  when an `@set` is requested and never creates or rewrites it.

### Changed

- Project-local skills remain automatic while unselected global skills stay
  outside each launch.
- The launch plaque reports how many global skills were admitted.

### Security

- Unknown, malformed, nested, unsafe-path, and ambiguous skill choices fail before
  Codex starts.

## [0.1.0-alpha.1] - 2026-08-21

### Added

- `clroom codex [ARGS...]` for the locally installed Codex CLI on macOS/Apple
  Silicon.
- A macOS Seatbelt policy that blocks global Codex instructions and known
  ambient skill roots while retaining project access.
- Clean launch defaults for apps, hooks, plugins, developer instructions and
  notifications, with explicit user arguments retaining final priority.
- Deterministic unsigned macOS/arm64 archive and `SHA256SUMS` verification.

### Changed

- The pre-launch screen is a compact status plaque that reports the enforced
  filesystem restrictions and temporary Codex defaults without delaying exec.

### Deprecated

### Removed

### Fixed

### Security

- The launcher does not log in, read or copy credentials, retain prompts, or
  modify provider configuration.
