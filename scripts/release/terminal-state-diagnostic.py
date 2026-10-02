#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import select
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "clroom.terminal-state-diagnostic.v1"
QUERY_TIMEOUT_SECONDS = 0.45
PASSIVE_WINDOW_SECONDS = 0.12

MODE_NAMES = {
    1: "application_cursor",
    47: "alternate_screen_47",
    1000: "mouse_x10",
    1002: "mouse_button_event",
    1003: "mouse_any_event",
    1004: "focus_reporting",
    1006: "mouse_sgr",
    1047: "alternate_screen_1047",
    1049: "alternate_screen_1049",
    2004: "bracketed_paste",
    2026: "synchronized_output",
    2031: "color_scheme_reporting",
}
MODE_STATE_NAMES = {
    0: "not_recognized",
    1: "set",
    2: "reset",
    3: "permanently_set",
    4: "permanently_reset",
}

FOCUS_EVENT_RE = re.compile(rb"\x1b\[[IO]")
DA1_RE = re.compile(rb"\x1b\[\?[0-9]+(?:;[0-9]+)*c")
DA2_RE = re.compile(rb"\x1b\[>[0-9]+(?:;[0-9]+)*c")
KITTY_FLAGS_RE = re.compile(rb"\x1b\[\?([0-9]+)u")
COLOR_SCHEME_REPORT_RE = re.compile(rb"\x1b\[\?997(?:;[12])?n")


def run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def termios_summary(attrs: list[Any]) -> dict[str, Any]:
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = attrs
    return {
        "iflag": int(iflag),
        "oflag": int(oflag),
        "cflag": int(cflag),
        "lflag": int(lflag),
        "ispeed": int(ispeed),
        "ospeed": int(ospeed),
        "icanon": bool(lflag & termios.ICANON),
        "echo": bool(lflag & termios.ECHO),
        "isig": bool(lflag & termios.ISIG),
        "ixon": bool(iflag & termios.IXON),
        "icrnl": bool(iflag & termios.ICRNL),
        "opost": bool(oflag & termios.OPOST),
        "cc_hex": [bytes([value]).hex() if isinstance(value, int) else bytes(value).hex() for value in cc],
    }


def read_window(fd: int, label: str, timeout: float) -> tuple[bytes, list[dict[str, Any]]]:
    start = time.monotonic()
    deadline = start + timeout
    chunks: list[dict[str, Any]] = []
    payload = bytearray()

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        readable, _, _ = select.select([fd], [], [], remaining)
        if fd not in readable:
            break
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        payload.extend(chunk)
        chunks.append(
            {
                "label": label,
                "t_ms": round((time.monotonic() - start) * 1000, 3),
                "hex": chunk.hex(),
                "length": len(chunk),
            }
        )
    return bytes(payload), chunks


def mode_query(mode: int) -> bytes:
    return f"\x1b[?{mode}$p".encode("ascii")


def mode_response_re(mode: int) -> re.Pattern[bytes]:
    return re.compile(rb"\x1b\[\?" + str(mode).encode("ascii") + rb";([0-4])\$y")


def strip_known_machine_sequences(data: bytes, extra_patterns: tuple[re.Pattern[bytes], ...]) -> bytes:
    remaining = data
    patterns = (
        FOCUS_EVENT_RE,
        DA1_RE,
        DA2_RE,
        KITTY_FLAGS_RE,
        COLOR_SCHEME_REPORT_RE,
        *extra_patterns,
    )
    changed = True
    while changed and remaining:
        changed = False
        for pattern in patterns:
            updated = pattern.sub(b"", remaining)
            if updated != remaining:
                remaining = updated
                changed = True
    return remaining


def query_and_capture(
    fd: int,
    label: str,
    query: bytes,
    expected: re.Pattern[bytes],
) -> dict[str, Any]:
    os.write(fd, query)
    raw, chunks = read_window(fd, label, QUERY_TIMEOUT_SECONDS)
    match = expected.search(raw)
    unexpected = strip_known_machine_sequences(raw, (expected,))
    return {
        "label": label,
        "query_hex": query.hex(),
        "response_hex": raw.hex(),
        "chunks": chunks,
        "matched": bool(match),
        "match_hex": match.group(0).hex() if match else None,
        "unexpected_hex": unexpected.hex(),
    }


