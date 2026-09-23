#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import tempfile
from pathlib import Path


def digest_tree(root: Path) -> str:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ValueError("empty-stage")
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        body = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def check_bindings(path: Path) -> tuple[str, str]:
    rows: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        parts = raw.split()
        if len(parts) != 2:
            raise ValueError("binding-row")
        run_id, digest = parts
        if not run_id.isdigit() or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("binding-value")
        rows.append((run_id, digest))
    if not rows:
        raise ValueError("binding-empty")
    if len({digest for _, digest in rows}) != 1:
        raise ValueError("divergent-successful-stages")
    return rows[0]


def self_test() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        stage = root / "stage"
        stage.mkdir()
        (stage / "a").write_text("one\n", encoding="utf-8")
        first = digest_tree(stage)
        second = digest_tree(stage)
        if first != second:
            raise SystemExit("STAGE_BINDING_SELF_TEST_FAIL:NONDETERMINISTIC")
        coherent = root / "coherent"
        coherent.write_text(f"1 {first}\n2 {first}\n", encoding="utf-8")
        if check_bindings(coherent) != ("1", first):
            raise SystemExit("STAGE_BINDING_SELF_TEST_FAIL:COHERENT")
        divergent = root / "divergent"
        divergent.write_text(f"1 {first}\n2 {'b' * 64}\n", encoding="utf-8")
        try:
            check_bindings(divergent)
        except ValueError as exc:
            if str(exc) != "divergent-successful-stages":
                raise
        else:
            raise SystemExit("STAGE_BINDING_SELF_TEST_FAIL:DIVERGENT")
    print("STAGE_BINDING_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dir", type=Path)
    group.add_argument("--check", type=Path)
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    try:
        if args.dir is not None:
            print(digest_tree(args.dir.resolve()))
            return 0
        run_id, digest = check_bindings(args.check.resolve())
    except ValueError as exc:
        raise SystemExit(f"STAGE_BINDING_BLOCKED:{exc}") from exc
    print(f"STAGE_BINDING_COHERENT selected_run={run_id} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
