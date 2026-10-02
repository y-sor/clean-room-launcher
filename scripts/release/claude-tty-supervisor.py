#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import hashlib
import json
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
import unicodedata

TERM_GRACE_SECONDS = 2.0
INPUT_SEQUENCE_TIMEOUT_SECONDS = 0.5
COMPOSER_READY_TIMEOUT_SECONDS = 20.0
OBSERVATION_WINDOW_SECONDS = 8.0
QUERY_TIMEOUT_SECONDS = 0.35
READY_MARKER = b"manual mode on"
READY_STATUS_TOKENS = (b"manual mode", b"shortcuts", b"/effort")
SCREEN_MAX_ROWS = 200
SCREEN_MAX_COLS = 512
SCREEN_MAX_SEQUENCE_BYTES = 8192

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
STANDARD_CPR_RE = re.compile(rb"\x1b\[[0-9]+;[0-9]+R")
STANDARD_CPR_QUERY = b"\x1b[6n"


def terminal_response_length(data: bytes, allow_standard_cpr: bool = False) -> int:
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
                if allow_standard_cpr and STANDARD_CPR_RE.fullmatch(sequence):
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


def classify_terminal_input(
    data: bytes,
    standard_cpr_budget: int = 0,
) -> tuple[bool, bool, int, bytes, int]:
    """Allow only correlated terminal-generated machine traffic; human key bytes fail closed."""
    forwarded = bytearray()
    count = 0
    standard_cpr_used = 0
    offset = 0
    while offset < len(data):
        allow_standard_cpr = standard_cpr_used < standard_cpr_budget
        length = terminal_response_length(
            data[offset:],
            allow_standard_cpr=allow_standard_cpr,
        )
        if length < 0:
            return True, False, count, bytes(forwarded), standard_cpr_used
        if length == 0:
            return False, True, count, bytes(forwarded), standard_cpr_used
        sequence = data[offset : offset + length]
        if STANDARD_CPR_RE.fullmatch(sequence):
            standard_cpr_used += 1
        forwarded.extend(sequence)
        count += 1
        offset += length
    return False, False, count, bytes(forwarded), standard_cpr_used


def count_standard_cpr_queries(previous_tail: bytes, data: bytes) -> tuple[int, bytes]:
    combined = previous_tail + data
    count = combined.count(STANDARD_CPR_QUERY)
    keep = max(0, len(STANDARD_CPR_QUERY) - 1)
    tail = combined[-keep:] if keep else b""
    return count, tail


def filter_runtime_terminal_input(
    data: bytes,
    standard_cpr_budget: int = 0,
) -> tuple[bytes, int, bytes, int, int]:
    """Relay recognized terminal protocol; discard all other runtime input."""
    forwarded = bytearray()
    response_count = 0
    standard_cpr_used = 0
    dropped_bytes = 0
    offset = 0
    while offset < len(data):
        allow_standard_cpr = standard_cpr_used < standard_cpr_budget
        length = terminal_response_length(
            data[offset:],
            allow_standard_cpr=allow_standard_cpr,
        )
        if length == 0:
            return data[offset:], response_count, bytes(forwarded), standard_cpr_used, dropped_bytes
        if length < 0:
            dropped_bytes += 1
            offset += 1
            continue
        sequence = data[offset : offset + length]
        if STANDARD_CPR_RE.fullmatch(sequence):
            standard_cpr_used += 1
        forwarded.extend(sequence)
        response_count += 1
        offset += length
    return b"", response_count, bytes(forwarded), standard_cpr_used, dropped_bytes


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


