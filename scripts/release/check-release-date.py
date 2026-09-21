#!/usr/bin/env python3
import argparse
import datetime as dt
import re
import subprocess
from pathlib import Path

VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[0-9]+)?")
TAGGER_RE = re.compile(r" (\d+) ([+-])(\d{2})(\d{2})$")


class ReleaseDateError(ValueError):
    pass


def parse_iso_date(raw: str, label: str) -> dt.date:
    try:
        value = dt.date.fromisoformat(raw)
    except ValueError as exc:
        raise ReleaseDateError(f"RELEASE_DATE_BLOCKED:{label}_INVALID:{raw}") from exc
    if value.isoformat() != raw:
        raise ReleaseDateError(f"RELEASE_DATE_BLOCKED:{label}_NON_CANONICAL:{raw}")
    return value


def tagger_utc_date_from_text(raw: str) -> dt.date:
    line = next((line for line in raw.splitlines() if line.startswith("tagger ")), None)
    if line is None:
        raise ReleaseDateError("RELEASE_DATE_BLOCKED:TAGGER_LINE_MISSING")
    match = TAGGER_RE.search(line)
    if match is None:
        raise ReleaseDateError("RELEASE_DATE_BLOCKED:TAGGER_TIMESTAMP_MALFORMED")
    offset_hours = int(match.group(3))
    offset_minutes = int(match.group(4))
    if offset_hours > 23 or offset_minutes > 59:
        raise ReleaseDateError("RELEASE_DATE_BLOCKED:TAGGER_OFFSET_MALFORMED")
    epoch = int(match.group(1))
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).date()


def tagger_date(tag_ref: str) -> dt.date:
    raw = subprocess.check_output(
        ["git", "cat-file", "-p", f"refs/tags/{tag_ref}"],
        text=True,
    )
    return tagger_utc_date_from_text(raw)


def changelog_release_date(changelog: Path, version: str) -> dt.date:
    prefix = f"## [{version}]"
    matches = [line for line in changelog.read_text(encoding="utf-8").splitlines() if line.startswith(prefix)]
    if len(matches) != 1:
        raise ReleaseDateError(
            f"RELEASE_DATE_BLOCKED:CHANGELOG_VERSION_HEADING_COUNT:{version}:{len(matches)}"
        )
    expected = re.fullmatch(
        rf"## \[{re.escape(version)}\] - (?P<date>\d{{4}}-\d{{2}}-\d{{2}})",
        matches[0],
    )
    if expected is None:
        raise ReleaseDateError(
            f"RELEASE_DATE_BLOCKED:CHANGELOG_VERSION_HEADING_MALFORMED:{version}"
        )
    return parse_iso_date(expected.group("date"), "CHANGELOG_DATE")


def validate_version(version: str) -> None:
    if VERSION_RE.fullmatch(version) is None:
        raise ReleaseDateError(f"RELEASE_DATE_BLOCKED:VERSION_INVALID:{version}")


def validate_candidate(changelog: Path, version: str) -> dt.date:
    validate_version(version)
    return changelog_release_date(changelog, version)


def validate(changelog: Path, version: str, tag_date: dt.date) -> dt.date:
    release_date = validate_candidate(changelog, version)
    if release_date > tag_date:
        raise ReleaseDateError(
            "RELEASE_DATE_BLOCKED:CHANGELOG_DATE_AFTER_TAG:"
            f"release={release_date.isoformat()}:tag={tag_date.isoformat()}"
        )
    return release_date


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="clroom-release-date-") as raw:
        root = Path(raw)
        changelog = root / "CHANGELOG.md"
        changelog.write_text(
            "# Changelog\n\n## [1.2.3] - 2026-09-20\n\n- item\n",
            encoding="utf-8",
        )
        assert validate(changelog, "1.2.3", dt.date(2026, 9, 20)) == dt.date(2026, 9, 20)
        assert validate(changelog, "1.2.3", dt.date(2026, 9, 21)) == dt.date(2026, 9, 20)
        epoch = int(dt.datetime(2026, 9, 21, 0, 30, tzinfo=dt.timezone.utc).timestamp())
        plus = f"tagger Test <test@example.com> {epoch} +1400\n"
        minus = f"tagger Test <test@example.com> {epoch} -1200\n"
        assert tagger_utc_date_from_text(plus) == dt.date(2026, 9, 21)
        assert tagger_utc_date_from_text(minus) == dt.date(2026, 9, 21)


        try:
            validate(changelog, "1.2.3", dt.date(2026, 9, 19))
        except ReleaseDateError as error:
            assert "CHANGELOG_DATE_AFTER_TAG" in str(error)
        else:
            raise AssertionError("future changelog date must fail closed")

        changelog.write_text(
            "# Changelog\n\n## [1.2.3] - 2026-09-20\n\n## [1.2.3] - 2026-09-20\n",
            encoding="utf-8",
        )
        try:
            validate(changelog, "1.2.3", dt.date(2026, 9, 21))
        except ReleaseDateError as error:
            assert "CHANGELOG_VERSION_HEADING_COUNT" in str(error)
        else:
            raise AssertionError("duplicate version headings must fail closed")

        changelog.write_text(
            "# Changelog\n\n## [1.2.3] - TBD\n",
            encoding="utf-8",
        )
        try:
            validate(changelog, "1.2.3", dt.date(2026, 9, 21))
        except ReleaseDateError as error:
            assert "CHANGELOG_VERSION_HEADING_MALFORMED" in str(error)
        else:
            raise AssertionError("malformed release date must fail closed")

    print("RELEASE_DATE_SELF_TEST_PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version")
    parser.add_argument("--tag-ref")
    parser.add_argument("--tag-date")
    parser.add_argument("--changelog", default="CHANGELOG.md")
    parser.add_argument("--candidate-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return
    if not args.version:
        parser.error("--version is required")
    modes = int(args.candidate_only) + int(bool(args.tag_ref)) + int(bool(args.tag_date))
    if modes != 1:
        parser.error("provide exactly one of --candidate-only, --tag-ref or --tag-date")

    try:
        if args.candidate_only:
            release_date = validate_candidate(Path(args.changelog), args.version)
            print(
                "RELEASE_DATE_CANDIDATE_PASS "
                f"version={args.version} changelog_date={release_date.isoformat()}"
            )
            return
        tag_date = tagger_date(args.tag_ref) if args.tag_ref else parse_iso_date(args.tag_date, "TAG_DATE")
        release_date = validate(Path(args.changelog), args.version, tag_date)
    except (OSError, subprocess.SubprocessError, ReleaseDateError) as error:
        raise SystemExit(str(error))

    print(
        "RELEASE_DATE_PASS "
        f"version={args.version} changelog_date={release_date.isoformat()} tag_date={tag_date.isoformat()}"
    )


if __name__ == "__main__":
    main()
