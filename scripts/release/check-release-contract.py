#!/usr/bin/env python3
import argparse, datetime, fnmatch, hashlib, json, os, re, subprocess, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "schemas/release/release-contract-v1.json"

def run(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def matches(path, pattern):
    return fnmatch.fnmatchcase(path, pattern) or Path(path).match(pattern)

def latest_published_release(repository):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/releases/latest",
        headers={"Accept":"application/vnd.github+json","User-Agent":"clroom-release-contract-v1"},
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.load(response)
    if data.get("draft") or data.get("prerelease"):
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:PUBLISHED_BASELINE_NOT_STABLE")
    if not data.get("published_at") or not data.get("tag_name"):
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:PUBLISHED_BASELINE_IDENTITY")
    if data.get("immutable") is not True:
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:PUBLISHED_BASELINE_NOT_IMMUTABLE")
    return data["tag_name"], data.get("published_at")

def classify(paths, contract):
    result = {}
    unknown = []
    for path in paths:
        domains = [d["id"] for d in contract["domains"] if any(matches(path, p) for p in d["patterns"])]
        if not domains:
            unknown.append(path)
        result[path] = domains
    return result, unknown

def ensure_ref(ref):
    try:
        run("git","rev-parse","--verify",ref)
    except subprocess.CalledProcessError:
        raise SystemExit(f"RELEASE_CONTRACT_BLOCKED:MISSING_GIT_REF:{ref}")

def migrate_review_v1(review, reviewed_content_digest):
    if review.get("schema_version") != "clroom.release-review.v1":
        raise ValueError("not release-review v1")
    if (
        not isinstance(reviewed_content_digest, str)
        or len(reviewed_content_digest) != 64
        or any(ch not in "0123456789abcdef" for ch in reviewed_content_digest)
    ):
        raise ValueError("migration requires a fresh reviewed content digest")
    migrated = dict(review)
    migrated["schema_version"] = "clroom.release-review.v2"
    migrated.pop("reviewed_through_commit", None)
    migrated["reviewed_content_digest"] = reviewed_content_digest
    return migrated

def review_semantic_sha(review):
    semantic = dict(review)
    semantic.pop("reviewed_content_digest", None)
    canonical = json.dumps(
        semantic,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

def changelog_release_date(lines, version):
    prefix = f"## [{version}]"
    headings = [line for line in lines if line.startswith(prefix)]
    if len(headings) != 1:
        raise ValueError(f"expected exactly one changelog heading for {version}")
    pattern = re.compile(rf"^## \[{re.escape(version)}\] - (\d{{4}}-\d{{2}}-\d{{2}})$")
    match = pattern.fullmatch(headings[0])
    if match is None:
        raise ValueError(f"changelog heading for {version} must use YYYY-MM-DD")
    raw = match.group(1)
    try:
        parsed = datetime.date.fromisoformat(raw)
    except ValueError as error:
        raise ValueError(f"invalid changelog date for {version}: {raw}") from error
    if parsed.isoformat() != raw:
        raise ValueError(f"non-canonical changelog date for {version}: {raw}")
    return parsed

def validate_changelog_tag_date(lines, version, tag_date):
    declared = changelog_release_date(lines, version)
    try:
        action = datetime.date.fromisoformat(tag_date)
    except ValueError as error:
        raise ValueError(f"invalid tag date: {tag_date}") from error
    if action.isoformat() != tag_date:
        raise ValueError(f"non-canonical tag date: {tag_date}")
    if declared > action:
        raise ValueError(
            f"changelog date {declared.isoformat()} is after tag date {action.isoformat()}"
        )
    return declared

def published_release_date(published_at):
    try:
        parsed = datetime.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError(f"invalid published baseline timestamp: {published_at}") from error
    return parsed.date()

def validate_changelog_baseline_date(declared, published_at):
    baseline = published_release_date(published_at)
    if declared < baseline:
        raise ValueError(
            f"changelog date {declared.isoformat()} is before published baseline date {baseline.isoformat()}"
        )
    return baseline

SEMVER_TOKEN = re.compile(
    r"(?<![0-9])(?P<prefix>v?)(?P<version>[0-9]+\.[0-9]+\.[0-9]+)(?P<plus>\+)?(?![0-9])"
)

def public_doc_version_policy(contract):
    policy = contract.get("policy", {}).get("public_doc_version_inventory")
    if not isinstance(policy, dict):
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:PUBLIC_DOC_VERSION_POLICY")
    if policy.get("provider_version_source") != "scripts/release/provider-pins.sh":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:PUBLIC_DOC_PROVIDER_VERSION_SOURCE")
    if policy.get("stale_or_unclassified_version") != "fail":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:PUBLIC_DOC_VERSION_FAIL_POLICY")
    for field in (
        "active_globs",
        "historical_exclusions",
        "historical_product_paths",
    ):
        if not isinstance(policy.get(field), list):
            raise SystemExit(f"RELEASE_CONTRACT_BLOCKED:PUBLIC_DOC_VERSION_POLICY:{field}")
    if not isinstance(policy.get("allowed_noncurrent_provider_versions"), dict):
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:PUBLIC_DOC_PROVIDER_ALLOWLIST")
    if not isinstance(policy.get("allowed_other_versions"), dict):
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:PUBLIC_DOC_OTHER_ALLOWLIST")
    return policy

def provider_versions_from_pins(policy):
    source = ROOT / policy["provider_version_source"]
    text = source.read_text(encoding="utf-8")
    result = {}
    for provider, variable in (("codex", "CODEX_VERSION"), ("claude", "CLAUDE_VERSION")):
        match = re.search(
            rf"^{variable}=([0-9]+\.[0-9]+\.[0-9]+)$",
            text,
            flags=re.MULTILINE,
        )
        if match is None:
            raise SystemExit(f"RELEASE_CONTRACT_BLOCKED:PUBLIC_DOC_PROVIDER_PIN:{provider}")
        result[provider] = match.group(1)
    return result

def public_doc_version_violation(path, line, prefix, version, candidate_version, pins, policy):
    historical_product_paths = policy["historical_product_paths"]
    provider_allow = policy["allowed_noncurrent_provider_versions"]
    other_allow = policy["allowed_other_versions"]

    if prefix == "v":
        if any(matches(path, pattern) for pattern in historical_product_paths):
            return None
        if version == candidate_version or version in other_allow:
            return None
        return f"STALE_PRODUCT_VERSION:expected={candidate_version}:actual={version}"

    lower = line.lower()
    providers = {provider for provider in ("codex", "claude") if provider in lower}
    if not providers:
        if any(matches(path, pattern) for pattern in historical_product_paths):
            return None
        if version == candidate_version or version in other_allow:
            return None
        compatibility_owners = [
            provider
            for provider, configured in provider_allow.items()
            if isinstance(configured, dict) and version in configured
        ]
        if len(compatibility_owners) == 1:
            return None
        return f"UNCLASSIFIED_VERSION:{version}"

    allowed = {candidate_version}
    for provider in providers:
        allowed.add(pins[provider])
        configured = provider_allow.get(provider, {})
        if not isinstance(configured, dict):
            return f"INVALID_PROVIDER_ALLOWLIST:{provider}"
        allowed.update(configured.keys())
    if version not in allowed:
        expected = ",".join(sorted(allowed))
        return f"STALE_PROVIDER_VERSION:actual={version}:allowed={expected}"
    return None

def validate_public_doc_versions(contract, candidate_version):
    policy = public_doc_version_policy(contract)
    pins = provider_versions_from_pins(policy)
    tracked = run("git", "ls-files").splitlines()
    paths = sorted(
        path
        for path in tracked
        if any(matches(path, pattern) for pattern in policy["active_globs"])
        and not any(matches(path, pattern) for pattern in policy["historical_exclusions"])
    )
    inventory = []
    violations = []
    for path in paths:
        text = (ROOT / path).read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in SEMVER_TOKEN.finditer(line):
                raw = match.group(0)
                prefix = match.group("prefix")
                version = match.group("version")
                violation = public_doc_version_violation(
                    path, line, prefix, version, candidate_version, pins, policy
                )
                inventory.append((path, line_number, raw, "PASS" if violation is None else violation))
                if violation is not None:
                    violations.append((path, line_number, raw, violation))
    if violations:
        for path, line_number, raw, violation in violations:
            print(
                f"PUBLIC_DOC_VERSION_DRIFT:{path}:{line_number}:{raw}:{violation}",
                file=sys.stderr,
            )
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:PUBLIC_DOC_VERSION_DRIFT")
    return inventory

def reviewed_content_digest(ref, review_path):
    raw = subprocess.check_output(["git", "ls-tree", "-r", "-z", ref], cwd=ROOT)
    records = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, path = record.split(b"\t", 1)
        decoded = path.decode("utf-8")
        if decoded == review_path:
            review_bytes = subprocess.check_output(
                ["git", "show", f"{ref}:{review_path}"],
                cwd=ROOT,
            )
            review = json.loads(review_bytes)
            semantic_sha = review_semantic_sha(review).encode("ascii")
            mode, object_type, _object_sha = meta.split(b" ", 2)
            meta = b" ".join((mode, object_type, semantic_sha))
        records.append((decoded, meta, path))
    digest = hashlib.sha256()
    for _, meta, path in sorted(records, key=lambda item: item[0]):
        digest.update(meta + b"\t" + path + b"\0")
    return digest.hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--review", default=None)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY","y-sor/clean-room-launcher"))
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--tag-date", default=None)
    args=parser.parse_args()

    contract=load_json(CONTRACT)
    if contract.get("schema_version")!="clroom.release-contract.v1":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:CONTRACT_SCHEMA")
    if contract.get("policy", {}).get("changelog_action_time_relation") != "declared_on_or_before_tag":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:CHANGELOG_ACTION_TIME_POLICY")
    if contract.get("policy", {}).get("candidate_version_relation") != "strictly_after_published_baseline":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:CANDIDATE_VERSION_POLICY")
    if contract.get("policy", {}).get("changelog_date_floor") != "published_baseline_date":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:CHANGELOG_DATE_FLOOR_POLICY")
    if contract.get("policy", {}).get("tag_remote_refresh_order") != "after_provider_checks_before_push":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:TAG_REMOTE_REFRESH_POLICY")
    public_doc_version_policy(contract)

    if args.self_test:
        sample=["src/cli/mod.rs","Cargo.lock",".github/workflows/ci.yml","scripts/release/readiness.sh","scripts/probe/check-sitemap.py","README.md","tests/cli/info.rs"]
        classified, unknown=classify(sample,contract)
        if unknown or any(not classified[p] for p in sample):
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL")
        if classify(["totally-new-root.bin"],contract)[1] != ["totally-new-root.bin"]:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_UNKNOWN")
        if contract.get("policy", {}).get("reviewed_content_drift") != "fail":
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_REVIEW_SEAL")
        if set(contract.get("contract_evolution_decisions", [])) != {"EXPAND", "NO_CHANGE"}:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_EVOLUTION_DECISIONS")
        if contract.get("policy", {}).get("changelog_action_time_relation") != "declared_on_or_before_tag":
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_ACTION_TIME_POLICY")
        if contract.get("policy", {}).get("candidate_version_relation") != "strictly_after_published_baseline":
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CANDIDATE_VERSION_POLICY")
        if contract.get("policy", {}).get("changelog_date_floor") != "published_baseline_date":
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_DATE_FLOOR_POLICY")
        if contract.get("policy", {}).get("tag_remote_refresh_order") != "after_provider_checks_before_push":
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_TAG_REMOTE_REFRESH_POLICY")
        doc_policy = public_doc_version_policy(contract)
        if not any(matches("docs/providers.md", pattern) for pattern in doc_policy["active_globs"]):
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_PUBLIC_DOC_ROOT_GLOB")
        if not any(matches("docs/release/RELEASE_CONTRACT.md", pattern) for pattern in doc_policy["active_globs"]):
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_PUBLIC_DOC_NESTED_GLOB")
        fixture_pins = {"codex": "0.156.0", "claude": "2.1.280"}
        if public_doc_version_violation(
            "docs/providers.md", "Codex CLI 0.154.0 exact", "", "0.154.0",
            "0.4.2", fixture_pins, doc_policy
        ) is None:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_STALE_CODEX_DOC_VERSION")
        if public_doc_version_violation(
            "docs/providers.md", "Claude Code 2.1.272 exact", "", "2.1.272",
            "0.4.2", fixture_pins, doc_policy
        ) is None:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_STALE_CLAUDE_DOC_VERSION")
        if public_doc_version_violation(
            "README.md", "prepared for v0.4.0", "v", "0.4.0",
            "0.4.2", fixture_pins, doc_policy
        ) is None:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_STALE_PRODUCT_DOC_VERSION")
        if public_doc_version_violation(
            "docs/agent-runners.md", "Runner v0.8.5 compatibility", "v", "0.8.5",
            "0.4.2", fixture_pins, doc_policy
        ) is None:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_EXTERNAL_PRODUCT_VERSION_RESIDUE")
        if public_doc_version_violation(
            "SECURITY.md", "| 0.4.0 | prior |", "", "0.4.0",
            "0.4.2", fixture_pins, doc_policy
        ) is not None:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_HISTORICAL_PRODUCT_VERSION")
        if public_doc_version_violation(
            "docs/providers.md", "Codex CLI 0.156.0 exact", "", "0.156.0",
            "0.4.2", fixture_pins, doc_policy
        ) is not None:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CURRENT_CODEX_DOC_VERSION")
        if public_doc_version_violation(
            "docs/codex.md", "ordinary parser/runtime minimum remains", "", "0.147.0",
            "0.4.2", fixture_pins, doc_policy
        ) is not None:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CONTEXT_FREE_COMPATIBILITY_FLOOR")
        if public_doc_version_violation(
            "docs/codex.md", "stale wrapped version", "", "0.154.0",
            "0.4.2", fixture_pins, doc_policy
        ) is None:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CONTEXT_FREE_STALE_VERSION")
        validate_public_doc_versions(
            contract,
            __import__("tomllib").loads((ROOT/"Cargo.toml").read_text(encoding="utf-8"))["package"]["version"],
        )
        sample_changelog = [
            "## [9.9.9] - 2026-09-20",
            "",
            "### Fixed",
            "",
            "- fixture",
        ]
        if validate_changelog_tag_date(sample_changelog, "9.9.9", "2026-09-20").isoformat() != "2026-09-20":
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_SAME_DAY")
        if validate_changelog_tag_date(sample_changelog, "9.9.9", "2026-09-21").isoformat() != "2026-09-20":
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_LATER_TAG")
        try:
            validate_changelog_tag_date(sample_changelog, "9.9.9", "2026-09-19")
        except ValueError:
            pass
        else:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_FUTURE_DECLARATION")
        try:
            changelog_release_date(sample_changelog + ["## [9.9.9] - invalid"], "9.9.9")
        except ValueError:
            pass
        else:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_DUPLICATE")
        try:
            changelog_release_date(["## [9.9.9] - 2026/09/20"], "9.9.9")
        except ValueError:
            pass
        else:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_MALFORMED_HEADING")
        try:
            changelog_release_date(["## [9.9.9] - 2026-02-30"], "9.9.9")
        except ValueError:
            pass
        else:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_INVALID_DATE")
        if validate_changelog_baseline_date(datetime.date(2026, 9, 20), "2026-09-20T23:59:59Z").isoformat() != "2026-09-20":
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_BASELINE_SAME_DAY")
        try:
            validate_changelog_baseline_date(datetime.date(2026, 9, 19), "2026-09-20T00:00:00Z")
        except ValueError:
            pass
        else:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_BEFORE_BASELINE")
        declaration = {
            "release": "v9.9.9",
            "product_outcome": "A",
            "reviewed_content_digest": "0" * 64,
        }
        semantic = review_semantic_sha(declaration)
        digest_only = dict(declaration)
        digest_only["reviewed_content_digest"] = "1" * 64
        if review_semantic_sha(digest_only) != semantic:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_SELF_DIGEST")
        changed = dict(declaration)
        changed["product_outcome"] = "B"
        if review_semantic_sha(changed) == semantic:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_REVIEW_SEMANTICS")
        fixture = load_json(ROOT / "tests/fixtures/release-review-v1.json")
        migrated = migrate_review_v1(fixture, "3" * 64)
        if migrated.get("schema_version") != "clroom.release-review.v2":
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_N_MINUS_1_SCHEMA")
        if "reviewed_through_commit" in migrated:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_N_MINUS_1_ANCESTRY_FIELD")
        if migrated.get("reviewed_content_digest") != "3" * 64:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_N_MINUS_1_RESEAL")
        if migrated.get("reviewed_content_digest") == fixture.get("reviewed_content_digest"):
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_N_MINUS_1_STALE_DIGEST_REUSED")
        if review_semantic_sha(migrated) == review_semantic_sha(fixture):
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_N_MINUS_1_SEMANTICS_UNCHANGED")
        print("RELEASE_CONTRACT_SELF_TEST_PASS")
        return

    version = __import__("tomllib").loads((ROOT/"Cargo.toml").read_text(encoding="utf-8"))["package"]["version"]
    doc_version_inventory = validate_public_doc_versions(contract, version)
    changelog_lines = (ROOT/"CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    try:
        declared_release_date = changelog_release_date(changelog_lines, version)
        if args.tag_date is not None:
            validate_changelog_tag_date(changelog_lines, version, args.tag_date)
    except ValueError as error:
        raise SystemExit(f"RELEASE_CONTRACT_BLOCKED:CHANGELOG_DATE:{error}") from error
    review_path = Path(args.review or ROOT/f"reports/release/v{version}-review.json")
    review=load_json(review_path)
    if review.get("schema_version")!="clroom.release-review.v2":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:REVIEW_SCHEMA")
    if "reviewed_through_commit" in review:
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:LEGACY_REVIEW_ANCESTRY_FIELD")
    if review.get("release") != f"v{version}":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:REVIEW_VERSION")

    latest_tag, published_at = latest_published_release(args.repository)
    if review.get("baseline_release") != latest_tag:
        raise SystemExit(f"RELEASE_CONTRACT_BLOCKED:BASELINE_DRIFT:{latest_tag}")
    try:
        lifecycle = run(
            "python3",
            "scripts/release/resolve-release-lifecycle.py",
            "--candidate-version",
            version,
            "--published-tag",
            latest_tag,
        )
    except subprocess.CalledProcessError as error:
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:CANDIDATE_NOT_ADVANCED") from error
    if lifecycle != "ACTIVE_CANDIDATE":
        raise SystemExit(f"RELEASE_CONTRACT_BLOCKED:CANDIDATE_LIFECYCLE:{lifecycle}")
    try:
        baseline_release_date = validate_changelog_baseline_date(declared_release_date, published_at)
    except ValueError as error:
        raise SystemExit(f"RELEASE_CONTRACT_BLOCKED:CHANGELOG_BASELINE_DATE:{error}") from error
    ensure_ref(latest_tag)
    base_commit=run("git","rev-list","-n","1",latest_tag)

    head = run("git","rev-parse","HEAD")
    review_relative = str(review_path.resolve().relative_to(ROOT))
    expected_digest = review.get("reviewed_content_digest")
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:REVIEW_CONTENT_DIGEST_MISSING")
    actual_digest = reviewed_content_digest("HEAD", review_relative)
    if actual_digest != expected_digest:
        raise SystemExit(
            f"RELEASE_CONTRACT_BLOCKED:REVIEW_CONTENT_DRIFT:expected={expected_digest}:actual={actual_digest}"
        )

    # Disable rename detection so a cross-domain move is classified as both a
    # deletion at the old path and an addition at the new path.
    changed=run("git","diff","--no-renames","--name-only",f"{base_commit}..HEAD").splitlines()
    classified, unknown=classify(changed,contract)
    if unknown:
        print("\n".join(f"UNCLASSIFIED_RELEASE_DELTA:{p}" for p in unknown),file=sys.stderr)
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:UNCLASSIFIED_RELEASE_DELTA")

    changed_domains=sorted({d for ds in classified.values() for d in ds})
    dispositions=review.get("domain_dispositions",{})
    domain_allowed=set(contract["domain_satisfying_dispositions"])
    near_miss_allowed=set(contract["near_miss_dispositions"])
    for domain in changed_domains:
        item=dispositions.get(domain)
        if not item or item.get("decision") not in domain_allowed or not item.get("evidence"):
            raise SystemExit(f"RELEASE_CONTRACT_BLOCKED:DOMAIN_DISPOSITION:{domain}")

    expanded = False
    for item in review.get("near_misses",[]):
        if item.get("decision") not in near_miss_allowed:
            raise SystemExit("RELEASE_CONTRACT_BLOCKED:NEAR_MISS_DISPOSITION")
        if item.get("decision")=="CONTRACT_EXPAND":
            expanded = True
            if not item.get("durable_control"):
                raise SystemExit("RELEASE_CONTRACT_BLOCKED:NEAR_MISS_CONTROL")

    evolution = review.get("contract_evolution_review")
    allowed_evolution = set(contract.get("contract_evolution_decisions", []))
    if not isinstance(evolution, dict) or evolution.get("decision") not in allowed_evolution:
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:CONTRACT_EVOLUTION_REVIEW")
    if not evolution.get("rationale"):
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:CONTRACT_EVOLUTION_RATIONALE")
    promoted = evolution.get("promoted_controls", [])
    if evolution.get("decision") == "EXPAND" and not promoted:
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:CONTRACT_EVOLUTION_CONTROLS")
    if expanded and evolution.get("decision") != "EXPAND":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:CONTRACT_EVOLUTION_MISMATCH")

    if not review.get("product_outcome"):
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:PRODUCT_OUTCOME")

    if args.report:
        print(f"RELEASE={review['release']}")
        print(f"PUBLISHED_BASELINE={latest_tag}")
        print(f"PUBLISHED_AT={published_at}")
        print(f"PUBLISHED_BASELINE_DATE={baseline_release_date.isoformat()}")
        print(f"CANDIDATE_LIFECYCLE={lifecycle}")
        print(f"BASE_COMMIT={base_commit}")
        print("REVIEW_BINDING=content-addressed")
        print(f"HEAD={head}")
        print("CHANGED_DOMAINS="+",".join(changed_domains))
        print(f"CHANGED_FILES={len(changed)}")
        print("=== COMMITS SINCE PUBLISHED RELEASE ===")
        print(run("git","log","--oneline",f"{base_commit}..HEAD"))
        print("=== FILES SINCE PUBLISHED RELEASE ===")
        for p in changed:
            print(f"{p}\t{','.join(classified[p])}")
        print(f"REVIEWED_CONTENT_DIGEST={actual_digest}")
        print(f"CHANGELOG_DECLARED_DATE={declared_release_date.isoformat()}")
        if args.tag_date is not None:
            print(f"TAG_ACTION_DATE={args.tag_date}")
        print(f"CONTRACT_EVOLUTION={evolution['decision']}")
        print(f"PUBLIC_DOC_VERSION_MENTIONS={len(doc_version_inventory)}")
        print("=== PUBLIC DOC VERSION INVENTORY ===")
        for path, line_number, raw, classification in doc_version_inventory:
            print(f"{path}:{line_number}\t{raw}\t{classification}")
        print("=== ARTIFACT CAPABILITY GATES ===")
        for gate in review.get("artifact_capability_gates",[]):
            print(f"{gate['phase']}\t{gate['id']}\t{gate['requirement']}")
    print(f"RELEASE_CONTRACT_PASS release={review['release']} baseline={latest_tag} binding=content-addressed")

if __name__=="__main__":
    main()
