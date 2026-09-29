#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CONTROLLED_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    ".github/workflows/dependency-review.yml",
    ".github/workflows/fuzz.yml",
    ".github/workflows/indexnow.yml",
    ".github/workflows/release-candidate.yml",
    ".github/workflows/release-promotion-rehearsal.yml",
    ".github/workflows/release.yml",
    ".github/workflows/scorecard.yml",
)
CODEQL_ACTIONS = {"init", "analyze", "upload-sarif"}
AUTOMATION_MARKERS = (
    "AUTOMATION_CHAIN_RELEASE_CANDIDATE_TO_PROMOTION_REHEARSAL",
    "AUTOMATION_CHAIN_TAG_TO_DRAFT",
    "AUTOMATION_CHAIN_NO_AUTO_PUBLISH",
)
CODEQL_RE = re.compile(
    r"uses:\s+github/codeql-action/(init|analyze|upload-sarif)@([0-9a-f]{40})\s+#\s+v([0-9]+\.[0-9]+\.[0-9]+)"
)


def read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def job_blocks(text: str) -> dict[str, str]:
    lines = text.splitlines()
    blocks: dict[str, list[str]] = {}
    in_jobs = False
    current: str | None = None
    for line in lines:
        if line == "jobs:":
            in_jobs = True
            current = None
            continue
        if not in_jobs:
            continue
        if line and not line.startswith(" "):
            break
        match = re.fullmatch(r"  ([A-Za-z0-9_-]+):", line)
        if match:
            current = match.group(1)
            blocks[current] = [line]
            continue
        if current is not None:
            blocks[current].append(line)
    return {name: "\n".join(lines) for name, lines in blocks.items()}


def validate_codeql_records(records: list[tuple[str, str, str]]) -> list[str]:
    errors: list[str] = []
    present = {action for action, _, _ in records}
    missing = sorted(CODEQL_ACTIONS - present)
    if missing:
        errors.append("CODEQL_FAMILY_MISSING:" + ",".join(missing))
    tuples = {(sha, version) for _, sha, version in records}
    if len(tuples) != 1:
        errors.append("CODEQL_FAMILY_DIVERGED")
    return errors


def require(errors: list[str], condition: bool, code: str) -> None:
    if not condition:
        errors.append(code)




def validate_supply_chain_verifier_contract(text: str) -> list[str]:
    errors: list[str] = []
    step = "name: Provision pinned Python supply-chain verifier"
    readiness = "name: Run canonical fail-closed gate"
    start = text.find(step)
    end = text.find(readiness)
    require(errors, start >= 0, "SUPPLY_CHAIN_VERIFIER_STEP_MISSING")
    require(errors, end >= 0 and start >= 0 and start < end, "SUPPLY_CHAIN_VERIFIER_ORDER")
    if start >= 0:
        block = text[start:end if end >= 0 else len(text)]
        require(
            errors,
            "if: env.CLROOM_RELEASE_LIFECYCLE == 'ACTIVE_CANDIDATE'" in block,
            "SUPPLY_CHAIN_VERIFIER_ACTIVE_ONLY",
        )
        require(
            errors,
            'verifier_root="$RUNNER_TEMP/clroom-supply-chain-verifier"' in block,
            "SUPPLY_CHAIN_VERIFIER_PRIVATE_VENV",
        )
        require(errors, "python3 -m venv" in block, "SUPPLY_CHAIN_VERIFIER_VENV")
        require(
            errors,
            "sys.version_info[:2] != (3, 14)" in block,
            "SUPPLY_CHAIN_VERIFIER_PYTHON_PIN",
        )
        verifier_requirements = {
            "attrs==26.1.0": "c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309",
            "jsonschema==4.26.0": "d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce",
            "jsonschema-specifications==2025.9.1": "98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe",
            "referencing==0.37.0": "381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231",
            "rpds-py==2026.6.3": "d7469697dce35be237db177d42e2a2ee26e6dcc5fc052078a6fefabd288c6edd",
        }
        for package, digest in verifier_requirements.items():
            require(
                errors,
                f"{package} --hash=sha256:{digest}" in block,
                "SUPPLY_CHAIN_VERIFIER_REQUIREMENT:" + package,
            )
        require(errors, "--only-binary=:all:" in block, "SUPPLY_CHAIN_VERIFIER_BINARY_ONLY")
        require(errors, "--require-hashes" in block, "SUPPLY_CHAIN_VERIFIER_REQUIRE_HASHES")
        require(
            errors,
            'echo "$verifier_root/bin" >> "$GITHUB_PATH"' in block,
            "SUPPLY_CHAIN_VERIFIER_PATH",
        )
        require(
            errors,
            '"rpds-py": "2026.6.3"' in block and '"jsonschema": "4.26.0"' in block,
            "SUPPLY_CHAIN_VERIFIER_CLOSURE_CHECK",
        )
    return errors