def validate_head(root: Path, expected_head: str) -> tuple[str, str, Path]:
    head = run_git(root, "rev-parse", "HEAD")
    if head != expected_head:
        raise RuntimeError(f"WRONG_HEAD:{head}")
    status = run_git(root, "status", "--porcelain")
    if status:
        raise RuntimeError("WORKTREE_NOT_CLEAN")
    origin = run_git(root, "remote", "get-url", "origin")
    common_dir = Path(run_git(root, "rev-parse", "--git-common-dir"))
    if not common_dir.is_absolute():
        common_dir = (root / common_dir).resolve()
    return head, origin, common_dir


def self_test() -> int:
    for mode in MODE_NAMES:
        query = mode_query(mode)
        if query.endswith((b"h", b"l")):
            raise SystemExit("TERMINAL_STATE_DIAGNOSTIC_SELF_TEST_FAIL:MUTATING_QUERY")
        response = f"\x1b[?{mode};2$y".encode("ascii")
        match = mode_response_re(mode).fullmatch(response)
        if match is None or int(match.group(1)) != 2:
            raise SystemExit("TERMINAL_STATE_DIAGNOSTIC_SELF_TEST_FAIL:MODE_RESPONSE")

    sample = (
        b"\x1b[O"
        b"\x1b[?997;1n"
        b"\x1b[?64;1;2;4;6;17;18;21;22;52c"
        b"\x1b[?1004;1$y"
    )
    leftover = strip_known_machine_sequences(sample, (mode_response_re(1004),))
    if leftover:
        raise SystemExit("TERMINAL_STATE_DIAGNOSTIC_SELF_TEST_FAIL:MACHINE_CLASSIFIER")
    if strip_known_machine_sequences(b"x", ()) != b"x":
        raise SystemExit("TERMINAL_STATE_DIAGNOSTIC_SELF_TEST_FAIL:HUMAN_INPUT_CLASSIFIER")
    if not KITTY_FLAGS_RE.fullmatch(b"\x1b[?3u"):
        raise SystemExit("TERMINAL_STATE_DIAGNOSTIC_SELF_TEST_FAIL:KITTY_FLAGS")
    print("TERMINAL_STATE_DIAGNOSTIC_SELF_TEST_PASS")
    return 0


