use std::{
    fs,
    io::Write,
    os::unix::{fs::PermissionsExt, process::ExitStatusExt},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::atomic::{AtomicU64, Ordering},
};

static SCRATCH_SEQUENCE: AtomicU64 = AtomicU64::new(0);

const CODEX_CLEAN_DEFAULTS: &[&str] = &[
    "-c",
    "features.apps=false",
    "-c",
    "features.hooks=false",
    "-c",
    "features.plugins=false",
    "-c",
    "features.remote_plugin=false",
    "-c",
    "developer_instructions=\"\"",
    "-c",
    "notify=[]",
    "-c",
    "shell_environment_policy.inherit=\"none\"",
    "-c",
    "shell_environment_policy.include_only=[\"PATH\",\"HOME\",\"TMPDIR\",\"TERM\",\"COLORTERM\",\"LANG\",\"LC_ALL\",\"LC_CTYPE\",\"TZ\"]",
    "-c",
    "shell_environment_policy.ignore_default_excludes=false",
];

struct Scratch(PathBuf);

impl Scratch {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "clroom-isolated-launch-{}-{}",
            std::process::id(),
            SCRATCH_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
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

fn isolated_fixture() -> (Scratch, PathBuf, PathBuf, PathBuf, PathBuf) {
    let root = Scratch::new();
    let project = root.join("project");
    let home = root.join("home");
    let codex_home = root.join("codex-home");
    let bin = root.join("bin");
    fs::create_dir_all(project.join("canaries")).unwrap();
    fs::create_dir_all(home.join(".agents/skills/ambient")).unwrap();
    fs::create_dir_all(&codex_home).unwrap();
    fs::create_dir_all(&bin).unwrap();
    fs::write(project.join("canaries/PROJECT.md"), b"project\n").unwrap();
    fs::write(codex_home.join("AGENTS.md"), b"global\n").unwrap();
    fs::write(codex_home.join("config.toml"), b"not valid TOML\n").unwrap();
    fs::write(codex_home.join("auth.json"), b"synthetic auth state\n").unwrap();
    fs::write(
        home.join(".agents/skills/ambient/SKILL.md"),
        b"ambient skill\n",
    )
    .unwrap();
    let fake = bin.join("codex");
    fs::write(
        &fake,
        "#!/bin/sh\n\
         if [ \"$1\" = --version ]; then printf '0.147.0\\n'; exit 0; fi\n\
         if [ \"$1\" = exec ] && [ \"$2\" = --ignore-user-config ] && [ \"$3\" = --help ]; then printf -- '--ignore-user-config\\n'; exit 0; fi\n\
         /bin/cat \"$PWD/canaries/PROJECT.md\" >/dev/null || exit 70\n\
         /bin/cat \"$CODEX_HOME/AGENTS.md\" >/dev/null 2>&1 && exit 71\n\
         /bin/cat \"$HOME/.agents/skills/ambient/SKILL.md\" >/dev/null 2>&1 && exit 72\n\
         printf '%s\\0' \"$@\" > \"$PWD/.clroom-capture\"\n\
         for argument in \"$@\"; do\n\
           if [ \"$argument\" = \"--stdio\" ]; then\n\
             input=$(/bin/cat)\n\
             printf 'stdout:%s\\n' \"$input\"\n\
             printf 'stderr:%s\\n' \"$input\" >&2\n\
             exit 0\n\
           fi\n\
         done\n\
         exit 42\n",
    )
    .unwrap();
    fs::set_permissions(&fake, fs::Permissions::from_mode(0o700)).unwrap();
    (root, project, home, codex_home, bin)
}

fn command(project: &Path, home: &Path, codex_home: &Path, bin: &Path, _capture: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_clroom"));
    command
        .current_dir(project)
        .env("PATH", bin)
        .env("HOME", home)
        .env("CODEX_HOME", codex_home);
    command
}

fn expected_argv(user_args: &[&str]) -> Vec<u8> {
    let mut arguments = CODEX_CLEAN_DEFAULTS
        .iter()
        .chain(user_args)
        .map(|argument| (*argument).to_owned())
        .collect::<Vec<_>>();
    if let Some(index) = user_args
        .iter()
        .position(|argument| matches!(*argument, "exec" | "e"))
    {
        arguments.insert(
            CODEX_CLEAN_DEFAULTS.len() + index + 1,
            "--ignore-user-config".to_owned(),
        );
    }
    arguments
        .iter()
        .flat_map(|argument| argument.as_bytes().iter().copied().chain([0]))
        .collect()
}

fn expected_exec_argv(user_args: &[&str]) -> Vec<u8> {
    let mut arguments = vec!["exec"];
    arguments.extend_from_slice(user_args);
    expected_argv(&arguments)
}

fn assert_launch_contract_diagnostics_hidden(transcript: &str) {
    for diagnostic in ["Boundary:", "Boundary controls:", "Managed:", "Model:"] {
        assert!(
            !transcript.contains(diagnostic),
            "interactive launch leaked diagnostic {diagnostic:?}:\n{transcript}"
        );
    }
}

#[cfg(target_os = "macos")]
#[test]
fn invalid_codex_identity_refuses_without_launch_contract_diagnostics() {
    // Break caught: a failed preflight either launches Codex or reintroduces
    // internal launch-contract diagnostics into the interactive transcript.
    let (_root, project, home, codex_home, bin) = isolated_fixture();
    let fake = bin.join("codex");
    fs::write(
        &fake,
        "#!/bin/sh\nif [ \"$1\" = --version ]; then printf 'invalid-version\\n'; exit 0; fi\nexit 99\n",
    )
    .unwrap();
    fs::set_permissions(&fake, fs::Permissions::from_mode(0o700)).unwrap();

    let output = Command::new("/usr/bin/expect")
        .args([
            "-c",
            concat!(
                "set timeout 5\n",
                "spawn -noecho $env(CLROOM_TEST_BIN) codex --version\n",
                "expect eof\n",
                "set child_status [wait]\n",
                "exit [lindex $child_status 3]\n",
            ),
        ])
        .current_dir(&project)
        .env("CLROOM_TEST_BIN", env!("CARGO_BIN_EXE_clroom"))
        .env("PATH", &bin)
        .env("HOME", &home)
        .env("CODEX_HOME", &codex_home)
        .env("COLUMNS", "80")
        .env("TERM", "xterm-256color")
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(2));
    let transcript = String::from_utf8(output.stdout).unwrap().replace('\r', "");
    assert!(transcript.contains("CLEAN ROOM"));
    assert_launch_contract_diagnostics_hidden(&transcript);
    assert!(!project.join(".clroom-capture").exists());
}

