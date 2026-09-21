# Release Contract

CLROOM reviews releases as a whole product delta, not as the last pull request.

The authoritative baseline is the latest published stable GitHub Release. Before
tagging, the release candidate must classify every changed path since that
baseline, record a disposition for every changed release domain, record all
known near-misses, and decide whether the release contract itself must expand.

## What is machine-enforced

`scripts/release/check-release-contract.py` fails closed when:

- the declared baseline is not the current latest published stable release;
- a changed path is not classified by the release contract;
- a changed domain lacks an evidence-backed disposition;
- a known near-miss lacks a disposition;
- contract expansion is declared without a durable promoted control;
- semantic product outcome is missing;
- the active review is not `clroom.release-review.v2` or still carries the
  legacy ancestry-bound `reviewed_through_commit` field;
- any tracked byte, executable mode, symlink, or semantic review declaration
  differs from the content-addressed review seal.

Release review is content-addressed, not commit-ancestry-addressed. Commit SHA
remains provenance, while acceptance binds to exact tracked content. Equivalent
reviewed content can therefore survive a squash after candidate-tree ==
accepted-tree verification, without a bookkeeping-only reseal PR. Mutable state
and action-time evidence are still refreshed separately.

The semantic review seal is a SHA-256 digest over the tracked Git tree
(mode/type/blob/path). The release review JSON participates through canonical
JSON semantics with only its self-referential `reviewed_content_digest` field
removed. The checker also carries an explicit v1 N−1 migration fixture proving
that v2 removes ancestry binding and requires a fresh content-addressed reseal;
the old ancestry-bound digest is rejected rather than silently reused. Changing source, docs, workflows, packaging, tests, scripts, file
modes, symlinks, dispositions, near-misses, product outcome, contract-evolution
decision, or capability gates therefore requires a fresh review seal.

Release-candidate readiness has two explicit lifecycle states. When the manifest
version still equals the latest immutable published stable release, readiness is
in `POST_PUBLISH`: historical review evidence is left untouched, governance,
negative-contract, regression, installer, and supply-chain checks still run, and
candidate-only whole-delta/artifact qualification is skipped. Once the manifest
version advances beyond that published release, readiness enters
`ACTIVE_CANDIDATE`: the full whole-delta release contract is required against
the latest published stable baseline, including a new versioned review snapshot
and candidate artifact/provider qualification. The tag workflow always runs the
full contract check for the exact tagged candidate.

## Contract evolution review

Every release must explicitly choose one:

- `EXPAND`: a new/repeated failure mode requires a new durable gate or evidence;
- `NO_CHANGE`: existing gates already detect all newly relevant failure modes,
  with a written rationale.

This is intentionally separate from ordinary CI. CI answers whether the current
candidate passes existing controls. Contract evolution asks whether the delta
made any existing control insufficient.

## Stable release metadata vs action-time state

Tracked candidate bytes must not depend on the wall-clock time at which an
irreversible release action happens. The changelog release heading is stable
content metadata and may be declared before the protected tag is actually
created. The annotated tagger timestamp remains the authoritative action-time
timestamp.

For a release version, the canonical release-date validator requires exactly one
well-formed ISO-date changelog heading and proves that the changelog date is not
later than the annotated tagger date. Equality is intentionally not required:
an operational delay across midnight must not force a bookkeeping-only content
change, a new candidate SHA, or fresh runtime qualification. Duplicate,
malformed, or future-relative-to-tag changelog dates fail closed. Both the local
protected-tag helper and the exact-tag Release workflow use the same validator.

## Artifact integrity

The release workflow qualifies the provider launchers extracted from the exact
release archive, not sibling build outputs. The archive, installer, SBOM,
checksums, provenance attestation bundle, and SBOM attestation bundle are
verified before a guarded Draft Release is created.

Publishing remains a separate action. Immediately before a protected tag
push, the tag helper refreshes the remote `main` tip, confirms the tag is still
absent, revalidates the active no-bypass `v*` tag ruleset, and reruns the
whole-release contract against the current published baseline. Any drift blocks
the push.

Because stable `v*` tags are protected against update/deletion, provider
capabilities with release-specific behavior are exercised on exact candidate
bytes before the irreversible tag/publish boundaries.

Before provider canaries or tag push, `scripts/release/check-provider-pins.sh`
fresh-resolves npm `latest` and registry integrity for the exact Codex and
Claude Code pins. A provider stable-version move blocks the release until pins,
qualification, and evidence are refreshed.

For whole-plugin activation:

1. **Pre-tag:** exact accepted `main` builds a candidate archive locally. Claude
   proves clean/selected plugin separation, its selected-plugin TUI, and that
   the pinned provider did not load AGENTS.md from an ancestor outside the
   selected current-project boundary. Codex proves clean → selected → clean MCP
   visibility through a task-owned standalone fixture, sibling absence through
   the runtime contract, unchanged ambient provider/plugin state, and a real
   provider PTY startup that reaches MCP initialize + tools/list. Before that
   PTY probe, the harness initializes a CLROOM-owned synthetic shadow, verifies
   its ownership marker, and records `trusted` only for the exact synthetic
   project so qualification never depends on scraping the trust UI. The harness
   sends no model prompt.
2. **Action-time tag guard:** the helper rechecks live stable provider pins and
   revalidates both local provider executable version/bytes against the accepted
   pre-tag evidence immediately before the protected tag push.
3. **Pre-publish:** repository release immutability must still be enabled, then
   the exact Draft Release archive is downloaded and its checksums/attestations
   plus the provider-specific automated capability probes are re-run.

