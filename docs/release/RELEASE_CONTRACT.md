# CLROOM Release Contract v1

This document defines the public, executable release contract for Clean Room
Launcher. It is a release-safety contract, not a claim of certification or
formal compliance.

The private Owner/GPT permission flow remains outside the public repository.
This document describes product-facing evidence and fail-closed release
conditions only.

## Goals

A CLROOM release is acceptable only when all of these are true:

1. The complete delta since the authoritative latest published stable release has been reviewed.
2. The exact release candidate source is accepted and current.
3. Security, dependency, documentation, packaging, and release-workflow changes
   are represented in the changelog and public support claims.
4. Current real provider versions used by each maintainer-machine smoke match the
   exact pin for that behavior. Baseline clean-launch qualification and
   capability-specific qualification remain separate evidence.
5. Provider behavior is exercised manually on the maintainer machine.
6. Real-provider automated qualification runs against binaries extracted from
   the release archive, never only against sibling build outputs.
7. A tag is created only after accepted-main evidence is current.
8. The Draft Release is verified before publication, including an Owner-machine
   smoke of the exact draft archive bytes.
9. Publication is a separate explicit gate.
10. Post-publication identity, immutable GitHub Release attestation, assets, and installation are verified from the public release surface.
11. Every stable release performs a release-contract evolution review: new near-misses, manual steps, external behavior changes, and gates that passed despite real blockers are classified and either promoted to deterministic enforcement or explicitly retained as semantic/human gates.

## Release state machine

```text
WHOLE-RELEASE REVIEW
  -> PROVIDER REFRESH
  -> RELEASE CANDIDATE ACCEPT
  -> MERGE
  -> ACCEPTED-MAIN LOCAL ARTIFACT SMOKE
  -> TAG GATE
  -> TAG WORKFLOW
  -> DRAFT RELEASE
  -> EXACT DRAFT-ASSET LOCAL SMOKE
  -> DRAFT ACCEPT
  -> PUBLISH GATE
  -> PUBLISH
  -> PUBLIC INSTALL VERIFY
```

No later state implies an earlier one. In particular:

- merged != tagged;
- tagged != draft verified;
- draft verified != published;
- published != public install verified.

## 1. Whole-release review

Review from the previous published release tag to the candidate, not only the
last feature PR.

At minimum inspect:

- every commit;
- every changed file;
- runtime/source changes;
- dependency and lockfile changes;
- CI/release workflow changes;
- packaging/installer changes;
- security-policy changes;
- documentation/public claims;
- changelog coverage;
- provider qualification pins.

Use:

```sh
scripts/release/review-release-delta.sh <previous-tag> [candidate-ref]
```

Material changes absent from the release notes are a release blocker.

## 1a. Release review declaration and contract evolution

The current release declaration is `release/review.json`. It is public product
evidence, not permission.

The release-candidate workflow resolves GitHub `releases/latest` and requires
that exact stable tag to equal the declaration's
`previous_published_stable_tag`. An arbitrary older caller-supplied tag is not
sufficient.

`scripts/release/check-release-review.py` computes change classes from the
whole delta and fails closed when:

- a changed path has no known release classification;
- a computed change class is absent from the release declaration;
- required evidence for runtime, dependency, public-truth, security,
  provider, or release-pipeline changes is undeclared;
- the release contract changed but contract evolution is not declared;
- the release lacks a product-level strategic outcome.

Evidence IDs are closed, not free-form labels. Machine evidence such as full
regression, dependency SCA, exact artifact binding, attestations, real-provider
qualification, and the whole-release delta check must be bound by regression
tests to executable gates. Semantic evidence such as strategic fit, public-truth
review, security review, and contract-evolution judgment remains explicit
human/maintainer evidence and must not be presented as machine-proven.

Semantic review is nevertheless machine-bound to exact repository content. The
release declaration records `reviewed_content_digest`: SHA-256 over the
candidate's deterministic tracked-tree records (file mode, blob identity, and
path), excluding only `release/review.json` itself. Any code, documentation,
workflow, executable-bit, symlink, packaging, or other tracked-content change
therefore fails closed as `review-content-drift` until a fresh semantic review
updates the seal. Because the seal binds content rather than an ephemeral PR
commit identity, it survives the repository's squash-merge workflow without
weakening the reviewed bytes.

The machine check cannot decide semantic product strategy. human/maintainer review must
still determine whether the release materially serves the current product
roadmap and whether a discovered failure mode should expand the contract.
Repeated or high-risk deterministic failures should become machine gates rather
than checklist prose.

## 2. Provider freshness and version truth

Codex and Claude are fast-moving external providers. Stable CLROOM releases
therefore require a fresh maintainer-machine check immediately before tag approval.

The public qualification source is `release/qualification.json`. The code,
provider canary provisioning, qualification verification, README, SECURITY,
CHANGELOG, and relevant docs must agree with it.

Run:

```sh
python3 scripts/release/check-provider-version-sync.py
scripts/release/local-release-smoke.sh pretag \
  --plugin-id <qualified-installed-claude-plugin-id>
```

The pre-tag smoke reads the currently installed real provider versions.

For the pre-tag and Draft plugin-activation smoke, installed Claude must match
`plugin_activation_exact`. Baseline Claude clean-launch qualification remains
separately pinned to `clean_exact` and is reproduced by the release
canary/archive qualification lane. Those two exact versions may intentionally
differ.

If an installed provider needed by the current smoke differs from that
behavior's exact pin, stop. Do not reinterpret an older qualification as
current. Provider install/update/downgrade remains a separate maintainer action.
After any approved pin/provider change, update canary package integrity, code
constants, and public claims in a reviewed PR; rerun CI/release readiness and
the local smoke.

For a stable release, baseline clean launch and plugin activation must each have
evidence bound to their own exact provider/version contract; one cannot stand in
for the other.

The smoke must never install, update, downgrade, enable, or disable a provider
or provider plugin. Provider maintenance is an explicit maintainer action outside the
release script.

## 3. Release candidate freeze

After release-candidate acceptance, scope is frozen. Only release blockers may
change the candidate:

- correctness;
- security/privacy;
- integration/provider compatibility;
- build/CI/release;
- false public claims;
- broken first-use/install path.

Any source HEAD change invalidates exact-head review and all evidence bound to
the old HEAD.

## 4. Artifact binding

The release archive is the product that users receive.

Automated real-provider qualification MUST execute `clroom-codex` and
`clroom-claude` extracted from the created archive. Qualifying
`target/.../release/*` beside the archive is insufficient release evidence.

The exact archive must also pass a deterministic capability falsifier for the
new Claude plugin path: a synthetic installed skill-only plugin must produce
exactly one CLROOM-owned `--plugin-dir`, its admitted root must remain
read-only, and adding an unqualified hook surface must refuse before the fake
provider launch. This machine gate complements rather than replaces the
real-provider pre-tag and Draft smokes.

The archive must remain bound to:

- release version;
- source commit;
- target;
- Cargo.lock;
- packaging policy;
- NOTICE/SBOM/provenance inputs.

## 5. Accepted-main pre-tag local smoke

Because CLROOM uses squash merge, PR-HEAD bytes are not sufficient evidence for
the final source identity. After merge and post-merge verification, run the
pre-tag local smoke again on accepted `main`.

Required evidence:

- exact accepted-main SHA;
- archive SHA-256;
- macOS Apple Silicon;
- real Codex version;
- real Claude version;
- inference-free Claude clean and selected-plugin startup through Claude's
  provider-native `--init-only` path;
- interactive Codex TUI startup without a model request;
- interactive clean Claude TUI startup without a model request, with the
  selected plugin skill confirmed absent from autocomplete;
- interactive Claude selected-plugin TUI startup without a model request, with
  the selected plugin skill confirmed visible from autocomplete;
- the selected plugin is already installed and inventory-qualified as
  skill-only before provider launch;
- persistent provider configuration unchanged.

A failure is a release blocker. A provider-version mismatch returns to the
provider-refresh step.

## 6. Tag gate

Tagging is a separate one-shot release action.

Immediately before tag creation verify:

- accepted `main` has not moved;
- all required checks are green on the exact accepted source;
- pre-tag local evidence is PASS and bound to that source;
- provider versions still match the qualification pins, re-read from the
  installed provider binaries immediately before the irreversible push;
- the tag does not already exist;
- changelog date and version identity are correct.

Stable release tags MUST be annotated tags. The release workflow rejects
lightweight tags and binds the changelog release date to the annotated tagger
date.

Because the protected `v*` tag namespace cannot be updated or deleted through
normal project operation, the irreversible remote push must not be the first
place tag shape is validated. After the maintainer authorizes the tag action, use:

```sh
scripts/release/push-release-tag.sh vX.Y.Z <exact-accepted-main-sha>
```

The helper rechecks exact local/remote `main`, remote tag absence, active
repository tag policy, package/changelog identity, and creates and validates the
annotated tag locally before its single remote push. If the push transport
fails, the helper reconciles the remote tag object and peeled commit before
reporting failure or success; it never blindly repeats an irreversible
protected-tag creation. A safe exact local tag may be reused only after
authoritative reconciliation shows the remote tag was not created; any mismatch
fails closed.

Tag identity is version-first: `vX.Y.Z`.

The active repository tag ruleset for `refs/tags/v*` must restrict both update
and deletion with no bypass actors. Read-only CI and tag workflows verify the
structural rules that GitHub exposes to read-only callers. GitHub intentionally
withholds `bypass_actors` unless the caller can write the ruleset, so the
maintainer-authenticated pre-push and pre-publish helpers perform the strict
action-time proof that the same ruleset has no bypass actors. This split avoids
both false CI failures and false no-bypass claims.

Published releases should remain immutable; Draft assets are assembled and
verified before publication.

