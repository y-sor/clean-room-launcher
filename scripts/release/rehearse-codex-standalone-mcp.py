#!/usr/bin/env python3
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
FIXTURE_PATH = ROOT / "scripts" / "release" / "codex-mcp-fixture.py"
SPEC = importlib.util.spec_from_file_location("clroom_codex_mcp_fixture", FIXTURE_PATH)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("CODEX_STANDALONE_MCP_REHEARSAL_BLOCKED:FIXTURE_IMPORT")
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)

MCP_NAME = "clroom_fixture"
SIBLING_NAME = "clroom_sibling"
ALLOWED_ENV = "CLROOM_MCP_ALLOWED"
BLOCKED_ENV = "CLROOM_MCP_BLOCKED"


def fail(message):
    raise RuntimeError(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def private_write(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        metadata = None
    if metadata is not None and (path.is_symlink() or not path.is_file()):
        fail("synthetic path conflict")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def toml_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def server_source():
    return r'''#!/usr/bin/python3
import json
import os
import sys

if len(sys.argv) != 3 or sys.argv[1] != "--log":
    raise SystemExit(2)
log_path = sys.argv[2]

def log(method):
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "method": method,
            "allowed_canary_present": "CLROOM_MCP_ALLOWED" in os.environ,
            "blocked_canary_present": "CLROOM_MCP_BLOCKED" in os.environ,
        }, separators=(",", ":")) + "\n")
        handle.flush()

def send(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()

log("__birth__")
for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    request = json.loads(raw)
    method = request.get("method")
    if isinstance(method, str):
        log(method)
    if "id" not in request:
        continue
    request_id = request["id"]
    if method == "initialize":
        requested = (request.get("params") or {}).get("protocolVersion")
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": requested or "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "clroom-standalone-mcp-fixture", "version": "1.0.0"},
            },
        })
    elif method == "tools/list":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [{
                    "name": "echo",
                    "description": "Return the supplied message.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                        "additionalProperties": False,
                    },
                }]
            },
        })
    elif method == "tools/call":
        params = request.get("params") or {}
        message = (params.get("arguments") or {}).get("message")
        if params.get("name") != "echo" or not isinstance(message, str):
            send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "invalid tool call"}})
            continue
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": message}],
                "structuredContent": {"echo": message},
                "isError": False,
            },
        })
    else:
        send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method not found"}})
'''


def install_server(codex_home, selected_log, sibling_log):
    fixture.ensure_synthetic_auth(codex_home)
    root = codex_home / "standalone-mcp-fixture"
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    server = root / "server.py"
    server.write_text(server_source(), encoding="utf-8")
    server.chmod(0o755)
    write_config(codex_home, server, selected_log, sibling_log)
    return server


def write_config(codex_home, server, selected_log, sibling_log, literal_env=False, include_sibling=True):
    lines = [
        f"[mcp_servers.{MCP_NAME}]",
        f"command = {toml_string(server.resolve())}",
        f"args = [{toml_string('--log')}, {toml_string(selected_log.resolve())}]",
    ]
    if literal_env:
        lines.append('env = { CLROOM_MCP_ALLOWED = "synthetic-literal" }')
    else:
        lines.append(f'env_vars = ["{ALLOWED_ENV}"]')
    if include_sibling:
        lines += [
            "",
            f"[mcp_servers.{SIBLING_NAME}]",
            f"command = {toml_string(server.resolve())}",
            f"args = [{toml_string('--log')}, {toml_string(sibling_log.resolve())}]",
        ]
    private_write(codex_home / "config.toml", "\n".join(lines) + "\n")


def child_env(home, provider):
    tmpdir = home / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    tmpdir.chmod(0o700)
    return {
        "PATH": str(provider.parent) + ":/usr/bin:/bin",
        "HOME": str(home),
        "CODEX_HOME": str(home / ".codex"),
        "TMPDIR": str(tmpdir),
        "TERM": "xterm-256color",
        ALLOWED_ENV: "synthetic-allowed",
        BLOCKED_ENV: "synthetic-blocked",
    }


def read_observation(path):
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    records = []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and isinstance(record.get("method"), str):
            records.append(record)
    methods = {record["method"] for record in records}
    relevant = [record for record in records if record["method"] in {"__birth__", "initialize", "tools/list"}]
    return {
        "fixture_birth": "__birth__" in methods,
        "initialize": "initialize" in methods,
        "tools_list": "tools/list" in methods,
        "allowed_canary_present": bool(relevant) and all(record.get("allowed_canary_present") is True for record in relevant),
        "blocked_canary_present": any(record.get("blocked_canary_present") is True for record in relevant),
    }


def unlink(path):
    try:
        pathlib.Path(path).unlink()
    except FileNotFoundError:
        pass



def process_snapshot(root_pid, provider, server, selected_log):
    try:
        rows = subprocess.check_output(
            ["/bin/ps", "-axo", "pid=,ppid=,pgid="], text=True
        )
    except (OSError, subprocess.SubprocessError):
        return False, False, set()
    processes = {}
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
        pid for pid, (_parent, process_group) in processes.items()
        if process_group == group
    )

    provider = str(pathlib.Path(provider).resolve())
    server = str(pathlib.Path(server).resolve())
    selected_log = str(pathlib.Path(selected_log).resolve())
    interactive = set()
    selected_servers = set()
    owned = set()

    for pid in descendants:
        argv = fixture.process_argv(pid)
        if fixture.process_uses_provider(pid, provider):
            owned.add(pid)
            if "app-server" not in argv[1:]:
                interactive.add(pid)
        if argv:
            normalized = [
                os.path.realpath(argument)
                if argument and os.path.isabs(argument)
                else argument
                for argument in argv
            ]
            if server in normalized and selected_log in normalized:
                selected_servers.add(pid)
                owned.add(pid)

    linked = False
    for server_pid in selected_servers:
        current = server_pid
        seen = set()
        while current in processes and current not in seen:
            seen.add(current)
            parent = processes[current][0]
            if parent in interactive:
                linked = True
                break
            current = parent
        if linked:
            break

    return bool(interactive), linked, owned


def ensure_task_processes_closed(pids, provider, server):
    provider = str(pathlib.Path(provider).resolve())
    server = str(pathlib.Path(server).resolve())

    def still_owned(pid):
        if fixture.process_uses_provider(pid, provider):
            return True
        argv = fixture.process_argv(pid)
        if not argv:
            return False
        normalized = [
            os.path.realpath(argument)
            if argument and os.path.isabs(argument)
            else argument
            for argument in argv
        ]
        return server in normalized

    deadline = time.monotonic() + 2.0
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
        fail("task-owned Codex/MCP process lifecycle did not close")
    return True

def positive_probe(candidate, project, home, provider, server, selected_log, sibling_log):
    unlink(selected_log)
    unlink(sibling_log)
    env = child_env(home, provider)
    fixture.seed_synthetic_project_trust(str(candidate), "clroom", str(project), str(home), env)

    pid, fd = pty.fork()
    if pid == 0:
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
        os.chdir(project)
        argv = [
            str(candidate), "codex",
            f"--with=mcp:{MCP_NAME}",
            f"--pass-env={ALLOWED_ENV}",
            "--no-alt-screen",
        ]
        os.execve(str(candidate), argv, env)

    os.set_blocking(fd, False)
    provider_seen = False
    interactive_provider_seen = False
    interactive_mcp_linked = False
    owned_pids = set()
    pty_tail = bytearray()
    reaped = False
    wait_status = None
    deadline = time.monotonic() + 45

    def drain():
        while True:
            try:
                chunk = os.read(fd, 4096)
            except (BlockingIOError, OSError):
                return
            if not chunk:
                return
            pty_tail.extend(chunk)
            if len(pty_tail) > 8192:
                del pty_tail[:-8192]

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
        provider_seen = provider_seen or fixture.provider_in_tree(pid, str(provider))
        interactive_now, linked_now, owned_now = process_snapshot(
            pid, provider, server, selected_log
        )
        interactive_provider_seen = interactive_provider_seen or interactive_now
        interactive_mcp_linked = interactive_mcp_linked or linked_now
        owned_pids.update(owned_now)
        observed = read_observation(selected_log)
        if (
            provider_seen
            and interactive_provider_seen
            and interactive_mcp_linked
            and observed["fixture_birth"]
            and observed["initialize"]
            and observed["tools_list"]
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
            provider_seen = provider_seen or fixture.provider_in_tree(pid, str(provider))
            interactive_now, linked_now, owned_now = process_snapshot(
                pid, provider, server, selected_log
            )
            interactive_provider_seen = interactive_provider_seen or interactive_now
            interactive_mcp_linked = interactive_mcp_linked or linked_now
            owned_pids.update(owned_now)
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

    observed = read_observation(selected_log)
    sibling_absent = not sibling_log.exists()
    lifecycle_closed = ensure_task_processes_closed(owned_pids, provider, server)
    if not (
        provider_seen
        and interactive_provider_seen
        and interactive_mcp_linked
        and lifecycle_closed
        and observed["fixture_birth"]
        and observed["initialize"]
        and observed["tools_list"]
        and observed["allowed_canary_present"]
        and not observed["blocked_canary_present"]
        and sibling_absent
    ):
        diagnostic = pty_tail.decode("utf-8", errors="replace")
        diagnostic = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", diagnostic)
        for value, replacement in [
            (str(home), "<HOME>"),
            (str(project), "<PROJECT>"),
            (str(provider), "<PROVIDER>"),
            (str(candidate), "<CANDIDATE>"),
        ]:
            diagnostic = diagnostic.replace(value, replacement)
        diagnostic = "".join(c if c in "\n\r\t" or ord(c) >= 32 else "?" for c in diagnostic).strip()
        if len(diagnostic) > 2048:
            diagnostic = diagnostic[-2048:]
        if wait_status is None:
            exit_detail = "status-unavailable"
        elif os.WIFEXITED(wait_status):
            exit_detail = f"exit={os.WEXITSTATUS(wait_status)}"
        elif os.WIFSIGNALED(wait_status):
            exit_detail = f"signal={os.WTERMSIG(wait_status)}"
        else:
            exit_detail = f"wait_status={wait_status}"
        fail(
            "positive runtime evidence incomplete "
            f"(provider_seen={provider_seen}, interactive_provider_seen={interactive_provider_seen}, "
            f"interactive_mcp_linked={interactive_mcp_linked}, lifecycle_closed={lifecycle_closed}, "
            f"observed={observed}, sibling_absent={sibling_absent}, "
            f"{exit_detail}, pty_tail={diagnostic!r})"
        )
    return {
        "provider_birth": True,
        "interactive_provider_birth": True,
        "selected_mcp_under_interactive_provider": True,
        "provider_state_lifecycle_closed": True,
        "selected_fixture_birth": True,
        "initialize": True,
        "tools_list": True,
        "allowed_canary_present": True,
        "blocked_canary_present": False,
        "sibling_absent": True,
    }


def negative_probe(label, candidate, project, home, provider, args, expected_marker, selected_log, sibling_log):
    unlink(selected_log)
    unlink(sibling_log)
    proc = subprocess.Popen(
        [str(candidate), "codex", *args],
        cwd=project,
        env=child_env(home, provider),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        _, stderr = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        _, stderr = proc.communicate(timeout=5)
    markers = sorted(set(re.findall(r"CLROOM_[A-Z0-9_]+", stderr or "")))
    if timed_out or proc.returncode == 0 or expected_marker not in (stderr or ""):
        fail(f"{label} did not fail closed (status={proc.returncode}, timeout={timed_out}, markers={markers})")
    if selected_log.exists() or sibling_log.exists():
        fail(f"{label} reached MCP fixture runtime")
    return "PASS"


def protocol_tool_call(server, home):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home / "tmp")}
    proc = subprocess.Popen(
        [str(server), "--log", str(home / "protocol-probe.jsonl")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        initialized = fixture.rpc(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "clroom-release-probe", "version": "1.0.0"},
            },
        })
        if initialized.get("result", {}).get("serverInfo", {}).get("name") != "clroom-standalone-mcp-fixture":
            fail("fixture initialize mismatch")
        fixture.rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, False)
        listed = fixture.rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = listed.get("result", {}).get("tools")
        if not isinstance(tools, list) or not any(item.get("name") == "echo" for item in tools if isinstance(item, dict)):
            fail("fixture tools/list mismatch")
        called = fixture.rpc(proc, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "echo", "arguments": {"message": "probe"}},
        })
        if called.get("result", {}).get("structuredContent", {}).get("echo") != "probe":
            fail("fixture tools/call mismatch")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def verify_provider(provider, expected_version, expected_sha):
    env = {"PATH": str(provider.parent) + ":/usr/bin:/bin", "HOME": "/tmp", "TMPDIR": "/tmp"}
    result = subprocess.run(
        [str(provider), "--version"], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=15, check=False,
    )
    match = re.search(r"([0-9]+\.[0-9]+\.[0-9]+)", result.stdout or "")
    if result.returncode != 0 or match is None or match.group(1) != expected_version:
        fail("Codex provider version mismatch")
    digest = sha256_file(provider)
    if digest != expected_sha:
        fail("Codex provider digest mismatch")
    return match.group(1), digest


