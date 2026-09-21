#!/usr/bin/env python3
import argparse
import datetime
import re
import tempfile
from pathlib import Path

VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[0-9]+)?$")


class ChangelogError(ValueError):
    pass


def parse_iso_date(value: str, label: str) -> datetime.date:
    try:
        parsed = datetime.date.fromisoformat(value)
    except ValueError as error:
        raise ChangelogError(f"{label}_INVALID:{value}") from error
    if parsed.isoformat() != value:
        raise ChangelogError(f"{label}_NON_CANONICAL:{value}")
    return parsed


def validate_release(path: Path, version: str, tag_date_text: str) -> tuple[datetime.date, str]:
    if not VERSION_RE.fullmatch(version):
        raise ChangelogError(f"VERSION_INVALID:{version}")
    tag_date = parse_iso_date(tag_date_text, "TAG_DATE")
    lines = path.read_text(encoding="utf-8").splitlines()
    heading = re.compile(rf"^## \[{re.escape(version)}\] - (?P<date>\d{{4}}-\d{{2}}-\d{{2}})$")
    matches = [(index, match) for index, line in enumerate(lines) if (match := heading.fullmatch(line))]
    if len(matches) != 1:
        raise ChangelogError(f"RELEASE_SECTION_COUNT:{len(matches)}")
    start, match = matches[0]
    declared_date = parse_iso_date(match.group("date"), "CHANGELOG_DATE")
    if declared_date > tag_date:
        raise ChangelogError(
            f"CHANGELOG_DATE_IN_FUTURE:declared={declared_date.isoformat()}:tag={tag_date.isoformat()}"
        )
    body = []
    for line in lines[start + 1 :]:
        if line.startswith("## ["):
            break
        body.append(line)
    if not "\n".join(body).strip():
        raise ChangelogError("RELEASE_SECTION_EMPTY")
    return declared_date, "\n".join(body).strip()


def self_test() -> None:
    cases = [
        ("same-day", "2026-09-21", "2026-09-21", True),
        ("earlier-declaration", "2026-09-20", "2026-09-21", True),
        ("future-declaration", "2026-09-22", "2026-09-21", False),
    ]
    with tempfile.TemporaryDirectory(prefix="clroom-changelog-contract-") as raw:
        path = Path(raw) / "CHANGELOG.md"
        for name, declared, tag_date, should_pass in cases:
            path.write_text(
                f"# Changelog\n\n## [9.9.9] - {declared}\n\n- fixture {name}\n\n## [9.9.8] - 2026-09-01\n\n- older\n",
                encoding="utf-8",
            )
            try:
                validate_release(path, "9.9.9", tag_date)
                passed = True
            except ChangelogError:
                passed = False
            if passed != should_pass:
                raise SystemExit(f"CHANGELOG_RELEASE_SELF_TEST_FAIL:{name}")
        path.write_text(
            "# Changelog\n\n## [9.9.9] - 2026-09-20\n\n- one\n\n## [9.9.9] - 2026-09-20\n\n- two\n",
            encoding="utf-8",
        )
        try:
            validate_release(path, "9.9.9", "2026-09-21")
        except ChangelogError as error:
            if not str(error).startswith("RELEASE_SECTION_COUNT:"):
                raise
        else:
            raise SystemExit("CHANGELOG_RELEASE_SELF_TEST_FAIL:duplicate")
    print("CHANGELOG_RELEASE_SELF_TEST_PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--changelog", default="CHANGELOG.md")
    parser.add_argument("--version")
    parser.add_argument("--tag-date")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return
    if not args.version or not args.tag_date:
        parser.error("--version and --tag-date are required unless --self-test is used")
    try:
        declared, _body = validate_release(Path(args.changelog), args.version, args.tag_date)
    except (OSError, ChangelogError) as error:
        raise SystemExit(f"CHANGELOG_RELEASE_BLOCKED:{error}") from error
    print(
        f"CHANGELOG_RELEASE_PASS version={args.version} declared_date={declared.isoformat()} "
        f"tag_date={args.tag_date}"
    )


if __name__ == "__main__":
    main()
