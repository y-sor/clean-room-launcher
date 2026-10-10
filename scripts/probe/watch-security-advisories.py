#!/usr/bin/env python3
"""Advisory evidence only: no CVE exploitation verdict and no release decisions."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
KEV_URL = "https://raw.githubusercontent.com/cisagov/kev-data/develop/known_exploited_vulnerabilities.json"
WINDOW_DAYS = 30
MAX_ADVISORIES = 100
MAX_PAGES = 20
MAX_RESPONSE = 8 * 1024 * 1024
CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,19}$")
GHSA_RE = re.compile(r"^GHSA-[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4}$")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("source-redirect-denied")


def fetch(url):
    if not (url.startswith("https://api.github.com/advisories?") or url == KEV_URL):
        raise ValueError("non-allowlisted-source")
    headers = {"User-Agent": "CLROOM-security-advisory-probe/1", "Accept": "application/vnd.github+json"}
    if url.startswith("https://api.github.com/") and os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as resp:
        if resp.status != 200:
            raise ValueError("non-200-source")
        data = resp.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise ValueError("oversize-source")
        return json.loads(data)


def installed_inventory(root):
    lock = tomllib.loads((root / "Cargo.lock").read_text(encoding="utf-8"))
    packages = lock.get("package")
    if not isinstance(packages, list) or not packages:
        raise ValueError("missing-lockfile-packages")
    rust = {}
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("malformed-lockfile-package")
        name, version = package.get("name"), package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("malformed-lockfile-version")
        # Only crates.io dependencies belong to the global Rust advisory ecosystem.
        if package.get("source", "").startswith("registry+"):
            rust.setdefault(name.lower(), set()).add(version)
    if not rust:
        raise ValueError("empty-rust-dependency-inventory")
    actions = set()
    for file in sorted((root / ".github/workflows").glob("*.yml")):
        content = file.read_text(encoding="utf-8")
        for item in re.findall(r"^\s*-?\s*uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/[A-Za-z0-9_./-]+)?@", content, re.M):
            actions.add(item.lower())
    for file in sorted((root / ".github/workflows").glob("*.yaml")):
        content = file.read_text(encoding="utf-8")
        for item in re.findall(r"^\s*-?\s*uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/[A-Za-z0-9_./-]+)?@", content, re.M):
            actions.add(item.lower())
    pins_text = (root / "scripts/release/provider-pins.sh").read_text(encoding="utf-8")
    pins = {}
    for key, name in (("CODEX_VERSION", "@openai/codex"), ("CLAUDE_VERSION", "@anthropic-ai/claude-code")):
        values = re.findall("^" + key + r"=(\d+\.\d+\.\d+)$", pins_text, re.M)
        if len(values) != 1:
            raise ValueError("ambiguous-provider-pin")
        pins[name] = values[0]
    return {"rust": rust, "actions": actions, "npm": pins}


def query(ecosystem, now):
    start = (now - dt.timedelta(days=WINDOW_DAYS)).date().isoformat()
    # 'modified' includes advisories published OR updated in the rolling window.
    params = urllib.parse.urlencode({"type": "reviewed", "ecosystem": ecosystem,
                                     "modified": ">=" + start, "per_page": MAX_ADVISORIES})
    return "https://api.github.com/advisories?" + params


def parse_advisories(ecosystem, records, inventory):
    if not isinstance(records, list) or len(records) > MAX_ADVISORIES:
        raise ValueError("advisory-page-unverified-or-truncated")
    matches = []
    for entry in records:
        if not isinstance(entry, dict) or not GHSA_RE.fullmatch(str(entry.get("ghsa_id", ""))):
            raise ValueError("invalid-advisory-shape")
        if entry.get("type") != "reviewed":
            raise ValueError("unexpected-advisory-type")
        if entry.get("withdrawn_at"):
            continue
        cvs = entry.get("vulnerabilities")
        if not isinstance(cvs, list):
            raise ValueError("missing-advisory-packages")
        for vuln in cvs:
            package = vuln.get("package") if isinstance(vuln, dict) else None
            if not isinstance(package, dict) or not isinstance(package.get("name"), str):
                raise ValueError("invalid-vulnerability-package")
            if package.get("ecosystem") != ecosystem:
                continue
            name = package["name"].lower()
            versions = (inventory["rust"].get(name, set()) if ecosystem == "rust"
                        else ({inventory["npm"][name]} if ecosystem == "npm" and name in inventory["npm"]
                              else {"github-action-pin"} if ecosystem == "actions" and name in inventory["actions"] else set()))
            if not versions:
                continue
            cve = entry.get("cve_id")
            if cve is not None and (not isinstance(cve, str) or not CVE_RE.fullmatch(cve)):
                raise ValueError("invalid-cve-id")
            matches.append({"ghsa_id": entry["ghsa_id"], "cve_id": cve, "ecosystem": ecosystem,
                            "package": name, "present_versions": sorted(versions),
                            "vendor_severity": entry.get("severity", "unknown"),
                            "vulnerable_range": vuln.get("vulnerable_version_range", "UNVERIFIED"),
                            "impact": "NEEDS_EXACT_RANGE_AND_REACHABILITY_CHECK",
                            "release_decision": "NOT_AUTHORIZED"})
    return matches


def collect_pages(ecosystem, inventory, getter, now):
    matches = []
    for page in range(1, MAX_PAGES + 1):
        url = query(ecosystem, now) + ("&page=" + str(page) if page > 1 else "")
        raw = getter(url)
        matches.extend(parse_advisories(ecosystem, raw, inventory))
        if len(raw) < MAX_ADVISORIES:
            return matches, page
    raise ValueError("advisory-page-limit-exceeded")


def parse_kev(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("vulnerabilities"), list):
        raise ValueError("invalid-kev-shape")
    rows = raw["vulnerabilities"]
    if not isinstance(raw.get("count"), int) or raw["count"] != len(rows) or len(rows) < 100:
        raise ValueError("invalid-kev-count")
    cves = set()
    for row in rows:
        cve = row.get("cveID") if isinstance(row, dict) else None
        if not isinstance(cve, str) or not CVE_RE.fullmatch(cve):
            raise ValueError("invalid-kev-cve")
        cves.add(cve)
    return cves


def source_reason(error):
    if isinstance(error, urllib.error.HTTPError):
        return "http-" + str(error.code)
    if isinstance(error, ValueError):
        code = str(error)
        if code in {"advisory-page-unverified-or-truncated", "advisory-page-limit-exceeded", "invalid-advisory-shape",
                    "unexpected-advisory-type", "missing-advisory-packages",
                    "invalid-vulnerability-package", "invalid-cve-id", "invalid-kev-shape",
                    "invalid-kev-count", "invalid-kev-cve", "source-redirect-denied",
                    "oversize-source", "non-allowlisted-source"}:
            return code
    return "source-unavailable-or-invalid"


def assemble(inventory, getter, now):
    signals, coverage = [], {}
    for ecosystem in ("rust", "actions", "npm"):
        try:
            matched, pages = collect_pages(ecosystem, inventory, getter, now)
            signals.extend(matched)
            coverage["github-reviewed-" + ecosystem] = "OBSERVED_RECENT_WINDOW_PAGES_" + str(pages)
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as error:
            coverage["github-reviewed-" + ecosystem] = "UNKNOWN:" + source_reason(error)
    try:
        kev = parse_kev(getter(KEV_URL))
        coverage["cisa-kev-mirror"] = "OBSERVED_SNAPSHOT"
        for item in signals:
            item["cisa_kev_listed"] = bool(item["cve_id"] and item["cve_id"] in kev)
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as error:
        coverage["cisa-kev-mirror"] = "UNKNOWN:" + source_reason(error)
        for item in signals:
            item["cisa_kev_listed"] = None
    bad = any(s.startswith("UNKNOWN") for s in coverage.values())
    return {"schema": "clroom.advisory-intake.v1",
            "observed_at": now.isoformat(), "source_commit": os.getenv("WATCH_SOURCE_HEAD", os.getenv("GITHUB_SHA", "LOCAL")),
            "coverage": coverage,
            "overall": "UNKNOWN_COVERAGE" if bad else "MATCHES_NEED_RESEARCH" if signals else "NO_MATCH_OBSERVED_IN_30_DAY_WINDOW",
            "release_decision": "NOT_AUTHORIZED",
            "signals": sorted(signals, key=lambda x: (x["ecosystem"], x["ghsa_id"], x["package"])),
            "nonclaims": [
                "Observed GHSA modifications in a rolling 30-day window, not a complete historical vulnerability audit.",
                "Package names may match while installed versions are not vulnerable; vulnerable version ranges and exploitability are NOT evaluated.",
                "CISA KEV only enriches matched CVEs and does not establish CLROOM exposure.",
                "Dependabot private alerts, OSV, provider native advisories and full threat assessment are NOT checked by this script.",
                "No severity classification, automatic PR, notification, pin update, release or publish is authorized."]}


def self_test():
    now = dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc)
    inv = {"rust": {"testcrate": {"1.2.3"}}, "actions": {"actions/checkout"},
           "npm": {"@openai/codex": "0.161.0", "@anthropic-ai/claude-code": "2.1.293"}}
    safe = {"ghsa_id": "GHSA-aaaa-bbbb-cccc", "type": "reviewed", "withdrawn_at": None,
            "severity": "critical", "cve_id": "CVE-2026-12345",
            "vulnerabilities": [{"package": {"ecosystem": "rust", "name": "testcrate"},
                                 "vulnerable_version_range": "<2.0.0"}]}
    sources = {query(e, now): [] for e in ("rust", "actions", "npm")}
    sources[query("rust", now)] = [safe]
    sources[KEV_URL] = {"count": 100, "vulnerabilities": [{"cveID": "CVE-2026-12345"}] +
                        [{"cveID": "CVE-2025-" + str(10000 + i)} for i in range(99)]}
    report = assemble(inv, sources.__getitem__, now)
    assert report["overall"] == "MATCHES_NEED_RESEARCH" and report["release_decision"] == "NOT_AUTHORIZED"
    assert report["signals"][0]["cisa_kev_listed"] is True
    assert report["signals"][0]["impact"] == "NEEDS_EXACT_RANGE_AND_REACHABILITY_CHECK"
    sources[query("rust", now)] = [dict(safe, vulnerabilities=[{"package":{"ecosystem":"rust","name":"unrelated"}}])]
    assert assemble(inv, sources.__getitem__, now)["overall"] == "NO_MATCH_OBSERVED_IN_30_DAY_WINDOW"
    sources[query("rust", now)] = [safe] * MAX_ADVISORIES
    sources[query("rust", now) + "&page=2"] = []
    assert assemble(inv, sources.__getitem__, now)["coverage"]["github-reviewed-rust"] == "OBSERVED_RECENT_WINDOW_PAGES_2"
    del sources[query("rust", now) + "&page=2"]
    def unavailable_page(url):
        if url == query("rust", now) + "&page=2":
            raise ValueError("simulated-source-page-unavailable")
        return sources[url]
    assert assemble(inv, unavailable_page, now)["overall"] == "UNKNOWN_COVERAGE"
    sources[query("rust", now)] = [safe]
    sources[KEV_URL] = {"count": 1, "vulnerabilities": []}
    assert assemble(inv, sources.__getitem__, now)["coverage"]["cisa-kev-mirror"].startswith("UNKNOWN")
    try:
        NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.invalid")
        raise AssertionError("unsafe redirect accepted")
    except ValueError:
        pass
    try:
        parse_advisories("rust", [{"ghsa_id":"bad"}], inv)
        raise AssertionError("malformed GHSA accepted")
    except ValueError:
        pass
    print("SECURITY_ADVISORY_INTAKE_SELF_TEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.output:
        ap.error("--output is required")
    report = assemble(installed_inventory(ROOT), fetch, dt.datetime.now(dt.timezone.utc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n### CLROOM security-advisory intake (not exploitability verdict)\n\n")
            f.write("State: **" + report["overall"] + "**. Release: NOT_AUTHORIZED.\n\n")
            f.write("Feeds: " + ", ".join(k + "=" + v for k,v in report["coverage"].items()) + "\n\n")
            f.write("Matching dependency-name candidates: " + str(len(report["signals"])) + ". Exact vulnerable range and reachability not determined.\n")
    else:
        print("SECURITY_ADVISORY_INTAKE:", report["overall"], "candidates", len(report["signals"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
