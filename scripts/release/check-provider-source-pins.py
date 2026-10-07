#!/usr/bin/env python3
import argparse
import pathlib
import re
from typing import Dict, Tuple

PIN_RE = re.compile(r"^(CODEX_VERSION|CLAUDE_VERSION)=([0-9]+\.[0-9]+\.[0-9]+)$", re.MULTILINE)
CONST_RE = re.compile(
    r"^pub const "
    r"(CODEX_CLEAN_EXACT|CLAUDE_CLEAN_EXACT|CODEX_PLUGIN_ACTIVATION_EXACT|CLAUDE_PLUGIN_ACTIVATION_EXACT)"
    r": \(u64, u64, u64\) = \(([0-9]+), ([0-9]+), ([0-9]+)\);$",
    re.MULTILINE,
)

EXPECTED_CONSTS = {
    "CODEX_VERSION": ("CODEX_CLEAN_EXACT", "CODEX_PLUGIN_ACTIVATION_EXACT"),
    "CLAUDE_VERSION": ("CLAUDE_CLEAN_EXACT", "CLAUDE_PLUGIN_ACTIVATION_EXACT"),
}


def parse_pins(text: str) -> Dict[str, Tuple[int, int, int]]:
    found: Dict[str, Tuple[int, int, int]] = {}
    for key, version in PIN_RE.findall(text):
        if key in found:
            raise ValueError(f"DUPLICATE_PIN:{key}")
        found[key] = tuple(int(part) for part in version.split("."))
    for key in EXPECTED_CONSTS:
        if key not in found:
            raise ValueError(f"MISSING_PIN:{key}")
    return found


def parse_consts(text: str) -> Dict[str, Tuple[int, int, int]]:
    found: Dict[str, Tuple[int, int, int]] = {}
    for key, major, minor, patch in CONST_RE.findall(text):
        if key in found:
            raise ValueError(f"DUPLICATE_CONST:{key}")
        found[key] = (int(major), int(minor), int(patch))
    for consts in EXPECTED_CONSTS.values():
        for key in consts:
            if key not in found:
                raise ValueError(f"MISSING_CONST:{key}")
    return found


def dotted(value: Tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in value)


def validate(pins_text: str, inventory_text: str) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    try:
        pins = parse_pins(pins_text)
        consts = parse_consts(inventory_text)
    except ValueError as exc:
        raise SystemExit(f"PROVIDER_SOURCE_PIN_BLOCKED:{exc}") from exc

    for pin_key, const_keys in EXPECTED_CONSTS.items():
        expected = pins[pin_key]
        for const_key in const_keys:
            actual = consts[const_key]
            if actual != expected:
                raise SystemExit(
                    f"PROVIDER_SOURCE_PIN_BLOCKED:{const_key}:"
                    f"expected={dotted(expected)}:actual={dotted(actual)}"
                )
    return pins["CODEX_VERSION"], pins["CLAUDE_VERSION"]


def self_test() -> int:
    pins = """CODEX_VERSION=0.161.0
CLAUDE_VERSION=2.1.293
"""
    valid = """pub const CODEX_CLEAN_EXACT: (u64, u64, u64) = (0, 161, 0);
pub const CLAUDE_CLEAN_EXACT: (u64, u64, u64) = (2, 1, 293);
pub const CODEX_PLUGIN_ACTIVATION_EXACT: (u64, u64, u64) = (0, 161, 0);
pub const CLAUDE_PLUGIN_ACTIVATION_EXACT: (u64, u64, u64) = (2, 1, 293);
"""
    validate(pins, valid)

    cases = {
        "stale_clean": (
            valid.replace(
                "CLAUDE_CLEAN_EXACT: (u64, u64, u64) = (2, 1, 293)",
                "CLAUDE_CLEAN_EXACT: (u64, u64, u64) = (2, 1, 292)",
            ),
            "PROVIDER_SOURCE_PIN_BLOCKED:CLAUDE_CLEAN_EXACT:expected=2.1.293:actual=2.1.292",
        ),
        "stale_plugin": (
            valid.replace(
                "CLAUDE_PLUGIN_ACTIVATION_EXACT: (u64, u64, u64) = (2, 1, 293)",
                "CLAUDE_PLUGIN_ACTIVATION_EXACT: (u64, u64, u64) = (2, 1, 292)",
            ),
            "PROVIDER_SOURCE_PIN_BLOCKED:CLAUDE_PLUGIN_ACTIVATION_EXACT:expected=2.1.293:actual=2.1.292",
        ),
        "stale_codex": (
            valid.replace(
                "CODEX_CLEAN_EXACT: (u64, u64, u64) = (0, 161, 0)",
                "CODEX_CLEAN_EXACT: (u64, u64, u64) = (0, 160, 0)",
            ),
            "PROVIDER_SOURCE_PIN_BLOCKED:CODEX_CLEAN_EXACT:expected=0.161.0:actual=0.160.0",
        ),
    }
    for name, (inventory, expected) in cases.items():
        try:
            validate(pins, inventory)
        except SystemExit as exc:
            if str(exc) != expected:
                raise SystemExit(f"PROVIDER_SOURCE_PIN_SELF_TEST_FAIL:{name}:wrong_error:{exc}")
        else:
            raise SystemExit(f"PROVIDER_SOURCE_PIN_SELF_TEST_FAIL:{name}:accepted")

    print("PROVIDER_SOURCE_PIN_SELF_TEST_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--pins", default="scripts/release/provider-pins.sh")
    parser.add_argument("--inventory", default="src/catalog/provider_inventory.rs")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    pins_path = pathlib.Path(args.pins)
    inventory_path = pathlib.Path(args.inventory)
    codex, claude = validate(
        pins_path.read_text(encoding="utf-8"),
        inventory_path.read_text(encoding="utf-8"),
    )
    print(
        f"PROVIDER_SOURCE_PIN_PASS codex={dotted(codex)} "
        f"claude={dotted(claude)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
