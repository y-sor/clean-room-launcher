#!/usr/bin/env python3
"""Verify sanitized real-provider evidence against one exact archive."""
import hashlib, json, os, re, sys, tarfile, tempfile

FIELDS = {"schema_version", "qualification", "scope", "real_provider_executed", "repeat_provider_executed", "lifecycle_runs", "fake_provider", "provider", "provider_version", "provider_digest", "clroom_source_head", "release_version", "target", "candidate_digest", "launch_path", "synthetic_ambient_config_present", "synthetic_ambient_config_applied", "exit_class"}
def fail(message):
    raise SystemExit("QUALIFICATION_INVALID:" + message)
if len(sys.argv) != 7: fail("usage")
archive, evidence, source, version, provider, expected_provider_version = sys.argv[1:]
if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", expected_provider_version): fail("expected-provider-version")
try:
    record = json.load(open(evidence, encoding="utf-8"))
except (OSError, ValueError): fail("malformed")
if set(record) != FIELDS: fail("fields")
if record["schema_version"] != "clroom.real-provider-qualification.v2" or record["qualification"] != "PASS": fail("status")
expected_scope = "real-provider-repeat-interactive-mcp-discovery-no-model" if provider == "codex" else "real-provider-startup-no-model"
if record["scope"] != expected_scope or not record["real_provider_executed"] or record["fake_provider"] or record["synthetic_ambient_config_applied"] is not False: fail("provider-evidence")
if provider == "codex":
    if record["lifecycle_runs"] != 2 or record["repeat_provider_executed"] is not True: fail("repeat-provider-lifecycle")
    if record["launch_path"] != "clroom codex --with=plugin:standalone-mcp@clroom-fixture --no-alt-screen (PTY) x2 same HOME": fail("interactive-path")
    if record["exit_class"] != "interactive-provider-repeat-mcp-qualified": fail("provider-observation")
else:
    if record["lifecycle_runs"] != 1 or record["repeat_provider_executed"] is not False: fail("provider-lifecycle")
if record["provider"] != provider or record["provider_version"] != expected_provider_version: fail("provider-version")
if record["clroom_source_head"] != source or record["release_version"] != version: fail("source-version")
if not record["synthetic_ambient_config_present"] or record["synthetic_ambient_config_applied"]: fail("ambient-config")
if not re.fullmatch(r"[0-9a-f]{64}", record["candidate_digest"]): fail("candidate-digest")
with tarfile.open(archive, "r:gz") as tar:
    suffix = "/bin/clroom-" + provider
    root = next(name for name in tar.getnames() if name.endswith(suffix))
    candidate = tar.extractfile(root).read()
if hashlib.sha256(candidate).hexdigest() != record["candidate_digest"]: fail("artifact-binding")
print("QUALIFICATION_VALID provider=" + provider + " scope=" + record["scope"])