#[cfg(target_os = "macos")]
#[test]
fn missing_codex_executable_refuses_without_launch_contract_diagnostics() {
    // Break caught: missing provider resolution reintroduces internal
    // launch-contract diagnostics instead of keeping them hidden.
    let (root, project, home, codex_home, _bin) = isolated_fixture();
    let empty_bin = root.join("empty-bin");
    fs::create_dir_all(&empty_bin).unwrap();
    let output = Command::new("/usr/bin/expect")
        .args([
            "-c",
            concat!(
                "set timeout 5\n",
                "spawn -noecho $env(CLROOM_TEST_BIN) codex --version\n",
                "expect eof\n",
                "set child_status [wait]\n",
                "exit [lindex $child_status 3]\n",
            ),
        ])
        .current_dir(&project)
        .env("CLROOM_TEST_BIN", env!("CARGO_BIN_EXE_clroom"))
        .env("PATH", &empty_bin)
        .env("HOME", &home)
        .env("CODEX_HOME", &codex_home)
        .env("COLUMNS", "80")
        .env("TERM", "xterm-256color")
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(2));
    let transcript = String::from_utf8(output.stdout).unwrap().replace('\r', "");
    assert!(transcript.contains("CLEAN ROOM"));
    assert_launch_contract_diagnostics_hidden(&transcript);
    assert!(!project.join(".clroom-capture").exists());
}

