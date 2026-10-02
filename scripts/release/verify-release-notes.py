#!/usr/bin/env python3
import argparse
import hashlib
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "clroom.release-facts.v1"
CANONICAL_INSTALL_URL = (
    "https://github.com/y-sor/clean-room-launcher/releases/latest/download/install.sh"
)

def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()

def candidate_body(changelog: Path, version: str) -> str:
    lines = changelog.read_text(encoding="utf-8").splitlines()
    prefix = f"## [{version}] - "
    starts = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    if len(starts) != 1:
        raise ValueError(f"expected exactly one changelog section for {version}")
    start = starts[0] + 1
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("## ["):
            end = i
            break
    body = "\n".join(lines[start:end]).strip()
    if not body:
        raise ValueError("candidate changelog body is empty")
    return body

def verify(
    *,
    notes: Path,
    changelog: Path,
    version: str,
    artifact: str,
    source_head: str,
    source_tree: str,
    reviewed_content_digest: str,
    codex_version: str,
    claude_version: str,
) -> dict:
    body = candidate_body(changelog, version)
    text = notes.read_text(encoding="utf-8")
    prefix = body + "\n\n## Install\n"
    if not text.startswith(prefix):
        raise ValueError("release notes body is not the exact candidate changelog section")
    required = (
        CANONICAL_INSTALL_URL,
        "## Download and verification",
        f"- `{artifact}`",
        f"`{artifact}.provenance.sigstore.json`",
        f"`{artifact}.sbom.sigstore.json`",
        "The distributed archive is currently unsigned at the Apple platform-signing layer.",
    )
    missing = [item for item in required if item not in text]
    if missing:
        raise ValueError("release notes footer missing: " + repr(missing))
    return {
        "schema_version": SCHEMA,
        "result": "PASS",
        "release_version": version,
        "source_head": source_head,
        "source_tree": source_tree,
        "reviewed_content_digest": reviewed_content_digest,
        "artifact_name": artifact,
        "providers": {
            "codex": {"version": codex_version},
            "claude": {"version": claude_version},
        },
        "qualified_platform": "macOS Apple Silicon",
        "apple_platform_signing": "unsigned",
        "apple_notarization": "notarized-no",
        "candidate_changelog_body_sha256": sha256_bytes(body.encode("utf-8")),
        "release_notes_sha256": sha256_bytes(text.encode("utf-8")),
        "canonical_install_url": CANONICAL_INSTALL_URL,
    }

def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        changelog = root / "CHANGELOG.md"
        notes = root / "release-notes.md"
        changelog.write_text(
            "# Changelog\n\n"
            "## [9.9.9] - 2026-10-02\n\n"
            "### Changed\n\n"
            "- Exact fixture.\n\n"
            "## [9.9.8] - 2026-10-01\n\n"
            "- Historical.\n",
            encoding="utf-8",
        )
        artifact = "clean-room-launcher-v9.9.9-aarch64-apple-darwin.tar.gz"
        body = candidate_body(changelog, "9.9.9")
        notes.write_text(
            body
            + "\n\n## Install\n\n"
            + f"curl --proto '=https' --tlsv1.2 -fsSL {CANONICAL_INSTALL_URL} | sh\n\n"
            + "## Download and verification\n\n"
            + f"- `{artifact}`\n"
            + f"- `{artifact}.provenance.sigstore.json`\n"
            + f"- `{artifact}.sbom.sigstore.json`\n\n"
            + "The distributed archive is currently unsigned at the Apple platform-signing layer.\n",
            encoding="utf-8",
        )
        record = verify(
            notes=notes,
            changelog=changelog,
            version="9.9.9",
            artifact=artifact,
            source_head="a" * 40,
            source_tree="b" * 40,
            reviewed_content_digest="c" * 64,
            codex_version="1.2.3",
            claude_version="4.5.6",
        )
        if record["result"] != "PASS":
            raise SystemExit("RELEASE_NOTES_SELF_TEST_FAIL:POSITIVE")
        bad = notes.read_text(encoding="utf-8").replace("Exact fixture.", "Drifted fixture.")
        notes.write_text(bad, encoding="utf-8")
        try:
            verify(
                notes=notes,
                changelog=changelog,
                version="9.9.9",
                artifact=artifact,
                source_head="a" * 40,
                source_tree="b" * 40,
                reviewed_content_digest="c" * 64,
                codex_version="1.2.3",
                claude_version="4.5.6",
            )
        except ValueError:
            pass
        else:
            raise SystemExit("RELEASE_NOTES_SELF_TEST_FAIL:BODY_DRIFT")
    print("RELEASE_NOTES_SELF_TEST_PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--notes")
    parser.add_argument("--changelog", default=str(ROOT / "CHANGELOG.md"))
    parser.add_argument("--version")
    parser.add_argument("--artifact")
    parser.add_argument("--source-head")
    parser.add_argument("--source-tree")
    parser.add_argument("--reviewed-content-digest")
    parser.add_argument("--codex-version")
    parser.add_argument("--claude-version")
    parser.add_argument("--output-facts")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (
        "notes", "version", "artifact", "source_head", "source_tree",
        "reviewed_content_digest", "codex_version", "claude_version",
        "output_facts",
    )
    missing = [name for name in required if not getattr(args, name)]
    if missing:
        parser.error("missing required arguments: " + ",".join(missing))
    record = verify(
        notes=Path(args.notes),
        changelog=Path(args.changelog),
        version=args.version,
        artifact=args.artifact,
        source_head=args.source_head,
        source_tree=args.source_tree,
        reviewed_content_digest=args.reviewed_content_digest,
        codex_version=args.codex_version,
        claude_version=args.claude_version,
    )
    Path(args.output_facts).write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "RELEASE_NOTES_SEMANTIC_PASS "
        f"version={args.version} sha256={record['release_notes_sha256']}"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
