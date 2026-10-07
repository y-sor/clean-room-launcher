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

Release-candidate readiness has three explicit lifecycle states. When the manifest
version still equals the latest immutable published stable release, readiness is
in `POST_PUBLISH`: historical review evidence is left untouched, governance,
negative-contract, regression, installer, and supply-chain checks still run, and
candidate-only whole-delta/artifact qualification is skipped. Once the manifest
version advances beyond that published release and its candidate tag is still
absent, readiness enters `ACTIVE_CANDIDATE`: the full whole-delta release
contract is required against the latest published stable baseline, including a
new versioned review snapshot and candidate artifact/provider qualification.

If that advanced manifest version already has a consumed protected tag, the
manifest identity is no longer eligible for another release regardless of
whether the current source still equals the tag source. Readiness enters
`RELEASE_QUARANTINED`. This state is a release-boundary circuit breaker, not a
repository-wide development freeze: ordinary source, docs, CI and maintenance
changes continue through the normal protected PR gates, while stale review
sealing and candidate artifact/provider lanes for the consumed identity remain
disabled. The consumed tag may not be moved, deleted, reused or published as a
repair path. Canonical tag creation still fails closed because a new tag must be
absent immediately before the one-shot action. The next fresh manifest version
with no existing protected tag returns to `ACTIVE_CANDIDATE` and must complete
the full whole-release contract over the complete published-baseline delta.

This separation keeps `RELEASE_SYSTEM_QUARANTINE` attached to the consequential
release boundary where it belongs. It must not be reimplemented as a path
allowlist for normal development; normal protected PR gates remain authoritative
for merge safety, while release eligibility remains fail-closed until a fresh
release identity satisfies the full release topology.

The protected tag helper runs the final full contract check before any new
irreversible tag push. Post-tag automation does not re-run the mutable
whole-release contract; it consumes the already accepted staged manifest and
immutable tag identity.

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
entrypoints extracted from that exact archive, and runs both the real Codex whole-
plugin MCP runtime and the bounded whole-plugin + standalone-MCP composition
runtime against that exact archive.

The same accepted-main workflow also rehearses the GitHub attestation mechanism
with the exact staged subjects before any tag exists. A successful workflow
uploads one content-addressed pre-tag stage artifact bound to the accepted source
SHA, source tree, reviewed-content digest, provider pins/integrities, exact
provider executable SHA-256 digests and exact file digests. The tag gate resolves only a successful accepted-main workflow
artifact for that exact SHA.

Workflow execution semantics are part of the release contract, not incidental
filesystem metadata. Every repo-local script invoked directly by a GitHub Actions
workflow must either be tracked executable in Git or be invoked through an
explicit interpreter such as `bash` or `python3`. Canonical readiness runs a
repository-wide workflow/script mode contract with negative fixtures so a
non-executable direct invocation fails before provider provisioning.

After accepted-main staging completes, a separate Ubuntu
`Release promotion rehearsal` workflow resolves the exact accepted stage using
the same explicit `bash scripts/release/resolve-pretag-stage.sh` invocation used
by the tag-triggered Release workflow. Because this rehearsal runs inside the
same accepted-main workflow run that produced the stage, it may opt the resolver
into that exact current run only through `CLROOM_PRETAG_CURRENT_RUN_ID`. The
resolver then independently requires GitHub Actions, the same run id, trusted
`push` on `refs/heads/main`, the exact source SHA/repository, and completed
success for eligibility, readiness, exact-byte staging and pre-tag attestation
before downloading the artifact. The tag-triggered Release workflow is forbidden
from setting this exception and continues to accept only a fully
`completed/success` accepted-main run. A deterministic admission self-test
covers completed-run acceptance, current-run acceptance, wrong event/SHA,
missing binding, failed completed runs, and missing/failed upstream jobs in the
cheap eligibility lane before provider provisioning. The protected tag helper
requires the exact-source rehearsal to have completed successfully. This closes runner OS,
Git file-mode and shell invocation parity before the irreversible tag boundary
without weakening post-tag stage selection.

Claude remains the one genuine local human-TTY boundary. Before tag creation,
the Owner runs the Claude stage smoke against the exact staged archive, not a
rebuild and not a Draft download. Its durable evidence binds the exact accepted
source/tree/review digest, Claude version, the exact frozen Claude provider
executable SHA-256 and staged archive SHA-256.

Provider latest is a pre-tag decision. check-provider-pins.sh resolves the
current npm stable tags and exact registry integrity during accepted-main
staging. Those provider inputs are frozen into the staged manifest/evidence.
After tag creation, release verification must not ask a mutable registry whether
the already accepted tuple is still latest; a later upstream release cannot
invalidate an already staged candidate.

