#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import os
import pty
import select
import signal
import sys
import termios
import time
import tty

STOP_BYTE = 0x1D  # Ctrl+]
SUBMIT_BYTES = {0x0A, 0x0D}  # LF / CR
FORBIDDEN_PROVIDER_CONTROL_BYTES = {0x03, 0x04, 0x1B}  # Ctrl+C / Ctrl+D / Escape
TERM_GRACE_SECONDS = 2.0


def filter_operator_input(data: bytes) -> tuple[bytes, str | None]:
    forwarded = bytearray()
    for value in data:
        if value == STOP_BYTE:
            return bytes(forwarded), "stop"
        if value in SUBMIT_BYTES:
            return bytes(forwarded), "submit"
        if value in FORBIDDEN_PROVIDER_CONTROL_BYTES:
            return bytes(forwarded), "provider-control"
        forwarded.append(value)
    return bytes(forwarded), None


def wait_for_child(pid: int, timeout: float) -> tuple[int, int] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        waited = os.waitpid(pid, os.WNOHANG)
        if waited != (0, 0):
            return waited
        time.sleep(0.02)
    return None


def terminate_task_owned_group(pid: int) -> None:
    pgid = os.getpgid(pid)
    if pgid == os.getpgrp():
        raise RuntimeError("child shares supervisor process group")
    os.killpg(pgid, signal.SIGTERM)
    if wait_for_child(pid, TERM_GRACE_SECONDS) is not None:
        return
    os.killpg(pgid, signal.SIGKILL)
    if wait_for_child(pid, TERM_GRACE_SECONDS) is None:
        raise RuntimeError("child process group did not terminate")


def spawn_child(argv: list[str]) -> tuple[int, int]:
    pid, master_fd = pty.fork()
    if pid == 0:
        os.execvpe(argv[0], argv, os.environ.copy())
        raise AssertionError("unreachable")
    return pid, master_fd


def supervise(argv: list[str]) -> int:
    if not argv:
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:COMMAND_REQUIRED", file=sys.stderr)
        return 64
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:INTERACTIVE_TTY_REQUIRED", file=sys.stderr)
        return 2

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    saved = termios.tcgetattr(stdin_fd)
    pid = -1
    master_fd = -1
    stop_seen = False
    blocked_reason: str | None = None

    try:
        pid, master_fd = spawn_child(argv)
        child_pgid = os.getpgid(pid)
        if child_pgid == os.getpgrp():
            raise RuntimeError("child process group is not task-owned")

        tty.setraw(stdin_fd)

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
                forwarded, event = filter_operator_input(data)
                if forwarded:
                    os.write(master_fd, forwarded)
                if event == "stop":
                    stop_seen = True
                    break
                if event == "submit":
                    blocked_reason = "SUBMIT_INPUT_ATTEMPTED"
                    break
                if event == "provider-control":
                    blocked_reason = "PROVIDER_CONTROL_INPUT_ATTEMPTED"
                    break

        if pid > 0:
            try:
                terminate_task_owned_group(pid)
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

    if blocked_reason is not None:
        print(f"CLAUDE_TTY_SUPERVISOR_BLOCKED:{blocked_reason}", file=sys.stderr)
        print("SUBMIT_BYTES_FORWARDED=0")
        print("HARNESS_STOP_FORWARDED=0")
        return 3

    if not stop_seen:
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:PROVIDER_EXITED_BEFORE_HARNESS_STOP", file=sys.stderr)
        print("SUBMIT_BYTES_FORWARDED=0")
        print("HARNESS_STOP_FORWARDED=0")
        return 4

    print("CLAUDE_TTY_SUPERVISOR=PASS")
    print("SUBMIT_BYTES_FORWARDED=0")
    print("HARNESS_STOP_FORWARDED=0")
    print("TASK_PROCESS_GROUP_CLOSED=YES")
    return 0


def self_test() -> int:
    cases = [
        (b"/frontend-design", b"/frontend-design", None),
        (b"abc\rrest", b"abc", "submit"),
        (b"abc\nrest", b"abc", "submit"),
        (b"abc\x1drest", b"abc", "stop"),
        (b"abc\x03rest", b"abc", "provider-control"),
        (b"abc\x04rest", b"abc", "provider-control"),
        (b"abc\x1brest", b"abc", "provider-control"),
    ]
    for raw, expected_forwarded, expected_event in cases:
        forwarded, event = filter_operator_input(raw)
        if forwarded != expected_forwarded or event != expected_event:
            raise SystemExit("CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:FILTER")

    pid, master_fd = spawn_child(["/bin/sh", "-c", "sleep 30 & wait"])
    try:
        time.sleep(0.05)
        terminate_task_owned_group(pid)
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
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    return supervise(command)


if __name__ == "__main__":
    raise SystemExit(main())