def diagnose(expected_head: str) -> int:
    root = Path(__file__).resolve().parents[2]
    if platform.system() != "Darwin":
        print("TERMINAL_STATE_DIAGNOSTIC_BLOCKED:MACOS_REQUIRED", file=sys.stderr)
        return 2
    if platform.machine() != "arm64":
        print("TERMINAL_STATE_DIAGNOSTIC_BLOCKED:APPLE_SILICON_REQUIRED", file=sys.stderr)
        return 2

    try:
        head, origin, common_dir = validate_head(root, expected_head)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"TERMINAL_STATE_DIAGNOSTIC_BLOCKED:{exc}", file=sys.stderr)
        return 2

    fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    saved = termios.tcgetattr(fd)
    before_summary = termios_summary(saved)
    size = os.get_terminal_size(fd)
    evidence: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "repo": "y-sor/clean-room-launcher",
        "head": head,
        "origin": origin,
        "tty": os.ttyname(fd),
        "terminal": {
            key: os.environ.get(key)
            for key in ("TERM", "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "COLORTERM", "LC_TERMINAL", "LC_TERMINAL_VERSION")
            if os.environ.get(key) is not None
        },
        "size": {"columns": size.columns, "lines": size.lines},
        "termios_before": before_summary,
        "queries": [],
        "mode_states": {},
        "passive_before": None,
        "passive_after": None,
        "unexpected_hex": [],
    }

    try:
        tty.setraw(fd)

        passive, chunks = read_window(fd, "passive_before", PASSIVE_WINDOW_SECONDS)
        evidence["passive_before"] = {"hex": passive.hex(), "chunks": chunks}
        passive_unexpected = strip_known_machine_sequences(passive, ())
        if passive_unexpected:
            evidence["unexpected_hex"].append(passive_unexpected.hex())

        for mode, name in MODE_NAMES.items():
            expected = mode_response_re(mode)
            result = query_and_capture(fd, f"decrqm:{mode}:{name}", mode_query(mode), expected)
            evidence["queries"].append(result)
            match = expected.search(bytes.fromhex(result["response_hex"]))
            state_code = int(match.group(1)) if match else None
            evidence["mode_states"][name] = {
                "mode": mode,
                "state_code": state_code,
                "state": MODE_STATE_NAMES.get(state_code, "unknown") if state_code is not None else "no_response",
            }
            if result["unexpected_hex"]:
                evidence["unexpected_hex"].append(result["unexpected_hex"])

        for label, query, pattern in (
            ("da1", b"\x1b[c", DA1_RE),
            ("da2", b"\x1b[>c", DA2_RE),
            ("kitty_keyboard_flags", b"\x1b[?u", KITTY_FLAGS_RE),
        ):
            result = query_and_capture(fd, label, query, pattern)
            evidence["queries"].append(result)
            if result["unexpected_hex"]:
                evidence["unexpected_hex"].append(result["unexpected_hex"])

        passive, chunks = read_window(fd, "passive_after", PASSIVE_WINDOW_SECONDS)
        evidence["passive_after"] = {"hex": passive.hex(), "chunks": chunks}
        passive_unexpected = strip_known_machine_sequences(passive, ())
        if passive_unexpected:
            evidence["unexpected_hex"].append(passive_unexpected.hex())
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        after = termios.tcgetattr(fd)
        evidence["termios_after"] = termios_summary(after)
        evidence["termios_restored"] = after == saved
        os.close(fd)

    kitty_flags = None
    for item in evidence["queries"]:
        if item["label"] == "kitty_keyboard_flags":
            match = KITTY_FLAGS_RE.search(bytes.fromhex(item["response_hex"]))
            kitty_flags = int(match.group(1)) if match else None
            break
    evidence["kitty_keyboard_flags"] = kitty_flags

    focus = evidence["mode_states"].get("focus_reporting", {})
    color_scheme = evidence["mode_states"].get("color_scheme_reporting", {})
    evidence_dir = common_dir / "clroom-release-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / f"terminal-state-{head[:12]}.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    unexpected_count = len(evidence["unexpected_hex"])
    focus_state = focus.get("state", "unknown")
    termios_restored = bool(evidence["termios_restored"])
    focus_known = focus_state not in ("unknown", "no_response")
    color_scheme_state = color_scheme.get("state", "unknown")
    color_scheme_known = color_scheme_state not in ("unknown", "no_response")
    status = (
        "PASS"
        if termios_restored
        and focus_known
        and color_scheme_known
        and unexpected_count == 0
        else "BLOCKED"
    )

    print(
        "TERMINAL_PREFLIGHT_SUMMARY "
        f"status={status} "
        f"head={head} "
        f"tty={evidence['tty']} "
        f"term_program={evidence['terminal'].get('TERM_PROGRAM', 'unknown')} "
        f"focus_reporting={focus_state} "
        f"color_scheme_reporting={color_scheme_state} "
        f"bracketed_paste={evidence['mode_states'].get('bracketed_paste', {}).get('state', 'unknown')} "
        f"kitty_flags={kitty_flags if kitty_flags is not None else 'unknown'} "
        f"unexpected_chunks={unexpected_count} "
        f"termios_restored={'YES' if termios_restored else 'NO'}"
    )
    print(f"EVIDENCE_FILE={evidence_path}")
    if status != "PASS":
        print("TERMINAL_STATE_DIAGNOSTIC_BLOCKED:INCOMPLETE_OR_CONTAMINATED_EVIDENCE", file=sys.stderr)
        return 3
    print("TERMINAL_STATE_DIAGNOSTIC=PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--expected-head")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.expected_head or not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        print("TERMINAL_STATE_DIAGNOSTIC_BLOCKED:EXPECTED_HEAD_REQUIRED", file=sys.stderr)
        return 64
    return diagnose(args.expected_head)


if __name__ == "__main__":
    raise SystemExit(main())
