# Contributing to Clean Room Launcher

Contributions are welcome when they preserve CLROOM's security, privacy, and
truthful-support boundaries.

## Before opening a pull request

For a small bug fix, documentation fix, test improvement, or narrowly scoped
maintenance change, you can open a pull request directly.

For a substantial behavior change, a new provider or platform, a new release or
installation path, or a change to the security model, open a GitHub issue first
so the intended outcome and support claim can be agreed before implementation.

Do not use a public issue for vulnerability details. Follow [SECURITY.md](SECURITY.md)
for private vulnerability reporting.

## Contribution process

1. Create a branch in your fork or repository from the current `main` branch.
2. Keep the change focused on one outcome and include tests for changed behavior.
3. Update user-facing documentation when behavior, installation, support, or
   limitations change.
4. Run the relevant local checks below.
5. Open a pull request against `main` describing the problem, the change, and
   the verification performed.
6. Address review and CI findings. A maintainer decides whether the change is
   accepted and merged.

## Acceptance requirements

Changes must preserve these project invariants:

- Do not commit credentials, private keys, prompts, transcripts, private paths,
  unrestricted home-directory contents, or private control-plane material.
- Security and privacy boundaries must fail closed rather than silently falling
  back to a less isolated launch.
- New or changed production behavior must include automated tests that exercise
  the behavior and important failure cases.
- Confirmed medium-or-higher exploitable findings from static analysis, fuzzing,
  dependency review, or other security analysis must be fixed before release;
  false positives or non-applicable findings must be documented rather than
  silently ignored.
- Provider, operating-system, architecture, installation, and version support
  claims must be backed by the corresponding qualification or verification
  evidence in the repository and CI.
- GitHub Actions dependencies must remain pinned to full commit SHAs and workflow
  permissions must stay least-privilege.
- Public files must continue to pass `scripts/check-public-boundary.sh`.
- Avoid unrelated refactors in security or release changes; keep review scope
  small enough to verify.

See [GOVERNANCE.md](GOVERNANCE.md) for the project's public governance rules and
[docs/threat-model.md](docs/threat-model.md) for the security model.

## Local verification

Run the cheapest checks relevant to the change first. For a normal Rust change,
the baseline is:

```sh
git diff --check
scripts/check-public-boundary.sh --root "$PWD"
cargo test --locked --all-targets
RUSTFLAGS='-D warnings' cargo build --locked --release --bins
```

Some release, packaging, provider-qualification, and platform checks require the
GitHub Actions environment or the qualified macOS Apple Silicon lane. The pull
request CI is authoritative for those checks.

If your change touches shell release or installer scripts, also run the relevant
syntax or self-tests already used by the repository's release-readiness workflow.
Do not weaken a failing check to make a contribution pass; fix the underlying
problem or document why the check does not apply.

## Tests for new functionality

Major new functionality must add or update automated tests in the same pull
request. Tests should cover the expected path and security-relevant negative or
failure behavior where applicable. Recent changes are expected to keep this
policy true rather than relying on manual testing alone.

## Bug reports and feature requests

Use [GitHub Issues](https://github.com/y-sor/clean-room-launcher/issues) for
non-sensitive bugs and feature requests. Include the CLROOM version, platform,
minimal reproduction, expected behavior, and observed behavior when relevant.

For vulnerabilities or reports containing sensitive details, use the process in
[SECURITY.md](SECURITY.md) instead.