class TerminalScreen:
    """Bounded fail-closed terminal screen model for composer readiness."""

    def __init__(self, rows: int = 80, cols: int = 240) -> None:
        self.rows = max(1, min(rows, SCREEN_MAX_ROWS))
        self.cols = max(1, min(cols, SCREEN_MAX_COLS))
        self.primary = self._blank_buffer()
        self.alternate = self._blank_buffer()
        self.alternate_active = False
        self.row = 0
        self.col = 0
        self.saved_primary = (0, 0)
        self.saved_alternate = (0, 0)
        self.scroll_top = 0
        self.scroll_bottom = self.rows - 1
        self.pending = bytearray()
        self.trusted = True
        self.unsupported_mutations = 0
        self.first_unsupported_identity = "NONE"
        self.first_unsupported_sha256 = "NONE"
        self._current_control_identity = "NONE"
        self._current_control_raw: bytes | None = None
        self.insert_mode = False
        self.autowrap = True
        self.last_char = " "

    def _blank_buffer(self) -> list[list[str]]:
        return [[" "] * self.cols for _ in range(self.rows)]

    @property
    def buffer(self) -> list[list[str]]:
        return self.alternate if self.alternate_active else self.primary

    def _mark_unsupported(
        self,
        identity: str | None = None,
        raw_control: bytes | None = None,
    ) -> None:
        self.trusted = False
        self.unsupported_mutations += 1
        if self.first_unsupported_identity != "NONE":
            return
        chosen_identity = identity or self._current_control_identity
        chosen_raw = raw_control if raw_control is not None else self._current_control_raw
        if re.fullmatch(r"[A-Za-z0-9_|=?;,:.+_-]{1,256}", chosen_identity or "") is None:
            chosen_identity = "INTERNAL_IDENTITY_INVALID"
            chosen_raw = None
        self.first_unsupported_identity = chosen_identity
        self.first_unsupported_sha256 = (
            hashlib.sha256(chosen_raw).hexdigest()
            if chosen_raw is not None
            else "NONE"
        )

    def _csi_identity(self, sequence: bytes) -> str:
        try:
            text = sequence.decode("ascii")
        except UnicodeDecodeError:
            return f"CSI|encoding=NONASCII|length={len(sequence)}"
        if not text:
            return "CSI|encoding=EMPTY"
        final = text[-1]
        body = text[:-1]
        prefix = ""
        while body and body[0] in "?><=":
            prefix += body[0]
            body = body[1:]
        intermediates = "".join(ch for ch in body if " " <= ch <= "/")
        params_raw = "".join(ch for ch in body if ch.isdigit() or ch == ";")
        return (
            f"CSI|prefix={prefix or '-'}|params={params_raw or '-'}|"
            f"intermediates_hex={intermediates.encode('ascii').hex() or '-'}|"
            f"final=0x{ord(final):02x}"
        )

    def _set_control_context(self, identity: str, raw_control: bytes) -> None:
        self._current_control_identity = identity
        self._current_control_raw = raw_control

    def _clear_control_context(self) -> None:
        self._current_control_identity = "NONE"
        self._current_control_raw = None

    def _clamp_cursor(self) -> None:
        self.row = max(0, min(self.row, self.rows - 1))
        self.col = max(0, min(self.col, self.cols - 1))

    def _char_width(self, value: str) -> int:
        if value == "\u200d" or unicodedata.combining(value):
            return 0
        return 2 if unicodedata.east_asian_width(value) in {"W", "F"} else 1

    def _scroll_up(self, count: int = 1) -> None:
        count = max(1, min(count, self.scroll_bottom - self.scroll_top + 1))
        for _ in range(count):
            del self.buffer[self.scroll_top]
            self.buffer.insert(self.scroll_bottom, [" "] * self.cols)

    def _scroll_down(self, count: int = 1) -> None:
        count = max(1, min(count, self.scroll_bottom - self.scroll_top + 1))
        for _ in range(count):
            del self.buffer[self.scroll_bottom]
            self.buffer.insert(self.scroll_top, [" "] * self.cols)

    def _linefeed(self) -> None:
        if self.row == self.scroll_bottom:
            self._scroll_up()
        else:
            self.row = min(self.rows - 1, self.row + 1)

    def _write_char(self, value: str) -> None:
        width = self._char_width(value)
        if width == 0:
            return
        if self.col >= self.cols:
            if self.autowrap:
                self.col = 0
                self._linefeed()
            else:
                self.col = self.cols - 1
        if width == 2 and self.col == self.cols - 1:
            self.col = 0
            self._linefeed()
        row = self.buffer[self.row]
        if self.insert_mode:
            for index in range(self.cols - 1, self.col + width - 1, -1):
                row[index] = row[index - width]
        row[self.col] = value
        if width == 2:
            row[self.col + 1] = " "
        self.last_char = value
        self.col += width
        if self.col >= self.cols:
            self.col = self.cols

    def _erase_display(self, mode: int) -> None:
        if mode in (2, 3):
            for index in range(self.rows):
                self.buffer[index] = [" "] * self.cols
            return
        if mode == 0:
            self._erase_line(0)
            for index in range(self.row + 1, self.rows):
                self.buffer[index] = [" "] * self.cols
            return
        if mode == 1:
            self._erase_line(1)
            for index in range(0, self.row):
                self.buffer[index] = [" "] * self.cols
            return
        self._mark_unsupported()

    def _erase_line(self, mode: int) -> None:
        row = self.buffer[self.row]
        if mode == 0:
            for index in range(self.col, self.cols):
                row[index] = " "
        elif mode == 1:
            for index in range(0, self.col + 1):
                row[index] = " "
        elif mode == 2:
            self.buffer[self.row] = [" "] * self.cols
        else:
            self._mark_unsupported()

    def _insert_chars(self, count: int) -> None:
        count = max(1, min(count, self.cols - self.col))
        row = self.buffer[self.row]
        for index in range(self.cols - 1, self.col + count - 1, -1):
            row[index] = row[index - count]
        for index in range(self.col, min(self.cols, self.col + count)):
            row[index] = " "

    def _delete_chars(self, count: int) -> None:
        count = max(1, min(count, self.cols - self.col))
        row = self.buffer[self.row]
        for index in range(self.col, self.cols - count):
            row[index] = row[index + count]
        for index in range(self.cols - count, self.cols):
            row[index] = " "

    def _erase_chars(self, count: int) -> None:
        count = max(1, min(count, self.cols - self.col))
        row = self.buffer[self.row]
        for index in range(self.col, min(self.cols, self.col + count)):
            row[index] = " "

    def _insert_lines(self, count: int) -> None:
        if not (self.scroll_top <= self.row <= self.scroll_bottom):
            return
        count = max(1, min(count, self.scroll_bottom - self.row + 1))
        for _ in range(count):
            del self.buffer[self.scroll_bottom]
            self.buffer.insert(self.row, [" "] * self.cols)

    def _delete_lines(self, count: int) -> None:
        if not (self.scroll_top <= self.row <= self.scroll_bottom):
            return
        count = max(1, min(count, self.scroll_bottom - self.row + 1))
        for _ in range(count):
            del self.buffer[self.row]
            self.buffer.insert(self.scroll_bottom, [" "] * self.cols)

    def _switch_alternate(self, enabled: bool, save_cursor: bool) -> None:
        if enabled == self.alternate_active:
            return
        if enabled:
            if save_cursor:
                self.saved_primary = (self.row, self.col)
            self.alternate = self._blank_buffer()
            self.alternate_active = True
            self.row = 0
            self.col = 0
        else:
            self.alternate_active = False
            if save_cursor:
                self.row, self.col = self.saved_primary
            self._clamp_cursor()
        self.scroll_top = 0
        self.scroll_bottom = self.rows - 1

    def _save_cursor(self) -> None:
        if self.alternate_active:
            self.saved_alternate = (self.row, self.col)
        else:
            self.saved_primary = (self.row, self.col)

    def _restore_cursor(self) -> None:
        if self.alternate_active:
            self.row, self.col = self.saved_alternate
        else:
            self.row, self.col = self.saved_primary
        self._clamp_cursor()

    def _params(self, raw: str, default: int = 1) -> list[int]:
        if not raw:
            return [default]
        values: list[int] = []
        for item in raw.split(";"):
            if item == "":
                values.append(default)
            elif item.isdigit():
                values.append(int(item))
            else:
                raise ValueError("non-numeric CSI parameter")
        return values

    def _handle_modes(self, raw: str, enabled: bool, private: bool) -> None:
        try:
            modes = self._params(raw, default=0)
        except ValueError:
            self._mark_unsupported()
            return
        for mode in modes:
            if private and mode in (47, 1047):
                self._switch_alternate(enabled, save_cursor=False)
            elif private and mode == 1049:
                self._switch_alternate(enabled, save_cursor=True)
            elif private and mode == 1048:
                self._save_cursor() if enabled else self._restore_cursor()
            elif not private and mode == 4:
                self.insert_mode = enabled
            elif private and mode == 7:
                self.autowrap = enabled
            elif private and mode in {
                1, 12, 25, 66, 1000, 1002, 1003, 1004, 1005, 1006, 1007,
                1015, 2004, 2026
            }:
                continue
            elif private:
                self._mark_unsupported()
            else:
                self._mark_unsupported()

    def _handle_csi(self, sequence: bytes) -> None:
        try:
            text = sequence.decode("ascii")
        except UnicodeDecodeError:
            self._mark_unsupported()
            return
        final = text[-1]
        body = text[:-1]
        prefix = ""
        while body and body[0] in "?><=":
            prefix += body[0]
            body = body[1:]
        intermediates = "".join(ch for ch in body if " " <= ch <= "/")
        params_raw = "".join(ch for ch in body if ch.isdigit() or ch == ";")

        if final == "m":
            return
        if final in {"n", "c"}:
            return
        if final == "p" and ("$" in intermediates or "?" in prefix):
            return
        if final == "u" and prefix:
            return
        if final == "q" and intermediates.strip() == "":
            return
        if final == "t":
            try:
                params = self._params(params_raw, default=0)
            except ValueError:
                self._mark_unsupported()
                return
            if params and params[0] in {13, 14, 16, 18, 19, 20, 21}:
                return
            self._mark_unsupported()
            return
        if final in {"h", "l"}:
            self._handle_modes(params_raw, final == "h", prefix == "?")
            return
        if prefix or (intermediates and final != "p"):
            self._mark_unsupported()
            return

        try:
            params = self._params(params_raw)
        except ValueError:
            self._mark_unsupported()
            return
        first = params[0] if params else 1

        if final == "A":
            self.row -= first
        elif final in {"B", "e"}:
            self.row += first
        elif final in {"C", "a"}:
            self.col += first
        elif final == "D":
            self.col -= first
        elif final == "E":
            self.row += first
            self.col = 0
        elif final == "F":
            self.row -= first
            self.col = 0
        elif final == "G" or final == chr(96):
            self.col = first - 1
        elif final == "d":
            self.row = first - 1
        elif final in {"H", "f"}:
            row = params[0] if params else 1
            col = params[1] if len(params) > 1 else 1
            self.row = row - 1
            self.col = col - 1
        elif final == "J":
            self._erase_display(0 if not params_raw else first)
        elif final == "K":
            self._erase_line(0 if not params_raw else first)
        elif final == "@":
            self._insert_chars(first)
        elif final == "P":
            self._delete_chars(first)
        elif final == "X":
            self._erase_chars(first)
        elif final == "L":
            self._insert_lines(first)
        elif final == "M":
            self._delete_lines(first)
        elif final == "S":
            self._scroll_up(first)
        elif final == "T":
            self._scroll_down(first)
        elif final == "r":
            top = params[0] if params else 1
            bottom = params[1] if len(params) > 1 else self.rows
            if not (1 <= top <= bottom <= self.rows):
                self._mark_unsupported()
                return
            self.scroll_top = top - 1
            self.scroll_bottom = bottom - 1
            self.row = self.scroll_top
            self.col = 0
        elif final == "s":
            self._save_cursor()
        elif final == "u":
            self._restore_cursor()
        elif final == "b":
            for _ in range(first):
                self._write_char(self.last_char)
        elif final in {"g", "I", "Z"}:
            if final == "I":
                self.col = min(self.cols - 1, ((self.col // 8) + first) * 8)
            elif final == "Z":
                self.col = max(0, ((max(0, self.col - 1) // 8) - first + 1) * 8)
        elif final == "p" and intermediates == "!":
            self.insert_mode = False
            self.scroll_top = 0
            self.scroll_bottom = self.rows - 1
            self.row = 0
            self.col = 0
        else:
            self._mark_unsupported()
            return
        self._clamp_cursor()

    def _utf8_length(self, first: int) -> int:
        if first < 0x80:
            return 1
        if 0xC2 <= first <= 0xDF:
            return 2
        if 0xE0 <= first <= 0xEF:
            return 3
        if 0xF0 <= first <= 0xF4:
            return 4
        return -1

    def feed(self, data: bytes) -> None:
        self.pending.extend(data)
        index = 0
        while index < len(self.pending):
            value = self.pending[index]
            if value == 0x1B:
                if index + 1 >= len(self.pending):
                    break
                kind = self.pending[index + 1]
                if kind == ord("["):
                    end = index + 2
                    while end < len(self.pending) and not (0x40 <= self.pending[end] <= 0x7E):
                        if not (0x20 <= self.pending[end] <= 0x3F):
                            bad = self.pending[end]
                            self._mark_unsupported(
                                f"CSI|parse=INVALID_BYTE|value=0x{bad:02x}",
                                bytes(self.pending[index : end + 1]),
                            )
                            end += 1
                            break
                        end += 1
                    if end >= len(self.pending):
                        break
                    sequence = bytes(self.pending[index + 2 : end + 1])
                    raw_control = b"\x1b[" + sequence
                    self._set_control_context(
                        self._csi_identity(sequence),
                        raw_control,
                    )
                    try:
                        self._handle_csi(sequence)
                    finally:
                        self._clear_control_context()
                    index = end + 1
                    continue
                if kind in (ord("]"), ord("P"), ord("_"), ord("^"), ord("X")):
                    cursor = index + 2
                    terminator = -1
                    while cursor < len(self.pending):
                        if kind == ord("]") and self.pending[cursor] == 0x07:
                            terminator = cursor + 1
                            break
                        if self.pending[cursor : cursor + 2] == b"\x1b\\":
                            terminator = cursor + 2
                            break
                        cursor += 1
                    if terminator < 0:
                        if len(self.pending) - index > SCREEN_MAX_SEQUENCE_BYTES:
                            self._mark_unsupported(
                                f"STRING|kind=0x{kind:02x}|reason=OVERFLOW"
                            )
                            index += 2
                            continue
                        break
                    index = terminator
                    continue
                if kind in b"()*+-./":
                    if index + 2 >= len(self.pending):
                        break
                    index += 3
                    continue
                if kind == ord("7"):
                    self._save_cursor()
                elif kind == ord("8"):
                    self._restore_cursor()
                elif kind == ord("D"):
                    self._linefeed()
                elif kind == ord("M"):
                    if self.row == self.scroll_top:
                        self._scroll_down()
                    else:
                        self.row = max(0, self.row - 1)
                elif kind == ord("E"):
                    self.col = 0
                    self._linefeed()
                elif kind == ord("c"):
                    self.primary = self._blank_buffer()
                    self.alternate = self._blank_buffer()
                    self.alternate_active = False
                    self.row = 0
                    self.col = 0
                    self.scroll_top = 0
                    self.scroll_bottom = self.rows - 1
                    self.insert_mode = False
                    self.autowrap = True
                elif kind in (ord("="), ord(">"), ord("H")):
                    pass
                elif kind == ord("#"):
                    if index + 2 >= len(self.pending):
                        break
                    if self.pending[index + 2] == ord("8"):
                        for row in range(self.rows):
                            self.buffer[row] = ["E"] * self.cols
                        self.row = 0
                        self.col = 0
                        index += 3
                        continue
                    self._mark_unsupported(
                        f"ESC_HASH|final=0x{self.pending[index + 2]:02x}",
                        bytes(self.pending[index : index + 3]),
                    )
                    index += 3
                    continue
                else:
                    self._mark_unsupported(
                        f"ESC|kind=0x{kind:02x}",
                        bytes(self.pending[index : index + 2]),
                    )
                index += 2
                continue

            if value == 0x0D:
                self.col = 0
                index += 1
                continue
            if value in (0x0A, 0x0B, 0x0C):
                self._linefeed()
                index += 1
                continue
            if value == 0x08:
                self.col = max(0, self.col - 1)
                index += 1
                continue
            if value == 0x09:
                self.col = min(self.cols - 1, ((self.col // 8) + 1) * 8)
                index += 1
                continue
            if value < 0x20 or value == 0x7F:
                index += 1
                continue

            length = self._utf8_length(value)
            if length < 0:
                self._mark_unsupported(
                    f"BYTE|value=0x{value:02x}",
                    bytes((value,)),
                )
                index += 1
                continue
            if index + length > len(self.pending):
                break
            raw = bytes(self.pending[index : index + length])
            try:
                decoded = raw.decode("utf-8")
            except UnicodeDecodeError:
                self._mark_unsupported(
                    f"UTF8|reason=DECODE_ERROR|length={len(raw)}",
                    raw,
                )
                index += 1
                continue
            self._write_char(decoded)
            index += length

        if index:
            del self.pending[:index]
        if len(self.pending) > SCREEN_MAX_SEQUENCE_BYTES:
            self._mark_unsupported("PENDING|reason=OVERFLOW")
            self.pending.clear()

    def rendered_rows(self) -> list[bytes]:
        return [
            re.sub(rb"\s+", b" ", "".join(row).encode("ascii", "ignore")).strip()
            for row in self.buffer
        ]

    def composer_ready_method(self) -> str | None:
        if not self.trusted or self.pending:
            return None
        for row in self.rendered_rows():
            if READY_MARKER in row:
                return "SCREEN_EXACT_MARKER"
            if all(token in row for token in READY_STATUS_TOKENS):
                return "SCREEN_STATUS_ROW"
        return None


def screen_diagnostic_record(
    screen: TerminalScreen,
    *,
    physical_terminal_state_restored: bool,
    task_process_session_closed: bool,
) -> dict[str, object]:
    return {
        "schema_version": "clroom.claude-screen-control-diagnostic.v1",
        "result": (
            "CAPTURED"
            if screen.first_unsupported_identity != "NONE"
            else "NOT_REPRODUCED"
        ),
        "unsupported_control_identity": screen.first_unsupported_identity,
        "unsupported_control_sha256": screen.first_unsupported_sha256,
        "unsupported_mutations": screen.unsupported_mutations,
        "screen_model_trusted": screen.trusted,
        "physical_terminal_state_restored": physical_terminal_state_restored,
        "task_process_session_closed": task_process_session_closed,
        "human_bytes_forwarded": 0,
        "submit_bytes_forwarded": 0,
        "raw_terminal_transcript_recorded": False,
    }


def write_screen_diagnostic(
    path: str,
    screen: TerminalScreen,
    *,
    physical_terminal_state_restored: bool,
    task_process_session_closed: bool,
) -> None:
    record = screen_diagnostic_record(
        screen,
        physical_terminal_state_restored=physical_terminal_state_restored,
        task_process_session_closed=task_process_session_closed,
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True, indent=2)
        handle.write("\n")


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
        unexpected, incomplete, _count, _forwarded, _standard_cpr_used = classify_terminal_input(raw)
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


def supervise(
    argv: list[str],
    probe_text: str | None,
    *,
    diagnose_unsupported: bool = False,
    diagnostic_evidence: str | None = None,
) -> int:
    if not argv:
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:COMMAND_REQUIRED", file=sys.stderr)
        return 64
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:INTERACTIVE_TTY_REQUIRED", file=sys.stderr)
        return 2

    if diagnose_unsupported:
        probe_bytes = b""
    else:
        if probe_text is None:
            print("CLAUDE_TTY_SUPERVISOR_BLOCKED:PROBE_TEXT_REQUIRED", file=sys.stderr)
            return 64
        try:
            probe_bytes = validate_probe_text(probe_text)
        except ValueError as exc:
            print(f"CLAUDE_TTY_SUPERVISOR_BLOCKED:INVALID_PROBE_TEXT:{exc}", file=sys.stderr)
            return 64

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    saved = termios.tcgetattr(stdin_fd)
    terminal_size = os.get_terminal_size(stdin_fd)
    screen = TerminalScreen(rows=terminal_size.lines, cols=terminal_size.columns)
    pid = -1
    master_fd = -1
    child_session: int | None = None
    baseline_state: dict[str, object] | None = None
    probe_injected = False
    composer_ready_seen = False
    composer_ready_via = "NONE"
    observation_window_completed = False
    terminal_responses_forwarded = 0
    terminal_response_bytes_forwarded = 0
    standard_cpr_queries_seen = 0
    standard_cpr_responses_forwarded = 0
    standard_cpr_query_tail = b""
    physical_input_bytes_dropped = 0
    physical_terminal_state_restored = False
    task_process_session_closed = False
    pending_input = b""
    pending_since: float | None = None
    blocked_reason: str | None = None
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

        if diagnose_unsupported:
            os.write(
                stdout_fd,
                b"\r\n[CLROOM screen diagnostic: machine-owned; no probe, prompt, or human input]\r\n",
            )
        else:
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
                    physical_input_bytes_dropped += len(pending_input)
                    pending_input = b""
                    pending_since = None
                    continue
                if not probe_injected and now >= ready_deadline:
                    if diagnose_unsupported:
                        blocked_reason = "DIAGNOSTIC_UNSUPPORTED_NOT_REPRODUCED"
                    else:
                        blocked_reason = (
                            "SCREEN_MODEL_UNTRUSTED"
                            if not screen.trusted
                            else "COMPOSER_READY_TIMEOUT"
                        )
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
                new_cpr_queries, standard_cpr_query_tail = count_standard_cpr_queries(
                    standard_cpr_query_tail,
                    data,
                )
                standard_cpr_queries_seen += new_cpr_queries
                screen.feed(data)
                if diagnose_unsupported:
                    if not screen.trusted:
                        blocked_reason = "DIAGNOSTIC_UNSUPPORTED_CAPTURED"
                        break
                elif not probe_injected:
                    detected_ready_via = screen.composer_ready_method()
                    if detected_ready_via is not None:
                        composer_ready_seen = True
                        composer_ready_via = detected_ready_via
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
                standard_cpr_budget = max(
                    0,
                    standard_cpr_queries_seen - standard_cpr_responses_forwarded,
                )
                (
                    pending_input,
                    response_count,
                    response_bytes,
                    standard_cpr_used,
                    dropped_bytes,
                ) = filter_runtime_terminal_input(
                    pending_input,
                    standard_cpr_budget=standard_cpr_budget,
                )
                physical_input_bytes_dropped += dropped_bytes
                if response_bytes:
                    os.write(master_fd, response_bytes)
                    terminal_responses_forwarded += response_count
                    terminal_response_bytes_forwarded += len(response_bytes)
                    standard_cpr_responses_forwarded += standard_cpr_used
                if pending_input:
                    continue
                pending_since = None

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
            task_process_session_closed = not task_owned_session_processes(child_session)

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
    print(f"COMPOSER_READY_METHOD={composer_ready_via}")
    print(f"SCREEN_MODEL_TRUSTED={'YES' if screen.trusted else 'NO'}")
    print(f"SCREEN_MODEL_UNSUPPORTED_MUTATIONS={screen.unsupported_mutations}")
    print(f"SCREEN_MODEL_FIRST_UNSUPPORTED_IDENTITY={screen.first_unsupported_identity}")
    print(f"SCREEN_MODEL_FIRST_UNSUPPORTED_SHA256={screen.first_unsupported_sha256}")
    print(f"PROBE_INJECTED={'YES' if probe_injected else 'NO'}")
    print(f"OBSERVATION_WINDOW_COMPLETED={'YES' if observation_window_completed else 'NO'}")
    print(f"TERMINAL_RESPONSES_FORWARDED={terminal_responses_forwarded}")
    print(f"TERMINAL_RESPONSE_BYTES_FORWARDED={terminal_response_bytes_forwarded}")
    print(f"STANDARD_CPR_QUERIES_SEEN={standard_cpr_queries_seen}")
    print(f"STANDARD_CPR_RESPONSES_FORWARDED={standard_cpr_responses_forwarded}")
    print(f"PHYSICAL_INPUT_BYTES_DROPPED={physical_input_bytes_dropped}")
    print(f"PHYSICAL_TERMINAL_STATE_RESTORED={'YES' if physical_terminal_state_restored else 'NO'}")
    print("HUMAN_BYTES_FORWARDED=0")
    print("HUMAN_CONTROL_ACTIONS_REQUIRED=0")
    print("SUBMIT_BYTES_FORWARDED=0")
    print("HARNESS_STOP_FORWARDED=0")
    print(f"TASK_PROCESS_SESSION_CLOSED={'YES' if task_process_session_closed else 'NO'}")

    if diagnostic_evidence is not None:
        write_screen_diagnostic(
            diagnostic_evidence,
            screen,
            physical_terminal_state_restored=physical_terminal_state_restored,
            task_process_session_closed=task_process_session_closed,
        )

    if diagnose_unsupported:
        if (
            blocked_reason == "DIAGNOSTIC_UNSUPPORTED_CAPTURED"
            and screen.first_unsupported_identity != "NONE"
            and physical_terminal_state_restored
            and task_process_session_closed
        ):
            print("CLAUDE_TTY_SCREEN_DIAGNOSTIC=CAPTURED")
            return 0
        if blocked_reason is not None:
            print(f"CLAUDE_TTY_SUPERVISOR_BLOCKED:{blocked_reason}", file=sys.stderr)
        else:
            print(
                "CLAUDE_TTY_SUPERVISOR_BLOCKED:DIAGNOSTIC_UNSUPPORTED_NOT_REPRODUCED",
                file=sys.stderr,
            )
        return 3

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
    return 0

def self_test() -> int:
    def expect_terminal(
        raw: bytes,
        expected: tuple[bool, bool, int, bytes, int],
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
    standard_cursor = b"\x1b[24;80R"
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
        expect_terminal(raw, (False, False, 1, raw, 0), label)

    expect_terminal(da1[:10], (False, True, 0, b"", 0), "DA1_FRAGMENT")
    expect_terminal(b"\x1b[", (False, True, 0, b"", 0), "FOCUS_FRAGMENT")
    expect_terminal(osc11[:-1], (False, True, 0, b"", 0), "OSC_FRAGMENT")
    expect_terminal(xtversion[:-1], (False, True, 0, b"", 0), "DCS_FRAGMENT")
    expect_terminal(kitty + focus_out + da1, (False, False, 3, kitty + focus_out + da1, 0), "MULTI_MACHINE_INPUT")
    expect_terminal(standard_cursor, (True, False, 0, b"", 0), "STANDARD_CPR_WITHOUT_QUERY")
    correlated = classify_terminal_input(standard_cursor, standard_cpr_budget=1)
    if correlated != (False, False, 1, standard_cursor, 1):
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:STANDARD_CPR_CORRELATION:"
            f"observed={correlated}"
        )
    over_budget = classify_terminal_input(standard_cursor + standard_cursor, standard_cpr_budget=1)
    if over_budget != (True, False, 1, standard_cursor, 1):
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:STANDARD_CPR_BUDGET:"
            f"observed={over_budget}"
        )
    query_count, query_tail = count_standard_cpr_queries(b"", b"prefix\x1b[")
    if query_count != 0:
        raise SystemExit("CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:STANDARD_CPR_QUERY_PREFIX")
    query_count, query_tail = count_standard_cpr_queries(query_tail, b"6n")
    if query_count != 1:
        raise SystemExit("CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:STANDARD_CPR_QUERY_SPLIT")

    runtime_unknown = filter_runtime_terminal_input(b"x")
    if runtime_unknown != (b"", 0, b"", 0, 1):
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:RUNTIME_UNKNOWN_NOT_DROPPED:"
            f"observed={runtime_unknown}"
        )
    runtime_mixed = filter_runtime_terminal_input(da1 + b"x" + focus_out)
    if runtime_mixed != (b"", 2, da1 + focus_out, 0, 1):
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:RUNTIME_MIXED_FILTER:"
            f"observed={runtime_mixed}"
        )
    runtime_cpr_unqueried = filter_runtime_terminal_input(standard_cursor)
    if runtime_cpr_unqueried != (b"", 0, b"", 0, len(standard_cursor)):
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:RUNTIME_CPR_UNQUERIED_NOT_DROPPED:"
            f"observed={runtime_cpr_unqueried}"
        )
    runtime_cpr_correlated = filter_runtime_terminal_input(
        standard_cursor,
        standard_cpr_budget=1,
    )
    if runtime_cpr_correlated != (b"", 1, standard_cursor, 1, 0):
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:RUNTIME_CPR_CORRELATION:"
            f"observed={runtime_cpr_correlated}"
        )
    runtime_cpr_over_budget = filter_runtime_terminal_input(
        standard_cursor + standard_cursor,
        standard_cpr_budget=1,
    )
    if runtime_cpr_over_budget != (b"", 1, standard_cursor, 1, len(standard_cursor)):
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:RUNTIME_CPR_OVER_BUDGET:"
            f"observed={runtime_cpr_over_budget}"
        )
    runtime_fragment = filter_runtime_terminal_input(da1[:10])
    if runtime_fragment != (da1[:10], 0, b"", 0, 0):
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:RUNTIME_FRAGMENT_BUFFER:"
            f"observed={runtime_fragment}"
        )

    for label, raw in (
        ("PRINTABLE", b"x"),
        ("CTRL_T", b"\x14"),
        ("CTRL_G", b"\x07"),
        ("ARROW", b"\x1b[A"),
        ("CSI_U_KEY", b"\x1b[116;5u"),
    ):
        unexpected, incomplete, _count, _forwarded, _standard_cpr_used = classify_terminal_input(raw)
        if not unexpected or incomplete:
            raise SystemExit(
                f"CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:HUMAN_INPUT_ACCEPTED:{label}"
            )

    styled_screen = TerminalScreen(rows=8, cols=96)
    styled_screen.feed(
        b"\x1b[2mstatus\x1b[0m: "
        b"\x1b[33mmanual\x1b[0m mode "
        b"\x1b[1mon\x1b[0m"
    )
    if styled_screen.composer_ready_method() != "SCREEN_EXACT_MARKER":
        raise SystemExit("CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_EXACT_MARKER")

    def paint_reverse(row: int, col: int, value: str) -> bytes:
        payload = bytearray()
        for offset, character in reversed(list(enumerate(value))):
            payload.extend(f"\x1b[{row};{col + offset}H".encode("ascii"))
            payload.extend(character.encode("ascii"))
        return bytes(payload)

    differential_ready = (
        paint_reverse(3, 1, "manual mode")
        + paint_reverse(3, 22, "shortcuts")
        + paint_reverse(3, 48, "/effort")
    )
    linear = visible_text(differential_ready)
    if any(token in linear for token in READY_STATUS_TOKENS):
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_DIFFERENTIAL_FIXTURE_NOT_DIFFERENTIAL"
        )
    differential_screen = TerminalScreen(rows=8, cols=96)
    for chunk in (
        differential_ready[:7],
        differential_ready[7:19],
        differential_ready[19:43],
        differential_ready[43:],
    ):
        differential_screen.feed(chunk)
    if differential_screen.composer_ready_method() != "SCREEN_STATUS_ROW":
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_DIFFERENTIAL_REDRAW"
        )
    if differential_screen.pending:
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_SPLIT_CSI"
        )

    differential_screen.feed(b"\x1b[3;1H\x1b[2K")
    if differential_screen.composer_ready_method() is not None:
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_CLEAR_REMOVES_READY"
        )

    trust_screen = TerminalScreen(rows=8, cols=96)
    trust_screen.feed(b"manual mode selection requires confirmation /effort")
    if trust_screen.composer_ready_method() is not None:
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_TRUST_FALSE_POSITIVE"
        )

    split_rows = TerminalScreen(rows=8, cols=96)
    split_rows.feed(b"manual mode\r\nshortcuts\r\n/effort")
    if split_rows.composer_ready_method() is not None:
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_SAME_ROW_REQUIRED"
        )

    unsupported_screen = TerminalScreen(rows=8, cols=96)
    unsupported_control = b"\x1b[?9999h"
    unsupported_screen.feed(b"PRIVATE_SENTINEL" + unsupported_control)
    expected_identity = (
        "CSI|prefix=?|params=9999|intermediates_hex=-|final=0x68"
    )
    expected_sha256 = hashlib.sha256(unsupported_control).hexdigest()
    if unsupported_screen.trusted or unsupported_screen.unsupported_mutations != 1:
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_UNSUPPORTED_MUTATION_UNTRUSTED"
        )
    if unsupported_screen.first_unsupported_identity != expected_identity:
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_CONTROL_IDENTITY"
        )
    if unsupported_screen.first_unsupported_sha256 != expected_sha256:
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_CONTROL_FINGERPRINT"
        )
    if "PRIVATE_SENTINEL" in unsupported_screen.first_unsupported_identity:
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_DIAGNOSTIC_PRIVACY"
        )
    diagnostic_record = screen_diagnostic_record(
        unsupported_screen,
        physical_terminal_state_restored=True,
        task_process_session_closed=True,
    )
    diagnostic_json = json.dumps(diagnostic_record, sort_keys=True)
    if "PRIVATE_SENTINEL" in diagnostic_json or "\\x1b" in diagnostic_json:
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_DIAGNOSTIC_PRIVACY"
        )
    if diagnostic_record["raw_terminal_transcript_recorded"] is not False:
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_DIAGNOSTIC_RAW_TRANSCRIPT"
        )
    if unsupported_screen.composer_ready_method() is not None:
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_UNTRUSTED_READY"
        )

    alternate_screen = TerminalScreen(rows=8, cols=96)
    alternate_screen.feed(b"primary\x1b[?1049hmanual mode shortcuts /effort")
    if alternate_screen.composer_ready_method() != "SCREEN_STATUS_ROW":
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_ALTERNATE_READY"
        )
    alternate_screen.feed(b"\x1b[?1049l")
    if alternate_screen.composer_ready_method() is not None:
        raise SystemExit(
            "CLAUDE_TTY_SUPERVISOR_SELF_TEST_FAIL:SCREEN_ALTERNATE_RESTORE"
        )

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
    parser.add_argument("--diagnose-unsupported", action="store_true")
    parser.add_argument("--diagnostic-evidence")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    if args.diagnostic_evidence is not None and not args.diagnose_unsupported:
        print(
            "CLAUDE_TTY_SUPERVISOR_BLOCKED:DIAGNOSTIC_EVIDENCE_REQUIRES_DIAGNOSTIC_MODE",
            file=sys.stderr,
        )
        return 64
    if not args.diagnose_unsupported and args.probe_text is None:
        print("CLAUDE_TTY_SUPERVISOR_BLOCKED:PROBE_TEXT_REQUIRED", file=sys.stderr)
        return 64
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    return supervise(
        command,
        args.probe_text,
        diagnose_unsupported=args.diagnose_unsupported,
        diagnostic_evidence=args.diagnostic_evidence,
    )


if __name__ == "__main__":
    raise SystemExit(main())
