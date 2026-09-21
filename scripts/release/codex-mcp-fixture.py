#!/usr/bin/env python3
import argparse
import ctypes
import fcntl
import json
import os
import pathlib
import pty
import selectors
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time

PLUGIN_ID = "standalone-mcp@clroom-fixture"
MCP_NAME = "clroom_fixture"

SERVER_SOURCE = r'''#!/usr/bin/python3
import json
import os
import sys

log_path = os.environ.get("CLROOM_MCP_FIXTURE_LOG")

def log(method):
    if not log_path:
        return
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(method + "\n")
        handle.flush()

def send(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()

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
        if params.get("name") != "echo":
            send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "unknown tool"}})
            continue
        message = (params.get("arguments") or {}).get("message")
        if not isinstance(message, str):
            send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "message required"}})
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

def install(codex_home: pathlib.Path, log_path: pathlib.Path) -> pathlib.Path:
    plugin = codex_home / "plugins" / "cache" / "clroom-fixture" / "standalone-mcp" / "local"
    (plugin / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "standalone-mcp", "version": "1.0.0"}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    server = plugin / "server.py"
    server.write_text(SERVER_SOURCE, encoding="utf-8")
    server.chmod(0o755)
    config = {
        "mcpServers": {
            MCP_NAME: {
                "command": str(server.resolve()),
                "env": {"CLROOM_MCP_FIXTURE_LOG": str(log_path.resolve())},
            }
        }
    }
    (plugin / ".mcp.json").write_text(json.dumps(config, separators=(",", ":")) + "\n", encoding="utf-8")
    return plugin.resolve()

def rpc(proc, request, expect_response=True):
    proc.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
    proc.stdin.flush()
    if not expect_response:
        return None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    events = selector.select(timeout=5)
    selector.close()
    if not events:
        raise RuntimeError("MCP response timeout")
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("MCP server closed stdout")
    return json.loads(line)

def probe_server(server: pathlib.Path):
    env = dict(os.environ)
    env.pop("CLROOM_MCP_FIXTURE_LOG", None)
    proc = subprocess.Popen(
        [str(server)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        initialized = rpc(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "clroom-release-probe", "version": "1.0.0"},
            },
        })
        if initialized.get("result", {}).get("serverInfo", {}).get("name") != "clroom-standalone-mcp-fixture":
            raise RuntimeError("unexpected MCP initialize result")
        rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, False)
        listed = rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = listed.get("result", {}).get("tools")
        if not isinstance(tools, list) or not any(isinstance(item, dict) and item.get("name") == "echo" for item in tools):
            raise RuntimeError("MCP tools/list did not expose echo")
        called = rpc(proc, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"message": "probe"}},
        })
        if called.get("result", {}).get("structuredContent", {}).get("echo") != "probe":
            raise RuntimeError("MCP tools/call did not return echo result")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

def process_path(pid):
    if sys.platform != "darwin":
        return None
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    buffer = ctypes.create_string_buffer(4096)
    library.proc_pidpath.restype = ctypes.c_int
    if library.proc_pidpath(int(pid), buffer, len(buffer)) <= 0:
        return None
    return os.path.realpath(os.fsdecode(buffer.value))

def provider_in_tree(root_pid, provider):
    try:
        rows = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid=,pgid="], text=True)
    except (OSError, subprocess.SubprocessError):
        return False
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
    provider = os.path.realpath(provider)
    return any(process_path(pid) == provider for pid in descendants)

def observed_methods(path):
    try:
        methods = set(pathlib.Path(path).read_text(encoding="utf-8").splitlines())
    except FileNotFoundError:
        methods = set()
    return "initialize" in methods and "tools/list" in methods

def probe_provider(candidate, mode, project, home, provider, plugin_id, log_path):
    log = pathlib.Path(log_path)
    try:
        log.unlink()
    except FileNotFoundError:
        pass
    tmpdir = pathlib.Path(home) / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    tmpdir.chmod(0o700)
    provider_dir = str(pathlib.Path(provider).resolve().parent)
    pid, fd = pty.fork()
    if pid == 0:
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
        env = {
            "PATH": provider_dir + ":/usr/bin:/bin",
            "HOME": str(pathlib.Path(home).resolve()),
            "CODEX_HOME": str((pathlib.Path(home) / ".codex").resolve()),
            "TMPDIR": str(tmpdir.resolve()),
            "TERM": "xterm-256color",
        }
        os.chdir(project)
        argv = [candidate]
        if mode == "clroom":
            argv.append("codex")
        argv.extend([f"--with=plugin:{plugin_id}", "--no-alt-screen"])
        os.execve(candidate, argv, env)
    os.set_blocking(fd, False)
    provider_seen = False
    methods_seen = False
    reaped = False
    wait_status = None
    pty_tail = bytearray()
    deadline = time.monotonic() + 45.0

    def drain_pty():
        while True:
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                return
            except OSError:
                return
            if not chunk:
                return
            pty_tail.extend(chunk)
            if len(pty_tail) > 8192:
                del pty_tail[:-8192]
    while time.monotonic() < deadline:
        drain_pty()
        try:
            waited, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            reaped = True
            break
        if waited:
            wait_status = status
            reaped = True
            break
        provider_seen = provider_seen or provider_in_tree(pid, provider)
        methods_seen = methods_seen or observed_methods(log)
        if provider_seen and methods_seen:
            break
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGINT)
    except (ProcessLookupError, PermissionError):
        pass
    if not reaped:
        for _ in range(40):
            drain_pty()
            try:
                waited, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                reaped = True
                break
            if waited:
                wait_status = status
                reaped = True
                break
            provider_seen = provider_seen or provider_in_tree(pid, provider)
            methods_seen = methods_seen or observed_methods(log)
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
    drain_pty()
    try:
        os.close(fd)
    except OSError:
        pass
    if not provider_seen:
        raise RuntimeError("real Codex provider was not observed")
    if not methods_seen:
        diagnostic = pty_tail.decode("utf-8", errors="replace")
        diagnostic = __import__("re").sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", diagnostic)
        for value, replacement in [
            (str(pathlib.Path(home).resolve()), "<HOME>"),
            (str(pathlib.Path(project).resolve()), "<PROJECT>"),
            (str(pathlib.Path(provider).resolve()), "<PROVIDER>"),
            (str(pathlib.Path(candidate).resolve()), "<CANDIDATE>"),
        ]:
            diagnostic = diagnostic.replace(value, replacement)
        diagnostic = "".join(
            character if character in "\n\r\t" or ord(character) >= 32 else "?"
            for character in diagnostic
        ).strip()
        if len(diagnostic) > 4096:
            diagnostic = diagnostic[-4096:]
        if wait_status is None:
            exit_detail = "running-or-status-unavailable"
        elif os.WIFEXITED(wait_status):
            exit_detail = f"exit={os.WEXITSTATUS(wait_status)}"
        elif os.WIFSIGNALED(wait_status):
            exit_detail = f"signal={os.WTERMSIG(wait_status)}"
        else:
            exit_detail = f"wait_status={wait_status}"
        raise RuntimeError(
            f"Codex did not reach MCP initialize + tools/list "
            f"(provider_seen={provider_seen}, process_reaped={reaped}, {exit_detail}, "
            f"pty_tail={diagnostic!r})"
        )
    print("CODEX_MCP_PROVIDER_PROBE_PASS")

def self_test():
    with tempfile.TemporaryDirectory(prefix="clroom-mcp-fixture-") as raw:
        root = pathlib.Path(raw)
        log = root / "mcp.log"
        plugin = install(root / ".codex", log)
        probe_server(plugin / "server.py")
    print("CODEX_MCP_FIXTURE_SELF_TEST_PASS")

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    install_p = sub.add_parser("install")
    install_p.add_argument("--codex-home", required=True)
    install_p.add_argument("--log", required=True)
    server_p = sub.add_parser("probe-server")
    server_p.add_argument("--server", required=True)
    provider_p = sub.add_parser("probe-provider")
    provider_p.add_argument("--candidate", required=True)
    provider_p.add_argument("--mode", choices=["clroom", "dropin"], required=True)
    provider_p.add_argument("--project", required=True)
    provider_p.add_argument("--home", required=True)
    provider_p.add_argument("--provider", required=True)
    provider_p.add_argument("--plugin-id", default=PLUGIN_ID)
    provider_p.add_argument("--log", required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            return
        if args.command == "install":
            print(install(pathlib.Path(args.codex_home), pathlib.Path(args.log)))
        elif args.command == "probe-server":
            probe_server(pathlib.Path(args.server))
            print("MCP_FIXTURE_TOOL_CALL_PASS")
        elif args.command == "probe-provider":
            probe_provider(
                os.path.realpath(args.candidate),
                args.mode,
                os.path.realpath(args.project),
                os.path.realpath(args.home),
                os.path.realpath(args.provider),
                args.plugin_id,
                os.path.realpath(args.log),
            )
        else:
            parser.error("command required")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"CODEX_MCP_FIXTURE_BLOCKED:{error}", file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
