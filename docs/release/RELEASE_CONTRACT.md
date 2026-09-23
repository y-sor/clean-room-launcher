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
and candidate artifact/provider qualification. The protected tag helper runs
the final full contract check before the irreversible push. Post-tag automation
does not re-run the mutable whole-release contract; it consumes the already
accepted staged manifest and immutable tag identity.

## Contract evolution review

Every release must explicitly choose one:

- `EXPAND`: a new/repeated failure mode requires a new durable gate or evidence;
- `NO_CHANGE`: existing gates already detect all newly relevant failure modes,
  with a written rationale.

This is intentionally separate from ordinary CI. CI answers whether the current
candidate passes existing controls. Contract evolution asks whether the delta
made any existing control insufficient.

## Artifact integrity and pre-tag closure

A protected release tag is an irreversible identity boundary, not a test trigger.
All technically reproducible release blockers must be closed before the tag.

The exact PR candidate still receives the earliest available product/runtime
rehearsal before merge. After an accepted squash/merge, exact shipping bytes can
change because the archive records the accepted source commit. Therefore
accepted-main Release-candidate automation builds the future shipping archive
once, generates the installer copy, checksums, CycloneDX SBOM and release notes,
freezes the current provider registry/integrity decision, qualifies the provider
entrypoints extracted from that exact archive, and runs the real Codex whole-
plugin MCP runtime against that exact archive.

The same accepted-main workflow also rehearses the GitHub attestation mechanism
with the exact staged subjects before any tag exists. A successful workflow
uploads one content-addressed pre-tag stage artifact bound to the accepted source
SHA, source tree, reviewed-content digest, provider pins/integrities and exact
file digests. The tag gate resolves only a successful accepted-main workflow
artifact for that exact SHA.

Claude remains the one genuine local human-TTY boundary. Before tag creation,
the Owner runs the Claude stage smoke against the exact staged archive, not a
rebuild and not a Draft download. Its durable evidence binds the exact accepted
source/tree/review digest, Claude version/provider bytes and staged archive
SHA-256.

Provider latest is a pre-tag decision. check-provider-pins.sh resolves the
current npm stable tags and exact registry integrity during accepted-main
staging. Those provider inputs are frozen into the staged manifest/evidence.
After tag creation, release verification must not ask a mutable registry whether
the already accepted tuple is still latest; a later upstream release cannot
invalidate an already staged candidate.

Immediately before the single tag push, push-release-tag.sh refreshes only
genuinely mutable action-time state: accepted main, tag/release absence, the
active no-bypass v* ruleset, immutable-release repository policy, release
contract and the presence/binding of the complete staged evidence. No build,
provider provisioning, provider runtime, installer test or registry freshness
check executes after this final guard before the irreversible push.

Post-tag automation is promotion-only. It resolves the already accepted staged
bytes, creates tag-bound attestations for those same bytes, creates/refreshes a
guarded Draft, uploads only the accepted release-visible files, downloads the
Draft again and proves byte equality plus tag-bound attestation identity. It
must not rebuild, rerun tests, provision providers, execute Codex/Claude runtime
qualification, or call repository-admin policy endpoints.

A transient GitHub/network failure in tag-bound attestation, Draft creation,
upload or reconciliation is retried on the same protected tag with the same
accepted bytes. It does not justify moving the tag or consuming another version.
Any deterministic post-tag blocker that was technically reproducible pre-tag is
a release-harness escape.

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
documentation changes in the same reviewed candidate. Release-candidate and
pre-tag contract checks block until that coherence is restored. This keeps candidate
bytes deterministic and makes documentation drift a pre-release failure rather
than a post-test auto-write.

For whole-plugin activation:

1. **Pre-merge rehearsal:** the exact PR candidate is rehearsed before GPT ACCEPT.
   Claude runs locally because its selected-plugin TUI requires a genuine human
   terminal confirmation; its evidence stays outside the tracked tree. Codex runs
   automatically in the macOS Release-candidate workflow and proves the real MCP
   runtime plus post-runtime clean-state closure. This catches product/runtime
   failures at the earliest candidate boundary.
2. **Accepted-main exact-byte staging:** after merge identity is known, the
   Release-candidate workflow builds the future shipping archive once and runs
   generic provider qualification plus the Codex whole-plugin runtime against
   that exact archive. The Owner then runs the Claude stage TTY smoke against
   that same downloaded staged archive. The successful accepted-main Actions run
   plus Claude stage evidence form the blocker closure required by the tag gate.
3. **Action-time tag guard:** the helper validates the successful staged Actions
   artifact and local Claude stage evidence, verifies immutable-release policy
   with the Owner-authenticated gh, refreshes main/tag/release/ruleset/contract
   state and performs one protected tag push. It does not re-decide provider
   latest.
4. **Post-tag promotion:** the Release workflow performs only tag-dependent
   attestation, exact-byte Draft promotion and reconciliation. There is no Codex
   Draft runtime job and no Claude Draft runtime probe.
5. **Pre-publish:** the canonical local verifier confirms repository release
   immutability, exact tag/Draft identity, exact byte equality with the pre-tag
   manifest, tag-bound attestations, successful promotion workflow and preserved
   Claude stage evidence. It performs no rebuild or provider/runtime rerun.

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

Accepted Claude evidence is invalid unless the exact candidate/Draft artifact
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

A successful promotion workflow is necessary but not by itself the publish
verdict. Before an Owner publish gate, the canonical local verifier
scripts/release/verify-draft-release.sh must reconcile:

- exact protected tag and source SHA;
- successful accepted-main pre-tag stage for that SHA;
- exact staged manifest and staged shipping-byte digests;
- preserved Claude exact-stage TTY evidence;
- successful exact-tag Release promotion workflow;
- Draft identity, release notes and exact six-asset public set;
- byte-for-byte equality of archive, SHA256SUMS, SBOM and installer against the
  pre-tag manifest;
- release-visible tag-bound provenance and CycloneDX attestation bundles;
- repository immutable-release policy.

The verifier explicitly does not rebuild, run Codex or Claude, provision a
provider, or query npm latest. Those are pre-tag blockers and must already be
closed.

Use:

~~~sh
# Before merge: exact PR candidate, only Claude remains a local human-TTY gate.
bash scripts/release/local-plugin-activation-smoke.sh rehearse \
  --expected-head <exact-pr-head> --plugin-id <qualified-claude-id>

# Codex pre-merge rehearsal is produced automatically by the PR
# Release-candidate workflow.

# After merge and successful accepted-main staging, download the canonical stage
# and run Claude once against those exact future shipping bytes:
bash scripts/release/resolve-pretag-stage.sh \
  <version> <accepted-main-sha> <stage-dir>
bash scripts/release/local-plugin-activation-smoke.sh stage \
  --expected-head <accepted-main-sha> \
  --artifact <stage-dir>/clean-room-launcher-v<version>-aarch64-apple-darwin.tar.gz \
  --plugin-id <qualified-claude-id>

# Only after that evidence passes may the Owner authorize the protected tag.
# After tag-bound promotion creates the Draft:
bash scripts/release/verify-draft-release.sh v<version> <exact-tag-source-sha>
~~~

Local Codex smoke commands remain diagnostic/development tools only. Canonical
Codex pre-merge and exact-stage evidence is produced by macOS GitHub Actions;
ambient local Codex is not a release input.


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
