#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile


PRODUCTION_REPOSITORY = "y-sor/clean-room-launcher"
REQUIRED_FIDELITY_ROWS = {
    "repository_plan_features",
    "release_settings",
    "tag_rulesets",
    "immutable_release_policy",
    "auth_permission_scope",
    "runner_os_shell_tool_versions",
    "network_routing",
    "ui",
    "resource_lifecycle",
}


def blocked(code: str, rc: int = 1) -> None:
    print(f"RELEASE_INTEGRATION_REHEARSAL_BLOCKED:{code}", file=sys.stderr)
    raise SystemExit(rc)


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def github_file_sha256(repository: str, path: str, ref: str) -> str:
    proc = run(["gh", "api", f"repos/{repository}/contents/{path}?ref={ref}"])
    if proc.returncode != 0:
        blocked(f"CANDIDATE_FILE_QUERY:{path}", proc.returncode or 1)
    try:
        record = json.loads(proc.stdout)
        content = record.get("content")
        if record.get("encoding") != "base64" or not isinstance(content, str):
            blocked(f"CANDIDATE_FILE_ENCODING:{path}")
        raw = base64.b64decode(content, validate=False)
    except (json.JSONDecodeError, ValueError):
        blocked(f"CANDIDATE_FILE_JSON:{path}")
    return hashlib.sha256(raw).hexdigest()


def identity_binding_errors(
    *,
    repository_id: str,
    expected_repository_id: str,
    resolved_candidate_head: str,
    expected_candidate_head: str,
    helper_sha256: str,
    candidate_helper_sha256: str,
    rehearsal_sha256: str,
    candidate_rehearsal_sha256: str,
) -> list[str]:
    errors: list[str] = []
    if repository_id != expected_repository_id:
        errors.append("REPOSITORY_ID_MISMATCH")
    if resolved_candidate_head != expected_candidate_head:
        errors.append("CANDIDATE_HEAD_MISMATCH")
    if helper_sha256 != candidate_helper_sha256:
        errors.append("ACTION_HELPER_SHA256_MISMATCH")
    if rehearsal_sha256 != candidate_rehearsal_sha256:
        errors.append("REHEARSAL_SHA256_MISMATCH")
    return errors


def load_json(path: pathlib.Path) -> dict:
    if not path.is_file():
        blocked(f"FILE_MISSING:{path}")
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        blocked(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def validate_fidelity_matrix(record: dict) -> dict[str, dict]:
    if record.get("schema_version") != "clroom.integration-fidelity-matrix.v1":
        blocked("FIDELITY_SCHEMA")
    rows = record.get("rows")
    if not isinstance(rows, list):
        blocked("FIDELITY_ROWS")
    by_property: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            blocked("FIDELITY_ROW_OBJECT")
        key = row.get("property")
        if not isinstance(key, str) or not key:
            blocked("FIDELITY_PROPERTY")
        if key in by_property:
            blocked(f"FIDELITY_DUPLICATE:{key}")
        if not isinstance(row.get("matched"), bool):
            blocked(f"FIDELITY_MATCHED:{key}")
        for field in ("lab_value", "target_value"):
            value = row.get(field)
            if not isinstance(value, str) or not value or value == "UNKNOWN":
                blocked(f"FIDELITY_VALUE:{key}:{field}")
        proof = row.get("exact_target_proof")
        if not row["matched"] and (not isinstance(proof, str) or not proof):
            blocked(f"FIDELITY_MISMATCH_PROOF:{key}")
        by_property[key] = row
    missing = sorted(REQUIRED_FIDELITY_ROWS - set(by_property))
    extra = sorted(set(by_property) - REQUIRED_FIDELITY_ROWS)
    if missing:
        blocked("FIDELITY_MISSING:" + ",".join(missing))
    if extra:
        blocked("FIDELITY_UNCLASSIFIED:" + ",".join(extra))
    return by_property


def repository_from_origin(url: str) -> str:
    value = url.strip()
    match = re.search(r"github\.com[:/](?P<repo>[^/]+/[^/]+?)(?:\.git)?$", value)
    if not match:
        return ""
    return match.group("repo")


def self_test() -> int:
    matrix = {
        "schema_version": "clroom.integration-fidelity-matrix.v1",
        "rows": [
            {
                "property": key,
                "matched": key != "tag_rulesets",
                "lab_value": "lab",
                "target_value": "target",
                "exact_target_proof": "" if key != "tag_rulesets" else "TARGET_RULESET_ACTION_TIME",
            }
            for key in sorted(REQUIRED_FIDELITY_ROWS)
        ],
    }
    rows = validate_fidelity_matrix(matrix)
    if rows["tag_rulesets"]["matched"] is not False:
        raise SystemExit("SELF_TEST:FIDELITY")
    if repository_from_origin("git@github.com:owner/repo.git") != "owner/repo":
        raise SystemExit("SELF_TEST:SSH_REMOTE")
    if repository_from_origin("https://github.com/owner/repo.git") != "owner/repo":
        raise SystemExit("SELF_TEST:HTTPS_REMOTE")

    binding = dict(
        repository_id="101",
        expected_repository_id="101",
        resolved_candidate_head="a" * 40,
        expected_candidate_head="a" * 40,
        helper_sha256="b" * 64,
        candidate_helper_sha256="b" * 64,
        rehearsal_sha256="c" * 64,
        candidate_rehearsal_sha256="c" * 64,
    )
    if identity_binding_errors(**binding):
        raise SystemExit("SELF_TEST:IDENTITY_BINDING_CLEAN")
    negative_cases = {
        "REPOSITORY_ID_MISMATCH": {"repository_id": "102"},
        "CANDIDATE_HEAD_MISMATCH": {"resolved_candidate_head": "d" * 40},
        "ACTION_HELPER_SHA256_MISMATCH": {"helper_sha256": "e" * 64},
        "REHEARSAL_SHA256_MISMATCH": {"rehearsal_sha256": "f" * 64},
    }
    for expected_code, overrides in negative_cases.items():
        case = dict(binding)
        case.update(overrides)
        if expected_code not in identity_binding_errors(**case):
            raise SystemExit(f"SELF_TEST:{expected_code}_NOT_REJECTED")

    print("RELEASE_INTEGRATION_REHEARSAL_SELF_TEST_PASS")
    return 0


def checked(cmd: list[str], label: str) -> str:
    proc = run(cmd)
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr.rstrip(), file=sys.stderr)
        blocked(label, proc.returncode or 1)
    return proc.stdout