Immediately before the single tag push, push-release-tag.sh refreshes only
genuinely mutable action-time state: accepted main, tag/release absence, the
active no-bypass v* ruleset, immutable-release repository policy, release
contract and the presence/binding of the complete staged evidence. Stage
download/content verification completes before this final mutable-state guard.
No build, stage retrieval, provider provisioning, provider runtime, installer
test or registry freshness check executes after the guard before the irreversible
push.

Post-tag automation is promotion-only. It resolves the already accepted staged
bytes, creates tag-bound attestations for those same bytes, creates/refreshes a
guarded Draft, uploads only the accepted release-visible files, downloads the
Draft again and proves byte equality plus tag-bound attestation identity. It
must not rebuild, rerun tests, provision providers, execute Codex/Claude runtime
qualification, or call repository-admin policy endpoints. The contract scans
the complete repository workflow directory: `.github/workflows/release.yml` is
the only workflow allowed to match a tag push; every other push workflow must
be explicitly branch-filtered.

A transient GitHub/network failure in tag-bound attestation, Draft creation,
upload or reconciliation is retried on the same protected tag with the same
accepted bytes. It does not justify moving the tag or consuming another version.
Any deterministic post-tag blocker that was technically reproducible pre-tag is
a release-harness escape.

## Release first-execution closure

`FIRST_EXECUTION_MATRIX` is the durable CLROOM rule for release boundaries.
A protected production release identity is never an integration-test trigger.

Status vocabulary:
- `MOVED_LEFT`: the future production path is already exercised at the earliest safe proof point.
- `LAB_REQUIRED`: the canonical path exists, but representative mutation evidence is still required from an approved disposable integration destination before the protected production boundary.
- `POST_BOUNDARY_ONLY`: the residue genuinely requires the boundary identity/effect itself.
- `SYSTEM_GAP`: proof is missing; the next consequential release boundary is closed.

Current Integration Lab-dependent rows remain `PRESERVED_PENDING_OWNER_GATE`
until the separately approved bounded Lab lifecycle rehearsal is executed and
its `INTEGRATION_FIDELITY_MATRIX` evidence is reconciled. This status is not a
release PASS and does not authorize any Lab or target mutation.

### Boundary / First-Execution Map