fn add_selective_skill_fixture(root: &Scratch, home: &Path, project: &Path) -> PathBuf {
    let global_skills = home.join(".agents/skills");
    let plugin = root.join("plugin-cache/superpowers");
    fs::create_dir_all(global_skills.join("arrow")).unwrap();
    fs::write(global_skills.join("arrow/SKILL.md"), b"exact\n").unwrap();
    fs::create_dir_all(project.join(".agents/skills/project-only")).unwrap();
    fs::write(
        project.join(".agents/skills/project-only/SKILL.md"),
        b"project\n",
    )
    .unwrap();
    fs::create_dir_all(plugin.join(".codex-plugin")).unwrap();
    fs::write(
        plugin.join(".codex-plugin/plugin.json"),
        br#"{"name":"superpowers","version":"1.0.0"}"#,
    )
    .unwrap();
    for name in ["systematic-debugging", "brainstorming"] {
        let target = global_skills.join(name);
        fs::create_dir_all(&target).unwrap();
        fs::write(target.join("SKILL.md"), format!("{name}\n")).unwrap();
    }
    plugin
}

#[test]
fn codex_handoff_preserves_literal_argv_exit_and_stdio_inside_the_isolated_boundary() {
    // Break caught: direct Codex execution lets the fake provider read ambient context.
    let (_root, project, home, codex_home, bin) = isolated_fixture();
    let capture = project.join(".clroom-capture");
    let output = command(&project, &home, &codex_home, &bin, &capture)
        .args(["codex", "exec", "--exit-42", "literal value"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(42));
    assert_eq!(
        fs::read(&capture).unwrap(),
        expected_exec_argv(&["--exit-42", "literal value"])
    );

    let mut child = command(&project, &home, &codex_home, &bin, &capture)
        .args(["codex", "exec", "--stdio"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(b"native streams\n")
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert_eq!(output.status, std::process::ExitStatus::from_raw(0));
    assert_eq!(output.stdout, b"stdout:native streams\n");
    assert_eq!(output.stderr, b"stderr:native streams\n");
    assert_eq!(
        fs::read(&capture).unwrap(),
        expected_exec_argv(&["--stdio"])
    );
}

#[test]
fn codex_handoff_launches_interactive_provider_with_persistent_clean_state() {
    let (_root, project, home, codex_home, bin) = isolated_fixture();
    let capture = project.join(".clroom-capture");
    let output = command(&project, &home, &codex_home, &bin, &capture)
        .args(["codex", "resume", "--last"])
        .output()
        .unwrap();
    assert_eq!(
        output.status.code(),
        Some(42),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(capture.exists());
    let state_root = codex_home.join(".clroom-clean-state-v1");
    assert!(state_root.join("home/auth.json").is_symlink());
    assert_eq!(state_root.parent(), Some(codex_home.as_path()));

    let second = command(&project, &home, &codex_home, &bin, &capture)
        .args(["codex", "resume", "--last"])
        .output()
        .unwrap();
    assert_eq!(second.status.code(), Some(42));
    assert!(state_root.join("home/auth.json").is_symlink());
}

#[test]
fn codex_handoff_keeps_explicit_user_overrides_after_clean_defaults() {
    let (_root, project, home, codex_home, bin) = isolated_fixture();
    let capture = project.join(".clroom-capture");
    let user_args = [
        "--enable",
        "apps",
        "--enable",
        "hooks",
        "--enable",
        "plugins",
        "-c",
        "developer_instructions=\"owner\"",
        "-c",
        "notify=[\"owner\"]",
        "features",
        "list",
    ];

    let output = command(&project, &home, &codex_home, &bin, &capture)
        .args(["codex", "exec"])
        .args(user_args)
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(42));
    assert_eq!(fs::read(&capture).unwrap(), expected_exec_argv(&user_args));
}

#[test]
fn codex_handoff_admits_exact_native_skills_for_this_run() {
    // Break caught: selection is forwarded to Codex or the sandbox still blocks
    // explicitly invited skills while admitting unrelated global skills.
    let (root, project, home, codex_home, bin) = isolated_fixture();
    let plugin = add_selective_skill_fixture(&root, &home, &project);
    let capture = project.join(".clroom-capture");
    let fake = bin.join("codex");
    fs::write(
        &fake,
        "#!/bin/sh\n\
         if [ \"$1\" = --version ]; then printf '0.147.0\\n'; exit 0; fi\n\
         if [ \"$1\" = exec ] && [ \"$2\" = --ignore-user-config ] && [ \"$3\" = --help ]; then printf -- '--ignore-user-config\\n'; exit 0; fi\n\
         /bin/cat \"$PWD/.agents/skills/project-only/SKILL.md\" >/dev/null || exit 73\n\
         /bin/cat \"$HOME/.agents/skills/arrow/SKILL.md\" >/dev/null || exit 74\n\
         /bin/cat \"$HOME/.agents/skills/systematic-debugging/SKILL.md\" >/dev/null || exit 75\n\
         /bin/cat \"$HOME/.agents/skills/brainstorming/SKILL.md\" >/dev/null || exit 76\n\
         /bin/cat \"$HOME/.agents/skills/ambient/SKILL.md\" >/dev/null 2>&1 && exit 77\n\
         printf '%s\\0' \"$@\" > \"$PWD/.clroom-capture\"\n\
         exit 42\n",
    )
    .unwrap();
    fs::set_permissions(&fake, fs::Permissions::from_mode(0o700)).unwrap();

    let output = command(&project, &home, &codex_home, &bin, &capture)
        .args([
            "codex",
            "exec",
            "--skill-set=arrow,systematic-debugging,brainstorming",
            "--exit-42",
            "literal value",
        ])
        .env(
            "CLROOM_PROJECT_SKILL",
            project.join(".agents/skills/project-only/SKILL.md"),
        )
        .env(
            "CLROOM_EXACT_SKILL",
            home.join(".agents/skills/arrow/SKILL.md"),
        )
        .env(
            "CLROOM_NAMESPACE_SKILL_A",
            plugin.join("skills/systematic-debugging/SKILL.md"),
        )
        .env(
            "CLROOM_NAMESPACE_SKILL_B",
            plugin.join("skills/brainstorming/SKILL.md"),
        )
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(42));
    assert_eq!(
        fs::read(&capture).unwrap(),
        expected_exec_argv(&["--exit-42", "literal value"])
    );
}

#[test]
fn codex_handoff_admits_one_native_skill_without_its_siblings() {
    let (root, project, home, codex_home, bin) = isolated_fixture();
    let plugin = add_selective_skill_fixture(&root, &home, &project);
    let capture = project.join(".clroom-capture");
    let fake = bin.join("codex");
    fs::write(
        &fake,
        "#!/bin/sh\n\
         if [ \"$1\" = --version ]; then printf '0.147.0\\n'; exit 0; fi\n\
         if [ \"$1\" = exec ] && [ \"$2\" = --ignore-user-config ] && [ \"$3\" = --help ]; then printf -- '--ignore-user-config\\n'; exit 0; fi\n\
         /bin/cat \"$PWD/.agents/skills/project-only/SKILL.md\" >/dev/null || exit 73\n\
         /bin/cat \"$HOME/.agents/skills/arrow/SKILL.md\" >/dev/null || exit 74\n\
         /bin/cat \"$HOME/.agents/skills/systematic-debugging/SKILL.md\" >/dev/null || exit 75\n\
         /bin/cat \"$HOME/.agents/skills/brainstorming/SKILL.md\" >/dev/null 2>&1 && exit 76\n\
         /bin/cat \"$HOME/.agents/skills/ambient/SKILL.md\" >/dev/null 2>&1 && exit 77\n\
         printf '%s\\0' \"$@\" > \"$PWD/.clroom-capture\"\n\
         exit 42\n",
    )
    .unwrap();
    fs::set_permissions(&fake, fs::Permissions::from_mode(0o700)).unwrap();

    let output = command(&project, &home, &codex_home, &bin, &capture)
        .args([
            "codex",
            "exec",
            "--skill-set=arrow,systematic-debugging",
            "features",
            "list",
        ])
        .env(
            "CLROOM_PROJECT_SKILL",
            project.join(".agents/skills/project-only/SKILL.md"),
        )
        .env(
            "CLROOM_EXACT_SKILL",
            home.join(".agents/skills/arrow/SKILL.md"),
        )
        .env(
            "CLROOM_NAMESPACE_SKILL_A",
            plugin.join("skills/systematic-debugging/SKILL.md"),
        )
        .env(
            "CLROOM_NAMESPACE_SKILL_B",
            plugin.join("skills/brainstorming/SKILL.md"),
        )
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(42));
    assert_eq!(
        fs::read(&capture).unwrap(),
        expected_exec_argv(&["features", "list"])
    );
}

#[test]
fn codex_handoff_rejects_invalid_and_unknown_selectors_before_exec() {
    let (root, project, home, codex_home, bin) = isolated_fixture();
    add_selective_skill_fixture(&root, &home, &project);
    let capture = project.join(".clroom-capture");

    for (selector, expected) in [
        ("", "invalid skill selector"),
        ("missing", "unknown skill selector 'missing'"),
    ] {
        let skills_argument = format!("--skill-set={selector}");
        let output = command(&project, &home, &codex_home, &bin, &capture)
            .args(["codex", skills_argument.as_str(), "--version"])
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(2), "selector={selector}");
        let stderr = String::from_utf8(output.stderr).unwrap();
        assert!(
            stderr.contains(expected),
            "selector={selector}, stderr={stderr}"
        );
        assert!(!capture.exists(), "selector={selector}");
    }
}