def validate_pretag_current_run_contract(
    resolver: str, promotion: str, release: str
) -> list[str]:
    errors: list[str] = []
    require(
        errors,
        "CLROOM_PRETAG_CURRENT_RUN_ID: ${{ github.run_id }}" in promotion,
        "PRETAG_CURRENT_RUN_PROMOTION_BINDING",
    )
    require(
        errors,
        "CLROOM_PRETAG_CURRENT_RUN_ID" not in release,
        "PRETAG_CURRENT_RUN_TAG_PATH_FORBIDDEN",
    )
    required_resolver_markers = {
        "PRETAG_CURRENT_RUN_ID_INPUT": 'current_run_id="${CLROOM_PRETAG_CURRENT_RUN_ID:-}"',
        "PRETAG_CURRENT_RUN_ACTIONS": '[[ "${GITHUB_ACTIONS:-}" == "true" ]]',
        "PRETAG_CURRENT_RUN_ID_MATCH": '[[ "${GITHUB_RUN_ID:-}" == "$current_run_id" ]]',
        "PRETAG_CURRENT_RUN_EVENT": '[[ "${GITHUB_EVENT_NAME:-}" == "push" ]]',
        "PRETAG_CURRENT_RUN_REF": '[[ "${GITHUB_REF:-}" == "refs/heads/main" ]]',
        "PRETAG_CURRENT_RUN_SHA": '[[ "${GITHUB_SHA:-}" == "$expected" ]]',
        "PRETAG_CURRENT_RUN_REPOSITORY": '[[ "${GITHUB_REPOSITORY:-}" == "$repository" ]]',
        "PRETAG_CURRENT_RUN_IN_PROGRESS_ONLY": 'run.get("status") == "in_progress"',
        "PRETAG_CURRENT_RUN_NO_CONCLUSION": 'run.get("conclusion") is None',
        "PRETAG_COMPLETED_RUN_STILL_REQUIRED": 'run.get("status") == "completed" and run.get("conclusion") == "success"',
    }
    for code, marker in required_resolver_markers.items():
        require(errors, marker in resolver, code)
    for name in (
        "Release eligibility and harness seal",
        "CLROOM release readiness",
        "Rehearse/stage exact release bytes",
        "Rehearse attestation mechanism before tag",
    ):
        require(errors, name in resolver, "PRETAG_CURRENT_RUN_UPSTREAM_JOB:" + name)
    require(
        errors,
        'job.get("status") != "completed" or job.get("conclusion") != "success"' in resolver,
        "PRETAG_CURRENT_RUN_UPSTREAM_SUCCESS",
    )
    return errors


def claude_prompt_mode_present(text: str) -> bool:
    for line in text.splitlines():
        tokens = line.replace('"', "").replace("'", "").split()
        for index, token in enumerate(tokens[:-1]):
            if token == "$clroom" and tokens[index + 1] == "claude":
                if any(item in {"-p", "--print"} for item in tokens[index + 2 :]):
                    return True
    return False