| Boundary | Exact external/system state | Future executable/helper/API branch | Failure mode | Earliest safe proof | Same canonical action path? | Representative external-state evidence | Genuinely boundary-only residue | Ambiguous-outcome reconciliation | Evidence identity / current status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PR candidate → merge | exact PR HEAD + reviewed diff + provider/runtime/UI inputs | product/runtime/provider paths; release harness contracts | shipped behavior or harness defect survives review | exact PR CI, negative tests, provider/runtime/UI rehearsal before GPT acceptance | yes for changed product/runtime paths | exact PR checks + required local human-only evidence | accepted-main commit identity does not exist yet | merge result is reconciled against exact accepted HEAD/tree | exact PR HEAD; `MOVED_LEFT` |
| accepted main staging | exact accepted main/tree + reviewed-content digest | `readiness.sh`, stage builder, resolver, preview, checksums, SBOM, installer, provider qualification | merge-byte/file-mode/stage drift | accepted-main Release-candidate workflow | yes | exact target Actions run and content-addressed stage | archive/source commit identity is accepted-main-specific | stage manifest/content digest readback | accepted main SHA + stage manifest; `MOVED_LEFT` |
| pre-tag target guard | target main, tag/release absence, active tag ruleset, immutable-release policy, exact local gh capabilities | `push-release-tag.sh` before the effect seam | stale main, weak ruleset, existing identity, unsupported tool/API path | local tag helper before local tag creation/push; live target reads | yes up to remote tag push | authenticated target reads + `check-publish-toolchain.sh` | exact remote tag identity | no mutation yet | expected main SHA + live target/tool state; `MOVED_LEFT` |
| remote tag push | absent remote canary/production tag + authenticated git remote | `release-external-action.py tag-push` | timeout/non-zero after remote tag may already exist; wrong peeled target | same helper against approved disposable canary before product tag | yes | approved Integration Lab/equivalent tag canary using the same helper | exact production protected tag identity | mandatory `git ls-remote` readback classifies PASS / absent / mismatch / unknown | helper content identity + Lab evidence; `LAB_REQUIRED` until approved rehearsal PASS |
| tag workflow prepare | exact immutable tag + accepted pre-tag stage | Release workflow tag/annotation checks + `resolve-pretag-stage.sh` | tag/source/title mismatch; stage resolver/runtime drift | accepted-main promotion rehearsal executes the same resolver invocation and stage verification | resolver path yes; tag identity check requires tag | accepted-main Ubuntu promotion rehearsal | exact tag annotation/ref identity and tag-trigger event context | read-only failure; no retry mutation | accepted-main rehearsal + exact tag after boundary; `MOVED_LEFT` with tag identity `POST_BOUNDARY_ONLY` |
| tag-bound attestations | exact tag source/ref + accepted staged subjects | pinned `actions/attest` + attestation verification | action/API/subject mismatch | accepted-main attestation mechanism rehearsal on exact staged subjects | mechanism yes; exact `refs/tags/<tag>` binding cannot exist before tag | target accepted-main attestation rehearsal | exact tag-bound source-ref/provenance identity | GitHub action result + later Draft/public attestation verification | staged subject digests; mechanism `MOVED_LEFT`, exact tag binding `POST_BOUNDARY_ONLY` |
| Draft create/edit/upload/download | representative existing/absent Draft + release assets | `release-external-action.py draft-promote` used by Release workflow | Draft state split, create/edit ambiguity, partial upload, asset byte drift, download semantics | approved disposable Integration Lab/equivalent lifecycle rehearsal | yes | same helper performs create/edit/upload/download/reconcile on canary | exact production Draft id/tag and tag-bound attestation assets | every mutation is followed by authoritative Draft readback; downloaded bytes must equal uploaded bytes | helper content identity + Lab evidence; `LAB_REQUIRED` until approved rehearsal PASS |
| production Draft verification | exact target Draft + tag-bound assets/attestations | `verify-draft-release.sh` + `release-external-action.py publish` without `--apply` | Draft lookup, numeric release-id fetch, body/assets/fingerprint parser first executes only at publish | immediately after Draft promotion and before publish approval | yes | exact target Draft plus prior Lab mutation semantics | none for read/validate/fingerprint path | no mutation; double fingerprint must remain stable | release id + exact Draft fingerprint; `MOVED_LEFT` once target Draft exists |
| Draft → published mutation | representative Draft + desired title/body/assets | `release-external-action.py publish --apply` | local failure after remote publish; partial/mismatched published state; immutability delay | approved disposable Integration Lab/equivalent using same helper; target gets same-path dry-run before publish | yes | canary Draft→published transition with fidelity matrix; target-specific immutable policy remains separately proven | one exact production Draft→published effect | numeric release-id reconciliation classifies exact published / unchanged Draft / mismatch / unknown; no blind retry | helper content identity + Lab evidence; `LAB_REQUIRED` until approved rehearsal PASS |
| latest propagation | newly published representative release | same publish helper reads `releases/latest` | publish succeeds but latest route lags or points elsewhere | Lab publish canary; current stable route rehearsal before provider work | yes for API/latest mechanics | Lab latest propagation + current target stable latest read | exact new product latest identity | bounded authoritative latest read; mismatch blocks completion | Lab evidence + target current stable rehearsal; `LAB_REQUIRED` for mutation semantics, new identity `POST_BOUNDARY_ONLY` |
| rendered GitHub Releases identity | exact target Draft before publish; authenticated rendered Releases UI | human observation of version-first title/list/sidebar after machine Draft verification | API fields are correct but rendered identity is misleading/wrong | pre-publish observation after all machine gates; readiness cue must precede observation | UI is genuinely human-only; machine identity path is already exact | authenticated target Draft UI | public visibility of the newly published entry | no mutation; observation binds release id + Draft fingerprint | private human observation evidence; pre-publish required, new public visibility `POST_BOUNDARY_ONLY` |
| public asset/download/install | current stable public route, then exact newly published release | `rehearse-public-route.sh` pre-publish; `verify-public-release.sh` post-publish | latest/download propagation, byte drift, attestation failure, isolated install failure | current stable route rehearsal before expensive provider lanes | verifier mechanics yes | current immutable stable public release | exact new public URLs/bytes and isolated install from those bytes | bounded release/download retries only after published identity is known | exact published tag + staged manifest; mechanics `MOVED_LEFT`, new route `POST_BOUNDARY_ONLY` |
| resource lifecycle / cleanup | task-owned Lab canary tag/Release and task-owned local resources | bounded cleanup under project authority | leaked canary state, accidental deletion of non-task resources | ownership inventory is created before Lab mutation; destructive cleanup only after separate Owner gate | cleanup helper/process must use recorded identities | authoritative Lab state readback before and after cleanup | none | deletion/non-idempotent cleanup requires destination reconciliation; unknown preserves state | canary repository id + tag + release id; `LAB_REQUIRED` lifecycle evidence |

### POST_BOUNDARY_ONLY_WHITELIST

Only the following first observations/effects are allowed to remain after their
consequential boundary:

- after merge: the exact accepted-main commit identity and source-commit-bound
  archive identity;
- after protected tag: the exact remote protected tag object, tag-trigger event
  context, and attestations whose subject source ref is that exact tag;
- after Draft promotion: the exact production Draft numeric id and tag-bound
  attestation assets created for that protected tag;
- after publish: the one exact production Draft→published effect, the newly
  published immutable Release identity, and whether that exact release becomes
  the repository latest object;
- after public visibility: the exact new `releases/latest/download` routes,
  newly published public bytes, isolated install from those public bytes, and
  rendered public Release visibility.