#[test]
fn codex_handoff_prefers_codex_local_duplicates_and_denies_agents_bodies() {
    // Break caught: granting both duplicate bodies makes Codex expose duplicate
    // picker rows even though the user selected each logical skill only once.
    let (root, project, home, codex_home, bin) = isolated_fixture();
    let first_plugin = add_selective_skill_fixture(&root, &home, &project);
    let codex_skills = codex_home.join("skills");
    fs::create_dir_all(codex_skills.join("arrow")).unwrap();
    fs::write(
        codex_skills.join("arrow/SKILL.md"),
        b"second arrow source\n",
    )
    .unwrap();

    let second_plugin = root.join("second-plugin-cache/superpowers");
    fs::create_dir_all(second_plugin.join("skills/systematic-debugging")).unwrap();
    fs::write(
        second_plugin.join("skills/systematic-debugging/SKILL.md"),
        b"second systematic-debugging source\n",
    )
    .unwrap();
    fs::create_dir_all(codex_skills.join("systematic-debugging")).unwrap();
    fs::write(
        codex_skills.join("systematic-debugging/SKILL.md"),
        b"codex systematic-debugging source\n",
    )
    .unwrap();

    let capture = project.join(".clroom-capture");
    let fake = bin.join("codex");
    fs::write(
        &fake,
        "#!/bin/sh\n\
         if [ \"$1\" = --version ]; then printf '0.147.0\\n'; exit 0; fi\n\
         if [ \"$1\" = exec ] && [ \"$2\" = --ignore-user-config ] && [ \"$3\" = --help ]; then printf -- '--ignore-user-config\\n'; exit 0; fi\n\
         /bin/ls \"$HOME/.agents/skills\" >/dev/null || exit 73\n\
         /bin/ls \"$CODEX_HOME/skills\" >/dev/null || exit 74\n\
         /bin/cat \"$CODEX_HOME/skills/arrow/SKILL.md\" >/dev/null || exit 75\n\
         /bin/cat \"$HOME/.agents/skills/arrow/SKILL.md\" >/dev/null 2>&1 && exit 76\n\
         /bin/cat \"$CODEX_HOME/skills/systematic-debugging/SKILL.md\" >/dev/null || exit 77\n\
         /bin/cat \"$HOME/.agents/skills/systematic-debugging/SKILL.md\" >/dev/null 2>&1 && exit 78\n\
         /bin/cat \"$HOME/.agents/skills/brainstorming/SKILL.md\" >/dev/null 2>&1 && exit 79\n\
         printf '%s\\0' \"$@\" > \"$PWD/.clroom-capture\"\n\
         exit 42\n",
    )
    .unwrap();
    fs::set_permissions(&fake, fs::Permissions::from_mode(0o700)).unwrap();

    let output = command(&project, &home, &codex_home, &bin, &capture)
        .args([
            "codex",
            "exec",
            "--skill-set=arrow,systematic-debugging",
            "--version",
        ])
        .env("CLROOM_ARROW_CODEX", codex_skills.join("arrow/SKILL.md"))
        .env(
            "CLROOM_ARROW_AGENTS",
            home.join(".agents/skills/arrow/SKILL.md"),
        )
        .env(
            "CLROOM_SYSTEMATIC_CODEX",
            second_plugin.join("skills/systematic-debugging/SKILL.md"),
        )
        .env(
            "CLROOM_SYSTEMATIC_AGENTS",
            first_plugin.join("skills/systematic-debugging/SKILL.md"),
        )
        .env(
            "CLROOM_UNSELECTED",
            first_plugin.join("skills/brainstorming/SKILL.md"),
        )
        .output()
        .unwrap();

    assert_eq!(
        output.status.code(),
        Some(42),
        "stderr={}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        fs::read(&capture).unwrap(),
        expected_exec_argv(&["--version"])
    );
}

