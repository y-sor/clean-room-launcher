#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

RUN_NAME = "Release candidate readiness"
WORKFLOW_PATH = ".github/workflows/release-candidate.yml"
REQUIRED_CURRENT_JOBS = {
    "Release eligibility and harness seal",
    "CLROOM release readiness",
    "Rehearse/stage exact release bytes",
    "Rehearse attestation mechanism before tag",
}


def fail(code: str) -> None:
    raise ValueError(code)


def classify_run(
    run: dict[str, object],
    expected_sha: str,
    repository: str,
    current_run_id: str,
) -> str:
    required = {
        "name": RUN_NAME,
        "event": "push",
        "path": WORKFLOW_PATH,
        "head_branch": "main",
        "head_sha": expected_sha,
    }
    for key, value in required.items():
        if run.get(key) != value:
            fail("RUN_IDENTITY")

    if run.get("status") == "completed" and run.get("conclusion") == "success":
        return "completed"

    if not current_run_id:
        fail("RUN_NOT_COMPLETED")
    if str(run.get("id")) != current_run_id:
        fail("CURRENT_RUN_ID")
    if run.get("status") != "in_progress" or run.get("conclusion") is not None:
        fail("CURRENT_RUN_STATE")

    observed_repository = (run.get("repository") or {}).get("full_name") if isinstance(run.get("repository"), dict) else None
    if observed_repository is not None and observed_repository != repository:
        fail("CURRENT_RUN_REPOSITORY")
    return "current"


def validate_current_jobs(data: dict[str, object]) -> None:
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        fail("CURRENT_RUN_JOBS")
    for name in REQUIRED_CURRENT_JOBS:
        matches = [job for job in jobs if isinstance(job, dict) and job.get("name") == name]
        if len(matches) != 1:
            fail("CURRENT_RUN_JOB_SET")
        job = matches[0]
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            fail("CURRENT_RUN_JOB_STATUS")


def self_test() -> None:
    sha = "a" * 40
    repository = "y-sor/clean-room-launcher"
    base = {
        "id": 123,
        "name": RUN_NAME,
        "event": "push",
        "path": WORKFLOW_PATH,
        "head_branch": "main",
        "head_sha": sha,
        "repository": {"full_name": repository},
    }

    completed = {**base, "status": "completed", "conclusion": "success"}
    if classify_run(completed, sha, repository, "") != "completed":
        raise SystemExit("PRETAG_RUN_ADMISSION_SELF_TEST_FAIL:COMPLETED")

    current = {**base, "status": "in_progress", "conclusion": None}
    if classify_run(current, sha, repository, "123") != "current":
        raise SystemExit("PRETAG_RUN_ADMISSION_SELF_TEST_FAIL:CURRENT")

    for label, mutated, run_id in (
        ("CURRENT_WITHOUT_BINDING", current, ""),
        ("WRONG_EVENT", {**current, "event": "pull_request"}, "123"),
        ("WRONG_SHA", {**current, "head_sha": "b" * 40}, "123"),
        ("FAILED_COMPLETED", {**base, "status": "completed", "conclusion": "failure"}, ""),
    ):
        try:
            classify_run(mutated, sha, repository, run_id)
        except ValueError:
            pass
        else:
            raise SystemExit(f"PRETAG_RUN_ADMISSION_SELF_TEST_FAIL:{label}")

    good_jobs = {
        "jobs": [
            {"name": name, "status": "completed", "conclusion": "success"}
            for name in sorted(REQUIRED_CURRENT_JOBS)
        ]
    }
    validate_current_jobs(good_jobs)

    missing = {"jobs": good_jobs["jobs"][:-1]}
    try:
        validate_current_jobs(missing)
    except ValueError:
        pass
    else:
        raise SystemExit("PRETAG_RUN_ADMISSION_SELF_TEST_FAIL:MISSING_JOB")

    failed = json.loads(json.dumps(good_jobs))
    failed["jobs"][0]["conclusion"] = "failure"
    try:
        validate_current_jobs(failed)
    except ValueError:
        pass
    else:
        raise SystemExit("PRETAG_RUN_ADMISSION_SELF_TEST_FAIL:FAILED_JOB")

    print("PRETAG_RUN_ADMISSION_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-json", type=Path)
    mode.add_argument("--jobs-json", type=Path)
    mode.add_argument("--self-test", action="store_true")
    parser.add_argument("--expected-sha", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--current-run-id", default="")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    try:
        if args.run_json is not None:
            if re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is None:
                fail("EXPECTED_SHA")
            if not args.repository:
                fail("REPOSITORY")
            if args.current_run_id and not args.current_run_id.isdigit():
                fail("CURRENT_RUN_ID")
            run = json.loads(args.run_json.read_text(encoding="utf-8"))
            print(
                classify_run(
                    run,
                    args.expected_sha,
                    args.repository,
                    args.current_run_id,
                )
            )
            return 0

        data = json.loads(args.jobs_json.read_text(encoding="utf-8"))
        validate_current_jobs(data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"PRETAG_RUN_ADMISSION_BLOCKED:{exc}") from exc

    print("PRETAG_RUN_ADMISSION_CURRENT_JOBS_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