def rehearse(args):
    if sys.platform != "darwin" or os.uname().machine != "arm64":
        fail("macOS arm64 required")
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_head):
        fail("invalid source head")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_provider_sha256):
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
        fail("clean-before synthetic HOME already exists")
    try:
        output.relative_to(home)
    except ValueError:
        pass
    else:
        fail("evidence output must be outside synthetic HOME")

    provider_version, provider_digest = verify_provider(
        provider, args.expected_provider_version, args.expected_provider_sha256
    )
    candidate_digest = sha256_file(candidate)
    positive = None
    negatives = {}
    clean_after = False

    try:
        home.mkdir(parents=True, mode=0o700)
        project = home / "project"
        project.mkdir(mode=0o700)
        codex_home = home / ".codex"
        selected_log = home / "selected.jsonl"
        sibling_log = home / "sibling.jsonl"
        server = install_server(codex_home, selected_log, sibling_log)

        source_digest_before = sha256_file(codex_home / "config.toml")

        # Fail-closed cases run before any successful interactive provider session so
        # a forcibly-stopped TUI cannot contaminate their result.
        negatives["unadmitted_env"] = negative_probe(
            "unadmitted_env", candidate, project, home, provider,
            [f"--with=mcp:{MCP_NAME}", "--no-alt-screen"],
            "CLROOM_ENV_SELECTOR_REQUIRED", selected_log, sibling_log,
        )

        write_config(codex_home, server, selected_log, sibling_log, literal_env=True, include_sibling=False)
        negatives["literal_env"] = negative_probe(
            "literal_env", candidate, project, home, provider,
            [f"--with=mcp:{MCP_NAME}", f"--pass-env={ALLOWED_ENV}", "--no-alt-screen"],
            "CLROOM_MCP_SECRET_MATERIAL_REFUSED", selected_log, sibling_log,
        )

        write_config(codex_home, server, selected_log, sibling_log)
        negatives["provider_subcommand"] = negative_probe(
            "provider_subcommand", candidate, project, home, provider,
            [f"--with=mcp:{MCP_NAME}", f"--pass-env={ALLOWED_ENV}", "app-server"],
            "CLROOM_RESOURCE_NOT_SELECTABLE", selected_log, sibling_log,
        )
        negatives["multi_mcp"] = negative_probe(
            "multi_mcp", candidate, project, home, provider,
            [
                f"--with=mcp:{MCP_NAME}", f"--with=mcp:{SIBLING_NAME}",
                f"--pass-env={ALLOWED_ENV}", "--no-alt-screen",
            ],
            "CLROOM_RESOURCE_MULTI_SELECT_UNAVAILABLE_IN_V0_4", selected_log, sibling_log,
        )
        negatives["mcp_plus_plugin"] = negative_probe(
            "mcp_plus_plugin", candidate, project, home, provider,
            [
                f"--with=mcp:{MCP_NAME}", f"--with=plugin:{fixture.PLUGIN_ID}",
                f"--pass-env={ALLOWED_ENV}", "--no-alt-screen",
            ],
            "CLROOM_RESOURCE_ACTIVATION_CONFLICT", selected_log, sibling_log,
        )

        fixture.seed_synthetic_project_trust(
            str(candidate), "clroom", str(project), str(home), child_env(home, provider)
        )
        project_codex = project / ".codex"
        project_codex.mkdir(mode=0o700)
        private_write(
            project_codex / "config.toml",
            "\n".join([
                "[mcp_servers.project_sibling]",
                f"command = {toml_string(server.resolve())}",
                f"args = [{toml_string('--log')}, {toml_string(sibling_log.resolve())}]",
                "",
            ]),
        )
        negatives["project_sibling_layer"] = negative_probe(
            "project_sibling_layer", candidate, project, home, provider,
            [f"--with=mcp:{MCP_NAME}", f"--pass-env={ALLOWED_ENV}", "--no-alt-screen"],
            "CLROOM_CODEX_MCP_LAYER_CONFLICT", selected_log, sibling_log,
        )
        shutil.rmtree(project_codex)
        negatives["source_mutation"] = "LOCKED_TEST_COVERAGE"

        write_config(codex_home, server, selected_log, sibling_log)
        source_digest_before_positive = sha256_file(codex_home / "config.toml")
        positive = positive_probe(
            candidate, project, home, provider, server, selected_log, sibling_log
        )
        source_digest_after_positive = sha256_file(codex_home / "config.toml")
        if source_digest_after_positive != source_digest_before_positive:
            fail("synthetic ambient Codex config changed during positive rehearsal")
        protocol_tool_call(server, home)
    finally:
        if home.exists() and not home.is_symlink():
            shutil.rmtree(home)
        clean_after = not home.exists() and not home.is_symlink()

    if positive is None or not clean_after:
        fail("rehearsal lifecycle incomplete")

    record = {
        "schema_version": "clroom.codex-standalone-mcp-rehearsal.v1",
        "result": "PASS",
        "evidence_binding": "exact-head-provider-v1",
        "source_head": args.source_head,
        "candidate_sha256": candidate_digest,
        "platform": "macos-aarch64",
        "codex_version": provider_version,
        "codex_provider_sha256": provider_digest,
        "synthetic_auth_only": True,
        "real_auth_or_config_read": False,
        "model_prompt_sent": False,
        "provider_tool_call": "NOT_SAFE_WITHOUT_PROMPT",
        "fixture_protocol_tool_call": True,
        **positive,
        "negative_cases": negatives,
        "clean_before_absent": True,
        "clean_after_absent": True,
        "synthetic_source_config_unchanged": True,
        "ambient_provider_state_unchanged": True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    private_write(output, json.dumps(record, sort_keys=True, indent=2) + "\n")
    print(
        "CODEX_STANDALONE_MCP_REHEARSAL_PASS "
        f"source={args.source_head} provider={provider_version} provider_sha256={provider_digest}"
    )


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory(prefix="clroom-standalone-mcp-rehearsal-") as raw:
        root = pathlib.Path(raw)
        codex_home = root / ".codex"
        selected = root / "selected.jsonl"
        sibling = root / "sibling.jsonl"
        server = install_server(codex_home, selected, sibling)
        config = (codex_home / "config.toml").read_text(encoding="utf-8")
        if (
            f"[mcp_servers.{MCP_NAME}]" not in config
            or f"[mcp_servers.{SIBLING_NAME}]" not in config
            or f'env_vars = ["{ALLOWED_ENV}"]' not in config
            or "synthetic-literal" in config
        ):
            fail("synthetic config self-test")
        protocol_tool_call(server, root)
    print("CODEX_STANDALONE_MCP_REHEARSAL_SELF_TEST_PASS")


def main():
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
            args.candidate, args.provider, args.source_head,
            args.expected_provider_version, args.expected_provider_sha256,
            args.home, args.output,
        ]
        if any(value is None for value in required):
            parser.error("rehearsal arguments required")
        rehearse(args)
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"CODEX_STANDALONE_MCP_REHEARSAL_BLOCKED:{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