## 7. Draft Release gate

The tag workflow builds, verifies, attests, and creates a Draft Release.

Before publish, run the local smoke against the exact Draft Release archive:

```sh
scripts/release/local-release-smoke.sh draft \
  --tag vX.Y.Z \
  --plugin-id <same-qualified-installed-claude-plugin-id>
```

This phase downloads the draft assets with authenticated GitHub CLI, verifies
checksums and attestations when available, extracts the exact archive, and
repeats provider/manual startup checks against those exact public-candidate
bytes.

This is the final protection against a difference between source/build evidence
and the bytes that would be published. Draft smoke evidence seals the release
notes body and SHA-256 of every release asset, not only the main archive.

Evidence is invalidated by drift in any fact it depends on. Immediately before
the irreversible tag push, the helper refreshes remote main, remote tag absence,
the no-bypass tag ruleset, provider versions, and provider executable bytes.
Immediately before publication, the helper refreshes the tag source, strict tag
policy, immutable-release policy, provider versions/bytes, Draft release body,
and all six asset digests against the exact Draft-smoke evidence.

## 8. Publish gate

Publishing is a separate maintainer action after Draft verification. A failed or
timed-out publish request is reconciled against authoritative GitHub Release
state before any retry; exact published state is accepted as delivered, exact
unchanged Draft state requires a fresh action-time gate for a later retry, and
any other outcome stops as ambiguous.

Before publish verify:

- tag, annotated tag message when present, package version, changelog version,
  and GitHub Release title agree;
- Release title starts with the version token;
- expected assets are complete;
- SHA256SUMS passes;
- provenance and SBOM attestation bundles both verify;
- exact draft-asset local smoke is PASS;
- release notes match the final whole-release delta;
- the release is still draft/unpublished.

Prefer immutable releases for published CLROOM releases. Draft all assets first,
then publish once.

## 9. Post-publish verification

After publish verify from the public user path, not the workspace:

```sh
scripts/release/post-publish-smoke.sh vX.Y.Z
```

The smoke verifies:

- `releases/latest` resolves to the intended version;
- public `install.sh` downloads successfully;
- checksums/attestations verify;
- a clean temporary install produces `clroom --version` for the published
  version;
- at least one no-model provider startup succeeds from the installed public
  bytes.

If an immutable published release is wrong, do not rewrite its tag/assets.
Prepare a corrective release and communicate the defect.

## Evidence invalidation

| Change | Evidence invalidated |
| --- | --- |
| source HEAD | exact-head review, build, local smoke, tag readiness |
| Cargo.lock/dependency | SCA, SBOM, build, local smoke |
| packaging/release workflow | artifact, provenance, draft verification |
| provider version/binary | provider qualification, local smoke, version docs |
| qualification pins/docs | version-sync gate, release notes review |
| tag target | tag workflow, draft evidence |
| draft artifact digest/assets | checksums, attestations, draft local smoke |
| published asset/tag identity | corrective release required; do not silently mutate |

Evidence from an invalidated state MUST NOT be carried forward as PASS.

## Evidence storage

Public repository:
- this contract;
- qualification pins;
- executable review/smoke/sync scripts;
- CI/release gates.

Private control plane:
- Owner gates;
- exact accepted source;
- evidence summaries/digests;
- per-release decision ledger;
- no raw provider transcripts, credentials, machine paths, or private logs.

Google Drive planning:
- human-readable planning and continuity handoff;
- not a permission source and not product SSOT.

GitHub Draft/Release:
- archive;
- installer;
- SHA256SUMS;
- CycloneDX SBOM;
- provenance/SBOM Sigstore bundles;
- release notes.

## Minimal release evidence record

A private per-release ledger should record only sanitized facts:

- release version;
- previous published tag;
- accepted source SHA;
- whole-release review PASS;
- CI/release-readiness run identities;
- artifact SHA-256;
- Codex tested version;
- Claude tested version;
- selected benign plugin ID used for activation smoke;
- pre-tag local smoke PASS timestamp;
- tag SHA;
- Draft Release asset digest;
- draft local smoke PASS timestamp;
- publish approval;
- published release identity;
- public install verification.

Never store raw provider session IDs, prompts, transcripts, credentials, home
paths, or unrestricted environment dumps.

## Design references

These are design references, not compliance claims:

- [NIST SSDF SP 800-218](https://csrc.nist.gov/pubs/sp/800/218/final),
  especially release archival/provenance and secure testing;
- [SLSA v1.2](https://slsa.dev/spec/v1.2/) build provenance;
- [OpenSSF Scorecard](https://scorecard.dev/) branch protection, pinned build
  dependencies, token permissions, vulnerability and CI checks;
- [GitHub artifact attestations](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds),
  protected tags/rulesets, Draft Releases, and immutable releases;
- [Google SRE release engineering](https://sre.google/sre-book/release-engineering/):
  repeatable processes, canarying, and recovery.