def validate_claude_release_smoke_contract(text: str) -> list[str]:
    errors: list[str] = []
    require(
        errors,
        '"schema_version":"clroom.plugin-release-smoke.v4"' in text,
        "CLAUDE_RELEASE_SMOKE_SCHEMA_V4",
    )
    require(
        errors,
        '"automated_probe_prompt_supplied":False' in text,
        "CLAUDE_RELEASE_SMOKE_PROMPT_EVIDENCE_FALSE",
    )
    require(
        errors,
        '"clean_tui_confirmed":clean_tui=="true"' in text,
        "CLAUDE_RELEASE_SMOKE_CLEAN_TTY",
    )
    require(
        errors,
        '"selected_tui_confirmed":interactive=="true"' in text,
        "CLAUDE_RELEASE_SMOKE_SELECTED_TTY",
    )
    require(
        errors,
        "No model prompt was sent in either TUI" in text,
        "CLAUDE_RELEASE_SMOKE_HUMAN_NO_PROMPT_CONFIRMATION",
    )
    require(
        errors,
        "Do not press Enter while autocomplete/search text remains in the composer." in text,
        "CLAUDE_RELEASE_SMOKE_SAFE_EXIT_NO_ENTER",
    )
    require(
        errors,
        "Press Ctrl+C to cancel and clear the composer; visually confirm it is empty." in text,
        "CLAUDE_RELEASE_SMOKE_SAFE_EXIT_CLEAR",
    )
    require(
        errors,
        "Then press Ctrl+D to exit from the empty composer. Do not use /exit for this rehearsal." in text,
        "CLAUDE_RELEASE_SMOKE_SAFE_EXIT_CTRL_D",
    )
    require(
        errors,
        "Clean composer was cleared and TUI exited with Ctrl+D without submitting input" in text,
        "CLAUDE_RELEASE_SMOKE_CLEAN_SAFE_EXIT_CONFIRMATION",
    )
    require(
        errors,
        "Selected composer was cleared and TUI exited with Ctrl+D without submitting input" in text,
        "CLAUDE_RELEASE_SMOKE_SELECTED_SAFE_EXIT_CONFIRMATION",
    )
    require(
        errors,
        "Exit normally with /exit." not in text,
        "CLAUDE_RELEASE_SMOKE_UNSAFE_SLASH_EXIT",
    )
    require(
        errors,
        not claude_prompt_mode_present(text),
        "CLAUDE_RELEASE_SMOKE_MODEL_PROMPT_FORBIDDEN",
    )
    require(
        errors,
        "--output-format stream-json" not in text,
        "CLAUDE_RELEASE_SMOKE_PRINT_MODE_FORBIDDEN",
    )
    return errors

