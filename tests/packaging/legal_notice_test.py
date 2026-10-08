#!/usr/bin/env python3
"""Focused CLROOM_PACKAGING contract for exact dependency licenses and artifact NOTICE."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "packaging/generate-notice.py"
POLICY = ROOT / "deny.toml"


def run(command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(
        command,
        cwd=ROOT,
        env=merged,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def main() -> int:
    if not GENERATOR.is_file() or not POLICY.is_file():
        raise SystemExit("CLROOM_PACKAGING_LEGAL_NOTICE_REFUSED:IMPLEMENTATION_MISSING")

    metadata_result = run(["cargo", "metadata", "--locked", "--offline", "--format-version", "1"])
    if metadata_result.returncode:
        raise SystemExit("CLROOM_PACKAGING_LEGAL_NOTICE_REFUSED:CARGO_METADATA")
    metadata = json.loads(metadata_result.stdout)
    root_id = metadata["resolve"]["root"]
    packages = sorted(
        (package for package in metadata["packages"] if package["id"] != root_id),
        key=lambda package: (package["name"], package["version"]),
    )

    with tempfile.TemporaryDirectory(prefix="clroom-packaging-legal-notice-") as temporary:
        notice = Path(temporary) / "NOTICE"
        generated = run([sys.executable, str(GENERATOR), "--output", str(notice)])
        if generated.returncode or generated.stdout != f"CLROOM_DEPENDENCY_NOTICE_PASS components={len(packages)}\n":
            raise SystemExit("CLROOM_PACKAGING_LEGAL_NOTICE_REFUSED:GENERATOR\n" + generated.stdout)
        body = notice.read_text(encoding="utf-8")

    if body.count("\n- ") != len(packages):
        raise SystemExit("CLROOM_PACKAGING_LEGAL_NOTICE_REFUSED:COMPONENT_COUNT")
    for package in packages:
        expected = f"- {package['name']} {package['version']} | {package['license']}\n"
        if body.count(expected) != 1:
            raise SystemExit("CLROOM_PACKAGING_LEGAL_NOTICE_REFUSED:COMPONENT:" + package["name"])
    if f"Component count: {len(packages)}\n" not in body:
        raise SystemExit("CLROOM_PACKAGING_LEGAL_NOTICE_REFUSED:CENSUS_HEADER")
    if not re.search(r"Cargo\.lock SHA-256: [0-9a-f]{64}\n", body):
        raise SystemExit("CLROOM_PACKAGING_LEGAL_NOTICE_REFUSED:LOCK_BINDING")
    if any(marker in body for marker in ("/Users/", "/home/", "Documents/it", "ghp_", "sk-")):
        raise SystemExit("CLROOM_PACKAGING_LEGAL_NOTICE_REFUSED:PRIVATE_DATA")
    for missing_file_package in ("jsonschema-regex@0.58.6", "jsonschema-value@0.58.6", "r-efi@5.3.0", "uuid-simd@0.8.0", "vsimd@0.8.0"):
        if f"Canonical fallback for: {missing_file_package}" not in body:
            raise SystemExit("CLROOM_PACKAGING_LEGAL_NOTICE_REFUSED:FALLBACK:" + missing_file_package)

    cargo_deny = os.environ.get("CLROOM_PACKAGING_CARGO_DENY", "cargo-deny")
    denied = run(
        [cargo_deny, "--config", str(POLICY), "--locked", "--offline", "check", "licenses"],
        env={"CARGO_TERM_COLOR": "never"},
    )
    if denied.returncode:
        raise SystemExit("CLROOM_PACKAGING_LEGAL_NOTICE_REFUSED:CARGO_DENY\n" + denied.stdout)

    build = (ROOT / "packaging/build-artifacts.sh").read_text(encoding="utf-8")
    verifier = (ROOT / "packaging/verify-artifact.py").read_text(encoding="utf-8")
    for needle in ("packaging/generate-notice.py", "deny.toml", "notice_generator_sha256", "license_policy_sha256", "cargo_lock_sha256", "--remap-path-prefix"):
        if needle not in build:
            raise SystemExit("CLROOM_PACKAGING_LEGAL_NOTICE_REFUSED:BUILD_BINDING:" + needle)
    for needle in ("Third-party dependency notices", "Component count:", "Cargo\\.lock SHA-256", "binary contains a private HOME path"):
        if needle not in verifier:
            raise SystemExit("CLROOM_PACKAGING_LEGAL_NOTICE_REFUSED:VERIFIER_BINDING:" + needle)

    print(f"CLROOM_PACKAGING_LEGAL_NOTICE_PASS components={len(packages)} fallbacks=5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
