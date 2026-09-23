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

## Artifact integrity

`PRETAG_BLOCKER_CLOSURE` is mandatory. The protected tag is an irreversible
identity boundary, not a build/test trigger.

The exact future shipping archive is built once from accepted `main` before
tagging because the archive embeds the accepted source commit. The pre-tag stage
also produces the checksums, SBOM, installer copy, release notes, exact-provider
qualification records, Codex whole-plugin runtime evidence, and a machine-readable
`clroom.release-stage.v1` manifest that binds all of those bytes to the accepted
source tree and content-review digest.

The same pre-tag workflow rehearses the GitHub attestation mechanism before the
tag exists. Tag-bound attestations are necessarily created after the tag, but
they bind the already accepted staged bytes; the tag workflow does not rebuild
or rerun provider/runtime qualification.

Claude's human-TTY whole-plugin check is the only local interactive boundary.
After accepted-main staging, the Owner/GPT local smoke runs against the exact
staged archive and writes `phase=stage` evidence bound to the same artifact
SHA-256. The protected tag helper refuses to push until both the Actions-owned
Codex stage evidence and the local Claude stage evidence match the staged
manifest.

Provider `latest` and registry integrity are resolved while producing the
pre-tag stage. That accepted provider tuple is frozen into stage evidence.
Neither the tag workflow nor pre-publish verifier asks a mutable registry whether
that already accepted tuple is still `latest`.

Repository-level release immutability and the no-update/no-delete/no-bypass
`v*` tag ruleset are checked with the Owner-authenticated `gh` boundary before
the tag push and again before publication. They are not delegated to an Actions
`GITHUB_TOKEN` that lacks repository-administration read authority.

Immediately before the single irreversible tag push, the helper refreshes only
mutable action-time state: exact `main`, tag/release absence, tag ruleset,
repository immutable-release policy, and the whole-release contract. No build,
provider, runtime, npm-latest or installer qualification is allowed after this
final guard.

Post-tag automation is promotion-only: resolve the successful exact-main stage,
create tag-bound attestations for those exact bytes, create/update the guarded
Draft, upload exactly the accepted public assets, then download and reconcile
them byte-for-byte against the pre-tag manifest. A transient GitHub/network
failure is retried on the same protected tag; it is not a reason to move the tag
or consume another version.

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
   Claude remains a genuine local human-TTY boundary. Codex runs automatically
   on macOS Actions with the pinned provider canary and content-addressed
   evidence. This remains the earliest product/runtime correctness boundary.
2. **Accepted-main exact-byte stage:** after merge/tree equality, the future
   shipping archive is built once from accepted `main`. Codex automatically
   reruns the whole-plugin runtime gate against that exact archive. Claude then
   runs one local `stage` TTY smoke against the same archive. Both evidence
   records must bind the exact staged artifact SHA-256.
3. **Tag:** the Owner-authenticated helper validates the stage manifest, Codex
   stage evidence, Claude stage evidence, immutable-release setting, tag
   protection and action-time repository identity before the protected push.
4. **Pre-publish:** the Draft verifier checks exact stage→Draft byte equality,
   release notes, tag-bound attestations, tag/Draft identity, repository policy
   and successful promotion workflow. It does not rerun Codex, Claude, build,
   provider qualification, or mutable npm-latest checks.

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

A successful Release workflow is not by itself a publish verdict. Before an
Owner publish gate, the canonical local verifier
`scripts/release/verify-draft-release.sh` must reconcile the exact tag and
source SHA, Draft identity and exact asset set, checksums and release-visible
attestations, current provider pins, pre-merge rehearsal and Draft provider
evidence, and every tag-triggered GitHub Actions run for that exact tag/SHA.
Any incomplete or non-success tag-triggered run blocks publication.

This verifier is read-only with respect to public release state. It does not
publish, edit, or replace release assets.

Use:

```sh
# Before merge, on the exact PR candidate HEAD, Claude is the human-TTY
# product/runtime rehearsal boundary:
bash scripts/release/local-plugin-activation-smoke.sh rehearse \
  --expected-head <exact-pr-head> --plugin-id <qualified-claude-id>

# Codex pre-merge rehearsal is produced by the macOS Release-candidate workflow.

# After merge, wait for the accepted-main Release-candidate run to produce
# release-stage-vX.Y.Z-<accepted-main-sha>, then run Claude once against the
# exact staged shipping archive:
bash scripts/release/resolve-release-stage.sh X.Y.Z <accepted-main-sha> <stage-dir>
bash scripts/release/local-plugin-activation-smoke.sh stage \
  --expected-head <accepted-main-sha> \
  --artifact <stage-dir>/clean-room-launcher-vX.Y.Z-aarch64-apple-darwin.tar.gz \
  --plugin-id <qualified-claude-id>

# Only after the pre-tag stage + Claude stage evidence pass may the protected
# tag helper run.

# After tag automation promotes the accepted bytes to a Draft:
bash scripts/release/verify-draft-release.sh vX.Y.Z <exact-tag-source-sha>
```

Local Codex commands are diagnostic/development tools only; canonical Codex
pre-merge and exact-byte stage evidence comes from GitHub Actions artifacts.
There is no Codex Draft runtime gate and no Claude Draft runtime gate: both
providers have already been exercised against the exact shipping archive before
the irreversible tag.

Rehearsal evidence remains content-addressed by reviewed content/tree/provider
inputs. Accepted-main stage evidence additionally binds the exact future shipping
artifact SHA-256. Dynamic evidence stays outside tracked source bytes.

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
