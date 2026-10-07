use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
    sync::atomic::{AtomicU64, Ordering},
};

static SCRATCH_SEQUENCE: AtomicU64 = AtomicU64::new(0);

fn scratch(name: &str) -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "clroom-presets-{name}-{}-{}",
        std::process::id(),
        SCRATCH_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let _ = fs::remove_dir_all(&path);
    fs::create_dir_all(&path).unwrap();
    path
}

fn run(root: &Path, args: &[&str]) -> std::process::Output {
    let home = root.join("home");
    let config = root.join("config");
    fs::create_dir_all(&home).unwrap();
    fs::create_dir_all(&config).unwrap();
    Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(args)
        .env("HOME", &home)
        .env("XDG_CONFIG_HOME", &config)
        .output()
        .expect("clroom must run")
}

fn write_presets(root: &Path, value: &str) {
    let dir = root.join("config/clroom");
    fs::create_dir_all(&dir).unwrap();
    fs::write(dir.join("presets.yaml"), value).unwrap();
}

fn stderr(output: std::process::Output) -> String {
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    String::from_utf8(output.stderr).unwrap()
}

#[test]
fn explicit_preset_requires_a_real_config_before_provider_birth() {
    let root = scratch("missing-config");
    let error = stderr(run(&root, &["codex", "--preset=review", "--version"]));
    assert!(error.starts_with("CLROOM_PRESET_CONFIG_UNAVAILABLE:"), "{error}");
}

#[test]
fn malformed_implicit_preset_file_fails_closed_before_provider_birth() {
    let root = scratch("malformed-config");
    write_presets(
        &root,
        r#"schema: clroom.presets.v1
presets:
  default:
    providers:
      codex: {}
    unexpected: true
"#,
    );
    let error = stderr(run(&root, &["codex", "--version"]));
    assert!(error.starts_with("CLROOM_PRESET_CONFIG_INVALID:"), "{error}");
}

#[test]
fn top_level_preset_provider_inference_refuses_ambiguity() {
    let root = scratch("ambiguous-provider");
    write_presets(
        &root,
        r#"schema: clroom.presets.v1
presets:
  review:
    providers:
      codex: {}
      claude: {}
"#,
    );
    let error = stderr(run(&root, &["--preset=review", "--version"]));
    assert_eq!(
        error,
        "CLROOM_PRESET_PROVIDER_REQUIRED: selected presets do not identify one provider; use clroom <codex|claude> --preset=... or add an unambiguous default-provider\n"
    );
}

#[test]
fn explicit_provider_must_be_permitted_by_every_selected_preset() {
    let root = scratch("provider-intersection");
    write_presets(
        &root,
        r#"schema: clroom.presets.v1
presets:
  codex-only:
    providers:
      codex: {}
"#,
    );
    let error = stderr(run(
        &root,
        &["claude", "--preset=codex-only", "--version"],
    ));
    assert_eq!(
        error,
        "CLROOM_PRESET_PROVIDER_UNAVAILABLE: selected presets do not permit claude; choose a compatible provider or use --preset=none\n"
    );
}

#[test]
fn auth_words_are_not_refused_when_they_are_not_the_first_explicit_provider_token() {
    let root = scratch("auth-word-as-later-provider-token");
    let output = run(&root, &["codex", "--model", "login", "--version"]);
    assert_ne!(output.status.code(), Some(2), "later provider values must not be mistaken for auth subcommands");
}

#[test]
fn preset_provider_args_cannot_shift_auth_subcommands_past_zero_auth_guard() {
    let root = scratch("auth-shift");
    write_presets(
        &root,
        r#"schema: clroom.presets.v1
presets:
  codex-shift:
    providers:
      codex:
        args:
          - --model
          - gpt-5
  claude-shift:
    providers:
      claude:
        args:
          - --model
          - sonnet
"#,
    );

    for args in [
        vec!["codex", "--preset=codex-shift", "login"],
        vec!["codex", "--preset=codex-shift", "logout"],
        vec!["claude", "--preset=claude-shift", "auth"],
        vec!["claude", "--preset=claude-shift", "login"],
    ] {
        let error = stderr(run(&root, &args));
        assert_eq!(
            error,
            "ZERO_AUTH_REFUSAL: provider-native preauthenticated session unavailable or ambiguous; continue locally\n"
        );
    }
}

#[test]
fn sensitive_provider_arguments_in_presets_are_rejected_before_provider_birth() {
    let root = scratch("sensitive-arg");
    write_presets(
        &root,
        r#"schema: clroom.presets.v1
presets:
  unsafe:
    providers:
      codex:
        args:
          - --api-key=must-not-be-loaded
"#,
    );
    let error = stderr(run(&root, &["codex", "--preset=unsafe", "--version"]));
    assert!(error.starts_with("CLROOM_PRESET_CONFIG_INVALID:"), "{error}");
    assert!(!error.contains("must-not-be-loaded"), "{error}");
}

#[test]
fn clroom_control_smuggling_in_provider_args_is_rejected() {
    let root = scratch("control-smuggling");
    write_presets(
        &root,
        r#"schema: clroom.presets.v1
presets:
  unsafe:
    providers:
      codex:
        args:
          - --with=mcp:ambient
"#,
    );
    let error = stderr(run(&root, &["codex", "--preset=unsafe", "--version"]));
    assert!(error.starts_with("CLROOM_PRESET_CONFIG_INVALID:"), "{error}");
}
