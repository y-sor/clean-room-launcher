#!/usr/bin/env python3
import argparse, fnmatch, hashlib, json, os, subprocess, sys, urllib.request
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
    args=parser.parse_args()

    contract=load_json(CONTRACT)
    if contract.get("schema_version")!="clroom.release-contract.v1":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:CONTRACT_SCHEMA")

    if args.self_test:
        sample=["src/cli/mod.rs","Cargo.lock",".github/workflows/ci.yml","scripts/release/readiness.sh","README.md","tests/cli/info.rs"]
        classified, unknown=classify(sample,contract)
        if unknown or any(not classified[p] for p in sample):
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL")
        if classify(["totally-new-root.bin"],contract)[1] != ["totally-new-root.bin"]:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_UNKNOWN")
        if contract.get("policy", {}).get("reviewed_content_drift") != "fail":
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_REVIEW_SEAL")
        if set(contract.get("contract_evolution_decisions", [])) != {"EXPAND", "NO_CHANGE"}:
            raise SystemExit("RELEASE_CONTRACT_SELF_TEST_FAIL_EVOLUTION_DECISIONS")
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
        print("RELEASE_CONTRACT_SELF_TEST_PASS")
        return

    version = __import__("tomllib").loads((ROOT/"Cargo.toml").read_text(encoding="utf-8"))["package"]["version"]
    review_path = Path(args.review or ROOT/f"reports/release/v{version}-review.json")
    review=load_json(review_path)
    if review.get("schema_version")!="clroom.release-review.v1":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:REVIEW_SCHEMA")
    if review.get("release") != f"v{version}":
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:REVIEW_VERSION")

    latest_tag, published_at = latest_published_release(args.repository)
    if review.get("baseline_release") != latest_tag:
        raise SystemExit(f"RELEASE_CONTRACT_BLOCKED:BASELINE_DRIFT:{latest_tag}")
    ensure_ref(latest_tag)
    base_commit=run("git","rev-list","-n","1",latest_tag)

    reviewed=review.get("reviewed_through_commit","")
    if not isinstance(reviewed, str) or len(reviewed) != 40 or any(ch not in "0123456789abcdef" for ch in reviewed):
        raise SystemExit("RELEASE_CONTRACT_BLOCKED:REVIEWED_COMMIT_ID")

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
        print(f"BASE_COMMIT={base_commit}")
        print(f"REVIEWED_THROUGH={reviewed}")
        print(f"HEAD={head}")
        print("CHANGED_DOMAINS="+",".join(changed_domains))
        print(f"CHANGED_FILES={len(changed)}")
        print("=== COMMITS SINCE PUBLISHED RELEASE ===")
        print(run("git","log","--oneline",f"{base_commit}..HEAD"))
        print("=== FILES SINCE PUBLISHED RELEASE ===")
        for p in changed:
            print(f"{p}\t{','.join(classified[p])}")
        print(f"REVIEWED_CONTENT_DIGEST={actual_digest}")
        print(f"CONTRACT_EVOLUTION={evolution['decision']}")
        print("=== ARTIFACT CAPABILITY GATES ===")
        for gate in review.get("artifact_capability_gates",[]):
            print(f"{gate['phase']}\t{gate['id']}\t{gate['requirement']}")
    print(f"RELEASE_CONTRACT_PASS release={review['release']} baseline={latest_tag} reviewed_through={reviewed}")

if __name__=="__main__":
    main()
