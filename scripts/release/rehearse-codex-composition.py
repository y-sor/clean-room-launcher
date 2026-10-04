#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import pathlib
import pty
import re
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
STANDALONE_PATH = ROOT / "scripts" / "release" / "rehearse-codex-standalone-mcp.py"
SPEC = importlib.util.spec_from_file_location("clroom_standalone_mcp_rehearsal", STANDALONE_PATH)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("CODEX_COMPOSITION_REHEARSAL_BLOCKED:STANDALONE_IMPORT")
standalone = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(standalone)

PLUGIN_ID = "composition@clroom-fixture"
PLUGIN_MCP = "clroom_plugin"
STANDALONE_MCP = "clroom_standalone"
SIBLING_MCP = "clroom_sibling"
ALLOWED_ENV = standalone.ALLOWED_ENV
BLOCKED_ENV = standalone.BLOCKED_ENV
PRIVATE_ARG_CANARY = "CLROOM_PRIVATE_ARG_CANARY"


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(paths: list[pathlib.Path]) -> str:
    digest = hashlib.sha256()
    for root in paths:
        root = root.resolve()
        digest.update(str(root).encode() + b"\0")
        candidates = [root]
        if root.is_dir():
            candidates.extend(sorted(root.rglob("*"), key=lambda item: str(item)))
        for path in candidates:
            relative = "." if path == root else str(path.relative_to(root))
            digest.update(relative.encode() + b"\0")
            if path.is_symlink():
                digest.update(b"symlink\0" + os.readlink(path).encode() + b"\0")
            elif path.is_file():
                digest.update(b"file\0")
                digest.update(path.read_bytes())
                digest.update(b"\0")
            elif path.is_dir():
                digest.update(b"dir\0")
            else:
                digest.update(b"other\0")
    return digest.hexdigest()


def install_server(root: pathlib.Path) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    server = root / "server.py"
    server.write_text(standalone.server_source(), encoding="utf-8")
    server.chmod(0o755)
    return server.resolve()