def main_run(args: argparse.Namespace) -> int:
    repository = args.repository
    if repository == PRODUCTION_REPOSITORY:
        blocked("PRODUCTION_REPOSITORY_FORBIDDEN", 65)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.canary_id):
        blocked("CANARY_ID")
    if not re.fullmatch(r"[0-9]+", args.expected_repository_id):
        blocked("EXPECTED_REPOSITORY_ID")
    if not re.fullmatch(r"[0-9a-f]{40}", args.candidate_head):
        blocked("CANDIDATE_HEAD")
    tag = f"canary/{args.canary_id}"
    owner_token = (
        f"YES:{repository}:{args.expected_repository_id}:"
        f"{args.candidate_head}:{args.canary_id}"
    )
    if args.owner_gate_env not in ("CLROOM_OWNER_LAB_REHEARSAL_APPROVED",):
        blocked("OWNER_GATE_ENV")
    if __import__("os").environ.get(args.owner_gate_env) != owner_token:
        blocked("OWNER_APPROVAL_TOKEN", 65)

    rehearsal_path = pathlib.Path(__file__).resolve()
    root = rehearsal_path.parents[2]
    helper = root / "scripts/release/release-external-action.py"
    if not helper.is_file():
        blocked("ACTION_HELPER_MISSING")
    helper_sha256 = sha256_file(helper)
    rehearsal_sha256 = sha256_file(rehearsal_path)

    for name in ("git", "gh", "python3"):
        if shutil.which(name) is None:
            blocked(f"COMMAND_MISSING:{name}", 74)
    checked(["gh", "auth", "status"], "GH_AUTH_REQUIRED")

    resolved_candidate_head = checked(
        [
            "gh",
            "api",
            f"repos/{PRODUCTION_REPOSITORY}/commits/{args.candidate_head}",
            "--jq",
            ".sha",
        ],
        "CANDIDATE_HEAD_QUERY",
    ).strip()
    candidate_helper_sha256 = github_file_sha256(
        PRODUCTION_REPOSITORY,
        "scripts/release/release-external-action.py",
        args.candidate_head,
    )
    candidate_rehearsal_sha256 = github_file_sha256(
        PRODUCTION_REPOSITORY,
        "scripts/release/rehearse-external-release-lifecycle.py",
        args.candidate_head,
    )

    origin = checked(["git", "remote", "get-url", "origin"], "ORIGIN_QUERY").strip()
    if repository_from_origin(origin) != repository:
        blocked(f"ORIGIN_REPOSITORY_MISMATCH:{repository_from_origin(origin) or 'unparsed'}")
    source_head = checked(["git", "rev-parse", "HEAD"], "HEAD_QUERY").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", source_head):
        blocked("HEAD_INVALID")
    if checked(["git", "status", "--porcelain"], "WORKTREE_QUERY").strip():
        blocked("WORKTREE_NOT_CLEAN")
    if run(["git", "show-ref", "--verify", "--quiet", f"refs/tags/{tag}"]).returncode == 0:
        blocked("LOCAL_TAG_PRESENT")

    remote = checked(
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
        "REMOTE_TAG_QUERY",
    )
    if remote.strip():
        blocked("REMOTE_TAG_PRESENT")

    releases = checked(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{repository}/releases?per_page=100",
            "--jq",
            ".[].tag_name",
        ],
        "RELEASE_COLLECTION_QUERY",
    )
    if tag in releases.splitlines():
        blocked("RELEASE_PRESENT")

    matrix = load_json(pathlib.Path(args.fidelity_matrix))
    fidelity_rows = validate_fidelity_matrix(matrix)
    allow_nonimmutable = not fidelity_rows["immutable_release_policy"]["matched"]

    repo_id = checked(
        ["gh", "api", f"repos/{repository}", "--jq", ".id"],
        "REPOSITORY_ID_QUERY",
    ).strip()
    if not repo_id.isdigit():
        blocked("REPOSITORY_ID")
    binding_errors = identity_binding_errors(
        repository_id=repo_id,
        expected_repository_id=args.expected_repository_id,
        resolved_candidate_head=resolved_candidate_head,
        expected_candidate_head=args.candidate_head,
        helper_sha256=helper_sha256,
        candidate_helper_sha256=candidate_helper_sha256,
        rehearsal_sha256=rehearsal_sha256,
        candidate_rehearsal_sha256=candidate_rehearsal_sha256,
    )
    if binding_errors:
        blocked("IDENTITY_BINDING:" + ",".join(binding_errors), 65)
    print(
        "RELEASE_INTEGRATION_IDENTITY_BINDING_PASS "
        f"candidate={args.candidate_head} helper_sha256={helper_sha256} "
        f"rehearsal_sha256={rehearsal_sha256}"
    )

    title = f"CLROOM release harness canary {args.canary_id}"
    checked(["git", "tag", "-a", tag, source_head, "-m", title], "LOCAL_TAG_CREATE")

    helper_cmd = [sys.executable, str(helper)]
    tag_push = run(
        helper_cmd
        + [
            "tag-push",
            "--remote",
            "origin",
            "--tag",
            tag,
            "--expected",
            source_head,
            "--simulate-local-error-after-action",
        ]
    )
    if tag_push.returncode != 0:
        if tag_push.stdout:
            print(tag_push.stdout.rstrip(), file=sys.stderr)
        if tag_push.stderr:
            print(tag_push.stderr.rstrip(), file=sys.stderr)
        blocked("TAG_PUSH_ACTION", tag_push.returncode)

    with tempfile.TemporaryDirectory(prefix="clroom-release-integration.") as raw:
        tmp = pathlib.Path(raw)
        payload = tmp / "payload.txt"
        metadata = tmp / "metadata.json"
        notes = tmp / "notes.md"
        preview = tmp / "publish-preview.json"
        download_dir = tmp / "draft-download"
        payload.write_text(f"CLROOM release harness canary {args.canary_id}\n", encoding="utf-8")
        metadata.write_text(
            json.dumps(
                {
                    "schema_version": "clroom.release-canary.v1",
                    "repository_id": int(repo_id),
                    "source_head": source_head,
                    "tag": tag,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        body = (
            "Synthetic CLROOM release-system canary. "
            "Not a product release and contains no production release bytes.\n"
        )
        notes.write_text(body, encoding="utf-8")
        preview.write_text(
            json.dumps(
                {
                    "tag_name": tag,
                    "release_title": title,
                    "draft": True,
                    "prerelease": False,
                    "body": body,
                    "expected_assets": [payload.name, metadata.name],
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        promote = run(
            helper_cmd
            + [
                "draft-promote",
                "--repository",
                repository,
                "--tag",
                tag,
                "--title",
                title,
                "--notes-file",
                str(notes),
                "--preview-json",
                str(preview),
                "--asset",
                str(payload),
                "--asset",
                str(metadata),
                "--download-dir",
                str(download_dir),
                "--simulate-local-error-after-action",
            ]
        )
        if promote.returncode != 0:
            if promote.stdout:
                print(promote.stdout.rstrip(), file=sys.stderr)
            if promote.stderr:
                print(promote.stderr.rstrip(), file=sys.stderr)
            blocked("DRAFT_PROMOTE_ACTION", promote.returncode)

        rehearsal = run(
            helper_cmd
            + [
                "publish",
                "--repository",
                repository,
                "--tag",
                tag,
                "--title",
                title,
                "--notes-file",
                str(notes),
                "--preview-json",
                str(preview),
            ]
        )
        if rehearsal.returncode != 0:
            if rehearsal.stdout:
                print(rehearsal.stdout.rstrip(), file=sys.stderr)
            if rehearsal.stderr:
                print(rehearsal.stderr.rstrip(), file=sys.stderr)
            blocked("PUBLISH_READ_REHEARSAL", rehearsal.returncode)

        publish_args = helper_cmd + [
            "publish",
            "--repository",
            repository,
            "--tag",
            tag,
            "--title",
            title,
            "--notes-file",
            str(notes),
            "--preview-json",
            str(preview),
            "--apply",
            "--simulate-local-error-after-action",
        ]
        if allow_nonimmutable:
            publish_args.append("--allow-nonimmutable")
        publish = run(publish_args)
        if publish.returncode != 0:
            if publish.stdout:
                print(publish.stdout.rstrip(), file=sys.stderr)
            if publish.stderr:
                print(publish.stderr.rstrip(), file=sys.stderr)
            blocked("PUBLISH_ACTION", publish.returncode)

    release_json = json.loads(
        checked(
            [
                "gh",
                "release",
                "view",
                tag,
                "--repo",
                repository,
                "--json",
                "databaseId,tagName,isDraft,isPrerelease,isImmutable,publishedAt,url",
            ],
            "PUBLISHED_RELEASE_QUERY",
        )
    )
    latest = json.loads(
        checked(["gh", "api", f"repos/{repository}/releases/latest"], "LATEST_QUERY")
    )
    if release_json.get("tagName") != tag or release_json.get("isDraft"):
        blocked("PUBLISHED_RELEASE_STATE")
    if latest.get("tag_name") != tag:
        blocked("LATEST_IDENTITY")

    evidence = {
        "schema_version": "clroom.release-integration-evidence.v1",
        "result": "PASS",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "repository": repository,
        "repository_id": int(repo_id),
        "source_head": source_head,
        "candidate_head": args.candidate_head,
        "canary_tag": tag,
        "release_id": release_json.get("databaseId"),
        "action_helper_sha256": helper_sha256,
        "rehearsal_sha256": rehearsal_sha256,
        "gh_version": checked(["gh", "--version"], "GH_VERSION").splitlines()[0],
        "tag_push": "PASS_WITH_SIMULATED_LOCAL_ERROR_RECONCILED",
        "draft_promote": "PASS_WITH_SIMULATED_LOCAL_ERROR_RECONCILED",
        "draft_upload": "PASS_WITH_SIMULATED_LOCAL_ERROR_RECONCILED",
        "publish_read_rehearsal": "PASS",
        "publish_transition": "PASS_WITH_SIMULATED_LOCAL_ERROR_RECONCILED",
        "latest_reconciliation": "PASS",
        "published_immutable": release_json.get("isImmutable"),
        "fidelity_matrix": matrix,
        "cleanup": {
            "status": "PRESERVED_PENDING_OWNER_GATE",
            "remote_tag": tag,
            "release_id": release_json.get("databaseId"),
        },
    }
    evidence_path = pathlib.Path(args.evidence)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"RELEASE_INTEGRATION_REHEARSAL_PASS tag={tag} release_id={release_json.get('databaseId')} evidence={evidence_path}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--repository")
    parser.add_argument("--expected-repository-id")
    parser.add_argument("--candidate-head")
    parser.add_argument("--canary-id")
    parser.add_argument("--fidelity-matrix")
    parser.add_argument("--evidence")
    parser.add_argument(
        "--owner-gate-env", default="CLROOM_OWNER_LAB_REHEARSAL_APPROVED"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        return self_test()
    missing = [
        name
        for name in (
            "repository",
            "expected_repository_id",
            "candidate_head",
            "canary_id",
            "fidelity_matrix",
            "evidence",
        )
        if not getattr(args, name)
    ]
    if missing:
        blocked("MISSING_ARGS:" + ",".join(missing), 64)
    return main_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
