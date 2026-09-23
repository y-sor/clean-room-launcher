# Release Contract

CLROOM reviews releases as a whole product delta, not as the last pull request.

The authoritative baseline is the latest published stable GitHub Release. Before
tagging, the release candidate must classify every changed path since that
baseline, record a disposition for every changed release domain, record all
known near-misses, and decide whether the release contract itself must expand.

## What is machine-enforced

`scripts/release/check-release-contract.py` fails closed when:

- the declared baseline is not the current latest published stable release;
- the candidate version is not strictly newer than that published baseline;
- the candidate changelog date is earlier than the published baseline date;
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

Tracked candidate metadata must not predict a future action-time value merely to
make an irreversible gate pass. The changelog date is a candidate-declared
release date; the annotated tagger timestamp is the authoritative action-time
timestamp. The canonical contract requires the candidate version to be strictly
newer than the latest published stable baseline and the declared changelog date
to be on or after that baseline publication date. At tag time it enforces only
the monotonic upper relation `declared_date <= tagger_date`. Exact-day equality
is forbidden because crossing midnight would otherwise force a bookkeeping-only
candidate mutation. Future-dated changelog entries still fail closed, and the
actual tagger timestamp is never rewritten or backdated.

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
and candidate artifact/provider qualification. The protected-tag helper runs the
full contract check before the irreversible tag push; the tag workflow does not
become a second correctness gate.

## Contract evolution review

Every release must explicitly choose one:

- `EXPAND`: a new/repeated failure mode requires a new durable gate or evidence;
- `NO_CHANGE`: existing gates already detect all newly relevant failure modes,
  with a written rationale.

This is intentionally separate from ordinary CI. CI answers whether the current
candidate passes existing controls. Contract evolution asks whether the delta
made any existing control insufficient.

## Artifact integrity

Release acceptance has two pre-tag layers. The exact PR candidate first closes
every blocker that is observable before merge. After merge, accepted-main
readiness builds the future shipping archive once with the accepted source
identity embedded, qualifies provider launchers extracted from that exact
archive, exercises Codex whole-plugin runtime against that archive, generates
the shipping SBOM/checksums/release notes, and writes a content-addressed
`clroom.release-stage.v1` manifest. A separate accepted-main job rehearses the
GitHub attestation mechanism against those staged bytes.

The provider registry decision is frozen at accepted-main staging:
`scripts/release/check-provider-pins.sh` fresh-resolves npm `latest` and exact
registry integrity before canaries are provisioned. The staged manifest records
the accepted Codex/Claude tuple and integrity values. A later tag or Draft path
must not ask mutable registries whether that already-qualified tuple is still
`latest`; a provider move affects the next staging decision, not already
accepted bytes.

Claude remains the one genuine local TTY boundary. Before tag creation, the
Owner-authenticated stage smoke downloads/uses the exact staged archive and
records `phase=stage`, `evidence_binding=exact-release-artifact-v1`, the
accepted source SHA/tree, review digest, provider bytes, and shipping archive
digest. Codex stage runtime is produced automatically by accepted-main Actions.

Only after staged Codex evidence, local Claude stage evidence, the attestation
rehearsal, and the whole-release contract are complete may
`scripts/release/push-release-tag.sh` enter its action-time guard. That guard
refreshes `main`, confirms tag and Release absence, revalidates the active
no-bypass `v*` ruleset, verifies the repository Immutable Releases setting
with the Owner-authenticated `gh` session, and reruns the release contract.
No build, provider provisioning, registry-latest decision, provider runtime, or
permission-capability probe runs after that guard before the single tag push.

The tag-triggered Release workflow is promotion-only. It resolves the successful
accepted-main stage artifact for the exact tag source SHA, verifies all staged
digests, creates only the unavoidable tag-bound provenance/SBOM attestations,
creates the guarded Draft, uploads the exact accepted bytes, downloads them
again, and byte-reconciles the remote Draft. It does not rebuild, rerun tests,
rerun Codex/Claude, query provider `latest`, or query repository-admin policy.

A transient GitHub transport/API failure during tag-bound promotion is retried on
the same immutable protected tag after authoritative reconciliation; it is not a
reason to move the tag or consume another release number. Any deterministic
post-tag blocker that was technically reproducible before tag is a harness
escape.

## Public documentation version coherence

Every active release candidate must inventory semantic-version mentions across
the active public documentation surface. The canonical release checker compares
provider-version claims with `scripts/release/provider-pins.sh`, permits only
explicitly declared compatibility/version-floor exceptions, and fails closed on
stale or unclassified provider versions. Every exception must use a canonical
semantic-version key and a non-empty machine-checked rationale. Current-version product surfaces such as
the README and install/support matrices must not keep an older exact release
version after the candidate advances.

Historical release records remain historical: `CHANGELOG.md` and the version
history table in `SECURITY.md` are not rewritten merely because a new candidate
exists. Provider claims inside `SECURITY.md`, however, are still checked against
the current provider pins.

The release harness never edits documentation after provider tests. A provider
pin move must be accompanied by the required qualification evidence and matching
documentation changes in the same reviewed candidate. Release-candidate and tag
contract checks block until that coherence is restored. This keeps candidate
bytes deterministic and makes documentation drift a pre-release failure rather
than a post-test auto-write.

For whole-plugin activation:

