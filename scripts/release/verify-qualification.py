#!/usr/bin/env python3
"""Verify sanitized real-provider evidence against one exact archive."""
import hashlib, json, os, re, sys, tarfile, tempfile
from pathlib import Path

FIELDS = {"schema_version", "qualification", "scope", "real_provider_executed", "fake_provider", "provider", "provider_version", "provider_digest", "clroom_source_head", "release_version", "target", "candidate_digest", "launch_path", "synthetic_ambient_config_present", "synthetic_ambient_config_applied", "exit_class"}
ROOT = Path(__file__).resolve().parents[2]
PIN_SOURCE = ROOT / "release/qualification.json"
def fail(message):
    raise SystemExit("QUALIFICATION_INVALID:" + message)
if len(sys.argv) != 6: fail("usage")
archive, evidence, source, version, provider = sys.argv[1:]
try:
    record = json.load(open(evidence, encoding="utf-8"))
except (OSError, ValueError): fail("malformed")
if set(record) != FIELDS: fail("fields")
if record["schema_version"] != "clroom.real-provider-qualification.v1" or record["qualification"] != "PASS": fail("status")
expected_scope = "real-provider-interactive-startup-no-model" if provider == "codex" else "real-provider-startup-no-model"
if record["scope"] != expected_scope or not record["real_provider_executed"] or record["fake_provider"] or record["synthetic_ambient_config_applied"] is not False: fail("provider-evidence")
if provider == "codex" and record["launch_path"] != "clroom codex --no-alt-screen (PTY)": fail("interactive-path")
if provider == "codex" and record["exit_class"] != "interactive-provider-observed": fail("provider-observation")
try:
    pins = json.loads(PIN_SOURCE.read_text(encoding="utf-8"))
    expected_provider_version = (
        pins["providers"]["codex"]["clean_exact"]
        if provider == "codex"
        else pins["providers"]["claude"]["clean_exact"]
    )
except (OSError, ValueError, KeyError, TypeError):
    fail("qualification-pins")
if record["provider"] != provider or record["provider_version"] != expected_provider_version:
    fail("provider-version")
if record["clroom_source_head"] != source or record["release_version"] != version: fail("source-version")
if not record["synthetic_ambient_config_present"] or record["synthetic_ambient_config_applied"]: fail("ambient-config")
if not re.fullmatch(r"[0-9a-f]{64}", record["candidate_digest"]): fail("candidate-digest")
with tarfile.open(archive, "r:gz") as tar:
    suffix = "/bin/clroom-" + provider
    root = next(name for name in tar.getnames() if name.endswith(suffix))
    candidate = tar.extractfile(root).read()
if hashlib.sha256(candidate).hexdigest() != record["candidate_digest"]: fail("artifact-binding")
print("QUALIFICATION_VALID provider=" + provider + " scope=" + record["scope"])