No CLI flag, JSON field, API endpoint, Draft lookup/fingerprint parser, tag-push
outcome classification, Draft create/edit/upload/download semantic, publish
reconciliation branch, current-stable public-route mechanic, or release-identity
rendering rule is permitted to appear here. In particular, Draft creation may
only follow an authoritative draft-capable absence proof; a non-zero
`gh release view` result alone is never interpreted as absence. The canonical
helper falls back to the authenticated release collection/numeric-id path and
treats an unreadable collection as `OUTCOME UNKNOWN` before mutation. These
semantics are reproducible earlier and must be `MOVED_LEFT` or proven through
the approved Integration Lab. Any new late path not listed above is
`SYSTEM_GAP` and blocks the next release boundary.

A branch, CLI/API field/flag, permission assumption, parser or recovery path that
can be safely executed earlier is not post-boundary-only. Static source markers,
a sibling verifier, or a separately rewritten mock do not establish execution
evidence for the canonical action path.

`release-external-action.py` is the canonical external state machine for the
three mutation families that otherwise tended to escape late: remote tag push,
Draft promotion, and Draft→published transition. Production wrappers and the
Integration Lab rehearsal call this same helper. Product-specific guards remain
outside it; external mutation/reconciliation semantics do not.

`rehearse-external-release-lifecycle.py` is intentionally mutation-locked by
an explicit Owner gate token and rejects the production repository. The gate
token is bound to the exact destination repository name + expected repository
ID + reviewed candidate HEAD + canary id, so approval cannot be replayed for a
different candidate or destination tuple. A normal run must use a non-product
`canary/<id>` identity, a complete
`clroom.integration-fidelity-matrix.v1`, synthetic payloads only, and the same
canonical external action helper. Before any tag or Release mutation it also
requires the expected disposable repository ID as a runtime input, resolves the
actual destination repository ID from GitHub, and fail-closes on mismatch.
The rehearsal binds its executable helper and rehearsal bytes to the exact
reviewed public candidate HEAD by fetching those two files at that commit and
comparing SHA-256 before the first mutation; the resulting private evidence
records the candidate HEAD and both executable digests. The Lab lifecycle also
forces a simulated local error after each successful tag push, Draft create/edit,
Draft upload and publish transition, so the canonical helper must prove the
authoritative remote outcome rather than succeeding only on a clean local return.
No private Lab identity is hardcoded into the public repository. It deliberately
preserves the resulting remote canary until the separately authorized cleanup
boundary.

External platform semantics that cannot be proven by fixture must be rehearsed
against representative non-production state before the production boundary.
Every fidelity mismatch remains an explicit exact-target proof obligation; a Lab
PASS never inherits target rulesets, immutability, auth scope, runner/tool,
network, UI, or resource-lifecycle properties that the Lab did not reproduce.

For non-idempotent boundary actions, a local timeout/non-zero/transport loss is
not the outcome. The canonical helper queries authoritative destination state and
classifies exact success, exact not-applied state, mismatch or `OUTCOME UNKNOWN`
before any retry.

The release train remains quarantined while any row above is `LAB_REQUIRED`
without approved evidence or `SYSTEM_GAP`. A new version number, reseal, or
protected tag cannot convert such a row to PASS.

## Publishable surface closure

Before a protected tag, accepted-main staging materializes structured
`release-facts.json`, exact `release-notes.md`, `publish-preview.json` and
`publishable-surface.json`. The semantic verifier checks the exact rendered
public body against authoritative product/provider facts independently of byte
hashes. The pre-tag manifest binds facts, preview and semantic-evidence digests.

The Release-candidate workflow has a distinct
`Publishable content semantic closure` predecessor. `Release required`, the
pre-tag attestation path and promotion rehearsal transitively require it.
Deleting, renaming or disconnecting that job is a harness-contract failure.
The protected-tag helper independently requires the exact main-push job to have
completed successfully and requires the staged publish-preview binding. Before
that helper may create a tag on the Owner machine, it also runs
`check-publish-toolchain.sh`: the exact local `gh` action tool must expose the
release-edit/view/download and attestation capabilities used later by guarded
publish/public verification, and authenticated current-stable release/API reads
must succeed. Tool presence alone is not capability evidence.

For every active candidate, macOS release readiness also executes
`rehearse-public-route.sh` before provider provisioning. That rehearsal uses
the current immutable published stable release to prove the non-candidate-
specific mechanics that post-public verification will later reuse: release
view/JSON, release asset download, public `releases/latest/download` installer
and checksum routing, and an isolated installer/first-use smoke. The exact new
release identity and new public bytes remain genuinely post-publication-only;
the tool/route mechanics do not.

