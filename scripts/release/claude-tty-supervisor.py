#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import fcntl
import os
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import time
import tty

TERM_GRACE_SECONDS = 2.0
INPUT_SEQUENCE_TIMEOUT_SECONDS = 0.5
COMPOSER_READY_TIMEOUT_SECONDS = 20.0
OBSERVATION_WINDOW_SECONDS = 8.0
QUERY_TIMEOUT_SECONDS = 0.35
READY_MARKER = b"manual mode on"
OUTPUT_TAIL_LIMIT = 131072

PHYSICAL_MODE_IDS = (
    1,
    47,
    66,
    1000,
    1002,
    1003,
    1004,
    1006,
    1007,
    1047,
    1049,
    2004,
    2026,
)
CRITICAL_PHYSICAL_MODES = (1004, 2004)

FOCUS_EVENT_RE = re.compile(rb"\x1b\[[IO]")
CSI_RESPONSE_PATTERNS = (
    FOCUS_EVENT_RE,
    re.compile(rb"\x1b\[\?[0-9]+(?:;[0-9]+)*c"),
    re.compile(rb"\x1b\[>[0-9]+(?:;[0-9]+)*c"),
    re.compile(rb"\x1b\[\?[0-9]+u"),
    re.compile(rb"\x1b\[\?[0-9]+;[0-9]+R"),
    re.compile(rb"\x1b\[\?[0-9]+;[0-9]+\$y"),
)
KITTY_FLAGS_RE = re.compile(rb"\x1b\[\?([0-9]+)u")


def terminal_response_length(data: bytes) -> int:
    """Return >0 for one complete terminal machine input, 0 for a valid prefix, -1 otherwise."""
    if not data or data[0] != 0x1B:
        return -1
    if len(data) == 1:
        return 0

    kind = data[1]
    if kind == ord("["):
        index = 2
        while index < len(data):
            value = data[index]
            if 0x40 <= value <= 0x7E:
                sequence = data[: index + 1]
                if any(pattern.fullmatch(sequence) for pattern in CSI_RESPONSE_PATTERNS):
                    return index + 1
                return -1
            if 0x20 <= value <= 0x3F:
                index += 1
                continue
            return -1
        return 0

    if kind == ord("]"):
        prefix10 = b"\x1b]10;"
        prefix11 = b"\x1b]11;"
        if len(data) < len(prefix10):
            if prefix10.startswith(data) or prefix11.startswith(data):
                return 0
            return -1
        if not (data.startswith(prefix10) or data.startswith(prefix11)):
            return -1
        bel = data.find(b"\x07", len(prefix10))
        st = data.find(b"\x1b\\", len(prefix10))
        ends = [value for value in (bel + 1 if bel >= 0 else -1, st + 2 if st >= 0 else -1) if value > 0]
        return min(ends) if ends else 0

    if kind == ord("P"):
        prefix = b"\x1bP>|"
        if len(data) < len(prefix):
            return 0 if prefix.startswith(data) else -1
        if not data.startswith(prefix):
            return -1
        st = data.find(b"\x1b\\", len(prefix))
        return st + 2 if st >= 0 else 0

    return -1


def classify_terminal_input(data: bytes) -> tuple[bool, bool, int, bytes]:
    """Allow only terminal-generated machine traffic; human key bytes fail closed."""
    forwarded = bytearray()
    count = 0
    offset = 0
    while offset < len(data):
        length = terminal_response_length(data[offset:])
        if length < 0:
            return True, False, count, bytes(forwarded)
        if length == 0:
            return False, True, count, bytes(forwarded)
        forwarded.extend(data[offset : offset + length])
        count += 1
        offset += length
    return False, False, count, bytes(forwarded)


