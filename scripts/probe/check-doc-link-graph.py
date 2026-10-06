#!/usr/bin/env python3
"""Validate CLROOM public documentation link-graph integrity."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

SITE_PREFIX = "/clean-room-launcher/"
CANONICAL_HOST = "y-sor.github.io"


class LinkGraphError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise LinkGraphError(message)


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"FILE_UNREADABLE:{path}:{exc}")


def markdown_links(text: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", text)]


def header_pages(config: str) -> set[str]:
    match = re.search(r"(?ms)^header_pages:\s*\n((?:\s+-\s+[^\n]+\n?)+)", config)
    if match is None:
        fail("HEADER_PAGES_MISSING")
    return {
        line.strip()[2:].strip()
        for line in match.group(1).splitlines()
        if line.strip().startswith("- ")
    }


def public_pages(root: Path) -> dict[str, Path]:
    docs = root / "docs"
    pages = {path.name: path for path in docs.glob("*.md") if path.is_file()}
    if "index.md" not in pages:
        fail("DOCS_HOME_MISSING")
    return pages


def canonical_to_source(path: str, pages: dict[str, Path]) -> str | None:
    clean = path.split("?", 1)[0].split("#", 1)[0]
    if clean == SITE_PREFIX.rstrip("/") or clean == SITE_PREFIX:
        return "index.md"
    if not clean.startswith(SITE_PREFIX):
        return None
    rel = clean[len(SITE_PREFIX):].strip("/")
    if not rel:
        return "index.md"
    if rel.endswith(".html"):
        candidate = rel[:-5] + ".md"
    else:
        candidate = rel + ".md"
    return candidate if candidate in pages else None


def relative_to_source(source: str, href: str, pages: dict[str, Path], root: Path) -> tuple[str | None, bool]:
    target = href.strip()
    if not target or target.startswith("#"):
        return source, True
    if target.startswith(("mailto:", "tel:", "javascript:")):
        return None, True

    parsed = urlparse(target)
    if parsed.scheme in {"http", "https"}:
        if parsed.netloc != CANONICAL_HOST:
            return None, True
        mapped = canonical_to_source(parsed.path, pages)
        return mapped, mapped is not None

    clean = target.split("#", 1)[0].split("?", 1)[0]
    if not clean:
        return source, True

    if clean.startswith("/"):
        mapped = canonical_to_source(clean, pages)
        return mapped, mapped is not None

    source_path = root / "docs" / source
    docs_root = (root / "docs").resolve()
    resolved = (source_path.parent / clean).resolve()
    try:
        rel = resolved.relative_to(docs_root)
    except ValueError:
        # Relative links that escape the Pages source tree do not become GitHub
        # repository links in rendered Pages. Use an explicit GitHub URL instead.
        return None, False

    if clean.endswith("/"):
        candidate_path = (source_path.parent / (clean.rstrip("/") + ".md")).resolve()
        candidate_name = candidate_path.name
        if (
            len(candidate_path.relative_to(docs_root).parts) == 1
            and candidate_name in pages
            and candidate_path == pages[candidate_name].resolve()
        ):
            return candidate_name, True

    if clean.endswith(".html"):
        candidate_path = (source_path.parent / (clean[:-5] + ".md")).resolve()
        candidate_name = candidate_path.name
        if (
            len(candidate_path.relative_to(docs_root).parts) == 1
            and candidate_name in pages
            and candidate_path == pages[candidate_name].resolve()
        ):
            return candidate_name, True

    if (
        len(rel.parts) == 1
        and rel.suffix == ".md"
        and rel.name in pages
        and resolved == pages[rel.name].resolve()
    ):
        return rel.name, True

    return None, resolved.exists()


def validate(root: Path) -> None:
    pages = public_pages(root)
    config = read(root / "docs" / "_config.yml")
    nav = header_pages(config)

    inbound: dict[str, set[str]] = defaultdict(set)
    broken: list[str] = []

    for source, path in pages.items():
        for href in markdown_links(read(path)):
            target, ok = relative_to_source(source, href, pages, root)
            if not ok:
                broken.append(f"{source}->{href}")
                continue
            if target is not None and target in pages and target != source:
                inbound[target].add(source)

    if broken:
        fail("BROKEN_INTERNAL_LINK:" + ",".join(sorted(broken)))

    orphaned = sorted(
        page
        for page in pages
        if page != "index.md" and page not in nav and not inbound.get(page)
    )
    if orphaned:
        fail("ORPHAN_PUBLIC_PAGE:" + ",".join(orphaned))

    print(
        "DOC_LINK_GRAPH_PASS "
        f"pages={len(pages)} nav={len(nav)} "
        f"linked={sum(1 for page in pages if page == 'index.md' or page in nav or inbound.get(page))}"
    )


def expect_failure(root: Path, reason: str) -> None:
    try:
        validate(root)
    except LinkGraphError as exc:
        if reason not in str(exc):
            fail(f"SELF_TEST_WRONG_FAILURE:expected={reason}:actual={exc}")
        return
    fail(f"SELF_TEST_NEGATIVE_PASSED:{reason}")


def write_fixture(
    root: Path,
    *,
    broken: bool = False,
    orphan: bool = False,
    wrong_prefix: bool = False,
    escape_docs: bool = False,
) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "_config.yml").write_text("header_pages:\n  - a.md\n", encoding="utf-8")
    (docs / "index.md").write_text(
        "---\nlayout: home\n---\n"
        + ("[broken](missing.md)\n" if broken else "[A](a.md)\n"),
        encoding="utf-8",
    )
    (docs / "a.md").write_text(
        "---\nlayout: page\n---\n"
        + (
            ""
            if orphan
            else (
                "[root](../README.md)\n"
                if escape_docs
                else ("[B](docs/b.md)\n" if wrong_prefix else "[B](b.md)\n")
            )
        ),
        encoding="utf-8",
    )
    (docs / "b.md").write_text("---\nlayout: page\n---\n", encoding="utf-8")
    (root / "README.md").write_text("# root\n", encoding="utf-8")


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="clroom-link-graph-") as temp:
        root = Path(temp) / "positive"
        write_fixture(root)
        validate(root)

        broken = Path(temp) / "broken"
        write_fixture(broken, broken=True)
        expect_failure(broken, "BROKEN_INTERNAL_LINK")

        orphan = Path(temp) / "orphan"
        write_fixture(orphan, orphan=True)
        expect_failure(orphan, "ORPHAN_PUBLIC_PAGE")

        wrong_prefix = Path(temp) / "wrong-prefix"
        write_fixture(wrong_prefix, wrong_prefix=True)
        expect_failure(wrong_prefix, "BROKEN_INTERNAL_LINK")

        escape_docs = Path(temp) / "escape-docs"
        write_fixture(escape_docs, escape_docs=True)
        expect_failure(escape_docs, "BROKEN_INTERNAL_LINK")

    print("DOC_LINK_GRAPH_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--root", type=Path)
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    try:
        if args.root is not None:
            validate(args.root.resolve())
            self_test()
        else:
            self_test()
    except LinkGraphError as exc:
        print(f"DOC_LINK_GRAPH_FAIL:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
