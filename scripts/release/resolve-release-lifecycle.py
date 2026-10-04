#!/usr/bin/env python3
import argparse
import re


CANDIDATE_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")
PUBLISHED_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def resolve(
    candidate_version: str,
    published_tag: str,
    *,
    candidate_source: str | None = None,
    candidate_tag_source: str | None = None,
) -> str:
    candidate = CANDIDATE_RE.fullmatch(candidate_version)
    published = PUBLISHED_TAG_RE.fullmatch(published_tag)
    if candidate is None:
        raise ValueError("CANDIDATE_VERSION")
    if published is None:
        raise ValueError("PUBLISHED_TAG")

    published_version = published_tag[1:]
    if candidate_version == published_version:
        return "POST_PUBLISH"

    candidate_core = tuple(int(candidate.group(i)) for i in range(1, 4))
    published_core = tuple(int(published.group(i)) for i in range(1, 4))
    if candidate_core <= published_core:
        raise ValueError("CANDIDATE_NOT_ADVANCED")

    if candidate_tag_source is None:
        return "ACTIVE_CANDIDATE"

    if candidate_source is None:
        raise ValueError("CANDIDATE_SOURCE_REQUIRED")
    if SHA_RE.fullmatch(candidate_source) is None:
        raise ValueError("CANDIDATE_SOURCE")
    if SHA_RE.fullmatch(candidate_tag_source) is None:
        raise ValueError("CANDIDATE_TAG_SOURCE")

    if candidate_tag_source == candidate_source:
        raise ValueError("CANDIDATE_TAG_ALREADY_BOUND")

    return "QUARANTINED_REPAIR"


def self_test() -> None:
    assert resolve("0.4.0", "v0.4.0") == "POST_PUBLISH"
    assert resolve("0.4.1", "v0.4.0") == "ACTIVE_CANDIDATE"
    assert resolve("0.5.0", "v0.4.0") == "ACTIVE_CANDIDATE"
    assert resolve("0.4.1-rc.1", "v0.4.0") == "ACTIVE_CANDIDATE"
    assert (
        resolve(
            "0.4.1",
            "v0.4.0",
            candidate_source="b" * 40,
            candidate_tag_source="a" * 40,
        )
        == "QUARANTINED_REPAIR"
    )

    blocked = (
        ("0.3.9", "v0.4.0", None, None),
        ("0.4.0-rc.1", "v0.4.0", None, None),
        ("0.4.0", "0.4.0", None, None),
        ("next", "v0.4.0", None, None),
        ("0.4.1", "v0.4.0", None, "a" * 40),
        ("0.4.1", "v0.4.0", "a" * 40, "a" * 40),
        ("0.4.1", "v0.4.0", "not-a-sha", "a" * 40),
    )
    for candidate_version, published_tag, source, tag_source in blocked:
        try:
            resolve(
                candidate_version,
                published_tag,
                candidate_source=source,
                candidate_tag_source=tag_source,
            )
        except ValueError:
            continue
        raise SystemExit(
            "RELEASE_LIFECYCLE_SELF_TEST_FAIL "
            f"candidate={candidate_version} published={published_tag}"
        )
    print("RELEASE_LIFECYCLE_SELF_TEST_PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-version")
    parser.add_argument("--published-tag")
    parser.add_argument("--candidate-source")
    parser.add_argument("--candidate-tag-source")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return
    if not args.candidate_version or not args.published_tag:
        parser.error("--candidate-version and --published-tag are required")

    try:
        print(
            resolve(
                args.candidate_version,
                args.published_tag,
                candidate_source=args.candidate_source,
                candidate_tag_source=args.candidate_tag_source,
            )
        )
    except ValueError as exc:
        raise SystemExit(f"RELEASE_LIFECYCLE_BLOCKED:{exc}") from exc


if __name__ == "__main__":
    main()
