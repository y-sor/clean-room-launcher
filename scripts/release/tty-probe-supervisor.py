#!/usr/bin/env python3
"""Release-only supervised interactive TTY probe.

The supervisor keeps provider UI observation interactive while owning two safety
properties that must not depend on provider UX:
- submit bytes are never forwarded;
- teardown is triggered by a harness-owned stop chord (Ctrl+]) and targets only
  the task-owned PTY child process group.
"""

from __future__ import annotations

import argparse
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
TERM_TIMEOUT_SECONDS = 2.0


def filter_input(data: bytes) -> tuple[bytes, bool, bool]:
    forwarded = bytearray()
    submit_attempted = False
    stop_requested = False
    for value in data:
        if value in SUBMIT_BYTES:
            submit_attempted = True
            continue
        if value == STOP_BYTE:
            stop_requested = True
            continue
        if not stop_requested:
            forwarded.append(value)
    return bytes(forwarded), submit_attempted, stop_requested


def wait_child(pid: int, timeout: float) -> tuple[bool, int | None]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        waited, status = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            return True, status
        time.sleep(0.05)
    return False, None


def terminate_child_group(pid: int) -> tuple[bool, str]:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        done, status = wait_child(pid, 0)
        return done, f"already-exited:{status}"

    done, status = wait_child(pid, TERM_TIMEOUT_SECONDS)
    if done:
        return True, f"sigterm:{status}"

    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    done, status = wait_child(pid, TERM_TIMEOUT_SECONDS)
    return done, f"sigkill:{status}"


def self_test() -> int:
    forwarded, submit, stop = filter_input(b"abc\rdef\nxyz\x1dignored")
    if forwarded != b"abcdefxyz" or not submit or not stop:
        raise SystemExit("TTY_SUPERVISOR_SELF_TEST_FAIL:FILTER")
    forwarded, submit, stop = filter_input(b"frontend-design")
    if forwarded != b"frontend-design" or submit or stop:
        raise SystemExit("TTY_SUPERVISOR_SELF_TEST_FAIL:PASS_THROUGH")
    forwarded, submit, stop = filter_input(b"abc\x1ddef")
    if forwarded != b"abc" or submit or not stop:
        raise SystemExit("TTY_SUPERVISOR_SELF_TEST_FAIL:STOP_NOT_TERMINAL")
    print("TTY_SUPERVISOR_SELF_TEST=PASS")
    return 0


def supervise(argv: list[str]) -> int:
    if not argv:
        raise SystemExit("TTY_SUPERVISOR_USAGE: command required after --")
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise SystemExit("TTY_SUPERVISOR_BLOCKED:INTERACTIVE_TTY_REQUIRED")

    child_pid, master_fd = pty.fork()
    if child_pid == 0:
        os.execvp(argv[0], argv)

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    previous = termios.tcgetattr(stdin_fd)
    submit_attempted = False
    stop_requested = False
    child_exited_early = False
    child_status: int | None = None

    try:
        tty.setraw(stdin_fd, when=termios.TCSANOW)
        os.write(
            stdout_fd,
            b"\r\n[CLROOM release probe: Enter is blocked; Ctrl+] ends observation]\r\n",
        )

        while not stop_requested:
            ready, _, _ = select.select([stdin_fd, master_fd], [], [])
            if master_fd in ready:
                try:
                    output = os.read(master_fd, 65536)
                except OSError:
                    output = b""
                if output:
                    os.write(stdout_fd, output)
                else:
                    child_exited_early = True
                    break

            if stdin_fd in ready:
                data = os.read(stdin_fd, 4096)
                forwarded, attempted, stop = filter_input(data)
                submit_attempted = submit_attempted or attempted
                if attempted:
                    os.write(
                        stdout_fd,
                        b"\r\n[CLROOM probe blocked Enter; this observation is invalid]\r\n",
                    )
                if forwarded:
                    os.write(master_fd, forwarded)
                if stop:
                    stop_requested = True
                    break
    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, previous)

    if child_exited_early:
        done, child_status = wait_child(child_pid, 0)
        if not done:
            done, teardown = terminate_child_group(child_pid)
        else:
            teardown = f"provider-exited:{child_status}"
    else:
        done, teardown = terminate_child_group(child_pid)

    print()
    print(f"TTY_SUPERVISOR_STOP_INTERCEPTED={'YES' if stop_requested else 'NO'}")
    print("TTY_SUPERVISOR_SUBMIT_BYTES_FORWARDED=0")
    print(f"TTY_SUPERVISOR_SUBMIT_ATTEMPTED={'YES' if submit_attempted else 'NO'}")
    print(f"TTY_SUPERVISOR_CHILD_CLOSED={'YES' if done else 'NO'}")
    print(f"TTY_SUPERVISOR_TEARDOWN={teardown}")

    if submit_attempted:
        return 65
    if not stop_requested:
        return 66
    if not done:
        return 67
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    return supervise(command)


if __name__ == "__main__":
    raise SystemExit(main())
