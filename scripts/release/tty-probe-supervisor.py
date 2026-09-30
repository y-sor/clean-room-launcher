#!/usr/bin/env python3
"""Release-only supervised interactive TTY probe.

Human input is never forwarded to the provider. Ctrl+T asks the harness to inject
one exact non-submitting probe string; Ctrl+G ends observation and is intercepted
before the provider. Teardown targets only the task-owned PTY child process group.
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

INJECT_BYTE = 0x14  # Ctrl+T
STOP_BYTE = 0x07  # Ctrl+G
TERM_TIMEOUT_SECONDS = 2.0


def classify_input(data: bytes) -> tuple[bool, bool, bool]:
    inject_requested = False
    stop_requested = False
    unexpected_input = False
    for value in data:
        if value == INJECT_BYTE:
            inject_requested = True
        elif value == STOP_BYTE:
            stop_requested = True
        else:
            unexpected_input = True
    return inject_requested, stop_requested, unexpected_input


def validate_probe_text(value: str) -> bytes:
    raw = value.encode("utf-8")
    if not raw:
        raise ValueError("empty")
    if any(byte < 0x20 or byte == 0x7F for byte in raw):
        raise ValueError("control-byte")
    return raw


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
    inject, stop, unexpected = classify_input(bytes([INJECT_BYTE]))
    if not inject or stop or unexpected:
        raise SystemExit("TTY_SUPERVISOR_SELF_TEST_FAIL:INJECT")
    inject, stop, unexpected = classify_input(bytes([STOP_BYTE]))
    if inject or not stop or unexpected:
        raise SystemExit("TTY_SUPERVISOR_SELF_TEST_FAIL:STOP")
    inject, stop, unexpected = classify_input(b"x\r\n")
    if inject or stop or not unexpected:
        raise SystemExit("TTY_SUPERVISOR_SELF_TEST_FAIL:UNEXPECTED_INPUT")
    if validate_probe_text("/frontend-design") != b"/frontend-design":
        raise SystemExit("TTY_SUPERVISOR_SELF_TEST_FAIL:PROBE_TEXT")
    for unsafe in ("", "x\n", "x\r"):
        try:
            validate_probe_text(unsafe)
        except ValueError:
            pass
        else:
            raise SystemExit("TTY_SUPERVISOR_SELF_TEST_FAIL:PROBE_CONTROL")
    print("TTY_SUPERVISOR_SELF_TEST=PASS")
    return 0


def supervise(argv: list[str], probe_text: str) -> int:
    if not argv:
        raise SystemExit("TTY_SUPERVISOR_USAGE: command required after --")
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise SystemExit("TTY_SUPERVISOR_BLOCKED:INTERACTIVE_TTY_REQUIRED")
    try:
        probe_bytes = validate_probe_text(probe_text)
    except ValueError as exc:
        raise SystemExit(f"TTY_SUPERVISOR_BLOCKED:INVALID_PROBE_TEXT:{exc}") from exc

    child_pid, master_fd = pty.fork()
    if child_pid == 0:
        os.execvp(argv[0], argv)

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    previous = termios.tcgetattr(stdin_fd)
    injected = False
    stop_requested = False
    unexpected_input = False
    child_exited_early = False
    child_status: int | None = None

    try:
        tty.setraw(stdin_fd, when=termios.TCSANOW)
        os.write(
            stdout_fd,
            b"\r\n[CLROOM release probe: Ctrl+T injects the fixed probe; Ctrl+G ends observation; all other human input is blocked]\r\n",
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
                inject, stop, unexpected = classify_input(data)
                unexpected_input = unexpected_input or unexpected
                if unexpected:
                    os.write(
                        stdout_fd,
                        b"\r\n[CLROOM probe blocked unexpected human input; this observation is invalid]\r\n",
                    )
                if inject:
                    if injected:
                        unexpected_input = True
                        os.write(
                            stdout_fd,
                            b"\r\n[CLROOM probe injection already performed; this observation is invalid]\r\n",
                        )
                    else:
                        os.write(master_fd, probe_bytes)
                        injected = True
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
    print(f"TTY_SUPERVISOR_PROBE_INJECTED={'YES' if injected else 'NO'}")
    print(f"TTY_SUPERVISOR_STOP_INTERCEPTED={'YES' if stop_requested else 'NO'}")
    print("TTY_SUPERVISOR_HUMAN_BYTES_FORWARDED=0")
    print("TTY_SUPERVISOR_SUBMIT_BYTES_FORWARDED=0")
    print(f"TTY_SUPERVISOR_UNEXPECTED_INPUT={'YES' if unexpected_input else 'NO'}")
    print(f"TTY_SUPERVISOR_CHILD_CLOSED={'YES' if done else 'NO'}")
    print(f"TTY_SUPERVISOR_TEARDOWN={teardown}")

    if unexpected_input:
        return 65
    if not injected:
        return 66
    if not stop_requested:
        return 67
    if not done:
        return 68
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--probe-text")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.probe_text is None:
        raise SystemExit("TTY_SUPERVISOR_USAGE: --probe-text is required")

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    return supervise(command, args.probe_text)


if __name__ == "__main__":
    raise SystemExit(main())