Post-tag automation remains promotion-only. It may bind tag-dependent
attestations and promote the accepted bytes, but it does not run
`release-facts.py`, `render-publish-preview.py` or
`verify-publishable-surface.py` as first-time gates. Draft reconciliation
compares title, body, draft/prerelease state and asset set to the exact accepted
preview.

Publication uses `scripts/release/publish-release.sh` only after a fresh Owner
publish gate. That helper performs final Draft verification, refreshes the
action-time Draft fingerprint immediately before the one publish mutation,
writes the accepted title/body during that transition, and reconciles the
immutable published object. A Draft must be resolved through the same
draft-capable `gh release view` surface used by the canonical Draft verifier,
then fetched by its numeric release id for the REST fingerprint. The
`releases/tags/<tag>` REST lookup is forbidden for the pre-publish Draft
fingerprint because it can return 404 while an authenticated Draft with that tag
exists. The harness contract carries a negative regression for that lookup
split. GitHub REST does not support conditional unsafe PATCH for this endpoint,
so the helper contains the unsupported CAS window in one process. The publish
mutation's local exit status is never treated as destination truth: after the
single mutation attempt the helper performs bounded authoritative reconciliation
by numeric release id. Exact published state is accepted even if the local
command reported failure; an exact unchanged Draft is classified as not
applied; partial/mismatched/unreadable state is `OUTCOME UNKNOWN` and is never
blind-retried. Latest-release reconciliation is separately bounded because
routing visibility can lag the publish transition.

`PUBLISHED` is not end-to-end completion.
`scripts/release/verify-public-release.sh` separately proves that the actual
Latest Release, `releases/latest/download` installer/checksum routes,
public asset bytes and attestations match accepted staging, then performs an
isolated macOS Apple Silicon install from the public installer route.

## Public documentation version coherence

Every active release candidate must inventory semantic-version mentions across
the active public documentation surface. The canonical release checker compares
provider-version claims with `scripts/release/provider-pins.sh`, permits only
explicitly declared compatibility/version-floor exceptions, and fails closed on
stale or unclassified provider versions. Every exception must use a canonical
semantic-version key and a non-empty machine-checked rationale. Current-version product surfaces such as
the README and install/support matrices must not keep an older exact release
version after the candidate advances.

Only older `CHANGELOG.md` sections are historical. The exact current candidate
section is active publishable release input and is scanned against current
provider/product facts before tag; a blanket CHANGELOG historical exclusion is
forbidden. The version history table in `SECURITY.md` remains historical.
Provider claims inside `SECURITY.md`, however, are still checked against the
current provider pins.

Current-source status wording must also survive the publication boundary without
becoming false. README and SECURITY use the exact Cargo package version while
GitHub Releases remains authoritative for whether that source version is Draft,
published, immutable, or Latest. Do not freeze boundary-sensitive words such as
`candidate` or `prepared for vX` into the same source that will be published
unchanged. `scripts/probe/check-doc-freshness.py` enforces this deterministic
subset in required docs-discovery CI and carries negative fixtures for stale
status and wrong-version drift.

The release harness never edits documentation after provider tests. A provider
pin move must be accompanied by the required qualification evidence and matching
documentation changes in the same reviewed candidate. Release-candidate and
pre-tag contract checks block until that coherence is restored. This keeps candidate
bytes deterministic and makes documentation drift a pre-release failure rather
than a post-test auto-write.

## Problem-language vector integrity

The public problem index is a semantic routing surface, not a one-time keyword
list. Technical users can describe the same configuration problem with different
provider terms, symptoms, workaround names, or incomplete vocabulary. Each
release therefore treats distinct problem-language coverage as a maintained
documentation asset.

`scripts/probe/check-problem-vectors.py` runs in required docs-discovery CI and
fails closed on hard inventory/cluster-floor regression, normalized duplicate
vectors, or loss of representative current problem families. The machine count
is only a regression signal. It does not authorize keyword stuffing, artificial
language, or one thin page per query variant.

Release research still owns the semantic part: compare the latest published
problem-language baseline with current product/provider changes and real user,
search-query, provider-issue, and developer-community terminology; add materially
distinct useful formulations; merge/retire duplicates with rationale; and map
the strongest new language into the corresponding canonical answer page when it
improves comprehension or routing. A material release change with zero new vector
findings requires evidence that this research was actually performed.

## Privacy, data-flow and crawler-purpose integrity

Each release must keep one current canonical public answer that separates CLROOM
launcher behavior from provider authentication/network behavior, selected
plugin/MCP behavior, installer/release downloads and documentation-site analytics.
Do not collapse those surfaces into a blanket "offline", "no data leaves the
machine" or "zero telemetry" claim.

The public answer must remain consistent with current source/runtime behavior and
must cover credentials, admitted MCP environment names/values, inspection
redaction, provider-owned network activity, website analytics and the explicit
non-claim that CLROOM is not a network sandbox.

