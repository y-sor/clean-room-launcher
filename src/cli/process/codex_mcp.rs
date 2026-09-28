use super::{
    CodexState, INTERNAL_PROVIDER_CHAIN_GUARD, ProviderEnvironment, apply_parent_environment,
};
use crate::cli::launch_contract::LaunchContract;
use clroom::adapters::{
    codex::isolation::IsolationPlan,
    identity::ProviderIdentity,
};
use serde_json::{Value, json};
use std::{
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::mpsc::{self, Receiver, RecvTimeoutError},
    thread,
    time::{Duration, Instant},
};

const PREFLIGHT_TIMEOUT: Duration = Duration::from_secs(5);

pub(super) fn preflight_layers(
    plan: &IsolationPlan,
    identity: &ProviderIdentity,
    state: &CodexState,
    project: &Path,
) -> Result<(), String> {
    let sandbox = Path::new("/usr/bin/sandbox-exec");
    if !sandbox.is_file() {
        return Err(preflight_failed());
    }
    let contract = LaunchContract::codex(&["app-server".to_owned()]);
    let mut command = Command::new(sandbox);
    apply_parent_environment(&mut command, ProviderEnvironment::Codex, &[]);
    command
        .arg("-p")
        .arg(&plan.profile)
        .arg("--")
        .arg(&identity.real_executable)
        .env(INTERNAL_PROVIDER_CHAIN_GUARD, "1")
        .env("CODEX_HOME", &state.shadow_home)
        .args(&contract.argv)
        .current_dir(project)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());

    let mut child = command.spawn().map_err(|_| preflight_failed())?;
    let result = run_protocol(&mut child, project);
    let _ = child.kill();
    let _ = child.wait();
    result
}

fn run_protocol(child: &mut Child, project: &Path) -> Result<(), String> {
    let mut stdin = child.stdin.take().ok_or_else(preflight_failed)?;
    let stdout = child.stdout.take().ok_or_else(preflight_failed)?;
    let (sender, receiver) = mpsc::channel::<Value>();
    let reader = thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    if let Ok(value) = serde_json::from_str::<Value>(&line) {
                        if sender.send(value).is_err() {
                            break;
                        }
                    }
                }
            }
        }
    });

    let deadline = Instant::now() + PREFLIGHT_TIMEOUT;
    write_message(
        &mut stdin,
        &json!({
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {
                    "name": "clroom-mcp-preflight",
                    "title": "CLROOM MCP preflight",
                    "version": env!("CARGO_PKG_VERSION")
                },
                "capabilities": {
                    "experimentalApi": true
                }
            }
        }),
    )?;
    let _ = receive_result(&receiver, deadline, 1)?;

    write_message(&mut stdin, &json!({"method": "initialized"}))?;
    write_message(
        &mut stdin,
        &json!({
            "id": 2,
            "method": "config/read",
            "params": {
                "includeLayers": true,
                "cwd": path_text(project)?
            }
        }),
    )?;
    let config = receive_result(&receiver, deadline, 2)?;
    drop(stdin);
    drop(receiver);
    let _ = reader.join();

    validate_layers(&config)
}

fn write_message(stdin: &mut impl Write, value: &Value) -> Result<(), String> {
    serde_json::to_writer(&mut *stdin, value).map_err(|_| preflight_failed())?;
    stdin.write_all(b"\n").map_err(|_| preflight_failed())?;
    stdin.flush().map_err(|_| preflight_failed())
}

fn receive_result(
    receiver: &Receiver<Value>,
    deadline: Instant,
    id: i64,
) -> Result<Value, String> {
    loop {
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .ok_or_else(preflight_failed)?;
        let message = match receiver.recv_timeout(remaining) {
            Ok(message) => message,
            Err(RecvTimeoutError::Timeout | RecvTimeoutError::Disconnected) => {
                return Err(preflight_failed());
            }
        };
        if message.get("id").and_then(Value::as_i64) != Some(id) {
            continue;
        }
        if message.get("error").is_some() {
            return Err(preflight_failed());
        }
        return message
            .get("result")
            .cloned()
            .ok_or_else(preflight_failed);
    }
}

fn validate_layers(result: &Value) -> Result<(), String> {
    let layers = result
        .get("layers")
        .and_then(Value::as_array)
        .ok_or_else(preflight_failed)?;
    for layer in layers {
        if layer.get("disabledReason").is_some_and(|value| !value.is_null()) {
            continue;
        }
        let Some(config) = layer.get("config").and_then(Value::as_object) else {
            return Err(preflight_failed());
        };
        if config
            .get("mcp_servers")
            .and_then(Value::as_object)
            .is_some_and(|servers| !servers.is_empty())
        {
            return Err(
                "CLROOM_CODEX_MCP_SIBLING_PRESENT: active Codex configuration contains an ambient MCP server; standalone selection refused before provider birth"
                    .to_owned(),
            );
        }
    }
    Ok(())
}

fn path_text(path: &Path) -> Result<String, String> {
    path.to_str()
        .map(str::to_owned)
        .ok_or_else(preflight_failed)
}

fn preflight_failed() -> String {
    "CLROOM_CODEX_MCP_PREFLIGHT_FAILED: Codex configuration layers could not be proven free of ambient MCP siblings; continue locally"
        .to_owned()
}

#[cfg(test)]
mod tests {
    use super::validate_layers;
    use serde_json::json;

    #[test]
    fn active_mcp_layer_is_refused_without_exposing_values() {
        let result = json!({
            "layers": [
                {
                    "name": {"type": "system"},
                    "config": {"mcp_servers": {"secret-server": {"env": {"TOKEN": "secret"}}}}
                }
            ]
        });
        let error = validate_layers(&result).unwrap_err();
        assert!(error.starts_with("CLROOM_CODEX_MCP_SIBLING_PRESENT:"));
        assert!(!error.contains("secret-server"));
        assert!(!error.contains("TOKEN"));
        assert!(!error.contains("secret"));
    }

    #[test]
    fn disabled_project_mcp_layer_does_not_block() {
        let result = json!({
            "layers": [
                {
                    "name": {"type": "project"},
                    "disabledReason": "project is untrusted",
                    "config": {"mcp_servers": {"ambient": {"command": "false"}}}
                },
                {
                    "name": {"type": "sessionFlags"},
                    "config": {"features": {"plugins": false}}
                }
            ]
        });
        assert_eq!(validate_layers(&result), Ok(()));
    }

    #[test]
    fn malformed_layer_response_fails_closed() {
        assert!(validate_layers(&json!({"layers": [{}]})).is_err());
        assert!(validate_layers(&json!({})).is_err());
    }
}