def check(root: Path) -> list[str]:
    errors: list[str] = []

    workflow_text = {path: read(root, path) for path in CONTROLLED_WORKFLOWS}
    records: list[tuple[str, str, str]] = []
    for text in workflow_text.values():
        records.extend(CODEQL_RE.findall(text))
    errors.extend(validate_codeql_records(records))

    dependabot = read(root, ".github/dependabot.yml")
    require(errors, "codeql-family:" in dependabot, "DEPENDABOT_CODEQL_GROUP_MISSING")
    require(
        errors,
        '"github/codeql-action/*"' in dependabot or "'github/codeql-action/*'" in dependabot,
        "DEPENDABOT_CODEQL_PATTERN_MISSING",
    )

    release_candidate = workflow_text[".github/workflows/release-candidate.yml"]
    errors.extend(validate_supply_chain_verifier_contract(release_candidate))

    claude_release_smoke = read(root, "scripts/release/local-plugin-activation-smoke.sh")
    errors.extend(validate_claude_release_smoke_contract(claude_release_smoke))
    claude_stage_verifier = read(root, "scripts/release/verify-claude-stage-evidence.py")
    require(
        errors,
        '"schema_version": "clroom.plugin-release-smoke.v4"' in claude_stage_verifier,
        "CLAUDE_STAGE_EVIDENCE_SCHEMA_V4",
    )
    require(
        errors,
        '"automated_probe_prompt_supplied": False' in claude_stage_verifier,
        "CLAUDE_STAGE_EVIDENCE_PROMPT_FALSE",
    )

    fuzz = workflow_text[".github/workflows/fuzz.yml"]
    require(errors, (root / "fuzz/Cargo.lock").is_file(), "FUZZ_LOCKFILE_MISSING")
    require(errors, "generate-lockfile" not in fuzz, "FUZZ_RUNTIME_LOCK_GENERATION")
    require(
        errors,
        "fetch --locked --manifest-path fuzz/Cargo.toml" in fuzz,
        "FUZZ_LOCKED_FETCH_MISSING",
    )
    require(errors, "CARGO_NET_OFFLINE: true" in fuzz, "FUZZ_OFFLINE_EXECUTION_MISSING")

    ci_jobs = job_blocks(workflow_text[".github/workflows/ci.yml"])
    require(errors, "harness-contract" in ci_jobs, "CI_HARNESS_JOB_MISSING")
    required = ci_jobs.get("required", "")
    require(errors, "name: Required" in required, "CI_REQUIRED_NAME")
    require(
        errors,
        "needs: [harness-contract, target-matrix, docs-discovery, qualified-target-lanes]" in required,
        "CI_REQUIRED_TOPOLOGY",
    )
    require(errors, "always()" in required, "CI_REQUIRED_ALWAYS")

    release_jobs = job_blocks(release_candidate)
    eligibility = release_jobs.get("release-eligibility", "")
    require(errors, "runs-on: ubuntu-latest" in eligibility, "RELEASE_ELIGIBILITY_RUNNER")
    require(errors, "check-release-contract.py --self-test" in eligibility, "RELEASE_ELIGIBILITY_SELF_TEST")
    require(errors, "check-release-contract.py --report" in eligibility, "RELEASE_ELIGIBILITY_SEAL")
    readiness = release_jobs.get("release-readiness", "")
    require(errors, "needs: release-eligibility" in readiness, "RELEASE_READINESS_NEEDS_ELIGIBILITY")
    stage = release_jobs.get("pretag-stage", "")
    require(
        errors,
        "needs: [release-eligibility, release-readiness]" in stage,
        "PRETAG_STAGE_TOPOLOGY",
    )
    attest = release_jobs.get("pretag-attestation-rehearsal", "")
    require(
        errors,
        "needs: [release-eligibility, release-readiness, pretag-stage]" in attest,
        "PRETAG_ATTEST_TOPOLOGY",
    )
    release_required = release_jobs.get("release-required", "")
    require(errors, "name: Release required" in release_required, "RELEASE_REQUIRED_NAME")
    require(
        errors,
        "needs: [release-eligibility, release-readiness, pretag-stage, pretag-attestation-rehearsal, promotion-prepare-rehearsal]" in release_required,
        "RELEASE_REQUIRED_TOPOLOGY",
    )
    require(errors, "if: always()" in release_required, "RELEASE_REQUIRED_ALWAYS")

    docs = read(root, "docs/release/RELEASE_CONTRACT.md")
    for marker in AUTOMATION_MARKERS:
        require(errors, marker in docs, "AUTOMATION_MARKER_MISSING:" + marker)

    promotion = workflow_text[".github/workflows/release-promotion-rehearsal.yml"]
    require(errors, "workflow_call:" in promotion, "PROMOTION_CHAIN_REUSABLE_TRIGGER")
    require(errors, "workflow_run:" not in promotion, "PROMOTION_CHAIN_PRIVILEGED_TRIGGER_FORBIDDEN")
    require(errors, "inputs.source_sha" not in promotion, "PROMOTION_CHAIN_UNTRUSTED_SOURCE_INPUT")
    require(errors, "ref: ${{ github.sha }}" in promotion, "PROMOTION_CHAIN_TRUSTED_CHECKOUT")
    require(errors, "SOURCE_SHA: ${{ github.sha }}" in promotion, "PROMOTION_CHAIN_TRUSTED_SOURCE")
    require(
        errors,
        "uses: ./.github/workflows/release-promotion-rehearsal.yml" in release_candidate,
        "PROMOTION_CHAIN_CALLER_MISSING",
    )
    promotion_job = release_jobs.get("promotion-prepare-rehearsal", "")
    require(errors, "github.event_name == 'push'" in promotion_job, "PROMOTION_CHAIN_PUSH_ONLY")
    require(errors, "github.ref == 'refs/heads/main'" in promotion_job, "PROMOTION_CHAIN_MAIN_ONLY")
    require(errors, "needs.release-eligibility.outputs.lifecycle == 'ACTIVE_CANDIDATE'" in promotion_job, "PROMOTION_CHAIN_ACTIVE_ONLY")
    require(
        errors,
        "promotion-prepare-rehearsal" in release_required,
        "RELEASE_REQUIRED_PROMOTION_TOPOLOGY",
    )
    lifecycle_guard = promotion.find("resolve-release-lifecycle.py")
    stage_resolver = promotion.find("bash scripts/release/resolve-pretag-stage.sh")
    require(
        errors,
        lifecycle_guard >= 0 and stage_resolver >= 0 and lifecycle_guard < stage_resolver,
        "PROMOTION_CHAIN_LIFECYCLE_GUARD",
    )
    require(
        errors,
        "PROMOTION_PREPARE_REHEARSAL_SKIPPED lifecycle=POST_PUBLISH" in promotion,
        "PROMOTION_CHAIN_POST_PUBLISH_NOOP",
    )
    require(errors, "contents: write" not in promotion, "PROMOTION_CHAIN_WRITE_PERMISSION")

    release = workflow_text[".github/workflows/release.yml"]
    require(errors, 'tags:\n      - "v*"' in release, "RELEASE_TAG_TRIGGER")
    require(errors, 'release create "$tag" --draft' in release, "RELEASE_DRAFT_ONLY")
    require(errors, "--draft=false" not in release, "RELEASE_AUTO_PUBLISH_FORBIDDEN")
    require(errors, "gh release publish" not in release, "RELEASE_AUTO_PUBLISH_COMMAND")

    resolver = read(root, "scripts/release/resolve-pretag-stage.sh")
    errors.extend(validate_pretag_current_run_contract(resolver, promotion, release))

    for path, text in workflow_text.items():
        require(errors, re.search(r"(?m)^concurrency:\s*$", text) is not None, f"WORKFLOW_CONCURRENCY:{path}")
        blocks = job_blocks(text)
        require(errors, bool(blocks), f"WORKFLOW_JOBS:{path}")
        for job, block in blocks.items():
            if re.search(r"(?m)^    uses:\s+\./\.github/workflows/", block):
                continue
            require(errors, "timeout-minutes:" in block, f"JOB_TIMEOUT:{path}:{job}")

    return errors