Crawler policy is likewise purpose-specific. Search/citation indexing,
user-initiated retrieval and model-training/model-improvement controls are
independent. The project-level robots declaration must name the current intended
categories and must not imply that a search allow proves a training opt-out.
Because CLROOM is hosted as a GitHub Pages project site, live rendered discovery
reconciliation separately checks the actual host-root `/robots.txt`, which is
the policy standards-compliant crawlers receive.

A future change to launcher telemetry, hosted-service/account requirements,
credential handling, analytics instrumentation, crawler training policy or
provider/network boundary is a material discovery/trust change and must update
the corresponding public answer and gates in the same candidate.

## Discovery metadata and routing integrity

`scripts/probe/check-discovery-metadata.py` protects the deterministic subset of
CLROOM's discovery architecture. Required docs-discovery CI verifies that:

- homepage custom entity markup describes the project honestly as
  `SoftwareSourceCode` with canonical repository, Rust language, runtime platform
  and license, rather than manufacturing review/rating data for a software-app
  rich-result shape;
- installation remains visible in primary docs navigation;
- high-value Codex/use-case/runner/comparison pages keep descriptions aligned with
  the current product surface;
- provider-support, configuration-matrix and limitations pages retain explicit section
  structure for qualified paths, provider-owned/non-qualified boundaries and major
  support limits so focused human/search/AI retrieval does not depend on surrounding
  site context;
- the top problem router links to the current MCP/plugin/worker/inspection/privacy and
  provider-profile comparison clusters and every routed anchor exists;
- the privacy/data-flow page retains distinct telemetry/credential/network/analytics
  language rather than a misleading blanket privacy slogan;
- project robots policy keeps explicit search/citation, user-fetch and
  training/model-improvement categories aligned with the current intended allow state;
- `llms.txt` keeps current high-value intent routing and explicitly separates
  provider-native behavior from CLROOM-qualified behavior.

The machine gate does not decide ranking or AI citations. Semantic release review
still owns whether descriptions, comparisons, headings, evidence and canonical
answers are useful and current.

`docs/glossary.md` is the canonical terminology bridge for overloaded CLROOM/provider
concepts that appear across multiple pages. Search/problem vectors may preserve user
synonyms, but canonical answers should map those synonyms back to stable product and
provider terms so humans and retrieval systems do not infer false distinctions.

Rendered HTML exposes the supplemental `llms.txt` routing surface through
`rel="describedby"` when the page template permits it. This is agent-routing metadata,
not a ranking claim. Do not manufacture stale Markdown alternates merely to satisfy an
external proposal.

`scripts/probe/check-doc-link-graph.py` validates relative documentation targets and
fails closed when an indexable top-level docs page becomes orphaned from both primary
navigation and explicit inbound links. This proves the deterministic internal-link
graph subset without pretending that link count itself is a ranking KPI.

## Post-public discovery observation loop

After publication, controllable discovery prerequisites are reconciled first:
canonical/rendered pages, sitemap, host-root robots policy, public routes, and
changed-URL notification. Search-engine crawling, ranking, snippet choice, AI citation,
and traffic are external outcomes and are never release PASS thresholds.

When first-party data is available, the next release baseline should review it as
diagnostic evidence. Useful inputs include:

- Google Search Console granular queries, query groups/themes, and meaningful
  top/trending-up/trending-down changes;
- Search Console generative-AI and other search-surface reporting when the property
  exposes it;
- Bing Webmaster Tools search and AI Performance evidence such as grounding queries,
  cited pages, topics/intents, citation share, and trend changes;
- privacy-safe referral/analytics signals and recurring support/community language.

The purpose is not to chase every metric. Use the evidence to discover vocabulary gaps,
missing canonical answers, weak internal routing, stale terminology, or pages whose
content does not satisfy the intent that is actually reaching them. Feed those findings
into the next `PROBLEM_LANGUAGE_VECTOR_COVERAGE`, discovery-impact map, and canonical
answer review.

Record insufficient or delayed data as such. Do not treat absence of impressions,
clicks, citations, or crawler activity as proof that the documentation is correct, and
do not manufacture content merely to move a dashboard number.

For whole-plugin activation:

1. **Pre-merge rehearsal:** the exact PR candidate is rehearsed before GPT ACCEPT.
   Claude runs locally because selected-plugin autocomplete remains the one
   genuine human visual observation; its evidence stays outside the tracked
   tree. The exact PR machine readiness owns mutable provider-latest resolution.
   The local smoke self-provisions the same pinned provider tuple from reviewed
   package integrities without re-querying latest, then machine preflight proves
   the exact skill-only selection is qualified. Clean and selected Claude
   sessions run through a task-owned PTY supervisor. Immediately before each
   clean or selected provider launch, the outer harness stops and requires one
   explicit readiness Enter while the operator is looking at that terminal.
   The acknowledgement is consumed before Claude starts and is never forwarded
   to provider stdin. The operator then keeps the terminal visible through the
   bounded observation window. The supervisor maintains a bounded rendered
   terminal screen model, waits for trusted same-row composer readiness, injects
   only the fixed non-submitting autocomplete probe, restores physical terminal
   state and owns task-session teardown before persistent-state verification.
   Unknown screen-mutating controls fail closed before probe injection. Human
   work is limited to the target absence/presence, sibling/plugin-error and
   no-inference observations; post-run y/N answers are accepted only when the
   corresponding pre-launch readiness acknowledgement was recorded. Evidence
   schema v6 binds both readiness acknowledgements, and the stage verifier
   rejects legacy v5 evidence. Provider exit UX is not part of the proof.

   A screen-model failure is diagnosed only through the canonical
   `diagnose-screen` phase of
   `scripts/release/local-plugin-activation-smoke.sh`. That phase runs only the
   clean Claude launch, injects no autocomplete probe, requires no human input or
   y/N confirmation, stops at the first unsupported control, restores/tears down
   task-owned state and emits only a normalized terminal-control identity plus
   SHA-256 fingerprint and invariant counters. Raw terminal text/transcripts,
   prompts, Owner paths and credential/provider-state contents are never
   serialized by this diagnostic. The diagnostic result is evidence for a
   subsequent semantic model change; it is never itself a qualification PASS.

   The prior Claude Code terminal incident captured DEC private mode 2031
   (`CSI ? 2031 h`), which enables terminal color-scheme change reporting. It
   does not mutate rendered screen cells, so the screen model admits it without
   losing readiness trust. Because it changes terminal protocol/state, the
   supervisor also treats mode 2031 as critical physical terminal state: it is
   queried before provider start, restored after task teardown and re-verified.
   The corresponding terminal-generated `CSI ? 997 n`,
   `CSI ? 997 ; 1 n` and `CSI ? 997 ; 2 n` reports are relayed as machine
   traffic; other values are not recognized as machine traffic and are discarded at runtime.

   Codex runs automatically in the macOS Release-candidate workflow and proves
   the real MCP runtime plus post-runtime clean-state closure. This catches
   product/runtime failures at the earliest candidate boundary.
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

For standalone Codex MCP activation:

1. **Pre-merge exact-provider rehearsal:** the exact PR candidate runs on macOS
   Apple Silicon against the pinned Codex provider. The selected root-user stdio
   MCP must reach provider startup, MCP `initialize` and `tools/list` without a
   model prompt; an independent fixture `tools/call` proves non-empty tool
   semantics. Evidence binds the exact candidate and provider bytes.
2. **Fail-closed negative closure:** literal MCP environment values, missing
   `--pass-env` admission, provider-subcommand use, multiple standalone MCP
   selections, overlap between the standalone MCP identity and an MCP identity
   already contributed by the selected whole plugin, active non-session MCP
   layers, and selected-source mutation must all fail before an interactive
   provider/MCP runtime is admitted. A distinct qualified whole plugin and
   standalone MCP are not a conflict in v0.5; their positive composition closure
   is defined below. The source-mutation oracle uses the
   task-owned preflight creation seam rather than timing-only polling. Provider
   processes observed while the task-owned `.mcp-preflight-*` directory exists
   belong to the machine-owned config-layer preflight even when provider argv
   presentation is not stable enough to preserve the `app-server` token.
   After that directory disappears, any provider mode other than a bounded
   version probe is an escape and fails the rehearsal. The final product launch
   independently revalidates the selected MCP before `exec`.
3. **Accepted-main exact-byte staging:** after merge identity is known, the same
   standalone-MCP capability is requalified against the exact future shipping
   archive and frozen pinned provider inputs before a protected tag can be
   created. Post-tag provider/runtime qualification remains forbidden.
4. **Provider-move invalidation:** changing the exact Codex provider tuple
   invalidates standalone-MCP runtime evidence and requires the pre-merge and
   accepted-main qualification paths to run again.

For bounded Codex whole-plugin + standalone-MCP composition:

1. **One resolved launch truth:** one typed resolved launch must own the exact
   provider identity, isolation plan, selected whole-plugin plan, selected
   standalone-MCP plan, admitted environment names, boundary controls and final
   provider arguments. Human diagnostics, machine JSON inspection, provider
   preflight and real launch must derive from that same resolved truth.
2. **Pre-merge exact-provider rehearsal:** the exact PR candidate must select one
   qualified whole plugin and one distinct qualified root-user stdio MCP in the
   same interactive Codex launch. Both MCP servers must be observed under the
   same interactive provider process and independently reach `initialize` and
   `tools/list`; no model prompt is sent.
3. **Composition negatives and privacy:** more than one plugin or standalone MCP,
   unsupported resource kinds, raw provider activation overlap, plugin/MCP MCP-ID
   overlap, unadmitted or literal MCP environment material, either-side source
   drift, active sibling MCP layers and unselected sibling activation all fail
   closed. Human/JSON evidence may expose selected identities, reasons and
   admitted environment names, but never environment values, MCP commands/args,
   private paths or raw provider argument values.