#[test]
fn codex_handoff_expands_multiple_named_sets_and_direct_skills_without_rewriting_config() {
    // Break caught: @set references leak to Codex, overlapping sets fail, or
    // clroom mutates the human-owned YAML while composing this launch.
    let (root, project, home, codex_home, bin) = isolated_fixture();
    let plugin = add_selective_skill_fixture(&root, &home, &project);
    let capture = project.join(".clroom-capture");
    let fake = bin.join("codex");
    fs::write(
        &fake,
        "#!/bin/sh\n\
         if [ \"$1\" = --version ]; then printf '0.147.0\\n'; exit 0; fi\n\
         if [ \"$1\" = exec ] && [ \"$2\" = --ignore-user-config ] && [ \"$3\" = --help ]; then printf -- '--ignore-user-config\\n'; exit 0; fi\n\
         /bin/cat \"$PWD/.agents/skills/project-only/SKILL.md\" >/dev/null || exit 73\n\
         /bin/cat \"$HOME/.agents/skills/arrow/SKILL.md\" >/dev/null || exit 74\n\
         /bin/cat \"$HOME/.agents/skills/systematic-debugging/SKILL.md\" >/dev/null || exit 75\n\
         /bin/cat \"$HOME/.agents/skills/brainstorming/SKILL.md\" >/dev/null || exit 76\n\
         /bin/cat \"$HOME/.agents/skills/ambient/SKILL.md\" >/dev/null 2>&1 && exit 77\n\
         printf '%s\\0' \"$@\" > \"$PWD/.clroom-capture\"\n\
         exit 42\n",
    )
    .unwrap();
    fs::set_permissions(&fake, fs::Permissions::from_mode(0o700)).unwrap();

    let config_home = root.join("config");
    let config = config_home.join("clroom/skill-sets.yaml");
    fs::create_dir_all(config.parent().unwrap()).unwrap();
    let yaml = b"review:\n  - arrow\n  - systematic-debugging\ndebugging:\n  - brainstorming\n  - arrow\ndocumentation:\n  - brainstorming\n";
    fs::write(&config, yaml).unwrap();

    let output = command(&project, &home, &codex_home, &bin, &capture)
        .args([
            "codex",
            "exec",
            "--skill-set=@review,@debugging,@documentation,arrow",
            "features",
            "list",
        ])
        .env("XDG_CONFIG_HOME", &config_home)
        .env(
            "CLROOM_PROJECT_SKILL",
            project.join(".agents/skills/project-only/SKILL.md"),
        )
        .env(
            "CLROOM_EXACT_SKILL",
            home.join(".agents/skills/arrow/SKILL.md"),
        )
        .env(
            "CLROOM_NAMESPACE_SKILL_A",
            plugin.join("skills/systematic-debugging/SKILL.md"),
        )
        .env(
            "CLROOM_NAMESPACE_SKILL_B",
            plugin.join("skills/brainstorming/SKILL.md"),
        )
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(42));
    assert_eq!(
        fs::read(&capture).unwrap(),
        expected_exec_argv(&["features", "list"])
    );
    assert_eq!(fs::read(&config).unwrap(), yaml);
}