def visible_text(data: bytes) -> bytes:
    """Best-effort printable TUI stream with ANSI/OSC/DCS controls removed."""
    out = bytearray()
    index = 0
    while index < len(data):
        value = data[index]
        if value == 0x1B:
            if index + 1 >= len(data):
                break
            kind = data[index + 1]
            if kind == ord("["):
                index += 2
                while index < len(data):
                    final = data[index]
                    index += 1
                    if 0x40 <= final <= 0x7E:
                        break
                continue
            if kind == ord("]"):
                index += 2
                while index < len(data):
                    if data[index] == 0x07:
                        index += 1
                        break
                    if data[index:index + 2] == b"\x1b\\":
                        index += 2
                        break
                    index += 1
                continue
            if kind == ord("P"):
                index += 2
                while index < len(data):
                    if data[index:index + 2] == b"\x1b\\":
                        index += 2
                        break
                    index += 1
                continue
            index += 2
            continue
        if value in (9, 10, 13):
            out.append(0x20)
        elif 0x20 <= value <= 0x7E:
            out.append(value)
        index += 1
    return re.sub(rb"\s+", b" ", bytes(out))


def mode_response_re(mode: int) -> re.Pattern[bytes]:
    return re.compile(rb"\x1b\[\?" + str(mode).encode("ascii") + rb";([0-4])\$y")


def read_query_response(
    stdin_fd: int,
    expected: re.Pattern[bytes],
    timeout: float = QUERY_TIMEOUT_SECONDS,
) -> bytes:
    payload = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        readable, _, _ = select.select([stdin_fd], [], [], max(0.0, remaining))
        if stdin_fd not in readable:
            break
        chunk = os.read(stdin_fd, 4096)
        if not chunk:
            break
        payload.extend(chunk)
        if expected.search(payload):
            while True:
                readable, _, _ = select.select([stdin_fd], [], [], 0)
                if stdin_fd not in readable:
                    break
                extra = os.read(stdin_fd, 4096)
                if not extra:
                    break
                payload.extend(extra)
            break

    raw = bytes(payload)
    if raw:
        unexpected, incomplete, _count, _forwarded = classify_terminal_input(raw)
        if unexpected or incomplete:
            raise RuntimeError("physical terminal query mixed with operator input")
    return raw


def query_physical_terminal_state(stdin_fd: int, stdout_fd: int) -> dict[str, object]:
    modes: dict[int, int | None] = {}
    for mode in PHYSICAL_MODE_IDS:
        expected = mode_response_re(mode)
        os.write(stdout_fd, f"\x1b[?{mode}$p".encode("ascii"))
        raw = read_query_response(stdin_fd, expected)
        match = expected.search(raw)
        modes[mode] = int(match.group(1)) if match else None

    os.write(stdout_fd, b"\x1b[?u")
    raw = read_query_response(stdin_fd, KITTY_FLAGS_RE)
    match = KITTY_FLAGS_RE.search(raw)
    kitty_flags = int(match.group(1)) if match else None

    for critical in CRITICAL_PHYSICAL_MODES:
        if modes.get(critical) is None:
            raise RuntimeError(f"physical terminal mode {critical} is not queryable")
    if kitty_flags is None:
        raise RuntimeError("physical terminal kitty keyboard flags are not queryable")

    return {"modes": modes, "kitty_flags": kitty_flags}


def restore_physical_terminal_state(stdout_fd: int, baseline: dict[str, object]) -> None:
    modes = baseline["modes"]
    if not isinstance(modes, dict):
        raise RuntimeError("invalid physical terminal baseline")
    for mode, state in modes.items():
        if state == 1:
            os.write(stdout_fd, f"\x1b[?{mode}h".encode("ascii"))
        elif state == 2:
            os.write(stdout_fd, f"\x1b[?{mode}l".encode("ascii"))

    kitty_flags = baseline["kitty_flags"]
    if not isinstance(kitty_flags, int):
        raise RuntimeError("invalid kitty keyboard baseline")
    os.write(stdout_fd, f"\x1b[={kitty_flags};1u".encode("ascii"))