1. **Pre-merge rehearsal:** the exact PR candidate is rehearsed before GPT ACCEPT.
   Claude runs locally because its selected-plugin TUI requires a genuine human
   terminal confirmation; its evidence stays outside the tracked tree. Codex runs
   automatically in the macOS Release-candidate workflow using the exact
   registry-integrity-pinned provider canary, proves clean → selected → clean MCP
   visibility through a task-owned standalone fixture, unchanged provider/plugin
   state, and a real provider PTY startup that reaches MCP initialize + tools/list.
   Successful Codex evidence is uploaded as a content-addressed GitHub Actions
   artifact and is the canonical Codex rehearsal transport. The harness sends no
   model prompt.
2. **Accepted-main stage closure:** the future shipping archive is built once from
   the accepted source SHA. Provider launchers extracted from that archive are
   qualified, Codex automatically repeats the whole-plugin MCP runtime against
   those exact bytes, the provider tuple is frozen into the stage manifest, and
   the attestation mechanism is rehearsed before tag. Claude then runs one local
   human-TTY `stage` smoke against that same archive and records the exact
   archive digest.
3. **Action-time tag guard:** the helper resolves and verifies the successful
   accepted-main stage, requires the local Claude stage evidence, checks tag/
   Release absence, no-bypass tag protection and Immutable Releases policy, then
   performs one protected tag push. It does not make a new provider-`latest`
   decision.
4. **Pre-publish:** the Draft verifier downloads the exact Draft assets, compares
   the four staged payload bytes against the accepted stage manifest, verifies
   tag-bound provenance/SBOM attestations, repository release immutability and
   every exact-tag workflow result. No provider/runtime/UI qualification is
   rerun after tag.

## Stateful provider lifecycle closure

A first successful provider startup is not sufficient evidence for a supported
stateful integration. When the provider can write durable state under a
CLROOM-managed or projected provider home, qualification must reuse the same
state root and prove the next supported launch still succeeds.

For Codex whole-plugin activation this means:

- exact-provider CI qualification executes two real-provider startups against
  the same synthetic home;
- exact-PR rehearsal executes
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
ambient input classes CLROOM claims to suppress. For Claude Code 2.1.280 the
built-in `agents-md` surface reads `AGENTS.md` and `.claude/AGENTS.md`
through ancestor directories. For Git projects, CLROOM uses the nearest real
(non-symlink) `.git` file or directory as the project instruction boundary;
outside Git it falls back to the launch directory. Those instruction names are
denied only above that boundary, so launching from a nested project directory
must still retain repo-root and nested project AGENTS files. Regression tests
must prove both the negative external-ancestor case and this nested-cwd positive
project case.

Accepted Claude evidence is invalid unless the exact candidate/staged shipping artifact
passes a synthetic launched-provider sandbox probe proving external ancestor
AGENTS.md and .claude/AGENTS.md are unreadable while project-local equivalents
remain readable. The probe must separately prove that the launched provider
body executed after version preflight; a provider `--version` success alone
cannot satisfy this evidence. Pre-merge rehearsal evidence additionally requires the real pinned-provider
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
`scripts/release/verify-draft-release.sh` must reconcile the exact protected
tag/source SHA, Draft identity and exact six-asset set, byte equality of the
four staged payload assets, tag-bound provenance/SBOM attestations, repository
Immutable Releases policy, the successful accepted-main stage artifact, and
every tag-triggered GitHub Actions run for that exact tag/SHA. It must not query
provider `latest`, rebuild, or rerun provider/runtime/UI qualification.

This verifier is read-only with respect to public release state. It does not
publish, edit, or replace release assets.

Use:

```sh
# Before merge, on the exact PR candidate HEAD, Claude remains the local
# human-TTY boundary:
bash scripts/release/local-plugin-activation-smoke.sh rehearse \
  --expected-head <exact-pr-head> --plugin-id <qualified-claude-id>

# Codex PR rehearsal is produced by the successful macOS
# Release-candidate workflow.

# After merge and successful accepted-main staging, download the exact staged
# archive and run the one local Claude stage TTY boundary before tag:
bash scripts/release/local-plugin-activation-smoke.sh stage \
  --expected-head <accepted-main-sha> \
  --artifact <path-to-staged-archive> \
  --plugin-id <qualified-claude-id>

# Codex exact-staged-byte runtime and attestation rehearsal are produced by the
# accepted-main Release-candidate workflow. Only after all stage evidence passes
# may the protected tag helper run.

# After tag promotion creates and byte-reconciles the Draft:
bash scripts/release/verify-draft-release.sh vX.Y.Z <exact-tag-source-sha>
```

Ambient local Codex installation state is never release-acceptance transport.
Canonical Codex PR rehearsal and accepted-main stage evidence come from
provenance-checked GitHub Actions artifacts described above.

Rehearsal evidence is content-addressed by the reviewed release digest plus the
exact Git tree and provider bytes. It may survive a squash only after
candidate-tree == accepted-tree verification; commit SHA remains provenance.
Dynamic local evidence is stored outside the tracked tree in the repository Git
common directory by default, while accepted-main staged bytes/evidence live in
content-addressed Actions artifacts. Normal task-worktree cleanup therefore does
not destroy the local Claude evidence. The tag helper refreshes only declared
action-time state after staged closure instead of rerunning provider/runtime
proofs solely because time passed.

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