#[test]
fn codex_handoff_rejects_invalid_named_sets_before_exec_without_echoing_yaml() {
    // Break caught: a missing, unknown, malformed, or nested set reaches Codex
    // or exposes the user's config content in an error.
    for (name, yaml, selector, expected) in [
        (
            "missing-file",
            None,
            "@review",
            "skill-set file is unavailable",
        ),
        (
            "unknown-set",
            Some("review:\n  - arrow\n"),
            "@missing",
            "unknown skill set '@missing'",
        ),
        (
            "malformed-yaml",
            Some("PRIVATE_MARKER: [\n"),
            "@review",
            "skill-set file is invalid",
        ),
        (
            "empty-set",
            Some("review: []\n"),
            "@review",
            "skill-set file is invalid",
        ),
        (
            "invalid-selector",
            Some("review:\n  - invalid:selector:shape\n"),
            "@review",
            "skill-set file is invalid",
        ),
        (
            "nested-set",
            Some("review:\n  - '@debugging'\n"),
            "@review",
            "nested skill set '@debugging' is not allowed",
        ),
    ] {
        let (root, project, home, codex_home, bin) = isolated_fixture();
        add_selective_skill_fixture(&root, &home, &project);
        let capture = project.join(".clroom-capture");
        let config_home = root.join("config");
        let config = config_home.join("clroom/skill-sets.yaml");
        if let Some(yaml) = yaml {
            fs::create_dir_all(config.parent().unwrap()).unwrap();
            fs::write(&config, yaml).unwrap();
        }

        let argument = format!("--skill-set={selector}");
        let output = command(&project, &home, &codex_home, &bin, &capture)
            .args(["codex", argument.as_str(), "--version"])
            .env("XDG_CONFIG_HOME", &config_home)
            .output()
            .unwrap();

        assert_eq!(output.status.code(), Some(2), "case={name}");
        let stderr = String::from_utf8(output.stderr).unwrap();
        assert!(stderr.contains(expected), "case={name}, stderr={stderr}");
        assert!(
            stderr.contains(config.to_str().unwrap()),
            "case={name}, stderr={stderr}"
        );
        assert!(!stderr.contains("PRIVATE_MARKER"), "case={name}");
        assert!(!capture.exists(), "case={name}");
    }
}