4. **No persistent provider mutation:** the rehearsal fingerprints the ambient
   root-user Codex config and plugin source before/after the composed runtime.
   Only CLROOM-owned transient/projected state may be created, and task-owned
   provider/MCP processes must close.
5. **Accepted-main exact-byte staging:** the exact future shipping archive must
   repeat the composed runtime and sanitized inspection against the frozen Codex
   provider bytes. Its evidence is a required pre-tag stage file bound to source
   SHA, archive SHA-256 and provider SHA-256. Post-tag runtime requalification is
   forbidden.
6. **Harness durability:** canonical harness validation must require both the
   pre-merge composition rehearsal and the exact-archive composition stage so
   neither proof can disappear silently in a later workflow edit.

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

The canonical release provider pins and the shipped product qualification
constants are one tuple contract, not independent mirrors. Canonical readiness
must derive the expected Codex/Claude version tuples from
`scripts/release/provider-pins.sh` and fail unless both clean-launch and
whole-plugin exact constants in `src/catalog/provider_inventory.rs` match.
The checker must include a negative self-test that rejects a stale clean or
plugin-activation tuple. Updating registry/package pins, public docs and a
mirrored test expectation without updating the shipped qualification constants
is therefore a pre-merge blocker.

## Provider ambient-input surface closure

Provider version changes can add new instruction/configuration discovery
surfaces without changing CLROOM itself. Startup/version/byte checks alone are
therefore insufficient for a clean-launch claim.

For every newly pinned provider tuple, release qualification must re-prove the
ambient input classes CLROOM claims to suppress. For Claude Code 2.1.289 the
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
  --expected-head <exact-pr-head> --plugin-id frontend-design@claude-plugins-official

# Only after a fail-closed unknown screen-control incident; machine-owned
# diagnostic, never a qualification PASS and never a substitute for rehearsal.
bash scripts/release/local-plugin-activation-smoke.sh diagnose-screen \
  --expected-head <exact-pr-head> --plugin-id frontend-design@claude-plugins-official

# Codex pre-merge rehearsal is produced automatically by the PR
# Release-candidate workflow.

# After merge and successful accepted-main staging, download the canonical stage
# and run Claude once against those exact future shipping bytes:
bash scripts/release/resolve-pretag-stage.sh \
  <version> <accepted-main-sha> <stage-dir>
bash scripts/release/local-plugin-activation-smoke.sh stage \
  --expected-head <accepted-main-sha> \
  --artifact <stage-dir>/clean-room-launcher-v<version>-aarch64-apple-darwin.tar.gz \
  --plugin-id frontend-design@claude-plugins-official

# Only after that evidence passes may the Owner authorize the protected tag.
# After tag-bound promotion creates the Draft:
bash scripts/release/verify-draft-release.sh v<version> <exact-tag-source-sha>

# Only after the separate Owner publish gate:
CLROOM_OWNER_PUBLISH_APPROVED=YES:v<version>:<exact-tag-source-sha> \
  bash scripts/release/publish-release.sh v<version> <exact-tag-source-sha>

# After publication, prove the real public latest/download install path:
bash scripts/release/verify-public-release.sh v<version> <exact-tag-source-sha>
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

## Declared automation-chain topology

`AUTOMATION_CHAIN_RELEASE_CANDIDATE_TO_PROMOTION_REHEARSAL`
The only automatic continuation from accepted-main `Release candidate readiness` into promotion preparation is a local reusable `workflow_call`. The caller is restricted to trusted `push` runs on `refs/heads/main` in `ACTIVE_CANDIDATE`, passes the exact `github.sha`, and closes the promotion rehearsal inside the same release-candidate run. That rehearsal alone binds `CLROOM_PRETAG_CURRENT_RUN_ID` to `github.run_id`; the resolver accepts it only after independently proving exact run/repository/ref/SHA identity and PASS of the upstream release jobs. The tag workflow never receives this binding and remains completed-run-only. Privileged `workflow_run` checkout chains are forbidden. The reusable workflow carries only `contents: read` and `actions: read` and performs no publication.

`AUTOMATION_CHAIN_TAG_TO_DRAFT`
A protected `v*` tag triggers the `Release` workflow. That workflow may bind attestations and create or refresh a GitHub Draft Release from already accepted bytes. It must not rebuild, requalify providers, mutate repository settings, move the tag, or publish the Draft.

`AUTOMATION_CHAIN_NO_AUTO_PUBLISH`
No repository workflow is authorized to publish a GitHub Release automatically. Publish remains a separate Owner action-time gate after exact Draft reconciliation. A fallback executor must preserve the same tag/source/byte identity and cannot bypass the canonical release helpers or evidence.
