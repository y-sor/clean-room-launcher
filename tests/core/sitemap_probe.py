#!/usr/bin/env python3
"""Validate CLROOM sitemap source contract and published sitemap bytes."""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

CANONICAL_SITEMAP = "https://y-sor.github.io/clean-room-launcher/sitemap.xml"
CANONICAL_HOME = "https://y-sor.github.io/clean-room-launcher/"
CANONICAL_HOST = "y-sor.github.io"
CANONICAL_PATH_PREFIX = "/clean-room-launcher/"
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
MAX_BYTES = 1_000_000
MAX_URLS = 200


class ValidationError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValidationError(f"unexpected redirect: {code} -> {newurl}")


def fail(message: str) -> None:
    raise ValidationError(message)


def validate_xml(payload: bytes) -> int:
    if len(payload) > MAX_BYTES:
        fail(f"sitemap too large: {len(payload)} bytes")

    if payload.startswith(b"\xef\xbb\xbf"):
        payload = payload[3:]

    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        fail(f"invalid XML: {exc}")

    urlset_tag = f"{{{SITEMAP_NS}}}urlset"
    url_tag = f"{{{SITEMAP_NS}}}url"
    loc_tag = f"{{{SITEMAP_NS}}}loc"

    if root.tag != urlset_tag:
        fail(f"unexpected root element: {root.tag}")

    locations: list[str] = []
    for child in root:
        if child.tag != url_tag:
            fail(f"unexpected urlset child: {child.tag}")
        locs = child.findall(loc_tag)
        if len(locs) != 1 or locs[0].text is None:
            fail("each <url> must contain exactly one non-empty <loc>")
        location = locs[0].text.strip()
        if not location:
            fail("empty <loc>")

        parsed = urlsplit(location)
        if (
            parsed.scheme != "https"
            or parsed.hostname != CANONICAL_HOST
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith(CANONICAL_PATH_PREFIX)
        ):
            fail(f"non-canonical sitemap URL: {location}")

        locations.append(location)

    if not locations:
        fail("sitemap has no URLs")
    if len(locations) > MAX_URLS:
        fail(f"sitemap URL count exceeds bounded maximum: {len(locations)}")
    if len(set(locations)) != len(locations):
        fail("sitemap contains duplicate URLs")
    if CANONICAL_HOME not in locations:
        fail("canonical homepage is missing from sitemap")

    return len(locations)


def validate_source(root: Path) -> None:
    config = (root / "docs/_config.yml").read_text(encoding="utf-8")
    robots = (root / "docs/robots.txt").read_text(encoding="utf-8")
    sitemap = (root / "docs/sitemap.xml").read_text(encoding="utf-8")

    required_config = (
        'url: "https://y-sor.github.io"',
        'baseurl: "/clean-room-launcher"',
        "repository: y-sor/clean-room-launcher",
    )
    for item in required_config:
        if item not in config:
            fail(f"missing docs config contract: {item}")
    if "jekyll-sitemap" in config:
        fail("jekyll-sitemap must remain disabled while the explicit sitemap is authoritative")

    if f"Sitemap: {CANONICAL_SITEMAP}" not in robots:
        fail("robots.txt does not declare the canonical sitemap")

    required_template = (
        "permalink: /sitemap.xml",
        f'<urlset xmlns="{SITEMAP_NS}">',
        "{% for page in site.html_pages %}",
        "{% unless page.sitemap == false %}",
        "{{ page.url | absolute_url | xml_escape }}",
    )
    for item in required_template:
        if item not in sitemap:
            fail(f"missing sitemap template contract: {item}")

    print("SITEMAP_SOURCE_PASS")


def self_test() -> None:
    valid = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}">
  <url><loc>{CANONICAL_HOME}</loc></url>
  <url><loc>{CANONICAL_HOME}faq/</loc></url>
</urlset>
""".encode()
    if validate_xml(valid) != 2:
        fail("positive fixture count mismatch")

    negative = {
        "malformed": b"<urlset>",
        "html": b"<html><body>not a sitemap</body></html>",
        "foreign-host": f"""<urlset xmlns="{SITEMAP_NS}">
          <url><loc>https://example.com/clean-room-launcher/</loc></url>
        </urlset>""".encode(),
        "duplicate": f"""<urlset xmlns="{SITEMAP_NS}">
          <url><loc>{CANONICAL_HOME}</loc></url>
          <url><loc>{CANONICAL_HOME}</loc></url>
        </urlset>""".encode(),
        "missing-home": f"""<urlset xmlns="{SITEMAP_NS}">
          <url><loc>{CANONICAL_HOME}faq/</loc></url>
        </urlset>""".encode(),
    }

    for name, payload in negative.items():
        try:
            validate_xml(payload)
        except ValidationError:
            continue
        fail(f"negative fixture unexpectedly passed: {name}")

    print("SITEMAP_NEGATIVE_TESTS_PASS")


def fetch_live() -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(
        CANONICAL_SITEMAP,
        headers={
            "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.1",
            "User-Agent": "CLROOM-Sitemap-Canary/1.0",
        },
        method="GET",
    )

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with opener.open(request, timeout=15) as response:
                if response.status != 200:
                    fail(f"unexpected HTTP status: {response.status}")
                if response.geturl() != CANONICAL_SITEMAP:
                    fail(f"unexpected final URL: {response.geturl()}")

                content_type = response.headers.get_content_type()
                if "xml" not in content_type:
                    fail(f"unexpected Content-Type: {content_type}")

                payload = response.read(MAX_BYTES + 1)
                count = validate_xml(payload)
                print(
                    "SITEMAP_LIVE_PASS "
                    f"urls={count} content_type={content_type} bytes={len(payload)}"
                )
                return
        except (urllib.error.URLError, TimeoutError, ValidationError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 2)

    fail(f"live sitemap check failed after 3 attempts: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source-root", type=Path)
    group.add_argument("--live", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    try:
        if args.source_root is not None:
            validate_source(args.source_root)
            self_test()
        elif args.live:
            fetch_live()
        else:
            self_test()
    except (OSError, ValidationError) as exc:
        print(f"SITEMAP_CHECK_FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
