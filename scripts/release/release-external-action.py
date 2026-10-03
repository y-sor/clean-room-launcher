#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time


def blocked(code: str, rc: int = 1) -> None:
    print(f"RELEASE_EXTERNAL_ACTION_BLOCKED:{code}", file=sys.stderr)
    raise SystemExit(rc)


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: pathlib.Path) -> dict:
    if not path.is_file():
        blocked(f"FILE_MISSING:{path}")
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        blocked(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def normalize_body(value: str | None) -> str:
    return (value or "").rstrip()


def asset_names(record: dict) -> set[str]:
    return {str(item.get("name")) for item in record.get("assets") or []}


def release_fingerprint(record: dict) -> str:
    value = {
        "id": record.get("id"),
        "tag_name": record.get("tag_name"),
        "name": record.get("name"),
        "draft": record.get("draft"),
        "prerelease": record.get("prerelease"),
        "body": record.get("body"),
        "updated_at": record.get("updated_at"),
        "assets": sorted(
            (
                item.get("id"),
                item.get("name"),
                item.get("size"),
                item.get("digest"),
                item.get("updated_at"),
            )
            for item in record.get("assets") or []
        ),
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def validate_release(
    release: dict,
    preview: dict,
    *,
    expect_draft: bool,
    check_assets: bool = True,
) -> list[str]:
    errors: list[str] = []
    if release.get("tag_name") != preview.get("tag_name"):
        errors.append("TAG")
    if release.get("name") != preview.get("release_title"):
        errors.append("TITLE")
    if release.get("draft") is not expect_draft:
        errors.append("DRAFT_STATE")
    if release.get("prerelease") is not preview.get("prerelease"):
        errors.append("PRERELEASE_STATE")
    if normalize_body(release.get("body")) != normalize_body(preview.get("body")):
        errors.append("BODY")
    expected_assets = set(preview.get("expected_assets") or [])
    if check_assets and expected_assets and asset_names(release) != expected_assets:
        errors.append("ASSET_SET")
    return errors


def classify_publish_state(
    after: dict, before: dict, preview: dict, *, require_immutable: bool = True
) -> str:
    if after.get("draft") is True:
        if release_fingerprint(after) == release_fingerprint(before):
            return "DRAFT_UNCHANGED"
        return "DRAFT_DRIFT"
    if validate_release(after, preview, expect_draft=False):
        return "PUBLISHED_MISMATCH"
    if not after.get("published_at"):
        return "PUBLISHED_PENDING_VISIBILITY"
    if require_immutable and after.get("immutable") is not True:
        return "PUBLISHED_PENDING_IMMUTABILITY"
    before_assets = {
        (item.get("name"), item.get("id"), item.get("size"), item.get("digest"))
        for item in before.get("assets") or []
    }
    after_assets = {
        (item.get("name"), item.get("id"), item.get("size"), item.get("digest"))
        for item in after.get("assets") or []
    }
    if after_assets != before_assets:
        return "PUBLISHED_ASSET_DRIFT"
    return "PUBLISHED_EXACT"


def parse_ls_remote(text: str, tag: str) -> tuple[str, str]:
    direct = ""
    peeled = ""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        if ref == f"refs/tags/{tag}":
            direct = sha
        elif ref == f"refs/tags/{tag}^{{}}":
            peeled = sha
    return direct, peeled


def self_test() -> int:
    preview = {
        "tag_name": "canary/test",
        "release_title": "Canary test",
        "draft": True,
        "prerelease": False,
        "body": "body\n",
        "expected_assets": ["payload.txt"],
    }
    before = {
        "id": 1,
        "tag_name": "canary/test",
        "name": "Canary test",
        "draft": True,
        "prerelease": False,
        "body": "body",
        "updated_at": "a",
        "published_at": None,
        "immutable": False,
        "assets": [
            {
                "id": 2,
                "name": "payload.txt",
                "size": 3,
                "digest": "sha256:x",
                "updated_at": "a",
            }
        ],
    }
    if validate_release(before, preview, expect_draft=True):
        raise SystemExit("SELF_TEST:DRAFT_VALIDATION")
    if classify_publish_state(dict(before), before, preview) != "DRAFT_UNCHANGED":
        raise SystemExit("SELF_TEST:DRAFT_UNCHANGED")
    drift = dict(before)
    drift["updated_at"] = "b"
    if classify_publish_state(drift, before, preview) != "DRAFT_DRIFT":
        raise SystemExit("SELF_TEST:DRAFT_DRIFT")
    published = dict(before)
    published.update({"draft": False, "published_at": "now", "immutable": True})
    if classify_publish_state(published, before, preview) != "PUBLISHED_EXACT":
        raise SystemExit("SELF_TEST:PUBLISHED_EXACT")
    pending = dict(published)
    pending["immutable"] = False
    if classify_publish_state(pending, before, preview) != "PUBLISHED_PENDING_IMMUTABILITY":
        raise SystemExit("SELF_TEST:PUBLISHED_PENDING")
    if classify_publish_state(
        pending, before, preview, require_immutable=False
    ) != "PUBLISHED_EXACT":
        raise SystemExit("SELF_TEST:NONIMMUTABLE_LAB")
    direct, peeled = parse_ls_remote(
        "a" * 40
        + "\trefs/tags/canary/test\n"
        + "b" * 40
        + "\trefs/tags/canary/test^{}\n",
        "canary/test",
    )
    if direct != "a" * 40 or peeled != "b" * 40:
        raise SystemExit("SELF_TEST:LS_REMOTE")
    print("RELEASE_EXTERNAL_ACTION_SELF_TEST_PASS")
    return 0


def gh_release_view(repository: str, tag: str) -> tuple[int, dict | None]:
    proc = run(
        [
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            repository,
            "--json",
            "databaseId,tagName,name,isDraft,isPrerelease,isImmutable,publishedAt,body,assets",
        ]
    )
    if proc.returncode != 0:
        return proc.returncode, None
    try:
        cli = json.loads(proc.stdout)
    except json.JSONDecodeError:
        blocked("RELEASE_VIEW_JSON")
    release_id = cli.get("databaseId")
    if not isinstance(release_id, int):
        blocked("RELEASE_DATABASE_ID")
    api = run(["gh", "api", f"repos/{repository}/releases/{release_id}"])
    if api.returncode != 0:
        blocked("RELEASE_BY_ID_QUERY")
    try:
        return 0, json.loads(api.stdout)
    except json.JSONDecodeError:
        blocked("RELEASE_BY_ID_JSON")


def cmd_tag_push(args: argparse.Namespace) -> int:
    push = run(["git", "push", args.remote, f"refs/tags/{args.tag}"])
    push_rc = push.returncode
    if args.simulate_local_error_after_action and push_rc == 0:
        push_rc = 97
    reconcile = run(
        [
            "git",
            "ls-remote",
            "--tags",
            args.remote,
            f"refs/tags/{args.tag}",
            f"refs/tags/{args.tag}^{{}}",
        ]
    )
    if reconcile.returncode != 0:
        print(
            f"TAG_PUSH_OUTCOME_UNKNOWN:REMOTE_RECONCILIATION_FAILED tag={args.tag} push_rc={push_rc}",
            file=sys.stderr,
        )
        return 82
    direct, peeled = parse_ls_remote(reconcile.stdout, args.tag)
    if peeled == args.expected:
        print(f"TAG_PUSH_PASS tag={args.tag} target={args.expected}")
        if push_rc != 0:
            print(f"TAG_PUSH_LOCAL_ERROR_RECONCILED=YES rc={push_rc}")
        return 0
    if direct or peeled:
        print(
            f"TAG_PUSH_BLOCKED:REMOTE_TARGET_MISMATCH tag={args.tag} direct={direct or 'none'} peeled={peeled or 'none'} expected={args.expected}",
            file=sys.stderr,
        )
        return 83
    if push_rc != 0:
        print(f"TAG_PUSH_OUTCOME_RECONCILED_ABSENT tag={args.tag}", file=sys.stderr)
        return 78
    print(
        f"TAG_PUSH_OUTCOME_UNKNOWN:REMOTE_TARGET_NOT_RECONCILED tag={args.tag}",
        file=sys.stderr,
    )
    return 73


def reconcile_draft(
    repository: str,
    tag: str,
    preview: dict,
    *,
    check_assets: bool,
) -> dict:
    rc, release = gh_release_view(repository, tag)
    if rc != 0 or release is None:
        blocked("DRAFT_RECONCILIATION_QUERY", 82)
    errors = validate_release(
        release, preview, expect_draft=True, check_assets=check_assets
    )
    if errors:
        blocked("DRAFT_RECONCILIATION:" + ",".join(errors), 83)
    return release


def cmd_draft_promote(args: argparse.Namespace) -> int:
    notes = pathlib.Path(args.notes_file)
    preview_path = pathlib.Path(args.preview_json)
    preview = load_json(preview_path)
    if not notes.is_file():
        blocked(f"NOTES_FILE:{notes}")
    if preview.get("tag_name") != args.tag or preview.get("release_title") != args.title:
        blocked("PREVIEW_IDENTITY")
    if preview.get("prerelease") is not args.prerelease:
        blocked("PREVIEW_PRERELEASE")
    if preview.get("draft") is not True:
        blocked("PREVIEW_DRAFT_STATE")

    assets = [pathlib.Path(item) for item in args.asset]
    if not assets:
        blocked("ASSETS_REQUIRED")
    for path in assets:
        if not path.is_file():
            blocked(f"ASSET:{path}")
    names = [path.name for path in assets]
    if len(names) != len(set(names)):
        blocked("ASSET_BASENAME_COLLISION")
    if set(names) != set(preview.get("expected_assets") or []):
        blocked("PREVIEW_ASSET_SET")
    expected_digests = {path.name: sha256_file(path) for path in assets}

    view_rc, existing = gh_release_view(args.repository, args.tag)
    if view_rc == 0:
        if existing is None:
            blocked("EXISTING_RELEASE_QUERY")
        existing_errors = validate_release(
            existing, preview, expect_draft=True, check_assets=False
        )
        if existing_errors:
            blocked("EXISTING_RELEASE_NOT_DRAFT:" + ",".join(existing_errors), 83)
        mutation = run(
            [
                "gh",
                "release",
                "edit",
                args.tag,
                "--repo",
                args.repository,
                "--title",
                args.title,
                "--notes-file",
                str(notes),
            ]
        )
    else:
        command = [
            "gh",
            "release",
            "create",
            args.tag,
            "--repo",
            args.repository,
            "--draft",
            "--verify-tag",
            "--title",
            args.title,
            "--notes-file",
            str(notes),
        ]
        if args.prerelease:
            command.append("--prerelease")
        mutation = run(command)

    mutation_rc = mutation.returncode
    if args.simulate_local_error_after_action and mutation_rc == 0:
        mutation_rc = 97

    try:
        release = reconcile_draft(
            args.repository, args.tag, preview, check_assets=False
        )
    except SystemExit:
        if mutation_rc != 0:
            print(
                f"DRAFT_PROMOTION_OUTCOME_UNKNOWN:CREATE_OR_EDIT tag={args.tag} mutation_rc={mutation_rc}",
                file=sys.stderr,
            )
            return 82
        raise

    upload = run(
        [
            "gh",
            "release",
            "upload",
            args.tag,
            "--repo",
            args.repository,
            *[str(path) for path in assets],
            "--clobber",
        ]
    )
    upload_rc = upload.returncode
    if args.simulate_local_error_after_action and upload_rc == 0:
        upload_rc = 98
    try:
        release = reconcile_draft(
            args.repository, args.tag, preview, check_assets=True
        )
    except SystemExit:
        if upload_rc != 0:
            print(
                f"DRAFT_PROMOTION_OUTCOME_UNKNOWN:UPLOAD tag={args.tag} mutation_rc={upload_rc}",
                file=sys.stderr,
            )
            return 82
        raise

    cleanup_download = args.download_dir is None
    download_dir = (
        pathlib.Path(args.download_dir)
        if args.download_dir
        else pathlib.Path(tempfile.mkdtemp(prefix="clroom-draft-promote."))
    )
    try:
        if download_dir.exists():
            shutil.rmtree(download_dir)
        download_dir.mkdir(parents=True)
        download = run(
            [
                "gh",
                "release",
                "download",
                args.tag,
                "--repo",
                args.repository,
                "--dir",
                str(download_dir),
            ]
        )
        if download.returncode != 0:
            blocked("DRAFT_DOWNLOAD")
        actual_names = {path.name for path in download_dir.iterdir() if path.is_file()}
        if actual_names != set(names):
            blocked("DRAFT_DOWNLOAD_ASSET_SET")
        for name, expected_digest in expected_digests.items():
            if sha256_file(download_dir / name) != expected_digest:
                blocked(f"DRAFT_DOWNLOAD_BYTE_DRIFT:{name}")
    finally:
        if cleanup_download:
            shutil.rmtree(download_dir, ignore_errors=True)

    if mutation_rc != 0:
        print(
            f"DRAFT_CREATE_OR_EDIT_LOCAL_ERROR_RECONCILED=YES rc={mutation_rc}"
        )
    if upload_rc != 0:
        print(f"DRAFT_UPLOAD_LOCAL_ERROR_RECONCILED=YES rc={upload_rc}")
    print(
        f"DRAFT_PROMOTION_RECONCILE_PASS tag={args.tag} release_id={release.get('id')}"
    )
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    preview = load_json(pathlib.Path(args.preview_json))
    notes = pathlib.Path(args.notes_file)
    if not notes.is_file():
        blocked(f"NOTES_FILE:{notes}")
    if preview.get("tag_name") != args.tag or preview.get("release_title") != args.title:
        blocked("PREVIEW_IDENTITY")
    if preview.get("draft") is not True:
        blocked("PREVIEW_DRAFT_STATE")

    rc, before = gh_release_view(args.repository, args.tag)
    if rc != 0 or before is None:
        blocked("DRAFT_QUERY")
    errors = validate_release(before, preview, expect_draft=True)
    if errors:
        blocked("DRAFT_VALIDATE:" + ",".join(errors))
    fingerprint_before = release_fingerprint(before)

    rc, action = gh_release_view(args.repository, args.tag)
    if rc != 0 or action is None:
        blocked("DRAFT_ACTION_QUERY")
    fingerprint_action = release_fingerprint(action)
    if fingerprint_action != fingerprint_before:
        blocked("DRAFT_CHANGED_BETWEEN_VERIFY_AND_ACTION")
    print(f"DRAFT_FINGERPRINT_ACTION_TIME=PASS sha256={fingerprint_action}")

    if not args.apply:
        print(
            f"PUBLISH_ACTION_REHEARSAL_PASS tag={args.tag} release_id={action.get('id')}"
        )
        return 0

    mutation = run(
        [
            "gh",
            "release",
            "edit",
            args.tag,
            "--repo",
            args.repository,
            "--draft=false",
            "--latest",
            "--verify-tag",
            "--title",
            args.title,
            "--notes-file",
            str(notes),
        ]
    )
    mutation_rc = mutation.returncode
    if args.simulate_local_error_after_action and mutation_rc == 0:
        mutation_rc = 99

    state = ""
    release_query_seen = False
    for attempt in range(5):
        rc, after = gh_release_view(args.repository, args.tag)
        if rc == 0 and after is not None:
            release_query_seen = True
            state = classify_publish_state(
                after,
                action,
                preview,
                require_immutable=not args.allow_nonimmutable,
            )
            if state == "PUBLISHED_EXACT":
                break
            if state not in {
                "DRAFT_UNCHANGED",
                "PUBLISHED_PENDING_IMMUTABILITY",
                "PUBLISHED_PENDING_VISIBILITY",
            }:
                print(
                    f"GUARDED_PUBLISH_OUTCOME_UNKNOWN:STATE_RECONCILIATION tag={args.tag} mutation_rc={mutation_rc} state={state}",
                    file=sys.stderr,
                )
                return 83
        if attempt < 4:
            time.sleep(1)

    if not release_query_seen:
        print(
            f"GUARDED_PUBLISH_OUTCOME_UNKNOWN:RELEASE_QUERY_AFTER_ACTION tag={args.tag} mutation_rc={mutation_rc}",
            file=sys.stderr,
        )
        return 82
    if state == "DRAFT_UNCHANGED":
        print(
            f"GUARDED_PUBLISH_NOT_APPLIED tag={args.tag} mutation_rc={mutation_rc}",
            file=sys.stderr,
        )
        return 78
    if state != "PUBLISHED_EXACT":
        print(
            f"GUARDED_PUBLISH_OUTCOME_UNKNOWN:STATE_RECONCILIATION tag={args.tag} mutation_rc={mutation_rc} state={state or 'none'}",
            file=sys.stderr,
        )
        return 83

    latest_ok = False
    for attempt in range(5):
        latest = run(["gh", "api", f"repos/{args.repository}/releases/latest"])
        if latest.returncode == 0:
            try:
                value = json.loads(latest.stdout)
            except json.JSONDecodeError:
                value = {}
            if (
                value.get("tag_name") == args.tag
                and value.get("draft") is False
                and value.get("prerelease") is False
                and (
                    args.allow_nonimmutable
                    or value.get("immutable") is True
                )
                and value.get("published_at")
            ):
                latest_ok = True
                break
        if attempt < 4:
            time.sleep(1)
    if not latest_ok:
        blocked("LATEST_RECONCILIATION", 83)

    if mutation_rc != 0:
        print(f"PUBLISH_MUTATION_LOCAL_ERROR_RECONCILED=YES rc={mutation_rc}")
    print(f"GUARDED_PUBLISH_PASS tag={args.tag}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")

    tag = sub.add_parser("tag-push")
    tag.add_argument("--remote", default="origin")
    tag.add_argument("--tag", required=True)
    tag.add_argument("--expected", required=True)
    tag.add_argument("--simulate-local-error-after-action", action="store_true")

    draft = sub.add_parser("draft-promote")
    draft.add_argument("--repository", required=True)
    draft.add_argument("--tag", required=True)
    draft.add_argument("--title", required=True)
    draft.add_argument("--notes-file", required=True)
    draft.add_argument("--preview-json", required=True)
    draft.add_argument("--prerelease", action="store_true")
    draft.add_argument("--asset", action="append", required=True)
    draft.add_argument("--download-dir")
    draft.add_argument("--simulate-local-error-after-action", action="store_true")

    publish = sub.add_parser("publish")
    publish.add_argument("--repository", required=True)
    publish.add_argument("--tag", required=True)
    publish.add_argument("--title", required=True)
    publish.add_argument("--notes-file", required=True)
    publish.add_argument("--preview-json", required=True)
    publish.add_argument("--apply", action="store_true")
    publish.add_argument("--allow-nonimmutable", action="store_true")
    publish.add_argument("--simulate-local-error-after-action", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "self-test":
        return self_test()
    if shutil.which("gh") is None:
        blocked("COMMAND_MISSING:gh", 74)
    if args.command == "tag-push":
        if shutil.which("git") is None:
            blocked("COMMAND_MISSING:git", 74)
        return cmd_tag_push(args)
    if args.command == "draft-promote":
        return cmd_draft_promote(args)
    if args.command == "publish":
        return cmd_publish(args)
    blocked("COMMAND")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