def terminal_state_matches(
    baseline: dict[str, object],
    observed: dict[str, object],
) -> bool:
    baseline_modes = baseline["modes"]
    observed_modes = observed["modes"]
    if not isinstance(baseline_modes, dict) or not isinstance(observed_modes, dict):
        return False
    for mode, expected in baseline_modes.items():
        if expected is None:
            continue
        if observed_modes.get(mode) != expected:
            return False
    return observed.get("kitty_flags") == baseline.get("kitty_flags")


def validate_probe_text(value: str) -> bytes:
    raw = value.encode("utf-8")
    if not raw:
        raise ValueError("empty")
    if any(value < 0x20 or value == 0x7F for value in raw):
        raise ValueError("control-byte")
    return raw


def reap_child_if_exited(pid: int) -> bool:
    try:
        waited = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True
    return waited != (0, 0)


def task_owned_session_processes(session_id: int) -> list[tuple[int, int]]:
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,pgid="],
        check=True,
        capture_output=True,
        text=True,
    )
    processes: list[tuple[int, int]] = []
    for raw in result.stdout.splitlines():
        fields = raw.split()
        if len(fields) != 2:
            continue
        try:
            pid, pgid = map(int, fields)
        except ValueError:
            continue
        try:
            sid = os.getsid(pid)
        except (ProcessLookupError, PermissionError):
            continue
        if sid == session_id:
            processes.append((pid, pgid))
    return processes


def signal_task_owned_session(session_id: int, sig: signal.Signals) -> None:
    supervisor_pgid = os.getpgrp()
    groups = sorted(
        {
            pgid
            for _pid, pgid in task_owned_session_processes(session_id)
            if pgid > 0 and pgid != supervisor_pgid
        }
    )
    for pgid in groups:
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass


