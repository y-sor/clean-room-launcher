#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
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


def validate_indexnow_dependency_wait_contract(text: str) -> list[str]:
    errors: list[str] = []
    require(errors, "timeout-minutes: 20" in text, "INDEXNOW_JOB_TIMEOUT")
    require(errors, "while true; do" in text, "INDEXNOW_WAIT_UNTIL_DEPENDENCY_TERMINAL")
    require(errors, "sleep 10" in text, "INDEXNOW_WAIT_POLL_INTERVAL")
    require(
        errors,
        'actions/runs?head_sha=$GITHUB_SHA&per_page=100' in text,
        "INDEXNOW_SAME_SHA_QUERY",
    )
    require(errors, '$1 == "CI"' in text, "INDEXNOW_CI_BINDING")
    require(
        errors,
        '$1 == "pages build and deployment"' in text,
        "INDEXNOW_PAGES_BINDING",
    )
    require(
        errors,
        'if [ "$ci_status" = completed ] && [ "$ci_conclusion" != success ]' in text,
        "INDEXNOW_CI_FAIL_FAST",
    )
    require(
        errors,
        'if [ "$pages_status" = completed ] && [ "$pages_conclusion" != success ]' in text,
        "INDEXNOW_PAGES_FAIL_FAST",
    )
    require(
        errors,
        '[ "$ci_status" = completed ] && [ "$ci_conclusion" = success ]'
        in text
        and '[ "$pages_status" = completed ] && [ "$pages_conclusion" = success ]'
        in text,
        "INDEXNOW_BOTH_DEPENDENCIES_REQUIRED",
    )
    require(errors, "seq 1 60" not in text, "INDEXNOW_FIXED_RETRY_WINDOW_FORBIDDEN")
    require(
        errors,
        "Timed out waiting for same-SHA CI and Pages deployment" not in text,
        "INDEXNOW_SECOND_DEADLINE_FORBIDDEN",
    )
    return errors


def validate_publish_draft_lookup_contract(text: str) -> list[str]:
    errors: list[str] = []
    start = text.find('draft_id=$(gh release view "$tag" --json databaseId --jq .databaseId)')
    end = text.find("\ngit fetch --quiet origin main", start if start >= 0 else 0)
    require(errors, start >= 0, "GUARDED_PUBLISH_DRAFT_VIEW_BY_TAG")
    require(errors, end > start >= 0, "GUARDED_PUBLISH_DRAFT_CAPTURE_BOUNDARY")
    if start >= 0 and end > start:
        block = text[start:end]
        require(
            errors,
            '[[ "$draft_id" =~ ^[0-9]+$ ]] || fail "DRAFT_ID_INVALID"' in block,
            "GUARDED_PUBLISH_DRAFT_ID_VALIDATION",
        )
        require(
            errors,
            "capture_and_validate_draft() {" in block,
            "GUARDED_PUBLISH_DRAFT_CAPTURE_MISSING",
        )
        require(
            errors,
            'gh api "repos/$repository/releases/$draft_id"' in block,
            "GUARDED_PUBLISH_DRAFT_FETCH_BY_ID",
        )
        require(
            errors,
            'releases/tags/$tag' not in block,
            "GUARDED_PUBLISH_DRAFT_TAG_LOOKUP_FORBIDDEN",
        )
    return errors


def validate_publish_outcome_reconciliation_contract(text: str) -> list[str]:
    errors: list[str] = []
    mutation = text.find('gh release edit "$tag" --draft=false --latest --verify-tag')
    final_pass = text.find('echo "GUARDED_PUBLISH_PASS tag=$tag target=$expected"')
    require(errors, mutation >= 0, "GUARDED_PUBLISH_MUTATION_MISSING")
    require(errors, final_pass > mutation >= 0, "GUARDED_PUBLISH_RECONCILIATION_BOUNDARY")
    if mutation >= 0 and final_pass > mutation:
        action_start = text.rfind("set +e", 0, mutation + 1)
        require(errors, action_start >= 0, "GUARDED_PUBLISH_MUTATION_RC_CAPTURE")
        block = text[action_start if action_start >= 0 else mutation:final_pass]
        for marker, code in (
            ("set +e", "GUARDED_PUBLISH_MUTATION_RC_CAPTURE"),
            ("publish_rc=$?", "GUARDED_PUBLISH_MUTATION_RC"),
            ('gh api "repos/$repository/releases/$draft_id"', "GUARDED_PUBLISH_RELEASE_ID_RECONCILE"),
            ("PUBLISHED_EXACT", "GUARDED_PUBLISH_PUBLISHED_EXACT"),
            ("DRAFT_UNCHANGED", "GUARDED_PUBLISH_NOT_APPLIED_CLASS"),
            ("GUARDED_PUBLISH_OUTCOME_UNKNOWN", "GUARDED_PUBLISH_UNKNOWN_CLASS"),
            ("for attempt in 1 2 3 4 5", "GUARDED_PUBLISH_BOUNDED_RECONCILIATION"),
            ("PUBLISHED_PENDING_IMMUTABILITY", "GUARDED_PUBLISH_PENDING_IMMUTABILITY"),
            ('gh api "repos/$repository/releases/latest"', "GUARDED_PUBLISH_LATEST_BY_API"),
        ):
            require(errors, marker in block, code)
        require(
            errors,
            "gh release list" not in block,
            "GUARDED_PUBLISH_POST_MUTATION_CLI_LIST_FORBIDDEN",
        )
        mutation_fail_pattern = re.search(
            r'gh release edit[\s\S]{0,300}\|\|\s*fail\s+"PUBLISH_TRANSITION"',
            block,
        )
        require(
            errors,
            mutation_fail_pattern is None,
            "GUARDED_PUBLISH_MUTATION_EARLY_FAIL_FORBIDDEN",
        )
    return errors




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
    resolver: str,
    admission: str,
    promotion: str,
    release: str,
    release_candidate: str,
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
    require(
        errors,
        "python3 scripts/release/pretag-run-admission.py --self-test" in release_candidate,
        "PRETAG_CURRENT_RUN_SELF_TEST_EARLY",
    )
    required_resolver_markers = {
        "PRETAG_CURRENT_RUN_ID_INPUT": 'current_run_id="${CLROOM_PRETAG_CURRENT_RUN_ID:-}"',
        "PRETAG_CURRENT_RUN_ACTIONS": '[[ "${GITHUB_ACTIONS:-}" == "true" ]]',
        "PRETAG_CURRENT_RUN_ID_MATCH": '[[ "${GITHUB_RUN_ID:-}" == "$current_run_id" ]]',
        "PRETAG_CURRENT_RUN_EVENT": '[[ "${GITHUB_EVENT_NAME:-}" == "push" ]]',
        "PRETAG_CURRENT_RUN_REF": '[[ "${GITHUB_REF:-}" == "refs/heads/main" ]]',
        "PRETAG_CURRENT_RUN_SHA": '[[ "${GITHUB_SHA:-}" == "$expected" ]]',
        "PRETAG_CURRENT_RUN_REPOSITORY": '[[ "${GITHUB_REPOSITORY:-}" == "$repository" ]]',
        "PRETAG_CURRENT_RUN_HELPER": "pretag-run-admission.py",
        "PRETAG_CURRENT_RUN_RUN_JSON": '--run-json "$tmp/run-$run_id.json"',
        "PRETAG_CURRENT_RUN_BINDING_ARG": 'run_args+=(--current-run-id "$current_run_id")',
        "PRETAG_CURRENT_RUN_JOBS_JSON": '--jobs-json "$tmp/jobs-$run_id.json"',
    }
    for code, marker in required_resolver_markers.items():
        require(errors, marker in resolver, code)

    required_admission_markers = {
        "PRETAG_CURRENT_RUN_IN_PROGRESS_ONLY": 'run.get("status") != "in_progress"',
        "PRETAG_CURRENT_RUN_NO_CONCLUSION": 'run.get("conclusion") is not None',
        "PRETAG_COMPLETED_RUN_STILL_REQUIRED": 'run.get("status") == "completed" and run.get("conclusion") == "success"',
        "PRETAG_CURRENT_RUN_JOB_STATUS": 'job.get("status") != "completed" or job.get("conclusion") != "success"',
        "PRETAG_CURRENT_RUN_SELF_TEST": "PRETAG_RUN_ADMISSION_SELF_TEST_PASS",
    }
    for code, marker in required_admission_markers.items():
        require(errors, marker in admission, code)
    for name in (
        "Release eligibility and harness seal",
        "CLROOM release readiness",
        "Rehearse/stage exact release bytes",
        "Rehearse attestation mechanism before tag",
    ):
        require(errors, name in admission, "PRETAG_CURRENT_RUN_UPSTREAM_JOB:" + name)
    return errors


def claude_prompt_mode_present(text: str) -> bool:
    for line in text.splitlines():
        tokens = line.replace('"', "").replace("'", "").split()
        for index, token in enumerate(tokens[:-1]):
            if token == "$clroom" and tokens[index + 1] == "claude":
                if any(item in {"-p", "--print"} for item in tokens[index + 2 :]):
                    return True
    return False