def install_plugin(codex_home: pathlib.Path, plugin_log: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    plugin = codex_home / "plugins" / "cache" / "clroom-fixture" / "composition" / "local"
    (plugin / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    standalone.private_write(
        plugin / ".codex-plugin" / "plugin.json",
        json.dumps({"name": "composition", "version": "1.0.0"}, separators=(",", ":")) + "\n",
    )
    server = install_server(plugin)
    standalone.private_write(
        plugin / ".mcp.json",
        json.dumps(
            {
                "mcpServers": {
                    PLUGIN_MCP: {
                        "command": str(server),
                        "args": ["--log", str(plugin_log.resolve())],
                    }
                }
            },
            separators=(",", ":"),
        )
        + "\n",
    )
    return plugin.resolve(), server


def write_root_config(
    codex_home: pathlib.Path,
    server: pathlib.Path,
    standalone_log: pathlib.Path,
    overlap_log: pathlib.Path,
    sibling_log: pathlib.Path,
) -> None:
    rows = [
        f"[mcp_servers.{STANDALONE_MCP}]",
        f"command = {standalone.toml_string(server)}",
        f"args = [{standalone.toml_string('--log')}, {standalone.toml_string(standalone_log.resolve())}]",
        f'env_vars = ["{ALLOWED_ENV}"]',
        "",
        f"[mcp_servers.{PLUGIN_MCP}]",
        f"command = {standalone.toml_string(server)}",
        f"args = [{standalone.toml_string('--log')}, {standalone.toml_string(overlap_log.resolve())}]",
        "",
        f"[mcp_servers.{SIBLING_MCP}]",
        f"command = {standalone.toml_string(server)}",
        f"args = [{standalone.toml_string('--log')}, {standalone.toml_string(sibling_log.resolve())}]",
        "",
    ]
    standalone.private_write(codex_home / "config.toml", "\n".join(rows))


def process_snapshot(
    root_pid: int,
    provider: pathlib.Path,
    servers: dict[str, tuple[pathlib.Path, pathlib.Path]],
) -> tuple[set[int], dict[str, set[int]], set[int]]:
    try:
        rows = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid=,pgid="], text=True)
    except (OSError, subprocess.SubprocessError):
        return set(), {name: set() for name in servers}, set()

    processes: dict[int, tuple[int, int]] = {}
    for row in rows.splitlines():
        fields = row.split()
        if len(fields) != 3:
            continue
        try:
            processes[int(fields[0])] = (int(fields[1]), int(fields[2]))
        except ValueError:
            continue

    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for child, (parent, _group) in processes.items():
            if parent in descendants and child not in descendants:
                descendants.add(child)
                changed = True
    group = processes.get(root_pid, (None, root_pid))[1]
    descendants.update(
        pid for pid, (_parent, process_group) in processes.items() if process_group == group
    )

    provider_path = str(provider.resolve())
    interactive: set[int] = set()
    server_pids = {name: set() for name in servers}
    owned: set[int] = set()
    for pid in descendants:
        argv = standalone.fixture.process_argv(pid)
        if standalone.fixture.process_uses_provider(pid, provider_path):
            owned.add(pid)
            if "app-server" not in argv[1:] and "--version" not in argv[1:]:
                interactive.add(pid)
        if not argv:
            continue
        normalized = [
            os.path.realpath(argument) if argument and os.path.isabs(argument) else argument
            for argument in argv
        ]
        for name, (server, log) in servers.items():
            if str(server.resolve()) in normalized and str(log.resolve()) in normalized:
                server_pids[name].add(pid)
                owned.add(pid)

    linked = {name: set() for name in servers}
    for name, pids in server_pids.items():
        for server_pid in pids:
            current = server_pid
            seen: set[int] = set()
            while current in processes and current not in seen:
                seen.add(current)
                parent = processes[current][0]
                if parent in interactive:
                    linked[name].add(server_pid)
                    break
                current = parent
    return interactive, linked, owned


def ensure_closed(
    pids: set[int],
    provider: pathlib.Path,
    servers: list[pathlib.Path],
) -> bool:
    provider_path = str(provider.resolve())
    server_paths = {str(path.resolve()) for path in servers}

    def still_owned(pid: int) -> bool:
        if standalone.fixture.process_uses_provider(pid, provider_path):
            return True
        argv = standalone.fixture.process_argv(pid)
        if not argv:
            return False
        normalized = {
            os.path.realpath(argument)
            for argument in argv
            if argument and os.path.isabs(argument)
        }
        return bool(normalized & server_paths)

    deadline = time.monotonic() + 2
    remaining = {pid for pid in pids if still_owned(pid)}
    while remaining and time.monotonic() < deadline:
        time.sleep(0.05)
        remaining = {pid for pid in remaining if still_owned(pid)}
    if remaining:
        for pid in remaining:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(0.1)
        remaining = {pid for pid in remaining if still_owned(pid)}
    if remaining:
        fail("task-owned composition process lifecycle did not close")
    return True


def inspect_probe(
    candidate: pathlib.Path,
    project: pathlib.Path,
    home: pathlib.Path,
    provider: pathlib.Path,
    plugin_server: pathlib.Path,
    root_server: pathlib.Path,
) -> dict[str, bool]:
    env = standalone.child_env(home, provider)
    args = [
        str(candidate),
        "--output",
        "json",
        "inspect",
        "codex",
        f"--with=plugin:{PLUGIN_ID}",
        f"--with=mcp:{STANDALONE_MCP}",
        f"--pass-env={ALLOWED_ENV}",
        "--model",
        PRIVATE_ARG_CANARY,
    ]
    result = subprocess.run(
        args,
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        fail(f"machine inspect failed: {result.stderr.strip()}")
    report = json.loads(result.stdout)
    resources = {
        (item.get("kind"), item.get("id"), item.get("decision"), item.get("reason"))
        for item in report.get("resources", [])
        if isinstance(item, dict)
    }
    required = {
        ("plugin", PLUGIN_ID, "selected", "explicit-selection"),
        ("mcp", STANDALONE_MCP, "selected", "explicit-selection"),
    }
    if report.get("schema_version") != "clroom.resolved-launch.v1" or not required.issubset(resources):
        fail("machine inspect did not report composed identities/reasons")
    if report.get("pass_env") != [ALLOWED_ENV]:
        fail("machine inspect pass-env names mismatch")
    if (report.get("provider_argv") or {}).get("values_exposed") is not False:
        fail("machine inspect provider argv values are not redacted")

    human = subprocess.run(
        [str(candidate), *args[3:]],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if human.returncode != 0:
        fail(f"human inspect failed: {human.stderr.strip()}")
    combined = result.stdout + human.stdout
    forbidden = [
        env[ALLOWED_ENV],
        env[BLOCKED_ENV],
        PRIVATE_ARG_CANARY,
        str(home.resolve()),
        str(project.resolve()),
        str(plugin_server.resolve()),
        str(root_server.resolve()),
    ]
    leaked = [value for value in forbidden if value and value in combined]
    if leaked:
        fail("inspect leaked private provider/env/path material")
    for marker in (PLUGIN_ID, STANDALONE_MCP, ALLOWED_ENV, "explicit-selection"):
        if marker not in combined:
            fail(f"inspect omitted sanitized marker: {marker}")
    return {
        "human_inspection_sanitized": True,
        "json_inspection_sanitized": True,
        "inspection_same_resource_identities": True,
    }


def overlap_negative(
    candidate: pathlib.Path,
    project: pathlib.Path,
    home: pathlib.Path,
    provider: pathlib.Path,
    logs: list[pathlib.Path],
) -> bool:
    for path in logs:
        standalone.unlink(path)
    result = subprocess.run(
        [
            str(candidate),
            "codex",
            f"--with=plugin:{PLUGIN_ID}",
            f"--with=mcp:{PLUGIN_MCP}",
            f"--pass-env={ALLOWED_ENV}",
            "--no-alt-screen",
        ],
        cwd=project,
        env=standalone.child_env(home, provider),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode == 0 or "CLROOM_RESOURCE_ACTIVATION_CONFLICT" not in result.stderr:
        fail("overlapping plugin/MCP identity did not fail closed")
    if any(path.exists() for path in logs):
        fail("overlap negative started a selected MCP server")
    return True


def positive_probe(
    candidate: pathlib.Path,
    project: pathlib.Path,
    home: pathlib.Path,
    provider: pathlib.Path,
    plugin_server: pathlib.Path,
    root_server: pathlib.Path,
    plugin_log: pathlib.Path,
    standalone_log: pathlib.Path,
    sibling_logs: list[pathlib.Path],
) -> dict[str, bool]:
    for path in [plugin_log, standalone_log, *sibling_logs]:
        standalone.unlink(path)
    standalone.seed_synthetic_project_trust(project, home)
    env = standalone.child_env(home, provider)

    pid, fd = pty.fork()
    if pid == 0:
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
        os.chdir(project)
        argv = [
            str(candidate),
            "codex",
            f"--with=plugin:{PLUGIN_ID}",
            f"--with=mcp:{STANDALONE_MCP}",
            f"--pass-env={ALLOWED_ENV}",
            "--no-alt-screen",
        ]
        os.execve(str(candidate), argv, env)

    os.set_blocking(fd, False)
    interactive_seen = False
    linked = {"plugin": set(), "standalone": set()}
    owned: set[int] = set()
    tail = bytearray()
    reaped = False
    wait_status = None
    deadline = time.monotonic() + 90

    def drain() -> None:
        while True:
            try:
                chunk = os.read(fd, 4096)
            except (BlockingIOError, OSError):
                return
            if not chunk:
                return
            tail.extend(chunk)
            if len(tail) > 8192:
                del tail[:-8192]

    servers = {
        "plugin": (plugin_server, plugin_log),
        "standalone": (root_server, standalone_log),
    }
    while time.monotonic() < deadline:
        drain()
        try:
            waited, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            reaped = True
            break
        if waited:
            wait_status = status
            reaped = True
            break
        interactive, linked_now, owned_now = process_snapshot(pid, provider, servers)
        interactive_seen = interactive_seen or bool(interactive)
        for name in linked:
            linked[name].update(linked_now[name])
        owned.update(owned_now)
        plugin_observed = standalone.read_observation(plugin_log, linked["plugin"])
        standalone_observed = standalone.read_observation(standalone_log, linked["standalone"])
        if (
            interactive_seen
            and linked["plugin"]
            and linked["standalone"]
            and plugin_observed["initialize"]
            and plugin_observed["tools_list"]
            and not plugin_observed["blocked_canary_present"]
            and standalone_observed["initialize"]
            and standalone_observed["tools_list"]
            and standalone_observed["allowed_canary_present"]
            and not standalone_observed["blocked_canary_present"]
        ):
            break
        time.sleep(0.05)

    try:
        os.killpg(pid, signal.SIGINT)
    except (ProcessLookupError, PermissionError):
        pass
    if not reaped:
        for _ in range(40):
            drain()
            try:
                waited, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                reaped = True
                break
            if waited:
                wait_status = status
                reaped = True
                break
            interactive, linked_now, owned_now = process_snapshot(pid, provider, servers)
            interactive_seen = interactive_seen or bool(interactive)
            for name in linked:
                linked[name].update(linked_now[name])
            owned.update(owned_now)
            time.sleep(0.05)
    if not reaped:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            _, wait_status = os.waitpid(pid, 0)
        except ChildProcessError:
            pass
    drain()
    try:
        os.close(fd)
    except OSError:
        pass

    plugin_observed = standalone.read_observation(plugin_log, linked["plugin"])
    standalone_observed = standalone.read_observation(standalone_log, linked["standalone"])
    lifecycle_closed = ensure_closed(owned, provider, [plugin_server, root_server])
    siblings_absent = not any(path.exists() for path in sibling_logs)
    success = (
        interactive_seen
        and bool(linked["plugin"])
        and bool(linked["standalone"])
        and plugin_observed["initialize"]
        and plugin_observed["tools_list"]
        and not plugin_observed["blocked_canary_present"]
        and standalone_observed["initialize"]
        and standalone_observed["tools_list"]
        and standalone_observed["allowed_canary_present"]
        and not standalone_observed["blocked_canary_present"]
        and siblings_absent
        and lifecycle_closed
    )
    if not success:
        diagnostic = tail.decode("utf-8", errors="replace")
        diagnostic = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", diagnostic)
        for value, replacement in (
            (str(home), "<HOME>"),
            (str(project), "<PROJECT>"),
            (str(provider), "<PROVIDER>"),
            (str(candidate), "<CANDIDATE>"),
        ):
            diagnostic = diagnostic.replace(value, replacement)
        if len(diagnostic) > 2048:
            diagnostic = diagnostic[-2048:]
        fail(
            "composed runtime evidence incomplete "
            f"(interactive={interactive_seen}, plugin_pids={len(linked['plugin'])}, "
            f"standalone_pids={len(linked['standalone'])}, plugin={plugin_observed}, "
            f"standalone={standalone_observed}, siblings_absent={siblings_absent}, "
            f"lifecycle_closed={lifecycle_closed}, wait_status={wait_status}, "
            f"pty_tail={diagnostic!r})"
        )
    return {
        "interactive_provider_birth": True,
        "plugin_mcp_under_interactive_provider": True,
        "standalone_mcp_under_interactive_provider": True,
        "plugin_mcp_initialize": True,
        "plugin_mcp_tools_list": True,
        "standalone_mcp_initialize": True,
        "standalone_mcp_tools_list": True,
        "standalone_env_admission": True,
        "blocked_env_absent": True,
        "unselected_siblings_absent": True,
        "task_owned_processes_closed": True,
        "model_prompt_sent": False,
    }


def rehearse(args: argparse.Namespace) -> None:
    if sys.platform != "darwin" or os.uname().machine != "arm64":
        fail("macOS arm64 required")
    if re.fullmatch(r"[0-9a-f]{40}", args.source_head or "") is None:
        fail("invalid source head")
    if re.fullmatch(r"[0-9a-f]{64}", args.expected_provider_sha256 or "") is None:
        fail("invalid expected provider digest")

    candidate = pathlib.Path(args.candidate).resolve()
    provider = pathlib.Path(args.provider).resolve()
    home = pathlib.Path(args.home).resolve()
    output = pathlib.Path(args.output).resolve()
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        fail("candidate executable missing")
    if not provider.is_file() or not os.access(provider, os.X_OK):
        fail("provider executable missing")
    if home.exists() or home.is_symlink():
        fail("synthetic HOME already exists")
    try:
        output.relative_to(home)
    except ValueError:
        pass
    else:
        fail("evidence output must be outside synthetic HOME")

    provider_version, provider_digest = standalone.verify_provider(
        provider, args.expected_provider_version, args.expected_provider_sha256
    )
    candidate_digest = sha256_file(candidate)
    clean_after = False
    try:
        home.mkdir(parents=True, mode=0o700)
        project = home / "project"
        project.mkdir(mode=0o700)
        (project / ".git").mkdir(mode=0o700)
        standalone.private_write(project / ".git" / "HEAD", "ref: refs/heads/main\n")
        codex_home = home / ".codex"
        standalone.fixture.ensure_synthetic_auth(codex_home)

        plugin_log = home / "plugin.jsonl"
        standalone_log = home / "standalone.jsonl"
        overlap_log = home / "overlap.jsonl"
        sibling_log = home / "sibling.jsonl"
        plugin_root, plugin_server = install_plugin(codex_home, plugin_log)
        root_server = install_server(codex_home / "composition-mcp")
        write_root_config(codex_home, root_server, standalone_log, overlap_log, sibling_log)

        ambient_before = fingerprint([codex_home / "config.toml", codex_home / "plugins"])
        plugin_before = fingerprint([plugin_root])
        inspection = inspect_probe(
            candidate, project, home, provider, plugin_server, root_server
        )
        overlap_refused = overlap_negative(
            candidate,
            project,
            home,
            provider,
            [plugin_log, standalone_log, overlap_log, sibling_log],
        )
        runtime = positive_probe(
            candidate,
            project,
            home,
            provider,
            plugin_server,
            root_server,
            plugin_log,
            standalone_log,
            [overlap_log, sibling_log],
        )
        ambient_after = fingerprint([codex_home / "config.toml", codex_home / "plugins"])
        plugin_after = fingerprint([plugin_root])
        if ambient_before != ambient_after or plugin_before != plugin_after:
            fail("ambient provider config/plugin source changed during composition rehearsal")
    finally:
        if home.exists() and not home.is_symlink():
            shutil.rmtree(home)
        clean_after = not home.exists() and not home.is_symlink()

    if not clean_after:
        fail("synthetic HOME lifecycle did not close")

    record = {
        "schema_version": "clroom.codex-composition-rehearsal.v1",
        "result": "PASS",
        "evidence_binding": "exact-head-provider-v1",
        "source_head": args.source_head,
        "candidate_sha256": candidate_digest,
        "platform": "macos-aarch64",
        "codex_version": provider_version,
        "codex_provider_sha256": provider_digest,
        "plugin_id": PLUGIN_ID,
        "plugin_mcp_id": PLUGIN_MCP,
        "standalone_mcp_id": STANDALONE_MCP,
        "overlap_conflict_refused": overlap_refused,
        "ambient_provider_state_unchanged": True,
        "plugin_source_unchanged": True,
        "synthetic_auth_only": True,
        "real_auth_or_config_read": False,
        "clean_after_absent": True,
        **inspection,
        **runtime,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    standalone.private_write(output, json.dumps(record, sort_keys=True, indent=2) + "\n")
    print(
        "CODEX_COMPOSITION_REHEARSAL_PASS "
        f"source={args.source_head} provider={provider_version} provider_sha256={provider_digest}"
    )


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="clroom-composition-rehearsal-") as raw:
        root = pathlib.Path(raw)
        codex_home = root / ".codex"
        standalone.fixture.ensure_synthetic_auth(codex_home)
        plugin_log = root / "plugin.jsonl"
        plugin_root, plugin_server = install_plugin(codex_home, plugin_log)
        root_server = install_server(codex_home / "composition-mcp")
        write_root_config(
            codex_home,
            root_server,
            root / "standalone.jsonl",
            root / "overlap.jsonl",
            root / "sibling.jsonl",
        )
        manifest = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text())
        mcp = json.loads((plugin_root / ".mcp.json").read_text())
        config = (codex_home / "config.toml").read_text()
        if manifest.get("name") != "composition":
            fail("plugin fixture manifest self-test")
        if PLUGIN_MCP not in (mcp.get("mcpServers") or {}):
            fail("plugin fixture MCP self-test")
        for marker in (STANDALONE_MCP, PLUGIN_MCP, SIBLING_MCP, ALLOWED_ENV):
            if marker not in config:
                fail(f"root MCP fixture self-test: {marker}")
        if not plugin_server.is_file() or not root_server.is_file():
            fail("composition server fixture self-test")
    print("CODEX_COMPOSITION_REHEARSAL_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--candidate")
    parser.add_argument("--provider")
    parser.add_argument("--source-head")
    parser.add_argument("--expected-provider-version")
    parser.add_argument("--expected-provider-sha256")
    parser.add_argument("--home")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return 0
        required = [
            args.candidate,
            args.provider,
            args.source_head,
            args.expected_provider_version,
            args.expected_provider_sha256,
            args.home,
            args.output,
        ]
        if any(value is None for value in required):
            parser.error("rehearsal arguments required")
        rehearse(args)
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"CODEX_COMPOSITION_REHEARSAL_BLOCKED:{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