def wait_for_session_closed(pid: int, session_id: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reap_child_if_exited(pid)
        if not task_owned_session_processes(session_id):
            return True
        time.sleep(0.02)
    reap_child_if_exited(pid)
    return not task_owned_session_processes(session_id)


def terminate_task_owned_session(pid: int, session_id: int) -> None:
    if session_id == os.getsid(0):
        raise RuntimeError("child shares supervisor session")
    signal_task_owned_session(session_id, signal.SIGTERM)
    if wait_for_session_closed(pid, session_id, TERM_GRACE_SECONDS):
        return
    signal_task_owned_session(session_id, signal.SIGKILL)
    if not wait_for_session_closed(pid, session_id, TERM_GRACE_SECONDS):
        raise RuntimeError("task-owned PTY session did not terminate")


def spawn_child(argv: list[str]) -> tuple[int, int]:
    master_fd, slave_fd = pty.openpty()
    ready_read, ready_write = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(master_fd)
            os.close(ready_read)
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            for target_fd in (0, 1, 2):
                if slave_fd != target_fd:
                    os.dup2(slave_fd, target_fd)
            if slave_fd > 2:
                os.close(slave_fd)
            os.write(ready_write, b"1")
            os.close(ready_write)
            os.execvpe(argv[0], argv, os.environ.copy())
        except BaseException:
            try:
                os.write(ready_write, b"0")
            except OSError:
                pass
            os._exit(127)

    os.close(slave_fd)
    os.close(ready_write)
    try:
        ready = os.read(ready_read, 1)
    finally:
        os.close(ready_read)
    if ready != b"1":
        try:
            os.waitpid(pid, 0)
        finally:
            os.close(master_fd)
        raise RuntimeError("child PTY session setup failed")
    return pid, master_fd


def supervise(argv: list[str], probe_text: str) -> int:
    if not argv:
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:COMMAND_REQUIRED", file=sys.stderr)
        return 64
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:INTERACTIVE_TTY_REQUIRED", file=sys.stderr)
        return 2

    try:
        probe_bytes = validate_probe_text(probe_text)
    except ValueError as exc:
        print(f"CLAUDE_TTY_SUPERVISOR_BLOCKED:INVALID_PROBE_TEXT:{exc}", file=sys.stderr)
        return 64

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    saved = termios.tcgetattr(stdin_fd)
    pid = -1
    master_fd = -1
    child_session: int | None = None
    baseline_state: dict[str, object] | None = None
    probe_injected = False
    composer_ready_seen = False
    observation_window_completed = False
    terminal_responses_forwarded = 0
    terminal_response_bytes_forwarded = 0
    physical_terminal_state_restored = False
    pending_input = b""
    pending_since: float | None = None
    blocked_reason: str | None = None
    output_tail = bytearray()
    ready_deadline = time.monotonic() + COMPOSER_READY_TIMEOUT_SECONDS
    observation_deadline: float | None = None

    try:
        tty.setraw(stdin_fd)
        baseline_state = query_physical_terminal_state(stdin_fd, stdout_fd)
        termios.tcflush(stdin_fd, termios.TCIFLUSH)

        pid, master_fd = spawn_child(argv)
        child_session = os.getsid(pid)
        if child_session == os.getsid(0):
            raise RuntimeError("child PTY session is not task-owned")

        os.write(
            stdout_fd,
            b"\r\n[CLROOM release probe: automatic non-submitting probe; bounded observation window; do not type]\r\n",
        )

        while True:
            now = time.monotonic()
            deadlines: list[float] = []
            if pending_input and pending_since is not None:
                deadlines.append(pending_since + INPUT_SEQUENCE_TIMEOUT_SECONDS)
            if not probe_injected:
                deadlines.append(ready_deadline)
            elif observation_deadline is not None:
                deadlines.append(observation_deadline)
            timeout = max(0.0, min(deadlines) - now) if deadlines else None

            readable, _, _ = select.select([stdin_fd, master_fd], [], [], timeout)
            now = time.monotonic()

            if not readable:
                if pending_input and pending_since is not None and now >= pending_since + INPUT_SEQUENCE_TIMEOUT_SECONDS:
                    blocked_reason = "UNEXPECTED_OPERATOR_INPUT"
                    break
                if not probe_injected and now >= ready_deadline:
                    blocked_reason = "COMPOSER_READY_TIMEOUT"
                    break
                if probe_injected and observation_deadline is not None and now >= observation_deadline:
                    observation_window_completed = True
                    break
                continue

            if master_fd in readable:
                try:
                    data = os.read(master_fd, 65536)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        data = b""
                    else:
                        raise
                if not data:
                    break
                os.write(stdout_fd, data)
                output_tail.extend(data)
                if len(output_tail) > OUTPUT_TAIL_LIMIT:
                    del output_tail[:-OUTPUT_TAIL_LIMIT]
                if not probe_injected and READY_MARKER in visible_text(bytes(output_tail)):
                    composer_ready_seen = True
                    os.write(master_fd, probe_bytes)
                    probe_injected = True
                    observation_deadline = time.monotonic() + OBSERVATION_WINDOW_SECONDS

            if stdin_fd in readable:
                chunk = os.read(stdin_fd, 4096)
                if not chunk:
                    blocked_reason = "OPERATOR_TTY_EOF"
                    break
                if not pending_input:
                    pending_since = time.monotonic()
                pending_input += chunk
                unexpected, incomplete, response_count, response_bytes = classify_terminal_input(pending_input)
                if unexpected:
                    blocked_reason = "UNEXPECTED_OPERATOR_INPUT"
                    break
                if incomplete:
                    continue
                pending_input = b""
                pending_since = None
                if response_bytes:
                    os.write(master_fd, response_bytes)
                    terminal_responses_forwarded += response_count
                    terminal_response_bytes_forwarded += len(response_bytes)

    except RuntimeError as exc:
        if blocked_reason is None:
            blocked_reason = "PHYSICAL_TERMINAL_STATE:" + str(exc).replace(" ", "_")
    finally:
        if master_fd >= 0:
            try:
                os.close(master_fd)
            except OSError:
                pass
            master_fd = -1

        if pid > 0 and child_session is not None:
            try:
                terminate_task_owned_session(pid, child_session)
            except ProcessLookupError:
                pass
            except RuntimeError:
                if blocked_reason is None:
                    blocked_reason = "TASK_SESSION_TEARDOWN"

        if baseline_state is not None:
            try:
                termios.tcflush(stdin_fd, termios.TCIFLUSH)
                restore_physical_terminal_state(stdout_fd, baseline_state)
                termios.tcdrain(stdout_fd)
                termios.tcflush(stdin_fd, termios.TCIFLUSH)
                observed_state = query_physical_terminal_state(stdin_fd, stdout_fd)
                if not terminal_state_matches(baseline_state, observed_state):
                    raise RuntimeError("post-teardown physical terminal state differs from baseline")
                physical_terminal_state_restored = True
                termios.tcflush(stdin_fd, termios.TCIFLUSH)
            except (OSError, RuntimeError):
                if blocked_reason is None:
                    blocked_reason = "PHYSICAL_TERMINAL_STATE_RESTORE"

        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, saved)

    sys.stdout.write("\n")
    sys.stdout.flush()

    print(f"COMPOSER_READY_SEEN={'YES' if composer_ready_seen else 'NO'}")
    print(f"PROBE_INJECTED={'YES' if probe_injected else 'NO'}")
    print(f"OBSERVATION_WINDOW_COMPLETED={'YES' if observation_window_completed else 'NO'}")
    print(f"TERMINAL_RESPONSES_FORWARDED={terminal_responses_forwarded}")
    print(f"TERMINAL_RESPONSE_BYTES_FORWARDED={terminal_response_bytes_forwarded}")
    print(f"PHYSICAL_TERMINAL_STATE_RESTORED={'YES' if physical_terminal_state_restored else 'NO'}")
    print("HUMAN_BYTES_FORWARDED=0")
    print("HUMAN_CONTROL_ACTIONS_REQUIRED=0")
    print("SUBMIT_BYTES_FORWARDED=0")
    print("HARNESS_STOP_FORWARDED=0")

    if blocked_reason is not None:
        print(f"CLAUDE_TTY_SUPERVISOR_BLOCKED:{blocked_reason}", file=sys.stderr)
        return 3
    if not composer_ready_seen:
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:COMPOSER_NOT_READY", file=sys.stderr)
        return 4
    if not probe_injected:
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:PROBE_NOT_INJECTED", file=sys.stderr)
        return 5
    if not observation_window_completed:
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:PROVIDER_EXITED_BEFORE_OBSERVATION_COMPLETE", file=sys.stderr)
        return 6
    if not physical_terminal_state_restored:
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:PHYSICAL_TERMINAL_STATE_NOT_RESTORED", file=sys.stderr)
        return 7

    print("CLAUDE_TTY_SUPERVISOR=PASS")
    print("TASK_PROCESS_SESSION_CLOSED=YES")
    return 0

