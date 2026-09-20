use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
    sync::atomic::{AtomicU64, Ordering},
};

static TEST_SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct Scratch(PathBuf);

impl Scratch {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "clroom-info-{}-{}",
            std::process::id(),
            TEST_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        Self(root)
    }

    fn join(&self, path: impl AsRef<Path>) -> PathBuf {
        self.0.join(path)
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn run_without_providers(args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(args)
        .env("PATH", "/nonexistent")
        .output()
        .expect("clroom must run")
}

#[test]
fn provider_info_reports_absent_provider_without_launching_it() {
    let output = run_without_providers(&["info", "codex"]);
    assert_eq!(output.status.code(), Some(0));
    assert!(output.stderr.is_empty());
    let stdout = String::from_utf8(output.stdout).unwrap();
    assert!(stdout.contains("Provider: Codex (not installed)\n"));
    assert!(stdout.contains("Clean launch: unqualified\n"));
    assert!(stdout.contains("Plugins: unknown / not selectable / unqualified"));
    assert!(stdout.contains("MCP: unknown / not selectable / unqualified"));
    assert!(stdout.contains("Native entries: no targets requested\n"));
    assert!(stdout.contains("Schema: clroom.provider-info.v1\n"));
}

#[test]
fn provider_info_json_is_one_versioned_document_on_stdout() {
    let output = run_without_providers(&["--output", "json", "info", "claude"]);
    assert_eq!(output.status.code(), Some(0));
    assert!(output.stderr.is_empty());
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["schema_version"], "clroom.provider-info.v1");
    assert_eq!(value["provider"]["id"], "claude");
    assert_eq!(value["provider"]["installed"], false);
    assert_eq!(value["clean_launch"]["qualification"], "unqualified");
    assert_eq!(
        value["clean_launch"]["exact_target"],
        "2.1.278 / macOS / Apple Silicon"
    );
    let capabilities = value["capabilities"].as_array().unwrap();
    assert_eq!(capabilities.len(), 2);
    assert!(capabilities.iter().all(|capability| capability["id"] != "browser"));
    assert!(value["native_entries"].is_array());
    assert!(value["combined"]["qualified_closure"].is_array());
}

#[test]
fn provider_info_refuses_sensitive_arguments_before_dispatch() {
    for args in [
        vec!["info", "codex", "--api-key=secret"],
        vec!["--output", "json", "info", "codex", "--token=secret"],
    ] {
        let output = run_without_providers(&args);
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stdout.is_empty());
        assert_eq!(
            String::from_utf8(output.stderr).unwrap(),
            "ZERO_AUTH_ARGUMENT_REFUSAL: sensitive argument refused before dispatch; continue locally\n"
        );
    }
}

#[test]
fn provider_info_accepts_separate_plugin_targets_without_enabling_them() {
    let output = run_without_providers(&[
        "--output",
        "json",
        "info",
        "codex",
        "plugin:alpha@market",
        "plugin:beta@market",
    ]);
    assert_eq!(output.status.code(), Some(0));
    assert!(output.stderr.is_empty());
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    let entries = value["native_entries"].as_array().unwrap();
    assert_eq!(entries.len(), 2);
    assert_eq!(entries[0]["installation"], "not_installed");
    assert_eq!(entries[0]["selection"], "not_selectable");
    assert_eq!(entries[0]["native"]["kind"], "plugin");
    assert_eq!(entries[0]["qualified_closure"], serde_json::json!([]));
    assert_eq!(entries[1]["installation"], "not_installed");
    assert_eq!(
        value["combined"]["conflicts"],
        serde_json::json!(["PLUGIN_NOT_INSTALLED"])
    );
}

#[test]
fn native_plugin_observation_does_not_require_an_exact_provider_tuple() {
    let root = Scratch::new();
    let home = root.join("home");
    let plugin = home.join(".claude/plugins/cache/example/superpowers/6.3.0");
    fs::create_dir_all(plugin.join(".claude-plugin")).unwrap();
    fs::create_dir_all(plugin.join("skills/brainstorming")).unwrap();
    fs::create_dir_all(home.join(".claude/plugins")).unwrap();
    fs::write(
        plugin.join(".claude-plugin/plugin.json"),
        r#"{"name":"superpowers","version":"6.3.0"}"#,
    )
    .unwrap();
    fs::write(plugin.join("skills/brainstorming/SKILL.md"), "fixture\n").unwrap();
    let registry = serde_json::json!({
        "plugins": {
            "superpowers@example": [
                {"installPath": plugin.to_string_lossy()}
            ]
        }
    });
    fs::write(
        home.join(".claude/plugins/installed_plugins.json"),
        serde_json::to_vec(&registry).unwrap(),
    )
    .unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args([
            "--output",
            "json",
            "info",
            "claude",
            "plugin:superpowers@example",
        ])
        .env("HOME", &home)
        .env("PATH", "/nonexistent")
        .output()
        .expect("clroom must run");

    assert_eq!(output.status.code(), Some(0));
    assert!(output.stderr.is_empty());
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["provider"]["installed"], false);
    assert_eq!(value["clean_launch"]["qualification"], "unqualified");
    let entry = &value["native_entries"][0];
    assert_eq!(entry["installation"], "installed");
    assert_eq!(entry["discovery"], "discoverable");
    assert_eq!(entry["selection"], "not_selectable");
    assert_eq!(entry["qualification"], "unqualified");
    assert_eq!(entry["reason_code"], "PLUGIN_ACTIVATION_V04");
    assert!(entry["effective_components"].as_array().unwrap().iter().any(|component| {
        component["kind"] == "skill" && component["id"] == "brainstorming"
    }));
}

#[test]
fn provider_info_rejects_comma_targets_and_non_plugin_target_kinds() {
    for args in [
        vec!["info", "codex", "plugin:a@market,plugin:b@market"],
        vec!["info", "codex", "mcp:server"],
        vec!["info", "codex", "plugin:../escape@market"],
    ] {
        let output = run_without_providers(&args);
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stdout.is_empty());
        assert_eq!(
            String::from_utf8(output.stderr).unwrap(),
            "INFO_NATIVE_TARGET_INVALID: use separate plugin:<provider-native-id> targets\n"
        );
    }
}