def self_test() -> None:
    sha_a = "a" * 40
    sha_b = "b" * 40
    clean = [("init", sha_a, "4.38.0"), ("analyze", sha_a, "4.38.0"), ("upload-sarif", sha_a, "4.38.0")]
    if validate_codeql_records(clean):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:CLEAN_CODEQL")
    split = [("init", sha_b, "4.38.1"), ("analyze", sha_a, "4.38.0"), ("upload-sarif", sha_a, "4.38.0")]
    if "CODEQL_FAMILY_DIVERGED" not in validate_codeql_records(split):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:SPLIT_CODEQL")
    missing = [("init", sha_a, "4.38.0"), ("analyze", sha_a, "4.38.0")]
    if not any(item.startswith("CODEQL_FAMILY_MISSING:") for item in validate_codeql_records(missing)):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:MISSING_CODEQL")
    verifier_fixture = """
      - name: Provision pinned Python supply-chain verifier
        if: env.CLROOM_RELEASE_LIFECYCLE == 'ACTIVE_CANDIDATE'
        run: |
          verifier_root="$RUNNER_TEMP/clroom-supply-chain-verifier"
          python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] != (3, 14) else 0)'
          attrs==26.1.0 --hash=sha256:c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309
          jsonschema==4.26.0 --hash=sha256:d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce
          jsonschema-specifications==2025.9.1 --hash=sha256:98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe
          referencing==0.37.0 --hash=sha256:381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231
          rpds-py==2026.6.3 --hash=sha256:d7469697dce35be237db177d42e2a2ee26e6dcc5fc052078a6fefabd288c6edd
          python3 -m venv "$verifier_root"
          "$verifier_root/bin/python" -m pip install --only-binary=:all: --require-hashes -r requirements.txt
          echo "$verifier_root/bin" >> "$GITHUB_PATH"
          expected = {"jsonschema": "4.26.0", "rpds-py": "2026.6.3"}
      - name: Run canonical fail-closed gate
    """
    if validate_supply_chain_verifier_contract(verifier_fixture):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:SUPPLY_CHAIN_VERIFIER_CLEAN")
    stale_verifier = verifier_fixture.replace("jsonschema==4.26.0", "jsonschema==4.25.1")
    if not any(
        error.startswith("SUPPLY_CHAIN_VERIFIER_REQUIREMENT:jsonschema==4.26.0")
        for error in validate_supply_chain_verifier_contract(stale_verifier)
    ):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:SUPPLY_CHAIN_VERIFIER_STALE")
    unhashed_verifier = verifier_fixture.replace("--require-hashes", "--no-require-hashes")
    if "SUPPLY_CHAIN_VERIFIER_REQUIRE_HASHES" not in validate_supply_chain_verifier_contract(unhashed_verifier):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:SUPPLY_CHAIN_VERIFIER_UNHASHED")
    missing_verifier = verifier_fixture.replace("Provision pinned Python supply-chain verifier", "Provision removed verifier")
    if "SUPPLY_CHAIN_VERIFIER_STEP_MISSING" not in validate_supply_chain_verifier_contract(missing_verifier):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:SUPPLY_CHAIN_VERIFIER_MISSING")
    resolver_fixture = """
current_run_id="${CLROOM_PRETAG_CURRENT_RUN_ID:-}"
[[ "${GITHUB_ACTIONS:-}" == "true" ]]
[[ "${GITHUB_RUN_ID:-}" == "$current_run_id" ]]
[[ "${GITHUB_EVENT_NAME:-}" == "push" ]]
[[ "${GITHUB_REF:-}" == "refs/heads/main" ]]
[[ "${GITHUB_SHA:-}" == "$expected" ]]
[[ "${GITHUB_REPOSITORY:-}" == "$repository" ]]
run.get("status") == "completed" and run.get("conclusion") == "success"
run.get("status") == "in_progress"
run.get("conclusion") is None
Release eligibility and harness seal
CLROOM release readiness
Rehearse/stage exact release bytes
Rehearse attestation mechanism before tag
job.get("status") != "completed" or job.get("conclusion") != "success"
"""
    promotion_fixture = "CLROOM_PRETAG_CURRENT_RUN_ID: ${{ github.run_id }}"
    release_fixture = 'tags:\n      - "v*"'
    if validate_pretag_current_run_contract(
        resolver_fixture, promotion_fixture, release_fixture
    ):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:PRETAG_CURRENT_RUN_CLEAN")
    missing_upstream = resolver_fixture.replace(
        "Rehearse attestation mechanism before tag", "missing attestation"
    )
    if not any(
        error.startswith("PRETAG_CURRENT_RUN_UPSTREAM_JOB:")
        for error in validate_pretag_current_run_contract(
            missing_upstream, promotion_fixture, release_fixture
        )
    ):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:PRETAG_CURRENT_RUN_UPSTREAM")
    tag_exception = release_fixture + "\nCLROOM_PRETAG_CURRENT_RUN_ID\n"
    if "PRETAG_CURRENT_RUN_TAG_PATH_FORBIDDEN" not in validate_pretag_current_run_contract(
        resolver_fixture, promotion_fixture, tag_exception
    ):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:PRETAG_CURRENT_RUN_TAG_PATH")
    weak_identity = resolver_fixture.replace(
        '[[ "${GITHUB_REF:-}" == "refs/heads/main" ]]', ""
    )
    if "PRETAG_CURRENT_RUN_REF" not in validate_pretag_current_run_contract(
        weak_identity, promotion_fixture, release_fixture
    ):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:PRETAG_CURRENT_RUN_IDENTITY")
    claude_smoke_fixture = """
"$clroom" claude
"$clroom" claude --with="plugin:$plugin_id"
"No model prompt was sent in either TUI"
"schema_version":"clroom.plugin-release-smoke.v4"
"automated_probe_prompt_supplied":False
"clean_tui_confirmed":clean_tui=="true"
"selected_tui_confirmed":interactive=="true"
"Do not press Enter while autocomplete/search text remains in the composer."
"Press Ctrl+C to cancel and clear the composer; visually confirm it is empty."
"Then press Ctrl+D to exit from the empty composer. Do not use /exit for this rehearsal."
"Clean composer was cleared and TUI exited with Ctrl+D without submitting input"
"Selected composer was cleared and TUI exited with Ctrl+D without submitting input"
"""
    if validate_claude_release_smoke_contract(claude_smoke_fixture):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:CLAUDE_NO_PROMPT_CLEAN")
    prompt_smokes = [
        claude_smoke_fixture + '\n"$clroom" claude -p "UNUSED"\n',
        claude_smoke_fixture + '\n"$clroom" claude --with="plugin:$plugin_id" --print "UNUSED"\n',
    ]
    for prompt_smoke in prompt_smokes:
        if "CLAUDE_RELEASE_SMOKE_MODEL_PROMPT_FORBIDDEN" not in validate_claude_release_smoke_contract(prompt_smoke):
            raise SystemExit("HARNESS_SELF_TEST_FAIL:CLAUDE_PROMPT_NOT_REJECTED")
    unsafe_exit_smoke = claude_smoke_fixture + '\n"Exit normally with /exit."\n'
    if "CLAUDE_RELEASE_SMOKE_UNSAFE_SLASH_EXIT" not in validate_claude_release_smoke_contract(unsafe_exit_smoke):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:CLAUDE_UNSAFE_EXIT_NOT_REJECTED")
    missing_clear_smoke = claude_smoke_fixture.replace(
        '"Press Ctrl+C to cancel and clear the composer; visually confirm it is empty."\n',
        "",
    )
    if "CLAUDE_RELEASE_SMOKE_SAFE_EXIT_CLEAR" not in validate_claude_release_smoke_contract(missing_clear_smoke):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:CLAUDE_SAFE_EXIT_CLEAR_NOT_REQUIRED")
    print("HARNESS_CONTRACT_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    errors = check(args.root.resolve())
    if errors:
        print("HARNESS_CONTRACT_BLOCKED")
        for error in errors:
            print(error)
        return 1
    print("HARNESS_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