def self_test() -> int:
    def expect_terminal(
        raw: bytes,
        expected: tuple[bool, bool, int, bytes],
        label: str,
    ) -> None:
        observed = classify_terminal_input(raw)
        if observed != expected:
            raise SystemExit(
                f"CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:TERMINAL_PROTOCOL_FILTER:{label}:"
                f"expected={expected}:observed={observed}"
            )

    da1 = b"\x1b[?64;1;2;4;6;17;18;21;22;52c"
    kitty = b"\x1b[?0u"
    da2 = b"\x1b[>0;95;0c"
    cursor = b"\x1b[?24;80R"
    decrpm = b"\x1b[?2026;1$y"
    focus_in = b"\x1b[I"
    focus_out = b"\x1b[O"
    osc10 = b"\x1b]10;rgb:ffff/ffff/ffff\x07"
    osc11 = b"\x1b]11;rgb:0000/0000/0000\x1b\\"
    xtversion = b"\x1bP>|iTerm2 3.6.5\x1b\\"

    for label, raw in (
        ("DA1", da1),
        ("KITTY_FLAGS", kitty),
        ("DA2", da2),
        ("CURSOR", cursor),
        ("DECRPM", decrpm),
        ("FOCUS_IN", focus_in),
        ("FOCUS_OUT", focus_out),
        ("OSC10", osc10),
        ("OSC11", osc11),
        ("XTVERSION", xtversion),
    ):
        expect_terminal(raw, (False, False, 1, raw), label)

    expect_terminal(da1[:10], (False, True, 0, b""), "DA1_FRAGMENT")
    expect_terminal(b"\x1b[", (False, True, 0, b""), "FOCUS_FRAGMENT")
    expect_terminal(osc11[:-1], (False, True, 0, b""), "OSC_FRAGMENT")
    expect_terminal(xtversion[:-1], (False, True, 0, b""), "DCS_FRAGMENT")
    expect_terminal(kitty + focus_out + da1, (False, False, 3, kitty + focus_out + da1), "MULTI_MACHINE_INPUT")

    for label, raw in (
        ("PRINTABLE", b"x"),
        ("CTRL_T", b"\x14"),
        ("CTRL_G", b"\x07"),
        ("ARROW", b"\x1b[A"),
        ("CSI_U_KEY", b"\x1b[116;5u"),
    ):
        unexpected, incomplete, _count, _forwarded = classify_terminal_input(raw)
        if not unexpected or incomplete:
            raise SystemExit(
                f"CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:HUMAN_INPUT_ACCEPTED:{label}"
            )

    styled_ready = (
        b"\x1b[2mstatus\x1b[0m: "
        b"\x1b[33mmanual\x1b[0m mode "
        b"\x1b[1mon\x1b[0m"
    )
    if READY_MARKER not in visible_text(styled_ready):
        raise SystemExit("CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:ANSI_READY_MARKER")

    baseline = {
        "modes": {1: 2, 1004: 2, 2004: 2, 2026: 1},
        "kitty_flags": 0,
    }
    same = {
        "modes": {1: 2, 1004: 2, 2004: 2, 2026: 1},
        "kitty_flags": 0,
    }
    changed = {
        "modes": {1: 2, 1004: 1, 2004: 2, 2026: 1},
        "kitty_flags": 0,
    }
    if not terminal_state_matches(baseline, same):
        raise SystemExit("CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:TERMINAL_STATE_EQUALITY")
    if terminal_state_matches(baseline, changed):
        raise SystemExit("CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:TERMINAL_STATE_DRIFT")

    if validate_probe_text("/frontend-design") != b"/frontend-design":
        raise SystemExit("CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:PROBE_TEXT")
    for unsafe in ("", "x\r", "x\n"):
        try:
            validate_probe_text(unsafe)
        except ValueError:
            pass
        else:
            raise SystemExit("CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:PROBE_CONTROL")

    split_group_child = """
import os
import signal
import time

child = os.fork()
if child == 0:
    os.setpgid(0, 0)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(30)
    raise SystemExit(0)

signal.signal(signal.SIGHUP, signal.SIG_IGN)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
os.waitpid(child, 0)
"""
    pid, master_fd = spawn_child([sys.executable, "-c", split_group_child])
    try:
        session_id = os.getsid(pid)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            groups = {pgid for _pid, pgid in task_owned_session_processes(session_id)}
            if len(groups) >= 2:
                break
            time.sleep(0.02)
        else:
            raise SystemExit("CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SPLIT_PROCESS_GROUP")

        terminate_task_owned_session(pid, session_id)
        if task_owned_session_processes(session_id):
            raise SystemExit("CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SESSION_RESIDUE")
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass

    print("CLAUDE_TTY_SUPERVISOR_SELF_TEST_PASS")
    return 0

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--probe-text")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    if args.probe_text is None:
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:PROBE_TEXT_REQUIRED", file=sys.stderr)
        return 64
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    return supervise(command, args.probe_text)


if __name__ == "__main__":
    raise SystemExit(main())