def validate_claude_tty_supervisor_contract(text: str) -> list[str]:
    errors: list[str] = []
    require(errors, "INJECT_BYTE" not in text, "CLAUDE_TTY_SUPERVISOR_HUMAN_INJECT_CHORD_FORBIDDEN")
    require(errors, "STOP_BYTE" not in text, "CLAUDE_TTY_SUPERVISOR_HUMAN_STOP_CHORD_FORBIDDEN")
    require(errors, "CSI_U_KEY_RE" not in text, "CLAUDE_TTY_SUPERVISOR_HUMAN_KEY_PROTOCOL_FORBIDDEN")
    require(errors, "def validate_probe_text(" in text, "CLAUDE_TTY_SUPERVISOR_FIXED_PROBE_VALIDATION")
    require(errors, "pty.fork()" not in text, "CLAUDE_TTY_SUPERVISOR_PLATFORM_FORKPTY_FORBIDDEN")
    require(errors, "pty.openpty()" in text, "CLAUDE_TTY_SUPERVISOR_OPENPTY")
    require(errors, "os.setsid()" in text, "CLAUDE_TTY_SUPERVISOR_EXPLICIT_SESSION")
    require(errors, "termios.TIOCSCTTY" in text, "CLAUDE_TTY_SUPERVISOR_CONTROLLING_TTY")
    require(errors, "ready_read, ready_write = os.pipe()" in text, "CLAUDE_TTY_SUPERVISOR_SESSION_READY_HANDSHAKE")
    require(errors, "READY_MARKER = b\"manual mode on\"" in text, "CLAUDE_TTY_SUPERVISOR_COMPOSER_READY_MARKER")
    require(errors, "READY_STATUS_TOKENS" in text, "CLAUDE_TTY_SUPERVISOR_COMPOSER_READY_STATUS_TOKENS")
    require(errors, "class TerminalScreen:" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_MODEL")
    require(errors, "SCREEN_MAX_ROWS" in text and "SCREEN_MAX_COLS" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_BOUNDS")
    require(errors, "def feed(self, data: bytes)" in text, "CLAUDE_TTY_SUPERVISOR_INCREMENTAL_SCREEN_FEED")
    require(errors, "def composer_ready_method(self)" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_READY_DETECTOR")
    require(errors, "SCREEN_DIFFERENTIAL_REDRAW" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_DIFFERENTIAL_TEST")
    require(errors, "SCREEN_CLEAR_REMOVES_READY" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_CLEAR_NEGATIVE_TEST")
    require(errors, "SCREEN_TRUST_FALSE_POSITIVE" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_TRUST_NEGATIVE_TEST")
    require(errors, "SCREEN_SAME_ROW_REQUIRED" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_SAME_ROW_TEST")
    require(errors, "SCREEN_SPLIT_CSI" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_SPLIT_CSI_TEST")
    require(errors, "SCREEN_UNSUPPORTED_MUTATION_UNTRUSTED" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_UNSUPPORTED_MUTATION_TEST")
    require(errors, "READY_VISIBLE_WINDOW_BYTES" not in text, "CLAUDE_TTY_SUPERVISOR_LINEAR_WINDOW_FORBIDDEN")
    require(errors, "output_tail" not in text, "CLAUDE_TTY_SUPERVISOR_LINEAR_OUTPUT_TAIL_FORBIDDEN")
    require(errors, "composer_ready_method(bytes(" not in text, "CLAUDE_TTY_SUPERVISOR_LINEAR_READY_CALL_FORBIDDEN")
    require(errors, "elif private:" in text and "self._mark_unsupported()" in text, "CLAUDE_TTY_SUPERVISOR_UNKNOWN_PRIVATE_MODE_FAIL_CLOSED")
    require(errors, "OBSERVATION_WINDOW_SECONDS" in text, "CLAUDE_TTY_SUPERVISOR_BOUNDED_OBSERVATION")
    require(errors, "os.write(master_fd, probe_bytes)" in text, "CLAUDE_TTY_SUPERVISOR_AUTOMATIC_PROBE")
    require(errors, "def terminal_response_length(" in text, "CLAUDE_TTY_SUPERVISOR_TERMINAL_RESPONSE_PARSER")
    require(errors, "def classify_terminal_input(" in text, "CLAUDE_TTY_SUPERVISOR_TERMINAL_INPUT_CLASSIFIER")
    require(errors, 'STANDARD_CPR_QUERY = b"\\x1b[6n"' in text, "CLAUDE_TTY_SUPERVISOR_STANDARD_CPR_QUERY")
    require(errors, "def count_standard_cpr_queries(" in text, "CLAUDE_TTY_SUPERVISOR_STANDARD_CPR_CORRELATION")
    require(errors, "standard_cpr_budget: int = 0" in text, "CLAUDE_TTY_SUPERVISOR_STANDARD_CPR_BUDGET")
    require(errors, "FOCUS_EVENT_RE" in text, "CLAUDE_TTY_SUPERVISOR_FOCUS_EVENT_RELAY")
    require(errors, "def visible_text(" in text and "linear = visible_text(differential_ready)" in text, "CLAUDE_TTY_SUPERVISOR_LINEAR_STREAM_REGRESSION_ORACLE")
    require(errors, "def query_physical_terminal_state(" in text, "CLAUDE_TTY_SUPERVISOR_PHYSICAL_STATE_SNAPSHOT")
    require(errors, "def restore_physical_terminal_state(" in text, "CLAUDE_TTY_SUPERVISOR_PHYSICAL_STATE_RESTORE")
    require(errors, "def terminal_state_matches(" in text, "CLAUDE_TTY_SUPERVISOR_PHYSICAL_STATE_VERIFY")
    require(errors, "pending_input = b\"\"" in text, "CLAUDE_TTY_SUPERVISOR_STREAMING_BUFFER")
    require(errors, "INPUT_SEQUENCE_TIMEOUT_SECONDS" in text, "CLAUDE_TTY_SUPERVISOR_INCOMPLETE_SEQUENCE_TIMEOUT")
    require(errors, "os.write(master_fd, response_bytes)" in text, "CLAUDE_TTY_SUPERVISOR_TERMINAL_RESPONSE_RELAY")
    require(errors, "TERMINAL_RESPONSES_FORWARDED=" in text, "CLAUDE_TTY_SUPERVISOR_TERMINAL_RESPONSE_EVIDENCE")
    require(errors, "TERMINAL_RESPONSE_BYTES_FORWARDED=" in text, "CLAUDE_TTY_SUPERVISOR_TERMINAL_RESPONSE_BYTE_EVIDENCE")
    require(errors, "STANDARD_CPR_RESPONSES_FORWARDED=" in text, "CLAUDE_TTY_SUPERVISOR_STANDARD_CPR_EVIDENCE")
    require(errors, "STANDARD_CPR_WITHOUT_QUERY" in text, "CLAUDE_TTY_SUPERVISOR_STANDARD_CPR_NEGATIVE_TEST")
    require(errors, "STANDARD_CPR_BUDGET" in text, "CLAUDE_TTY_SUPERVISOR_STANDARD_CPR_BOUNDED_TEST")
    require(errors, "COMPOSER_READY_SEEN=" in text, "CLAUDE_TTY_SUPERVISOR_READY_EVIDENCE")
    require(errors, "COMPOSER_READY_METHOD=" in text, "CLAUDE_TTY_SUPERVISOR_READY_METHOD_EVIDENCE")
    require(errors, "SCREEN_MODEL_TRUSTED=" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_TRUST_EVIDENCE")
    require(errors, "SCREEN_MODEL_UNSUPPORTED_MUTATIONS=" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_UNSUPPORTED_EVIDENCE")
    require(errors, "COLOR_SCHEME_REPORT_MODE = 2031" in text, "CLAUDE_TTY_SUPERVISOR_COLOR_SCHEME_MODE_2031")
    require(errors, "COLOR_SCHEME_REPORT_RE" in text, "CLAUDE_TTY_SUPERVISOR_COLOR_SCHEME_REPORT_RELAY")
    require(errors, "SCREEN_MODE_2031_INCIDENT_FINGERPRINT" in text, "CLAUDE_TTY_SUPERVISOR_COLOR_SCHEME_INCIDENT_REPLAY")
    require(errors, "SCREEN_MODE_2031_CRITICAL_RESTORE" in text, "CLAUDE_TTY_SUPERVISOR_COLOR_SCHEME_CRITICAL_RESTORE")
    require(errors, "COLOR_SCHEME_REPORT_INVALID" in text, "CLAUDE_TTY_SUPERVISOR_COLOR_SCHEME_REPORT_NEGATIVE")
    require(errors, "SCREEN_MODEL_FIRST_UNSUPPORTED_IDENTITY=" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_CONTROL_IDENTITY_EVIDENCE")
    require(errors, "SCREEN_MODEL_FIRST_UNSUPPORTED_SHA256=" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_CONTROL_FINGERPRINT_EVIDENCE")
    require(errors, "--diagnose-unsupported" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_DIAGNOSTIC_MODE")
    require(errors, "no probe, prompt, or human input" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_DIAGNOSTIC_NO_PROBE_BANNER")
    require(errors, "CLAUDE_TTY_SCREEN_DIAGNOSTIC=CAPTURED" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_DIAGNOSTIC_CAPTURED")
    require(errors, '"raw_terminal_transcript_recorded": False' in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_DIAGNOSTIC_NO_RAW_TRANSCRIPT")
    require(errors, "SCREEN_DIAGNOSTIC_PRIVACY" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_DIAGNOSTIC_PRIVACY_TEST")
    require(errors, "SCREEN_CONTROL_FINGERPRINT" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_CONTROL_FINGERPRINT_TEST")
    require(errors, "os.O_EXCL" in text and "0o600" in text, "CLAUDE_TTY_SUPERVISOR_SCREEN_DIAGNOSTIC_PRIVATE_CREATE")
    require(errors, "OBSERVATION_WINDOW_COMPLETED=" in text, "CLAUDE_TTY_SUPERVISOR_OBSERVATION_EVIDENCE")
    require(errors, "PHYSICAL_TERMINAL_STATE_RESTORED=" in text, "CLAUDE_TTY_SUPERVISOR_PHYSICAL_STATE_EVIDENCE")
    require(errors, "HUMAN_BYTES_FORWARDED=0" in text, "CLAUDE_TTY_SUPERVISOR_HUMAN_INPUT_EVIDENCE")
    require(errors, "HUMAN_CONTROL_ACTIONS_REQUIRED=0" in text, "CLAUDE_TTY_SUPERVISOR_ZERO_HUMAN_ACTION_EVIDENCE")
    require(errors, "SUBMIT_BYTES_FORWARDED=0" in text, "CLAUDE_TTY_SUPERVISOR_SUBMIT_EVIDENCE")
    require(errors, "HARNESS_STOP_FORWARDED=0" in text, "CLAUDE_TTY_SUPERVISOR_STOP_EVIDENCE")
    require(errors, "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:HUMAN_INPUT_ACCEPTED" in text, "CLAUDE_TTY_SUPERVISOR_HUMAN_INPUT_NEGATIVE_TEST")
    require(errors, "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:TERMINAL_PROTOCOL_FILTER" in text, "CLAUDE_TTY_SUPERVISOR_TERMINAL_PROTOCOL_SELF_TEST")
    require(errors, "os.killpg(" in text, "CLAUDE_TTY_SUPERVISOR_PROCESS_GROUP_TEARDOWN")
    require(errors, "def task_owned_session_processes(" in text, "CLAUDE_TTY_SUPERVISOR_SESSION_INVENTORY")
    require(errors, "def terminate_task_owned_session(" in text, "CLAUDE_TTY_SUPERVISOR_SESSION_TEARDOWN")
    supervise_index = text.find("def supervise(")
    close_index = text.find("master_fd = -1", supervise_index)
    teardown_index = text.find("terminate_task_owned_session(pid, child_session)", supervise_index)
    require(
        errors,
        supervise_index >= 0 and close_index > supervise_index and teardown_index > close_index,
        "CLAUDE_TTY_SUPERVISOR_PTY_CLOSE_BEFORE_TEARDOWN",
    )
    require(errors, '["/bin/ps", "-axo", "pid=,pgid="]' in text, "CLAUDE_TTY_SUPERVISOR_PROCESS_ENUMERATION")
    require(errors, "sid = os.getsid(pid)" in text, "CLAUDE_TTY_SUPERVISOR_SESSION_ID_LOOKUP")
    require(errors, "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SPLIT_PROCESS_GROUP" in text, "CLAUDE_TTY_SUPERVISOR_SPLIT_GROUP_SELF_TEST")
    require(errors, "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SESSION_RESIDUE" in text, "CLAUDE_TTY_SUPERVISOR_SESSION_RESIDUE_SELF_TEST")
    require(errors, "TASK_PROCESS_SESSION_CLOSED=" in text, "CLAUDE_TTY_SUPERVISOR_CLEANUP_EVIDENCE")
    require(
        errors,
        "CLAUDE_TTY_SUPERVISOR_SELF_TEST_PASS" in text,
        "CLAUDE_TTY_SUPERVISOR_SELF_TEST_MARKER",
    )
    return errors
def validate_claude_release_smoke_contract(text: str) -> list[str]:
    errors: list[str] = []
    stripped_lines = {line.strip() for line in text.splitlines()}
    require(
        errors,
        '"schema_version":"clroom.plugin-release-smoke.v6"' in text,
        "CLAUDE_RELEASE_SMOKE_SCHEMA_V6",
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
        '"clean_tui_supervised":clean_tui_supervised=="true"' in text,
        "CLAUDE_RELEASE_SMOKE_CLEAN_SUPERVISED",
    )
    require(
        errors,
        '"selected_tui_supervised":selected_tui_supervised=="true"' in text,
        "CLAUDE_RELEASE_SMOKE_SELECTED_SUPERVISED",
    )
    require(
        errors,
        '"interactive_human_bytes_forwarded":False' in text,
        "CLAUDE_RELEASE_SMOKE_HUMAN_BYTES_BLOCKED",
    )
    require(
        errors,
        '"interactive_submit_bytes_blocked_by_supervisor":True' in text,
        "CLAUDE_RELEASE_SMOKE_SUBMIT_BLOCKED",
    )
    require(
        errors,
        '"interactive_harness_owned_teardown":True' in text,
        "CLAUDE_RELEASE_SMOKE_HARNESS_TEARDOWN",
    )
    require(
        errors,
        '"physical_terminal_preflight_passed":physical_terminal_preflight=="true"' in text,
        "CLAUDE_RELEASE_SMOKE_PHYSICAL_TERMINAL_PREFLIGHT",
    )
    require(
        errors,
        '"interactive_terminal_state_restored":interactive_terminal_state_restored=="true"' in text,
        "CLAUDE_RELEASE_SMOKE_TERMINAL_STATE_RESTORED",
    )
    require(
        errors,
        '"clean_observation_ready_acknowledged":clean_observation_ready=="true"' in text,
        "CLAUDE_RELEASE_SMOKE_CLEAN_OBSERVATION_READY_EVIDENCE",
    )
    require(
        errors,
        '"selected_observation_ready_acknowledged":selected_observation_ready=="true"' in text,
        "CLAUDE_RELEASE_SMOKE_SELECTED_OBSERVATION_READY_EVIDENCE",
    )
    require(
        errors,
        '"selected_tui_confirmed":interactive=="true"' in text,
        "CLAUDE_RELEASE_SMOKE_SELECTED_TTY",
    )
    require(
        errors,
        "No inference/model response appeared in either TUI" in text,
        "CLAUDE_RELEASE_SMOKE_HUMAN_NO_PROMPT_CONFIRMATION",
    )
    require(
        errors,
        'python3 "$root/scripts/release/claude-tty-supervisor.py" --probe-text "$probe_text" -- "$clroom" claude' in stripped_lines,
        "CLAUDE_RELEASE_SMOKE_CLEAN_SUPERVISOR_LAUNCH",
    )
    require(
        errors,
        'python3 "$root/scripts/release/claude-tty-supervisor.py" --probe-text "$probe_text" -- "$clroom" claude --with="plugin:$plugin_id"' in stripped_lines,
        "CLAUDE_RELEASE_SMOKE_SELECTED_SUPERVISOR_LAUNCH",
    )
    require(errors, 'cd "$root"' in stripped_lines, "CLAUDE_RELEASE_SMOKE_EXACT_CHECKOUT_TUI")
    require(
        errors,
        'python3 "$root/scripts/release/terminal-state-diagnostic.py" --expected-head "$head"' in stripped_lines,
        "CLAUDE_RELEASE_SMOKE_PHYSICAL_TERMINAL_PREFLIGHT_CALL",
    )
    require(errors, 'cd "$tui_project"' not in stripped_lines, "CLAUDE_RELEASE_SMOKE_SYNTHETIC_TUI_FORBIDDEN")
    require(
        errors,
        "The AGENTS boundary is already machine-proved; human work is autocomplete observation only." in text,
        "CLAUDE_RELEASE_SMOKE_MACHINE_AGENTS_BOUNDARY",
    )
    require(
        errors,
        "Repo/nested project AGENTS.md was reported as loaded" not in text
        and "No AGENTS.md above the synthetic Git project was reported as loaded" not in text,
        "CLAUDE_RELEASE_SMOKE_HUMAN_AGENTS_RECHECK_FORBIDDEN",
    )
    require(
        errors,
        "Do not type into Claude." in text
        and "The readiness Enter is consumed by the harness before Claude starts and is never forwarded to Claude." in text
        and "Keep this terminal visible until the bounded observation window ends and the confirmation questions appear." in text,
        "CLAUDE_RELEASE_SMOKE_SUPERVISOR_INPUT_GUARD",
    )
    clean_ready_prompt = "Press Enter only when you are ready to observe the CLEAN autocomplete window"
    selected_ready_prompt = "Press Enter only when you are ready to observe the SELECTED autocomplete window"
    clean_ready_read = "IFS= read -r clean_ready_answer"
    selected_ready_read = "IFS= read -r selected_ready_answer"
    clean_launch = 'python3 "$root/scripts/release/claude-tty-supervisor.py" --probe-text "$probe_text" -- "$clroom" claude'
    selected_launch = 'python3 "$root/scripts/release/claude-tty-supervisor.py" --probe-text "$probe_text" -- "$clroom" claude --with="plugin:$plugin_id"'
    require(
        errors,
        clean_ready_prompt in text
        and clean_ready_read in text
        and '[[ -z "$clean_ready_answer" ]] || fail "CLEAN_OBSERVATION_READY_INVALID"' in text,
        "CLAUDE_RELEASE_SMOKE_CLEAN_OBSERVATION_READY",
    )
    require(
        errors,
        selected_ready_prompt in text
        and selected_ready_read in text
        and '[[ -z "$selected_ready_answer" ]] || fail "SELECTED_OBSERVATION_READY_INVALID"' in text,
        "CLAUDE_RELEASE_SMOKE_SELECTED_OBSERVATION_READY",
    )
    clean_ready_index = text.find(clean_ready_read)
    clean_launch_index = text.find(clean_launch)
    selected_ready_index = text.find(selected_ready_read)
    selected_launch_index = text.find(selected_launch)
    require(
        errors,
        clean_ready_index >= 0 and clean_launch_index > clean_ready_index,
        "CLAUDE_RELEASE_SMOKE_CLEAN_OBSERVATION_READY_ORDER",
    )
    require(
        errors,
        selected_ready_index >= 0 and selected_launch_index > selected_ready_index,
        "CLAUDE_RELEASE_SMOKE_SELECTED_OBSERVATION_READY_ORDER",
    )
    require(
        errors,
        "injects the exact non-submitting probe automatically" in text
        and "bounded observation window" in text
        and "then owns teardown" in text,
        "CLAUDE_RELEASE_SMOKE_AUTOMATIC_OBSERVATION",
    )
    require(
        errors,
        "Press Ctrl+T" not in text and "Press Ctrl+G" not in text,
        "CLAUDE_RELEASE_SMOKE_HUMAN_CONTROL_ACTIONS_FORBIDDEN",
    )
    require(
        errors,
        "PERSISTENT_CONFIG_CHANGED_CLEAN_INTERACTIVE" in text,
        "CLAUDE_RELEASE_SMOKE_CLEAN_FINGERPRINT",
    )
    require(
        errors,
        "PERSISTENT_CONFIG_CHANGED_SELECTED_INTERACTIVE" in text,
        "CLAUDE_RELEASE_SMOKE_SELECTED_FINGERPRINT",
    )
    require(
        errors,
        '"$phase" == "diagnose-screen"' in text,
        "CLAUDE_RELEASE_SMOKE_SCREEN_DIAGNOSTIC_PHASE",
    )
    require(
        errors,
        "--diagnose-unsupported" in text
        and "--diagnostic-evidence" in text,
        "CLAUDE_RELEASE_SMOKE_SCREEN_DIAGNOSTIC_LAUNCH",
    )
    require(
        errors,
        "No human observation or keypress is required." in text,
        "CLAUDE_RELEASE_SMOKE_SCREEN_DIAGNOSTIC_MACHINE_ONLY",
    )
    require(
        errors,
        "SCREEN_CONTROL_IDENTITY=" in text
        and "SCREEN_CONTROL_SHA256=" in text
        and "SCREEN_CONTROL_RAW_TRANSCRIPT_RECORDED=NO" in text
        and "SCREEN_CONTROL_DIAGNOSTIC=PASS" in text,
        "CLAUDE_RELEASE_SMOKE_SCREEN_DIAGNOSTIC_SANITIZED_EVIDENCE",
    )
    require(
        errors,
        "PERSISTENT_CONFIG_CHANGED_SCREEN_DIAGNOSTIC" in text,
        "CLAUDE_RELEASE_SMOKE_SCREEN_DIAGNOSTIC_FINGERPRINT",
    )
    diagnostic_start = text.find('if [[ "$phase" == "diagnose-screen" ]]')
    diagnostic_exit = text.find("exit 0", diagnostic_start)
    diagnostic_read = text.find("read -r", diagnostic_start)
    diagnostic_selected = text.find('--with="plugin:$plugin_id"', diagnostic_start)
    require(
        errors,
        diagnostic_start >= 0
        and diagnostic_exit > diagnostic_start
        and (diagnostic_read < 0 or diagnostic_read > diagnostic_exit),
        "CLAUDE_RELEASE_SMOKE_SCREEN_DIAGNOSTIC_NO_HUMAN_READ",
    )
    require(
        errors,
        diagnostic_start >= 0
        and diagnostic_exit > diagnostic_start
        and (diagnostic_selected < 0 or diagnostic_selected > diagnostic_exit),
        "CLAUDE_RELEASE_SMOKE_SCREEN_DIAGNOSTIC_CLEAN_ONLY",
    )
    forbidden = (
        "Press Escape once to dismiss autocomplete",
        "Visually confirm the composer is empty.",
        "Press Ctrl+C to cancel and clear the composer",
        "Press Ctrl+T",
        "Press Ctrl+G",
        "Press Ctrl+D twice within 800 ms",
        "Then press Ctrl+D to exit",
        "Exit normally with /exit.",
    )
    for marker in forbidden:
        require(errors, marker not in text, "CLAUDE_RELEASE_SMOKE_PROVIDER_EXIT_FORBIDDEN:" + marker)
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
    errors.extend(
        validate_indexnow_dependency_wait_contract(
            workflow_text[".github/workflows/indexnow.yml"]
        )
    )

    dependabot = read(root, ".github/dependabot.yml")
    require(errors, "codeql-family:" in dependabot, "DEPENDABOT_CODEQL_GROUP_MISSING")
    require(
        errors,
        '"github/codeql-action/*"' in dependabot or "'github/codeql-action/*'" in dependabot,
        "DEPENDABOT_CODEQL_PATTERN_MISSING",
    )

    release_candidate = workflow_text[".github/workflows/release-candidate.yml"]
    errors.extend(validate_supply_chain_verifier_contract(release_candidate))

    public_route_rehearsal_path = root / "scripts/release/rehearse-public-route.sh"
    require(errors, public_route_rehearsal_path.is_file(), "PUBLIC_ROUTE_REHEARSAL_MISSING")
    if public_route_rehearsal_path.is_file():
        public_route_rehearsal = public_route_rehearsal_path.read_text(encoding="utf-8")
        for marker in (
            "PUBLIC_ROUTE_REHEARSAL_SELF_TEST_PASS",
            "PUBLIC_ROUTE_REHEARSAL_PASS",
            'gh release view --repo "$repository"',
            'gh release view "$tag" --repo "$repository"',
            'gh release download "$tag"',
            "releases/latest/download",
            "ISOLATED_PUBLIC_INSTALL",
        ):
            require(errors, marker in public_route_rehearsal, "PUBLIC_ROUTE_REHEARSAL_CONTRACT:" + marker)
        syntax = subprocess.run(
            ["bash", "-n", str(public_route_rehearsal_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        require(errors, syntax.returncode == 0, "PUBLIC_ROUTE_REHEARSAL_BASH_SYNTAX")
        rehearsal_self_test = subprocess.run(
            ["bash", str(public_route_rehearsal_path), "--self-test"],
            capture_output=True,
            text=True,
            check=False,
        )
        if rehearsal_self_test.returncode != 0:
            if rehearsal_self_test.stdout:
                print(rehearsal_self_test.stdout, end="", file=sys.stderr)
            if rehearsal_self_test.stderr:
                print(rehearsal_self_test.stderr, end="", file=sys.stderr)
        require(
            errors,
            rehearsal_self_test.returncode == 0
            and "PUBLIC_ROUTE_REHEARSAL_SELF_TEST_PASS" in rehearsal_self_test.stdout,
            "PUBLIC_ROUTE_REHEARSAL_SELF_TEST",
        )
    route_step = release_candidate.find("Rehearse current published public route before expensive lanes")
    provider_step = release_candidate.find("Provision pinned real provider canaries")
    require(errors, route_step >= 0, "PUBLIC_ROUTE_REHEARSAL_WORKFLOW_STEP")
    require(
        errors,
        route_step >= 0 and provider_step >= 0 and route_step < provider_step,
        "PUBLIC_ROUTE_REHEARSAL_BEFORE_PROVIDER",
    )
    require(
        errors,
        "bash scripts/release/rehearse-public-route.sh --self-test" in release_candidate
        and "bash scripts/release/rehearse-public-route.sh" in release_candidate,
        "PUBLIC_ROUTE_REHEARSAL_WORKFLOW_INVOCATION",
    )

    accepted_main_claude_stage_path = root / "scripts/release/run-accepted-main-claude-stage.sh"
    require(errors, accepted_main_claude_stage_path.is_file(), "ACCEPTED_MAIN_CLAUDE_STAGE_ENTRYPOINT_MISSING")
    if accepted_main_claude_stage_path.is_file():
        accepted_main_claude_stage = accepted_main_claude_stage_path.read_text(encoding="utf-8")
        for marker in (
            'git rev-parse --show-toplevel',
            'gh repo view --json nameWithOwner --jq .nameWithOwner',
            'gh api "repos/$repository/git/ref/heads/main" --jq .object.sha',
            'git fetch --quiet --tags "https://github.com/$repository.git" main',
            'git worktree add --detach "$worktree" "$accepted_before"',
            'scripts/release/resolve-pretag-stage.sh',
            '"artifact_name"',
            'scripts/release/local-plugin-activation-smoke.sh stage',
            'scripts/release/verify-claude-stage-evidence.py',
            'MAIN_MOVED_DURING_FETCH',
            'MAIN_MOVED_AFTER_EVIDENCE',
            'ACCEPTED_MAIN_CLAUDE_STAGE_PASS',
        ):
            require(
                errors,
                marker in accepted_main_claude_stage,
                "ACCEPTED_MAIN_CLAUDE_STAGE_ENTRYPOINT_CONTRACT:" + marker,
            )
        for forbidden in (
            "/path/to/",
            "git reset",
            "git clean",
            "git stash",
            'rm -rf "$worktree"',
        ):
            require(
                errors,
                forbidden not in accepted_main_claude_stage,
                "ACCEPTED_MAIN_CLAUDE_STAGE_ENTRYPOINT_FORBIDDEN:" + forbidden,
            )
        syntax = subprocess.run(
            ["bash", "-n", str(accepted_main_claude_stage_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        require(errors, syntax.returncode == 0, "ACCEPTED_MAIN_CLAUDE_STAGE_ENTRYPOINT_BASH_SYNTAX")

    claude_release_smoke = read(root, "scripts/release/local-plugin-activation-smoke.sh")
    errors.extend(validate_claude_release_smoke_contract(claude_release_smoke))
    claude_tty_supervisor_path = root / "scripts/release/claude-tty-supervisor.py"
    claude_tty_supervisor = claude_tty_supervisor_path.read_text(encoding="utf-8")
    errors.extend(validate_claude_tty_supervisor_contract(claude_tty_supervisor))
    supervisor_self_test = subprocess.run(
        [sys.executable, str(claude_tty_supervisor_path), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
    )
    if supervisor_self_test.returncode != 0:
        if supervisor_self_test.stdout:
            print(supervisor_self_test.stdout, end="", file=sys.stderr)
        if supervisor_self_test.stderr:
            print(supervisor_self_test.stderr, end="", file=sys.stderr)
    require(
        errors,
        supervisor_self_test.returncode == 0
        and "CLAUDE_TTY_SUPERVISOR_SELF_TEST_PASS" in supervisor_self_test.stdout,
        "CLAUDE_TTY_SUPERVISOR_SELF_TEST",
    )
    terminal_diagnostic_path = root / "scripts/release/terminal-state-diagnostic.py"
    require(errors, terminal_diagnostic_path.is_file(), "TERMINAL_STATE_DIAGNOSTIC_MISSING")
    terminal_diagnostic = terminal_diagnostic_path.read_text(encoding="utf-8")
    for marker in (
        'SCHEMA_VERSION = "clroom.terminal-state-diagnostic.v1"',
        'os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)',
        '"focus_reporting"',
        '"bracketed_paste"',
        '"color_scheme_reporting"',
        'COLOR_SCHEME_REPORT_RE',
        'b"\\x1b[?u"',
        '"termios_restored"',
        '"chunks"',
        '"unexpected_hex"',
        '"TERMINAL_PREFLIGHT_SUMMARY "',
    ):
        require(errors, marker in terminal_diagnostic, "TERMINAL_STATE_DIAGNOSTIC_CONTRACT:" + marker)
    require(errors, 'query.endswith((b"h", b"l"))' in terminal_diagnostic, "TERMINAL_STATE_DIAGNOSTIC_QUERY_ONLY")
    terminal_diagnostic_self_test = subprocess.run(
        [sys.executable, str(terminal_diagnostic_path), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
    )
    if terminal_diagnostic_self_test.returncode != 0:
        if terminal_diagnostic_self_test.stdout:
            print(terminal_diagnostic_self_test.stdout, end="", file=sys.stderr)
        if terminal_diagnostic_self_test.stderr:
            print(terminal_diagnostic_self_test.stderr, end="", file=sys.stderr)
    require(
        errors,
        terminal_diagnostic_self_test.returncode == 0
        and "TERMINAL_STATE_DIAGNOSTIC_SELF_TEST_PASS" in terminal_diagnostic_self_test.stdout,
        "TERMINAL_STATE_DIAGNOSTIC_SELF_TEST",
    )
    provider_source_pin_checker_path = root / "scripts/release/check-provider-source-pins.py"
    require(errors, provider_source_pin_checker_path.is_file(), "PROVIDER_SOURCE_PIN_CHECKER_MISSING")
    if provider_source_pin_checker_path.is_file():
        provider_source_pin_checker = provider_source_pin_checker_path.read_text(encoding="utf-8")
        for marker in (
            "PROVIDER_SOURCE_PIN_BLOCKED:",
            "CLAUDE_CLEAN_EXACT",
            "CLAUDE_PLUGIN_ACTIVATION_EXACT",
            "CODEX_CLEAN_EXACT",
            "CODEX_PLUGIN_ACTIVATION_EXACT",
            "PROVIDER_SOURCE_PIN_SELF_TEST_PASS",
        ):
            require(
                errors,
                marker in provider_source_pin_checker,
                "PROVIDER_SOURCE_PIN_CHECKER_CONTRACT:" + marker,
            )
        provider_source_pin_self_test = subprocess.run(
            [sys.executable, str(provider_source_pin_checker_path), "--self-test"],
            capture_output=True,
            text=True,
            check=False,
        )
        if provider_source_pin_self_test.returncode != 0:
            if provider_source_pin_self_test.stdout:
                print(provider_source_pin_self_test.stdout, end="", file=sys.stderr)
            if provider_source_pin_self_test.stderr:
                print(provider_source_pin_self_test.stderr, end="", file=sys.stderr)
        require(
            errors,
            provider_source_pin_self_test.returncode == 0
            and "PROVIDER_SOURCE_PIN_SELF_TEST_PASS" in provider_source_pin_self_test.stdout,
            "PROVIDER_SOURCE_PIN_CHECKER_SELF_TEST",
        )

    readiness = read(root, "scripts/release/readiness.sh")
    require(
        errors,
        "python3 scripts/release/check-provider-source-pins.py --self-test" in readiness,
        "PROVIDER_SOURCE_PIN_SELF_TEST_DISCONNECTED",
    )
    require(
        errors,
        'python3 scripts/release/check-provider-source-pins.py || fail "PROVIDER_SOURCE_PIN_CONTRACT"' in readiness,
        "PROVIDER_SOURCE_PIN_CHECK_DISCONNECTED",
    )
    for literal_escape, code in (
        ('PROVIDER_SOURCE_PIN_CONTRACT"\\npython3', "RELEASE_READINESS_LITERAL_NEWLINE_AFTER_PROVIDER_CONTRACT"),
        ('RELEASE_EXTERNAL_ACTION_SELF_TEST"\\npython3', "RELEASE_READINESS_LITERAL_NEWLINE_AFTER_EXTERNAL_ACTION"),
        ('PROVIDER_SOURCE_PIN_CHECKER_MISSING"\\n[[', "RELEASE_READINESS_LITERAL_NEWLINE_AFTER_PROVIDER_CHECK"),
        ('RELEASE_EXTERNAL_ACTION_HELPER_MISSING"\\n[[', "RELEASE_READINESS_LITERAL_NEWLINE_AFTER_EXTERNAL_HELPER"),
    ):
        require(errors, literal_escape not in readiness, code)
    require(
        errors,
        'python3 scripts/release/release-external-action.py self-test || fail "RELEASE_EXTERNAL_ACTION_SELF_TEST"' in readiness,
        "RELEASE_EXTERNAL_ACTION_SELF_TEST_DISCONNECTED",
    )
    require(
        errors,
        'python3 scripts/release/rehearse-external-release-lifecycle.py --self-test || fail "RELEASE_INTEGRATION_REHEARSAL_SELF_TEST"' in readiness,
        "RELEASE_INTEGRATION_REHEARSAL_SELF_TEST_DISCONNECTED",
    )

    claude_stage_verifier = read(root, "scripts/release/verify-claude-stage-evidence.py")
    require(
        errors,
        'SCHEMA_VERSION = "clroom.plugin-release-smoke.v6"' in claude_stage_verifier,
        "CLAUDE_STAGE_EVIDENCE_SCHEMA_V6",
    )
    require(
        errors,
        '"automated_probe_prompt_supplied": False' in claude_stage_verifier,
        "CLAUDE_STAGE_EVIDENCE_PROMPT_FALSE",
    )
    for marker in (
        '"clean_tui_supervised": True',
        '"selected_tui_supervised": True',
        '"interactive_human_bytes_forwarded": False',
        '"interactive_submit_bytes_blocked_by_supervisor": True',
        '"interactive_harness_owned_teardown": True',
        '"physical_terminal_preflight_passed": True',
        '"interactive_terminal_state_restored": True',
        '"clean_observation_ready_acknowledged": True',
        '"selected_observation_ready_acknowledged": True',
    ):
        require(errors, marker in claude_stage_verifier, "CLAUDE_STAGE_EVIDENCE_SUPERVISOR:" + marker)
    require(
        errors,
        "CLAUDE_STAGE_EVIDENCE_SELF_TEST_PASS" in claude_stage_verifier
        and 'legacy["schema_version"] = "clroom.plugin-release-smoke.v5"' in claude_stage_verifier,
        "CLAUDE_STAGE_EVIDENCE_READINESS_NEGATIVE_SELF_TEST",
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
    publishable = release_jobs.get("publishable-content", "")
    require(errors, "name: Publishable content semantic closure" in publishable, "PUBLISHABLE_CONTENT_JOB_MISSING")
    require(errors, "needs: [release-eligibility, pretag-stage]" in publishable, "PUBLISHABLE_CONTENT_TOPOLOGY")
    require(errors, "verify-publishable-surface.py" in publishable, "PUBLISHABLE_CONTENT_SEMANTIC_VERIFIER")
    require(errors, "--evidence pretag-stage/publishable-surface.json" in publishable, "PUBLISHABLE_CONTENT_EVIDENCE_BINDING")
    eligibility = release_jobs.get("release-eligibility", "")
    require(errors, "runs-on: ubuntu-latest" in eligibility, "RELEASE_ELIGIBILITY_RUNNER")
    require(errors, "check-release-contract.py --self-test" in eligibility, "RELEASE_ELIGIBILITY_SELF_TEST")
    require(errors, "resolve-release-lifecycle.py --self-test" in eligibility, "RELEASE_LIFECYCLE_SELF_TEST_EARLY")
    require(errors, "tag_source: ${{ steps.lifecycle.outputs.tag_source }}" in eligibility, "RELEASE_QUARANTINE_TAG_SOURCE_OUTPUT")
    require(errors, "RELEASE_QUARANTINED" in eligibility, "RELEASE_QUARANTINE_ELIGIBILITY_BRANCH")
    require(errors, "RELEASE_QUARANTINE_PASS" in eligibility, "RELEASE_QUARANTINE_IDENTITY_GATE")
    require(errors, "check-quarantine-repair-scope.py" not in eligibility, "RELEASE_QUARANTINE_PATH_ALLOWLIST_FORBIDDEN")
    require(errors, "check-release-contract.py --report" in eligibility, "RELEASE_ELIGIBILITY_SEAL")
    readiness = release_jobs.get("release-readiness", "")
    require(errors, "needs: release-eligibility" in readiness, "RELEASE_READINESS_NEEDS_ELIGIBILITY")
    require(
        errors,
        "if: needs.release-eligibility.outputs.lifecycle != 'RELEASE_QUARANTINED'" in readiness,
        "RELEASE_QUARANTINE_EXPENSIVE_READINESS_SKIP",
    )
    stage = release_jobs.get("pretag-stage", "")
    require(
        errors,
        "needs: [release-eligibility, release-readiness]" in stage,
        "PRETAG_STAGE_TOPOLOGY",
    )
    attest = release_jobs.get("pretag-attestation-rehearsal", "")
    require(
        errors,
        "needs: [release-eligibility, release-readiness, pretag-stage, publishable-content]" in attest,
        "PRETAG_ATTEST_TOPOLOGY",
    )
    release_required = release_jobs.get("release-required", "")
    require(errors, "name: Release required" in release_required, "RELEASE_REQUIRED_NAME")
    require(
        errors,
        "needs: [release-eligibility, release-readiness, pretag-stage, publishable-content, pretag-attestation-rehearsal, promotion-prepare-rehearsal]" in release_required,
        "RELEASE_REQUIRED_TOPOLOGY",
    )
    require(errors, "if: always()" in release_required, "RELEASE_REQUIRED_ALWAYS")
    require(errors, "publishable-content" in release_required, "PUBLISHABLE_CONTENT_RELEASE_REQUIRED")
    require(errors, 'PUBLISHABLE: ${{ needs.publishable-content.result }}' in release_required, "PUBLISHABLE_CONTENT_RESULT_BINDING")
    require(errors, 'test "$PUBLISHABLE" = success' in release_required, "PUBLISHABLE_CONTENT_SUCCESS_REQUIRED")
    require(errors, "RELEASE_QUARANTINED:*" in release_required, "RELEASE_QUARANTINE_REQUIRED_CASE")
    require(
        errors,
        release_required.count('test "$READINESS" = skipped') >= 1
        and release_required.count('test "$STAGE" = skipped') >= 2,
        "RELEASE_QUARANTINE_REQUIRED_SKIPS",
    )
    require(
        errors,
        not (root / "scripts/release/check-quarantine-repair-scope.py").exists(),
        "RELEASE_QUARANTINE_PATH_ALLOWLIST_MUST_BE_REMOVED",
    )

    docs = read(root, "docs/release/RELEASE_CONTRACT.md")
    for marker in AUTOMATION_MARKERS:
        require(errors, marker in docs, "AUTOMATION_MARKER_MISSING:" + marker)
    require(errors, "FIRST_EXECUTION_MATRIX" in docs, "RELEASE_FIRST_EXECUTION_MATRIX_MISSING")
    for marker in (
        "Boundary / First-Execution Map",
        "POST_BOUNDARY_ONLY_WHITELIST",
        "release-external-action.py",
        "rehearse-external-release-lifecycle.py",
        "LAB_REQUIRED",
        "exact remote protected tag object",
        "the one exact production Draft→published effect",
        "exact new `releases/latest/download` routes",
        "rendered GitHub Releases identity",
        "resource lifecycle / cleanup",
        "PRESERVED_PENDING_OWNER_GATE",
        "RELEASE_QUARANTINED",
        "consumed protected tag",
        "normal protected PR gates",
    ):
        require(errors, marker in docs, "RELEASE_FIRST_EXECUTION_MATRIX_CONTRACT:" + marker)

    capability_step = release_candidate.find(
        "Probe post-tag GitHub action capabilities on representative runner"
    )
    lifecycle_step = release_candidate.find("Resolve published release lifecycle")
    require(
        errors,
        capability_step >= 0
        and lifecycle_step >= 0
        and capability_step < lifecycle_step,
        "REPRESENTATIVE_RUNNER_TOOLCHAIN_ORDER",
    )
    require(
        errors,
        "bash scripts/release/check-publish-toolchain.sh --capabilities-only"
        in release_candidate,
        "REPRESENTATIVE_RUNNER_TOOLCHAIN_INVOCATION",
    )

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
    draft_verifier = read(root, "scripts/release/verify-draft-release.sh")
    require(errors, 'tags:\n      - "v*"' in release, "RELEASE_TAG_TRIGGER")
    integration_rehearsal_path = root / "scripts/release/rehearse-external-release-lifecycle.py"
    require(
        errors,
        integration_rehearsal_path.is_file(),
        "RELEASE_INTEGRATION_REHEARSAL_MISSING",
    )
    if integration_rehearsal_path.is_file():
        integration_rehearsal = integration_rehearsal_path.read_text(encoding="utf-8")
        for marker in (
            "CLROOM_OWNER_LAB_REHEARSAL_APPROVED",
            "PRODUCTION_REPOSITORY_FORBIDDEN",
            "clroom.integration-fidelity-matrix.v1",
            "release-external-action.py",
            "github_file_sha256",
            "expected_repository_id",
            "candidate_head",
            'f"YES:{repository}:{args.expected_repository_id}:"',
            "IDENTITY_BINDING",
            "RELEASE_INTEGRATION_IDENTITY_BINDING_PASS",
            "tag-push",
            "draft-promote",
            "publish",
            "PRESERVED_PENDING_OWNER_GATE",
            "RELEASE_INTEGRATION_REHEARSAL_PASS",
        ):
            require(
                errors,
                marker in integration_rehearsal,
                "RELEASE_INTEGRATION_REHEARSAL_CONTRACT:" + marker,
            )
        require(
            errors,
            integration_rehearsal.count("--simulate-local-error-after-action") >= 3,
            "RELEASE_INTEGRATION_AMBIGUOUS_OUTCOME_REHEARSAL",
        )
        for marker in (
            "PASS_WITH_SIMULATED_LOCAL_ERROR_RECONCILED",
            '"draft_upload": "PASS_WITH_SIMULATED_LOCAL_ERROR_RECONCILED"',
        ):
            require(
                errors,
                marker in integration_rehearsal,
                "RELEASE_INTEGRATION_RECONCILIATION_EVIDENCE:" + marker,
            )
        rehearsal_self_test = subprocess.run(
            [sys.executable, str(integration_rehearsal_path), "--self-test"],
            capture_output=True,
            text=True,
            check=False,
        )
        require(
            errors,
            rehearsal_self_test.returncode == 0
            and "RELEASE_INTEGRATION_REHEARSAL_SELF_TEST_PASS"
            in rehearsal_self_test.stdout,
            "RELEASE_INTEGRATION_REHEARSAL_SELF_TEST",
        )

    require(
        errors,
        "python3 scripts/release/release-external-action.py publish"
        in draft_verifier
        and '|| fail "PUBLISH_ACTION_REHEARSAL"' in draft_verifier,
        "DRAFT_VERIFIER_PUBLISH_ACTION_REHEARSAL",
    )

    require(
        errors,
        "python3 scripts/release/release-external-action.py draft-promote" in release,
        "RELEASE_DRAFT_ONLY_CANONICAL_PATH",
    )
    require(errors, "--draft=false" not in release, "RELEASE_AUTO_PUBLISH_FORBIDDEN")
    require(errors, "gh release publish" not in release, "RELEASE_AUTO_PUBLISH_COMMAND")
    require(
        errors,
        "--preview-json release-stage/publish-preview.json" in release
        and "--notes-file release-stage/release-notes.md" in release,
        "DRAFT_PREVIEW_RECONCILIATION",
    )
    publish_toolchain_path = root / "scripts/release/check-publish-toolchain.sh"
    require(errors, publish_toolchain_path.is_file(), "PUBLISH_TOOLCHAIN_CHECK_MISSING")
    if publish_toolchain_path.is_file():
        publish_toolchain = publish_toolchain_path.read_text(encoding="utf-8")
        for marker in (
            "PUBLISH_TOOLCHAIN_SELF_TEST_PASS",
            "PUBLISH_TOOLCHAIN_CAPABILITY_PASS",
            "RELEASE_CREATE_CAPABILITY",
            "RELEASE_EDIT_CAPABILITY",
            "RELEASE_UPLOAD_CAPABILITY",
            "RELEASE_VIEW_JSON_CAPABILITY",
            "RELEASE_BY_ID_API_CAPABILITY",
            "LATEST_API_CAPABILITY",
            "IMMUTABLE_POLICY_API_CAPABILITY",
        ):
            require(errors, marker in publish_toolchain, "PUBLISH_TOOLCHAIN_CONTRACT:" + marker)
        syntax = subprocess.run(
            ["bash", "-n", str(publish_toolchain_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        require(errors, syntax.returncode == 0, "PUBLISH_TOOLCHAIN_BASH_SYNTAX")
        toolchain_self_test = subprocess.run(
            ["bash", str(publish_toolchain_path), "--self-test"],
            capture_output=True,
            text=True,
            check=False,
        )
        if toolchain_self_test.returncode != 0:
            if toolchain_self_test.stdout:
                print(toolchain_self_test.stdout, end="", file=sys.stderr)
            if toolchain_self_test.stderr:
                print(toolchain_self_test.stderr, end="", file=sys.stderr)
        require(
            errors,
            toolchain_self_test.returncode == 0
            and "PUBLISH_TOOLCHAIN_SELF_TEST_PASS" in toolchain_self_test.stdout,
            "PUBLISH_TOOLCHAIN_SELF_TEST",
        )

    tag_helper = read(root, "scripts/release/push-release-tag.sh")
    for marker, code in (
        ("ensure_remote_tag_absent INITIAL || exit 68", "TAG_HELPER_CONSUMED_TAG_BLOCK_INITIAL"),
        ("ensure_release_absent INITIAL || exit 68", "TAG_HELPER_CONSUMED_RELEASE_BLOCK_INITIAL"),
        (
            "ensure_remote_tag_absent ACTION_TIME || { cleanup_local_tag; exit 76; }",
            "TAG_HELPER_CONSUMED_TAG_BLOCK_ACTION_TIME",
        ),
        (
            "ensure_release_absent ACTION_TIME || { cleanup_local_tag; exit 76; }",
            "TAG_HELPER_CONSUMED_RELEASE_BLOCK_ACTION_TIME",
        ),
    ):
        require(errors, marker in tag_helper, code)
    require(errors, "PUBLISHABLE_CONTENT_JOB_PASS" in tag_helper, "TAG_HELPER_PUBLISHABLE_CONTENT_JOB")
    require(errors, "PUBLISH_PREVIEW_BINDING_PASS" in tag_helper, "TAG_HELPER_PUBLISH_PREVIEW_BINDING")
    require(
        errors,
        "bash scripts/release/check-publish-toolchain.sh --self-test" in tag_helper
        and "bash scripts/release/check-publish-toolchain.sh" in tag_helper,
        "TAG_HELPER_PUBLISH_TOOLCHAIN_GATE",
    )
    require(errors, "publish-preview.json" in draft_verifier, "DRAFT_VERIFIER_PUBLISH_PREVIEW")

    external_action_path = root / "scripts/release/release-external-action.py"
    require(errors, external_action_path.is_file(), "RELEASE_EXTERNAL_ACTION_HELPER_MISSING")
    if external_action_path.is_file():
        external_action = external_action_path.read_text(encoding="utf-8")
        for marker in (
            "RELEASE_EXTERNAL_ACTION_SELF_TEST_PASS",
            "tag-push",
            "draft-promote",
            "publish",
            "git\", \"push",
            "TAG_PUSH_OUTCOME_RECONCILED_ABSENT",
            "--clobber",
            "DRAFT_DOWNLOAD_BYTE_DRIFT",
            "gh_release_lookup_for_promote",
            "RELEASE_LOOKUP_UNCERTAIN",
            "RELEASE_COLLECTION_DUPLICATE",
            "databaseId,tagName,name,isDraft,isPrerelease,isImmutable,publishedAt,body,assets",
            "DRAFT_UNCHANGED",
            "PUBLISHED_PENDING_IMMUTABILITY",
            "PUBLISHED_EXACT",
            "PUBLISH_ACTION_REHEARSAL_PASS",
            "GUARDED_PUBLISH_OUTCOME_UNKNOWN",
        ):
            require(errors, marker in external_action, "RELEASE_EXTERNAL_ACTION_CONTRACT:" + marker)
        external_self_test = subprocess.run(
            [sys.executable, str(external_action_path), "self-test"],
            capture_output=True,
            text=True,
            check=False,
        )
        require(
            errors,
            external_self_test.returncode == 0
            and "RELEASE_EXTERNAL_ACTION_SELF_TEST_PASS" in external_self_test.stdout,
            "RELEASE_EXTERNAL_ACTION_SELF_TEST",
        )

    require(
        errors,
        "python3 scripts/release/release-external-action.py draft-promote" in release,
        "RELEASE_DRAFT_CANONICAL_ACTION_PATH",
    )
    require(
        errors,
        'gh release upload "$tag"' not in release,
        "RELEASE_DRAFT_INLINE_UPLOAD_FORBIDDEN",
    )

    tag_helper = read(root, "scripts/release/push-release-tag.sh")
    require(
        errors,
        "python3 scripts/release/release-external-action.py tag-push" in tag_helper,
        "TAG_HELPER_CANONICAL_EXTERNAL_ACTION",
    )
    require(
        errors,
        'git push origin "refs/tags/$tag"' not in tag_helper,
        "TAG_HELPER_INLINE_PUSH_FORBIDDEN",
    )

    publish_helper = read(root, "scripts/release/publish-release.sh")
    publish_syntax = subprocess.run(
        ["bash", "-n", str(root / "scripts/release/publish-release.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    require(errors, publish_syntax.returncode == 0, "GUARDED_PUBLISH_BASH_SYNTAX")
    for item in (
        "CLROOM_OWNER_PUBLISH_APPROVED",
        "verify-draft-release.sh",
        "resolve-pretag-stage.sh",
        "PRETAG_STAGE_BINDING",
        "MAIN_DRIFT_ACTION_TIME",
        "TAG_TARGET_ACTION_TIME",
        "IMMUTABLE_RELEASE_POLICY_ACTION_TIME",
        "python3 scripts/release/release-external-action.py publish",
        "--preview-json",
        "--apply",
    ):
        require(errors, item in publish_helper, "GUARDED_PUBLISH_CONTRACT:" + item)
    require(
        errors,
        'gh release edit "$tag" --draft=false --latest' not in publish_helper,
        "GUARDED_PUBLISH_INLINE_MUTATION_FORBIDDEN",
    )

    public_verify = read(root, "scripts/release/verify-public-release.sh")
    for item in (
        "releases/latest/download",
        "ISOLATED_PUBLIC_INSTALL",
        "PUBLIC_INSTALL_ROUTE_VERIFY_PASS",
        "PUBLIC_RELEASE_STATE_PROPAGATION",
        "ASSET_DOWNLOAD_PROPAGATION",
        "--retry 5 --retry-all-errors --retry-delay 1",
    ):
        require(errors, item in public_verify, "PUBLIC_INSTALL_ROUTE_CONTRACT:" + item)
    public_verify_syntax = subprocess.run(
        ["bash", "-n", str(root / "scripts/release/verify-public-release.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    require(errors, public_verify_syntax.returncode == 0, "PUBLIC_INSTALL_ROUTE_BASH_SYNTAX")

    resolver = read(root, "scripts/release/resolve-pretag-stage.sh")
    admission = read(root, "scripts/release/pretag-run-admission.py")
    errors.extend(
        validate_pretag_current_run_contract(
            resolver, admission, promotion, release, release_candidate
        )
    )

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

    indexnow_fixture = """
timeout-minutes: 20
while true; do
  runs=$(gh api --paginate "repos/$GITHUB_REPOSITORY/actions/runs?head_sha=$GITHUB_SHA&per_page=100")
  ci=$(printf '%s\\n' "$runs" | awk -F '\\t' '$1 == "CI" { print; exit }')
  pages=$(printf '%s\\n' "$runs" | awk -F '\\t' '$1 == "pages build and deployment" { print; exit }')
  if [ "$ci_status" = completed ] && [ "$ci_conclusion" != success ]; then exit 1; fi
  if [ "$pages_status" = completed ] && [ "$pages_conclusion" != success ]; then exit 1; fi
  if [ "$ci_status" = completed ] && [ "$ci_conclusion" = success ] && [ "$pages_status" = completed ] && [ "$pages_conclusion" = success ]; then exit 0; fi
  sleep 10
done
"""
    if validate_indexnow_dependency_wait_contract(indexnow_fixture):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:INDEXNOW_WAIT_CLEAN")
    stale_indexnow = indexnow_fixture.replace(
        "while true; do",
        "for attempt in $(seq 1 60); do",
    ) + "\\nTimed out waiting for same-SHA CI and Pages deployment\\n"
    stale_errors = validate_indexnow_dependency_wait_contract(stale_indexnow)
    if "INDEXNOW_FIXED_RETRY_WINDOW_FORBIDDEN" not in stale_errors:
        raise SystemExit("HARNESS_SELF_TEST_FAIL:INDEXNOW_FIXED_WINDOW")
    if "INDEXNOW_SECOND_DEADLINE_FORBIDDEN" not in stale_errors:
        raise SystemExit("HARNESS_SELF_TEST_FAIL:INDEXNOW_SECOND_DEADLINE")
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
pretag-run-admission.py
--run-json "$tmp/run-$run_id.json"
run_args+=(--current-run-id "$current_run_id")
--jobs-json "$tmp/jobs-$run_id.json"
"""
    admission_fixture = """
run.get("status") == "completed" and run.get("conclusion") == "success"
run.get("status") != "in_progress"
run.get("conclusion") is not None
Release eligibility and harness seal
CLROOM release readiness
Rehearse/stage exact release bytes
Rehearse attestation mechanism before tag
job.get("status") != "completed" or job.get("conclusion") != "success"
PRETAG_RUN_ADMISSION_SELF_TEST_PASS
"""
    promotion_fixture = "CLROOM_PRETAG_CURRENT_RUN_ID: ${{ github.run_id }}"
    release_fixture = 'tags:\n      - "v*"'
    candidate_fixture = "python3 scripts/release/pretag-run-admission.py --self-test"
    if validate_pretag_current_run_contract(
        resolver_fixture,
        admission_fixture,
        promotion_fixture,
        release_fixture,
        candidate_fixture,
    ):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:PRETAG_CURRENT_RUN_CLEAN")
    missing_upstream = admission_fixture.replace(
        "Rehearse attestation mechanism before tag", "missing attestation"
    )
    if not any(
        error.startswith("PRETAG_CURRENT_RUN_UPSTREAM_JOB:")
        for error in validate_pretag_current_run_contract(
            resolver_fixture,
            missing_upstream,
            promotion_fixture,
            release_fixture,
            candidate_fixture,
        )
    ):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:PRETAG_CURRENT_RUN_UPSTREAM")
    tag_exception = release_fixture + "\nCLROOM_PRETAG_CURRENT_RUN_ID\n"
    if "PRETAG_CURRENT_RUN_TAG_PATH_FORBIDDEN" not in validate_pretag_current_run_contract(
        resolver_fixture,
        admission_fixture,
        promotion_fixture,
        tag_exception,
        candidate_fixture,
    ):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:PRETAG_CURRENT_RUN_TAG_PATH")
    weak_identity = resolver_fixture.replace(
        '[[ "${GITHUB_REF:-}" == "refs/heads/main" ]]', ""
    )
    if "PRETAG_CURRENT_RUN_REF" not in validate_pretag_current_run_contract(
        weak_identity,
        admission_fixture,
        promotion_fixture,
        release_fixture,
        candidate_fixture,
    ):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:PRETAG_CURRENT_RUN_IDENTITY")
    missing_behavioral_self_test = candidate_fixture.replace("--self-test", "--report")
    if "PRETAG_CURRENT_RUN_SELF_TEST_EARLY" not in validate_pretag_current_run_contract(
        resolver_fixture,
        admission_fixture,
        promotion_fixture,
        release_fixture,
        missing_behavioral_self_test,
    ):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:PRETAG_CURRENT_RUN_SELF_TEST")
    claude_smoke_fixture = """
if [[ "$phase" == "diagnose-screen" ]]; then
"No human observation or keypress is required."
python3 "$root/scripts/release/claude-tty-supervisor.py" --diagnose-unsupported --diagnostic-evidence "$diagnostic_evidence" -- "$clroom" claude
"SCREEN_CONTROL_IDENTITY="
"SCREEN_CONTROL_SHA256="
"SCREEN_CONTROL_RAW_TRANSCRIPT_RECORDED=NO"
"SCREEN_CONTROL_DIAGNOSTIC=PASS"
"PERSISTENT_CONFIG_CHANGED_SCREEN_DIAGNOSTIC"
exit 0
fi
cd "$root"
"Press Enter only when you are ready to observe the CLEAN autocomplete window"
IFS= read -r clean_ready_answer
[[ -z "$clean_ready_answer" ]] || fail "CLEAN_OBSERVATION_READY_INVALID"
python3 "$root/scripts/release/claude-tty-supervisor.py" --probe-text "$probe_text" -- "$clroom" claude
cd "$root"
"Press Enter only when you are ready to observe the SELECTED autocomplete window"
IFS= read -r selected_ready_answer
[[ -z "$selected_ready_answer" ]] || fail "SELECTED_OBSERVATION_READY_INVALID"
python3 "$root/scripts/release/claude-tty-supervisor.py" --probe-text "$probe_text" -- "$clroom" claude --with="plugin:$plugin_id"
"The AGENTS boundary is already machine-proved; human work is autocomplete observation only."
python3 "$root/scripts/release/terminal-state-diagnostic.py" --expected-head "$head"
"No inference/model response appeared in either TUI"
"schema_version":"clroom.plugin-release-smoke.v6"
"automated_probe_prompt_supplied":False
"clean_tui_confirmed":clean_tui=="true"
"clean_tui_supervised":clean_tui_supervised=="true"
"selected_tui_supervised":selected_tui_supervised=="true"
"interactive_human_bytes_forwarded":False
"interactive_submit_bytes_blocked_by_supervisor":True
"interactive_harness_owned_teardown":True
"physical_terminal_preflight_passed":physical_terminal_preflight=="true"
"interactive_terminal_state_restored":interactive_terminal_state_restored=="true"
"clean_observation_ready_acknowledged":clean_observation_ready=="true"
"selected_observation_ready_acknowledged":selected_observation_ready=="true"
"selected_tui_confirmed":interactive=="true"
"Do not type into Claude."
"The supervisor waits for the normal composer, injects the exact non-submitting probe automatically, keeps the TUI open for a bounded observation window, then owns teardown."
"The readiness Enter is consumed by the harness before Claude starts and is never forwarded to Claude."
"Keep this terminal visible until the bounded observation window ends and the confirmation questions appear."
"PERSISTENT_CONFIG_CHANGED_CLEAN_INTERACTIVE"
"PERSISTENT_CONFIG_CHANGED_SELECTED_INTERACTIVE"
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
    for provider_exit in (
        "Press Escape once to dismiss autocomplete",
        "Visually confirm the composer is empty.",
        "Press Ctrl+C to cancel and clear the composer",
        "Press Ctrl+D twice within 800 ms",
        "Exit normally with /exit.",
    ):
        provider_exit_errors = validate_claude_release_smoke_contract(
            claude_smoke_fixture + "\n" + provider_exit
        )
        if not any(
            code.startswith("CLAUDE_RELEASE_SMOKE_PROVIDER_EXIT_FORBIDDEN:")
            for code in provider_exit_errors
        ):
            raise SystemExit("HARNESS_SELF_TEST_FAIL:CLAUDE_PROVIDER_EXIT_NOT_REJECTED")
    synthetic_tui = claude_smoke_fixture.replace('cd "$root"\n', 'cd "$tui_project"\n', 1)
    if "CLAUDE_RELEASE_SMOKE_SYNTHETIC_TUI_FORBIDDEN" not in validate_claude_release_smoke_contract(synthetic_tui):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:CLAUDE_SYNTHETIC_TUI_NOT_REJECTED")
    human_agents = claude_smoke_fixture + '\nRepo/nested project AGENTS.md was reported as loaded\n'
    if "CLAUDE_RELEASE_SMOKE_HUMAN_AGENTS_RECHECK_FORBIDDEN" not in validate_claude_release_smoke_contract(human_agents):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:CLAUDE_HUMAN_AGENTS_RECHECK_NOT_REJECTED")
    missing_supervisor = claude_smoke_fixture.replace(
        'python3 "$root/scripts/release/claude-tty-supervisor.py" --probe-text "$probe_text" -- "$clroom" claude\n',
        "",
    )
    if "CLAUDE_RELEASE_SMOKE_CLEAN_SUPERVISOR_LAUNCH" not in validate_claude_release_smoke_contract(missing_supervisor):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:CLAUDE_SUPERVISOR_NOT_REQUIRED")

    missing_clean_ready = claude_smoke_fixture.replace("IFS= read -r clean_ready_answer\n", "")
    if "CLAUDE_RELEASE_SMOKE_CLEAN_OBSERVATION_READY" not in validate_claude_release_smoke_contract(missing_clean_ready):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:CLAUDE_CLEAN_READY_NOT_REQUIRED")

    missing_selected_ready = claude_smoke_fixture.replace("IFS= read -r selected_ready_answer\n", "")
    if "CLAUDE_RELEASE_SMOKE_SELECTED_OBSERVATION_READY" not in validate_claude_release_smoke_contract(missing_selected_ready):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:CLAUDE_SELECTED_READY_NOT_REQUIRED")

    clean_launch_line = 'python3 "$root/scripts/release/claude-tty-supervisor.py" --probe-text "$probe_text" -- "$clroom" claude\n'
    late_clean_ready = claude_smoke_fixture.replace("IFS= read -r clean_ready_answer\n", "")
    late_clean_ready = late_clean_ready.replace(clean_launch_line, clean_launch_line + "IFS= read -r clean_ready_answer\n")
    if "CLAUDE_RELEASE_SMOKE_CLEAN_OBSERVATION_READY_ORDER" not in validate_claude_release_smoke_contract(late_clean_ready):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:CLAUDE_CLEAN_READY_ORDER_NOT_REQUIRED")

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
