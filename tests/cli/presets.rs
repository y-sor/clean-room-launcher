use std::{
    fs,
    os::unix::fs::PermissionsExt,
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

fn run_with_fake_provider(
    root: &Path,
    provider: &str,
    args: &[&str],
) -> (std::process::Output, PathBuf) {
    let bin = root.join("bin");
    fs::create_dir_all(&bin).unwrap();
    let marker = root.join("provider-started");
    let version = match provider {
        "codex" => "0.161.0",
        "claude" => "2.1.293",
        _ => unreachable!(),
    };
    let executable = bin.join(provider);
    fs::write(
        &executable,
        format!(
            "#!/bin/sh\nprintf started >> '{}'\nif [ \"$1\" = --version ]; then printf '{}\\n'; exit 0; fi\nexit 0\n",
            marker.display(),
            version,
        ),
    )
    .unwrap();
    let mut permissions = fs::metadata(&executable).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(&executable, permissions).unwrap();

    let home = root.join("home");
    let config = root.join("config");
    fs::create_dir_all(&home).unwrap();
    fs::create_dir_all(&config).unwrap();
    if provider == "codex" {
        let codex_home = home.join(".codex");
        fs::create_dir_all(&codex_home).unwrap();
        fs::write(codex_home.join("auth.json"), b"synthetic auth state").unwrap();
    }
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(args)
        .env("HOME", &home)
        .env("XDG_CONFIG_HOME", &config)
        .env("PATH", bin)
        .output()
        .expect("clroom must run");
    (output, marker)
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
fn aggregate_resolved_preset_composition_is_bounded_before_provider_birth() {
    let root = scratch("aggregate-resolution-bound");
    let mut yaml = String::from("schema: clroom.presets.v1\npresets:\n");
    for index in 0..5 {
        yaml.push_str(&format!(
            "  p{index}:\n    providers:\n      codex:\n        args:\n"
        ));
        for arg_index in 0..256 {
            yaml.push_str(&format!("          - --preset-test-{index}-{arg_index}\n"));
        }
    }
    write_presets(&root, &yaml);

    let error = stderr(run(
        &root,
        &["codex", "--preset=p0,p1,p2,p3,p4", "--version"],
    ));
    assert_eq!(
        error,
        "CLROOM_PRESET_RESOLUTION_TOO_LARGE: selected preset composition exceeds the bounded launch budget; select fewer presets or reduce preset contents\n"
    );
}

#[test]
fn provider_global_option_values_that_look_like_auth_commands_are_not_commands() {
    let root = scratch("auth-word-as-later-provider-token");
    let (output, marker) = run_with_fake_provider(&root, "codex", &["codex", "--model", "login"]);
    assert!(marker.exists(), "login is consumed as the --model value");
    assert_ne!(
        String::from_utf8_lossy(&output.stderr),
        "ZERO_AUTH_REFUSAL: provider-native preauthenticated session unavailable or ambiguous; continue locally\n"
    );

    let root = scratch("auth-word-profile-value");
    let (output, marker) =
        run_with_fake_provider(&root, "codex", &["codex", "--profile", "auth"]);
    assert!(marker.exists(), "auth is consumed as the --profile value");
    assert_ne!(
        String::from_utf8_lossy(&output.stderr),
        "ZERO_AUTH_REFUSAL: provider-native preauthenticated session unavailable or ambiguous; continue locally\n"
    );
}

#[test]
fn auth_commands_after_provider_global_options_are_refused_before_provider_birth() {
    let cases: &[(&str, &[&str])] = &[
        ("codex", &["codex", "--profile", "safe", "login"]),
        ("codex", &["codex", "--model", "gpt-5", "logout"]),
        (
            "codex",
            &["codex", "-c", "model_reasoning_effort=high", "login"],
        ),
        ("claude", &["claude", "--model", "sonnet", "auth"]),
        (
            "claude",
            &["claude", "--permission-mode", "plan", "auth"],
        ),
    ];

    for (provider, args) in cases {
        let root = scratch("global-option-auth-command");
        let (output, marker) = run_with_fake_provider(&root, provider, args);
        assert!(
            !marker.exists(),
            "provider child must not start for arguments {args:?}"
        );
        assert_eq!(
            stderr(output),
            "ZERO_AUTH_REFUSAL: provider-native preauthenticated session unavailable or ambiguous; continue locally\n",
            "arguments: {args:?}"
        );
    }
}

#[test]
fn preset_provider_argv_cannot_shift_explicit_auth_commands_past_zero_auth() {
    let root = scratch("preset-auth-provider-argv-shift");
    write_presets(
        &root,
        r#"schema: clroom.presets.v1
presets:
  codex-safe:
    providers:
      codex:
        args:
          - --profile
          - safe
  claude-safe:
    providers:
      claude:
        args:
          - --model
          - sonnet
  codex-default:
    default-provider: codex
    providers:
      codex:
        args:
          - --profile
          - safe
"#,
    );

    let cases: &[(&str, &[&str])] = &[
        (
            "codex",
            &["codex", "--preset=codex-safe", "--profile", "safe", "login"],
        ),
        (
            "claude",
            &["claude", "--preset=claude-safe", "--model", "sonnet", "auth"],
        ),
        (
            "codex",
            &["--preset=codex-default", "--profile", "safe", "login"],
        ),
    ];

    for (provider, args) in cases {
        let case_root = scratch("preset-auth-provider-argv-shift-case");
        write_presets(
            &case_root,
            &fs::read_to_string(root.join("config/clroom/presets.yaml")).unwrap(),
        );
        let (output, marker) = run_with_fake_provider(&case_root, provider, args);
        assert!(
            !marker.exists(),
            "provider child must not start for arguments {args:?}"
        );
        assert_eq!(
            stderr(output),
            "ZERO_AUTH_REFUSAL: provider-native preauthenticated session unavailable or ambiguous; continue locally\n",
            "arguments: {args:?}"
        );
    }
}

#[test]
fn terminator_keeps_auth_looking_provider_data_literal() {
    let root = scratch("auth-word-after-provider-terminator");
    let (output, marker) =
        run_with_fake_provider(&root, "codex", &["codex", "--", "login"]);
    assert!(marker.exists(), "auth-looking data after -- remains literal");
    assert_ne!(
        String::from_utf8_lossy(&output.stderr),
        "ZERO_AUTH_REFUSAL: provider-native preauthenticated session unavailable or ambiguous; continue locally\n"
    );
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
