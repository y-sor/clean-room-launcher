#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    facts_path = Path(args.facts)
    notes_path = Path(args.notes)
    facts_bytes = facts_path.read_bytes()
    notes_bytes = notes_path.read_bytes()
    facts = json.loads(facts_bytes)
    body = notes_bytes.decode("utf-8")
    if not body.strip():
        raise SystemExit("PUBLISH_PREVIEW_BLOCKED:EMPTY_BODY")
    record = {
        "schema_version": "clroom.publish-preview.v1",
        "release_version": facts["release_version"],
        "tag_name": facts["tag_name"],
        "release_title": facts["release_title"],
        "draft": facts["draft"],
        "prerelease": facts["prerelease"],
        "body": body,
        "body_sha256": sha256_bytes(notes_bytes),
        "facts_sha256": sha256_bytes(facts_bytes),
        "expected_assets": facts["expected_assets"],
        "install_url": facts["install_url"],
        "public_claims": {
            "codex_version": facts["providers"]["codex"]["version"],
            "claude_version": facts["providers"]["claude"]["version"],
            "platform_target": facts["platform"]["target"],
            "apple_platform_signing": facts["apple_platform_signing"],
        },
    }
    Path(args.output).write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"PUBLISH_PREVIEW_PASS tag={record['tag_name']} "
        f"body_sha256={record['body_sha256']}"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