#[test]
fn codex_handoff_rejects_a_relative_xdg_skill_set_path_before_exec() {
    // Break caught: an unsafe explicit config root silently falls back to HOME,
    // making clroom read a different set file than the user requested.
    let (root, project, home, codex_home, bin) = isolated_fixture();
    add_selective_skill_fixture(&root, &home, &project);
    let capture = project.join(".clroom-capture");

    let output = command(&project, &home, &codex_home, &bin, &capture)
        .args(["codex", "--skill-set=@review", "--version"])
        .env("XDG_CONFIG_HOME", "relative/config")
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(2));
    assert_eq!(
        String::from_utf8(output.stderr).unwrap(),
        "CLROOM_SKILL_SET_CONFIG_PATH_INVALID: skill-set config root is unavailable\n"
    );
    assert!(!capture.exists());
}

#[test]
fn codex_handoff_forwards_the_unreleased_old_skills_spelling_to_codex() {
    // Break caught: clroom keeps two launcher flags for one concept and can
    // never forward a future provider-native --skills option.
    let (_root, project, home, codex_home, bin) = isolated_fixture();
    let capture = project.join(".clroom-capture");
    let user_args = ["--skills=provider-native", "--version"];

    let output = command(&project, &home, &codex_home, &bin, &capture)
        .args(["codex", "exec"])
        .args(user_args)
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(42));
    assert_eq!(fs::read(&capture).unwrap(), expected_exec_argv(&user_args));
}

#[test]
fn codex_handoff_refuses_when_home_is_not_supplied() {
    // Break caught: a missing isolation input silently falls back to ambient Codex.
    let (_root, project, home, codex_home, bin) = isolated_fixture();
    let capture = bin.join("missing-home-capture");
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .current_dir(&project)
        .args(["codex", "--help"])
        .env("PATH", &bin)
        .env_remove("HOME")
        .env("CODEX_HOME", &codex_home)
        .env("CLROOM_PROJECT_CANARY", project.join("canaries/PROJECT.md"))
        .env("CLROOM_GLOBAL_AGENTS", codex_home.join("AGENTS.md"))
        .env(
            "CLROOM_AMBIENT_SKILL",
            home.join(".agents/skills/ambient/SKILL.md"),
        )
        .env("CLROOM_CAPTURE_PATH", &capture)
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
    assert_eq!(
        String::from_utf8(output.stderr).unwrap(),
        "CLROOM_ISOLATION_INVALID: HOME is unavailable; continue locally\n"
    );
    assert!(!capture.exists());
    assert!(!home.join("unused").exists());
}
