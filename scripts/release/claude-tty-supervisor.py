#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import os
import pty
import select
import signal
import subprocess
import sys
import termios
import time
import tty

INJECT_BYTE = 0x14  # Ctrl+T
STOP_BYTE = 0x07  # Ctrl+G
TERM_GRACE_SECONDS = 2.0


def classify_operator_input(data: bytes) -> tuple[bool, bool, bool]:
    inject = False
    stop = False
    unexpected = False
    for value in data:
        if value == INJECT_BYTE:
            inject = True
        elif value == STOP_BYTE:
            stop = True
        else:
            unexpected = True
    return inject, stop, unexpected


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
    pid, master_fd = pty.fork()
    if pid == 0:
        os.execvpe(argv[0], argv, os.environ.copy())
        raise AssertionError("unreachable")
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
    stop_seen = False
    probe_injected = False
    blocked_reason: str | None = None

    try:
        pid, master_fd = spawn_child(argv)
        child_session = os.getsid(pid)
        if child_session == os.getsid(0):
            raise RuntimeError("child PTY session is not task-owned")

        tty.setraw(stdin_fd)
        os.write(
            stdout_fd,
            b"\r\n[CLROOM release probe: Ctrl+T injects the fixed probe; Ctrl+G ends observation; all other human input is blocked]\r\n",
        )

        while True:
            readable, _, _ = select.select([stdin_fd, master_fd], [], [])

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

            if stdin_fd in readable:
                data = os.read(stdin_fd, 4096)
                if not data:
                    blocked_reason = "OPERATOR_TTY_EOF"
                    break

                inject, stop, unexpected = classify_operator_input(data)
                if unexpected:
                    blocked_reason = "UNEXPECTED_OPERATOR_INPUT"
                    break
                if inject:
                    if probe_injected:
                        blocked_reason = "PROBE_ALREADY_INJECTED"
                        break
                    os.write(master_fd, probe_bytes)
                    probe_injected = True
                if stop:
                    stop_seen = True
                    break

        if master_fd >= 0:
            try:
                os.close(master_fd)
            except OSError:
                pass
            master_fd = -1

        if pid > 0:
            try:
                terminate_task_owned_session(pid, child_session)
            except ProcessLookupError:
                pass

    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, saved)
        if master_fd >= 0:
            try:
                os.close(master_fd)
            except OSError:
                pass

    sys.stdout.write("\n")
    sys.stdout.flush()

    print(f"PROBE_INJECTED={'YES' if probe_injected else 'NO'}")
    print("HUMAN_BYTES_FORWARDED=0")
    print("SUBMIT_BYTES_FORWARDED=0")
    print("HARNESS_STOP_FORWARDED=0")

    if blocked_reason is not None:
        print(f"CLAUDE_TTY_SUPERVISOR_BLOCKED:{blocked_reason}", file=sys.stderr)
        return 3
    if not probe_injected:
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:PROBE_NOT_INJECTED", file=sys.stderr)
        return 4
    if not stop_seen:
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:PROVIDER_EXITED_BEFORE_HARNESS_STOP", file=sys.stderr)
        return 5

    print("CLAUDE_TTY_SUPERVISOR=PASS")
    print("TASK_PROCESS_SESSION_CLOSED=YES")
    return 0


def self_test() -> int:
    cases = [
        (bytes([INJECT_BYTE]), (True, False, False)),
        (bytes([STOP_BYTE]), (False, True, False)),
        (b"x", (False, False, True)),
        (b"\r", (False, False, True)),
        (b"\n", (False, False, True)),
        (b"\x1b", (False, False, True)),
    ]
    for raw, expected in cases:
        if classify_operator_input(raw) != expected:
            raise SystemExit("CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:FILTER")

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
