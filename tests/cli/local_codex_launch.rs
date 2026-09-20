use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::PathBuf,
    process::Command,
    sync::atomic::{AtomicU64, Ordering},
};

static SCRATCH_SEQUENCE: AtomicU64 = AtomicU64::new(0);

const CODEX_CLEAN_DEFAULTS: &str = "-c\0features.apps=false\0-c\0features.hooks=false\0-c\0features.plugins=false\0-c\0features.remote_plugin=false\0-c\0developer_instructions=\"\"\0-c\0notify=[]\0-c\0shell_environment_policy.inherit=\"none\"\0-c\0shell_environment_policy.include_only=[\"PATH\",\"HOME\",\"TMPDIR\",\"TERM\",\"COLORTERM\",\"LANG\",\"LC_ALL\",\"LC_CTYPE\",\"TZ\"]\0-c\0shell_environment_policy.ignore_default_excludes=false\0";

fn fake_codex() -> (PathBuf, PathBuf) {
    let dir = std::env::temp_dir().join(format!(
        "clroom-codex-launch-{}-{}",
        std::process::id(),
        SCRATCH_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let executable = dir.join("codex");
    let capture = dir.join("capture");
    let source = dir.join("fake-provider.rs");
    fs::write(
        &source,
        format!(
            r#"use std::{{env, fs}};
fn main() {{
    if env::args().nth(1).as_deref() == Some("--version") {{ println!("0.147.0"); return; }}
    assert!(env::var_os("CLROOM_INHERITED_MARKER").is_none());
    let args = env::args().skip(1).collect::<Vec<_>>();
    if args == ["exec", "--ignore-user-config", "--help"] {{
        println!("--ignore-user-config");
        return;
    }}
    fs::write({:?}, format!("{{}}\0", args.join("\0"))).unwrap();
    if args.iter().any(|argument| argument == "--exit-42") {{ std::process::exit(42); }}
}}
"#,
            capture
        ),
    )
    .unwrap();
    let output = Command::new("rustc")
        .args([source, PathBuf::from("-o"), executable.clone()])
        .output()
        .expect("rustc must start");
    assert!(output.status.success(), "fake provider must compile");
    fs::set_permissions(&executable, fs::Permissions::from_mode(0o700)).unwrap();
    (executable, capture)
}

fn fake_codex_requires_synthetic_clean_fixture() -> (PathBuf, PathBuf) {
    let dir = std::env::temp_dir().join(format!(
        "clroom-codex-preflight-{}-{}",
        std::process::id(),
        SCRATCH_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let executable = dir.join("codex");
    let capture = dir.join("capture");
    let source = dir.join("fake-provider.rs");
    fs::write(
        &source,
        format!(
            r#"use std::{{env, fs, path::PathBuf}};
fn main() {{
    if env::args().nth(1).as_deref() == Some("--version") {{ println!("0.147.0"); return; }}
    let args = env::args().skip(1).collect::<Vec<_>>();
    if args == ["exec", "--ignore-user-config", "--help"] {{
        let home = PathBuf::from(env::var("HOME").unwrap());
        let codex_home = PathBuf::from(env::var("CODEX_HOME").unwrap());
        if home == PathBuf::from("/") || codex_home == PathBuf::from("/") {{ fs::write({:?}, b"preflight=61").unwrap(); std::process::exit(61); }}
        let config = codex_home.join("config.toml");
        if fs::metadata(&config).is_err() {{ fs::write({:?}, b"preflight=62").unwrap(); std::process::exit(62); }}
        if fs::read_to_string(&config).is_ok() {{ fs::write({:?}, b"preflight=63").unwrap(); std::process::exit(63); }}
        if fs::write(&config, b"must stay denied").is_ok() {{ fs::write({:?}, b"preflight=64").unwrap(); std::process::exit(64); }}
        println!("--ignore-user-config");
        return;
    }}
    fs::write({:?}, format!("{{}}\0", args.join("\0"))).unwrap();
}}
"#,
            capture, capture, capture, capture, capture
        ),
    )
    .unwrap();
    let output = Command::new("rustc")
        .args([source, PathBuf::from("-o"), executable.clone()])
        .output()
        .expect("rustc must start");
    assert!(output.status.success(), "fake provider must compile");
    fs::set_permissions(&executable, fs::Permissions::from_mode(0o700)).unwrap();
    (executable, capture)
}

#[test]
fn codex_exec_preflight_uses_a_populated_synthetic_home_with_production_shape() {
    let (codex, capture) = fake_codex_requires_synthetic_clean_fixture();
    let root = codex.parent().unwrap().join("launch-home");
    let codex_home = root.join(".codex");
    fs::create_dir_all(&codex_home).unwrap();
    fs::write(codex_home.join("config.toml"), "synthetic-config\n").unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(["codex", "exec", "--ignore-user-config", "--help"])
        .env("PATH", codex.parent().unwrap())
        .env("HOME", &root)
        .env("CODEX_HOME", &codex_home)
        .output()
        .expect("clroom must run");

    assert_eq!(
        output.status.code(),
        Some(0),
        "production-shaped synthetic preflight must pass: stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    let observed = fs::read_to_string(&capture).unwrap();
    assert!(observed.starts_with(CODEX_CLEAN_DEFAULTS));
    assert!(observed.ends_with("exec\0--ignore-user-config\0--help\0"));
}

#[test]
fn codex_exec_without_native_clean_config_support_refuses_before_provider_launch() {
    let (codex, capture) = fake_codex();
    let unsupported_dir = codex.parent().unwrap().join("unsupported-bin");
    fs::create_dir(&unsupported_dir).unwrap();
    let source = unsupported_dir.join("fake-provider.rs");
    let unsupported = unsupported_dir.join("codex");
    fs::write(
        &source,
        format!(
            r#"use std::{{env, fs}};
fn main() {{
    if env::args().nth(1).as_deref() == Some("--version") {{ println!("0.147.0"); return; }}
    let args = env::args().skip(1).collect::<Vec<_>>();
    if args == ["exec", "--ignore-user-config", "--help"] {{ std::process::exit(64); }}
    fs::write({:?}, b"provider-born").unwrap();
}}
"#,
            capture
        ),
    )
    .unwrap();
    let output = Command::new("rustc")
        .args([source, PathBuf::from("-o"), unsupported.clone()])
        .output()
        .expect("rustc must start");
    assert!(output.status.success(), "fake provider must compile");
    fs::set_permissions(&unsupported, fs::Permissions::from_mode(0o700)).unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(["codex", "exec", "safe prompt"])
        .env("PATH", unsupported.parent().unwrap())
        .output()
        .expect("clroom must run");
    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&output.stderr).contains("CLROOM_CODEX_EXEC_UNSUPPORTED"));
    assert!(!capture.exists());
}

fn fake_codex_with_env_capture() -> (PathBuf, PathBuf, PathBuf) {
    let dir = std::env::temp_dir().join(format!(
        "clroom-codex-env-launch-{}-{}",
        std::process::id(),
        SCRATCH_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let executable = dir.join("codex");
    let capture = dir.join("capture");
    let env_capture = dir.join("env-capture");
    let source = dir.join("fake-provider.rs");
    fs::write(
        &source,
        format!(
            r#"use std::{{env, fs}};
fn main() {{
    if env::args().nth(1).as_deref() == Some("--version") {{ println!("0.147.0"); return; }}
    let args = env::args().skip(1).collect::<Vec<_>>();
    if args == ["exec", "--ignore-user-config", "--help"] {{
        println!("--ignore-user-config");
        return;
    }}
    fs::write({:?}, format!("{{}}\0", args.join("\0"))).unwrap();
    let status = ["RUNNER_REQUESTED", "RUNNER_UNREQUESTED"]
        .iter()
        .map(|name| format!("{{name}}={{}}", if env::var_os(name).is_some() {{ "present" }} else {{ "absent" }}))
        .collect::<Vec<_>>()
        .join("\n");
    fs::write({:?}, format!("{{status}}\n")).unwrap();
    if args.iter().any(|argument| argument == "--exit-42") {{ std::process::exit(42); }}
}}
"#,
            capture, env_capture
        ),
    )
    .unwrap();
    let output = Command::new("rustc")
        .args([source, PathBuf::from("-o"), executable.clone()])
        .output()
        .expect("rustc must start");
    assert!(output.status.success(), "fake provider must compile");
    fs::set_permissions(&executable, fs::Permissions::from_mode(0o700)).unwrap();
    (executable, capture, env_capture)
}

#[test]
fn direct_codex_command_launches_literal_local_child_and_returns_status() {
    let (codex, capture) = fake_codex();
    let path = codex.parent().unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(["codex", "exec", "--exit-42", "safe-value"])
        .env("PATH", path)
        .env("CLROOM_INHERITED_MARKER", "inherited")
        .output()
        .expect("clroom must run");
    assert_eq!(output.status.code(), Some(42));
    assert_eq!(
        fs::read_to_string(capture).unwrap(),
        format!("{CODEX_CLEAN_DEFAULTS}exec\0--ignore-user-config\0--exit-42\0safe-value\0")
    );
}

#[test]
fn codex_without_legacy_boundary_forwards_native_help() {
    let (codex, capture) = fake_codex();
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(["codex", "--help"])
        .env("PATH", codex.parent().unwrap())
        .env("CLROOM_INHERITED_MARKER", "must-not-inherit")
        .output()
        .expect("clroom must run");
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(
        fs::read_to_string(capture).unwrap(),
        format!("{CODEX_CLEAN_DEFAULTS}--help\0")
    );
}

#[test]
fn codex_sensitive_tail_refuses_before_child_construction() {
    let (codex, capture) = fake_codex();
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(["codex", "--api-key", "must-not-be-read"])
        .env("PATH", codex.parent().unwrap())
        .env("CLROOM_INHERITED_MARKER", "must-not-inherit")
        .output()
        .expect("clroom must run");
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    assert_eq!(
        String::from_utf8(output.stderr).unwrap(),
        "ZERO_AUTH_ARGUMENT_REFUSAL: sensitive argument refused before dispatch; continue locally\n"
    );
    assert!(!capture.exists());
}

#[test]
fn codex_unavailable_is_local_status_not_login_flow() {
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(["codex", "--help"])
        .env("PATH", "/definitely/not-a-clroom-command-path")
        .output()
        .expect("clroom must run");
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    assert_eq!(
        String::from_utf8(output.stderr).unwrap(),
        "LOCAL_CODEX_UNAVAILABLE: executable 'codex' not found; continue locally\n"
    );
}

#[test]
fn codex_pass_env_is_exact_and_denies_unrequested_names() {
    let (codex, capture, env_capture) = fake_codex_with_env_capture();
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(["codex", "--pass-env=RUNNER_REQUESTED", "exec", "--exit-42"])
        .env("PATH", codex.parent().unwrap())
        .env("RUNNER_REQUESTED", "synthetic-value-must-not-print")
        .env("RUNNER_UNREQUESTED", "synthetic-value-must-not-print")
        .output()
        .expect("clroom must run");
    assert_eq!(output.status.code(), Some(42));
    assert!(!String::from_utf8_lossy(&output.stdout).contains("synthetic-value-must-not-print"));
    assert!(!String::from_utf8_lossy(&output.stderr).contains("synthetic-value-must-not-print"));
    assert_eq!(
        fs::read_to_string(env_capture).unwrap(),
        "RUNNER_REQUESTED=present\nRUNNER_UNREQUESTED=absent\n"
    );
    let argv = fs::read_to_string(capture).unwrap();
    assert!(argv.contains("--ignore-user-config"));
    assert!(argv.contains("RUNNER_REQUESTED"));
    assert!(!argv.contains("RUNNER_UNREQUESTED"));
}

#[test]
fn codex_pass_env_rejects_wildcards_before_child_birth() {
    let (codex, capture, _env_capture) = fake_codex_with_env_capture();
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(["codex", "--pass-env=RUNNER_*"])
        .env("PATH", codex.parent().unwrap())
        .env("RUNNER_SECRET", "synthetic-value-must-not-print")
        .output()
        .expect("clroom must run");
    assert_eq!(output.status.code(), Some(2));
    assert_eq!(
        String::from_utf8(output.stderr).unwrap(),
        "CLROOM_ENV_SELECTOR_INVALID: invalid environment name; use --pass-env=NAME\n"
    );
    assert!(!capture.exists());
}