## Stateful provider lifecycle closure

A first successful provider startup is not sufficient evidence for a supported
stateful integration. When the provider can write durable state under a
CLROOM-managed or projected provider home, qualification must reuse the same
state root and prove the next supported launch still succeeds.

For Codex whole-plugin activation this means:

- exact-provider CI qualification executes two real-provider startups against
  the same synthetic home;
- accepted-main pre-tag qualification executes
  clean → selected → clean → real-provider MCP runtime probe → clean on the same
  CLROOM shadow generation;
- the final post-runtime clean launch must succeed before evidence is
  accepted or a protected tag can be created;
- legitimate provider-owned state must not be deleted merely to make
  qualification pass;
- any newly admitted provider-state path requires exact pinned-provider
  evidence plus a negative test proving unknown or pre-existing unowned state
  still fails closed.

A provider version change invalidates this lifecycle evidence and requires fresh
qualification against the new exact provider tuple.

## Provider ambient-input surface closure

Provider version changes can add new instruction/configuration discovery
surfaces without changing CLROOM itself. Startup/version/byte checks alone are
therefore insufficient for a clean-launch claim.

For every newly pinned provider tuple, release qualification must re-prove the
ambient input classes CLROOM claims to suppress. For Claude Code 2.1.278 the
built-in `agents-md` surface reads `AGENTS.md` and `.claude/AGENTS.md`
through ancestor directories. For Git projects, CLROOM uses the nearest real
(non-symlink) `.git` file or directory as the project instruction boundary;
outside Git it falls back to the launch directory. Those instruction names are
denied only above that boundary, so launching from a nested project directory
must still retain repo-root and nested project AGENTS files. Regression tests
must prove both the negative external-ancestor case and this nested-cwd positive
project case.

Accepted Claude evidence is invalid unless the exact candidate/Draft artifact
passes a synthetic launched-provider sandbox probe proving external ancestor
AGENTS.md and .claude/AGENTS.md are unreadable while project-local equivalents
remain readable. The probe must separately prove that the launched provider
body executed after version preflight; a provider `--version` success alone
cannot satisfy this evidence. Accepted pre-tag evidence additionally requires the real pinned-provider
selected-plugin TUI to run inside a task-owned synthetic nested Git project and
confirm both sides of the boundary: repo/nested project AGENTS.md is reported as
loaded, while AGENTS.md and .claude/AGENTS.md above that Git project are not.
This prevents a permission-denied ancestor walk that drops all project
instructions from being mistaken for a clean PASS. A provider pin move requires
both the machine boundary probe and this real-provider instruction-surface
evidence to be refreshed before a protected tag can be created.

## Exact-tag pre-publish reconciliation

A successful Release workflow is not by itself a publish verdict. Before an
Owner publish gate, the canonical local verifier
`scripts/release/verify-draft-release.sh` must reconcile the exact tag and
source SHA, Draft identity and exact asset set, checksums and release-visible
attestations, current provider pins, accepted pre-tag and Draft provider
evidence, and every tag-triggered GitHub Actions run for that exact tag/SHA.
Any incomplete or non-success tag-triggered run blocks publication.

This verifier is read-only with respect to public release state. It does not
publish, edit, or replace release assets.

Use:

```sh
bash scripts/release/local-plugin-activation-smoke.sh pretag --plugin-id <qualified-claude-id>
bash scripts/release/local-codex-plugin-activation-smoke.sh pretag \
  --plugin-id <qualified-codex-id> --expected-mcp <plugin-mcp-name>

bash scripts/release/local-plugin-activation-smoke.sh draft \
  --tag vX.Y.Z --plugin-id <qualified-claude-id>
bash scripts/release/local-codex-plugin-activation-smoke.sh draft \
  --tag vX.Y.Z --plugin-id <qualified-codex-id> --expected-mcp <plugin-mcp-name>

# After both Draft smokes PASS, reconcile the complete exact-tag verdict:
bash scripts/release/verify-draft-release.sh vX.Y.Z <exact-tag-source-sha>
```

These smokes never install, update, enable persistently, remove, or downgrade a
provider/plugin. Claude's automated probe uses its established startup evidence
path. Codex configuration visibility is not runtime proof. Release qualification
uses a task-owned standalone MCP fixture with the real pinned provider and
requires provider startup, MCP `initialize`, `tools/list` with at least one
tool, and a real fixture tool call. `mcp list --json` remains a configuration
check only. The app-owned `codex_app` surface is classified
`PLUGIN_HOST_REQUIRED` in standalone CLROOM and cannot satisfy this gate.

## Local audit

To inspect what is actually in the candidate relative to the last published
release:

```sh
scripts/release/local-release-audit.sh
```

For the full local test/build/artifact pass:

```sh
scripts/release/local-release-audit.sh --full
```

For an `ACTIVE_CANDIDATE`, the summary prints the authoritative published
baseline, the complete commit list, every changed file and its release domain,
the contract-evolution decision, artifact capability gates, and the
dependency/version diff. Full mode additionally runs the public-boundary check,
installer self-test, all locked tests, builds a candidate archive, verifies its
metadata, and prints its SHA-256.

For `POST_PUBLISH`, the same historical review snapshot is not rewritten or
reapplied as if it covered new bytes. The audit binds to the immutable published
baseline, reports the dependency/version delta, and full mode runs the local
regression/security checks but skips candidate-only artifact construction until
the manifest advances to a new release version.

Local audit complements GitHub CI and real-provider/draft-artifact evidence; it
does not grant merge, tag, or publish permission.
