use std::{
    ffi::OsString,
    fs,
    os::unix::{ffi::OsStringExt, fs::PermissionsExt},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::atomic::{AtomicU64, Ordering},
    thread,
    time::{Duration, Instant},
};

static SCRATCH_SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct Scratch(PathBuf);

struct ProjectionResidue(Vec<PathBuf>);

struct ChildGuard(Option<Child>);

struct ProcessGuard(Option<u32>);

impl ChildGuard {
    fn id(&self) -> u32 {
        self.0.as_ref().unwrap().id()
    }

    fn wait_after_signal(&mut self) {
        if let Some(mut child) = self.0.take() {
            let _ = child.wait();
        }
    }
}

impl Drop for ChildGuard {
    fn drop(&mut self) {
        if let Some(mut child) = self.0.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

impl ProcessGuard {
    fn stop(&mut self) {
        if let Some(pid) = self.0.take() {
            let _ = signal_process(pid, "TERM");
            wait_for_process_exit(pid);
        }
    }
}

impl Drop for ProcessGuard {
    fn drop(&mut self) {
        if let Some(pid) = self.0.take() {
            let _ = signal_process(pid, "KILL");
        }
    }
}

impl Drop for ProjectionResidue {
    fn drop(&mut self) {
        for path in &self.0 {
            let _ = fs::remove_dir_all(path);
        }
    }
}

impl Scratch {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "clroom-claude-launch-{}-{}",
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

fn fixture() -> (Scratch, PathBuf, PathBuf, PathBuf, PathBuf) {
    let root = Scratch::new();
    let project = root.join("project");
    let home = root.join("home");
    let bin = root.join("bin");
    let capture = home.join("capture");
    fs::create_dir_all(project.join(".claude/skills/project-only")).unwrap();
    fs::create_dir_all(home.join(".claude/skills/arrow")).unwrap();
    fs::create_dir_all(home.join(".claude/skills/ambient")).unwrap();
    for root in [".ssh", ".aws", ".config/gcloud", ".azure"] {
        fs::create_dir_all(home.join(root)).unwrap();
        fs::write(home.join(root).join("canary"), b"synthetic\n").unwrap();
    }
    fs::create_dir_all(&bin).unwrap();
    fs::write(project.join("CLAUDE.md"), b"project context\n").unwrap();
    fs::write(
        project.join(".claude/skills/project-only/SKILL.md"),
        b"project skill\n",
    )
    .unwrap();
    fs::write(home.join(".claude/CLAUDE.md"), b"global instruction\n").unwrap();
    fs::write(home.join(".claude/settings.json"), b"{\"hooks\":{}}\n").unwrap();
    fs::write(
        home.join(".claude.json"),
        b"{\"hasCompletedOnboarding\":true}\n",
    )
    .unwrap();
    fs::write(home.join(".claude/skills/arrow/SKILL.md"), b"arrow\n").unwrap();
    fs::write(home.join(".claude/skills/ambient/SKILL.md"), b"ambient\n").unwrap();

    let plugin = home.join(".codex/plugins/cache/superpowers");
    fs::create_dir_all(plugin.join(".claude-plugin")).unwrap();
    fs::create_dir_all(plugin.join("skills/systematic-debugging")).unwrap();
    fs::write(
        plugin.join(".claude-plugin/plugin.json"),
        br#"{"name":"superpowers","version":"1.0.0"}"#,
    )
    .unwrap();
    fs::write(
        plugin.join("skills/systematic-debugging/SKILL.md"),
        b"systematic debugging\n",
    )
    .unwrap();
    std::os::unix::fs::symlink(
        plugin.join("skills/systematic-debugging"),
        home.join(".claude/skills/systematic-debugging"),
    )
    .unwrap();
    let outside = root.join("outside-skill");
    fs::create_dir_all(&outside).unwrap();
    fs::write(outside.join("SKILL.md"), b"must stay outside\n").unwrap();
    std::os::unix::fs::symlink(&outside, home.join(".claude/skills/escape")).unwrap();
    fs::create_dir_all(home.join(".config/clroom")).unwrap();
    fs::write(
        home.join(".config/clroom/skill-sets.yaml"),
        b"saved:\n  - arrow\n  - superpowers:systematic-debugging\n",
    )
    .unwrap();

    let fake = bin.join("claude");
    fs::write(
        &fake,
        "#!/bin/sh\n\
         if [ \"$1\" = --version ]; then printf '2.1.223\\n'; exit 0; fi\n\
         [ -z \"${CLAUDE_CONFIG_DIR+x}\" ] || exit 79\n\
         [ -r \"$HOME/.claude.json\" ] || exit 80\n\
         [ \"$CLAUDE_CODE_DISABLE_AUTO_MEMORY\" = 1 ] || exit 82\n\
         [ \"$CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN\" = 1 ] || exit 87\n\
         [ \"$CLAUDE_CODE_SUBPROCESS_ENV_SCRUB\" = 1 ] || exit 96\n\
         [ -r \"$PWD/CLAUDE.md\" ] || exit 71\n\
         [ -r \"$PWD/.claude/skills/project-only/SKILL.md\" ] || exit 72\n\
         [ ! -r \"$HOME/.claude/CLAUDE.md\" ] || exit 83\n\
         [ ! -r \"$HOME/.claude/settings.json\" ] || exit 84\n\
         [ -r \"$HOME/.claude/skills/arrow/SKILL.md\" ] || exit 86\n\
         [ ! -r \"$HOME/.claude/skills/ambient/SKILL.md\" ] || exit 85\n\
         projection=\n\
         previous=\n\
         probe_env=\n\
         for argument in \"$@\"; do\n\
           if [ \"$previous\" = add_dir ]; then projection=$argument; previous=; continue; fi\n\
           case \"$argument\" in\n\
             --setting-sources) previous=sources ;;\n\
             project,local) [ \"$previous\" = sources ] || exit 73; previous= ;;\n\
             --strict-mcp-config) : ;;\n\
             --add-dir) previous=add_dir ;;\n\
             --clroom-env-probe) probe_env=1 ;;\n\
           esac\n\
         done\n\
         [ -n \"$projection\" ] || exit 74\n\
         [ ! -e \"$projection/.claude-plugin\" ] || exit 75\n\
         [ -r \"$projection/.claude/skills/arrow/SKILL.md\" ] || exit 76\n\
         [ -r \"$projection/.claude/skills/systematic-debugging/SKILL.md\" ] || exit 77\n\
         [ ! -e \"$projection/.claude/skills/ambient\" ] || exit 78\n\
         if [ -f \"$HOME/.clroom-hold-provider\" ]; then\n\
           printf '%s\n' \"$projection\" > \"$HOME/capture.projection-path\"\n\
           printf '%s\n' \"$$\" > \"$HOME/capture.provider-pid\"\n\
           trap 'exit 0' TERM INT\n\
           while :; do /bin/sleep 1; done\n\
         fi\n\
         if [ -f \"$HOME/.clroom-probe-protected-writes\" ]; then\n\
           if printf 'tampered\n' 2>/dev/null >> \"$HOME/.claude/skills/arrow/SKILL.md\"; then exit 88; fi\n\
           if mkdir \"$projection/tampered\" 2>/dev/null; then exit 89; fi\n\
           printf 'project-write\n' >> \"$PWD/CLAUDE.md\" || exit 97\n\
           for path in \"$HOME/.ssh/canary\" \"$HOME/.aws/canary\" \"$HOME/.config/gcloud/canary\" \"$HOME/.azure/canary\"; do\n\
             /bin/cat \"$path\" >/dev/null 2>&1 && exit 98\n\
             printf 'blocked\n' >> \"$path\" 2>/dev/null && exit 99\n\
           done\n\
         fi\n\
         if [ -n \"$probe_env\" ]; then\n\
           [ -z \"${UNRELATED_TOKEN+x}\" ] || exit 90\n\
           [ -z \"${UNRELATED_SECRET+x}\" ] || exit 91\n\
           [ -z \"${UNRELATED_KEY+x}\" ] || exit 92\n\
           [ -z \"${MCP_CONFIG+x}\" ] || exit 93\n\
           [ -n \"${TERM+x}\" ] || exit 94\n\
           [ -n \"${LANG+x}\" ] || exit 95\n\
         fi\n\
         printf '%s' \"${CLAUDE_CONFIG_DIR-unset}\" > \"$HOME/capture.config\"\n\
         printf '%s\\0' \"$@\" > \"$HOME/capture\"\n\
         exit 42\n",
    )
    .unwrap();
    fs::set_permissions(&fake, fs::Permissions::from_mode(0o700)).unwrap();
    (root, project, home, bin, capture)
}

#[test]
fn claude_projection_exposes_only_selected_skills_as_live_native_links() {
    let (_root, _project, home, _bin, _capture) = fixture();
    let source = home.join(".claude/skills/arrow");
    let helper = source.join("run.sh");
    fs::write(&helper, b"#!/bin/sh\nexit 0\n").unwrap();
    fs::set_permissions(&helper, fs::Permissions::from_mode(0o700)).unwrap();

    let projection =
        clroom::adapters::claude::projection::project(&home, &["arrow".to_owned()]).unwrap();
    let selected = projection.add_dir.join(".claude/skills/arrow");
    let projected_helper = selected.join("run.sh");

    assert!(selected.is_dir());
    assert!(
        fs::symlink_metadata(&selected)
            .unwrap()
            .file_type()
            .is_symlink(),
        "Claude must receive a native live link to the selected skill"
    );
    assert_eq!(
        fs::canonicalize(&selected).unwrap(),
        fs::canonicalize(&source).unwrap()
    );
    assert_eq!(fs::read(selected.join("SKILL.md")).unwrap(), b"arrow\n");
    assert_eq!(fs::read(&projected_helper).unwrap(), b"#!/bin/sh\nexit 0\n");
    assert_ne!(
        fs::metadata(projected_helper).unwrap().permissions().mode() & 0o111,
        0
    );
    assert!(!projection.add_dir.join(".claude-plugin").exists());
    assert!(!projection.add_dir.join(".claude/skills/ambient").exists());
    assert!(
        projection
            .allowed_source_paths()
            .contains(&fs::canonicalize(&source).unwrap()),
        "the sandbox must allow the live selected source"
    );

    fs::write(source.join("SKILL.md"), b"arrow updated\n").unwrap();
    assert_eq!(
        fs::read(selected.join("SKILL.md")).unwrap(),
        b"arrow updated\n",
        "an edit made during a long session must be visible immediately"
    );
}

#[test]
fn claude_projection_provider_view_is_canonical_and_inside_storage() {
    let (_root, _project, home, _bin, _capture) = fixture();
    let projection =
        clroom::adapters::claude::projection::project(&home, &["arrow".to_owned()]).unwrap();

    assert_eq!(
        projection.add_dir,
        fs::canonicalize(&projection.add_dir).unwrap(),
        "provider-facing view must use canonical spelling"
    );
    assert!(
        projection
            .add_dir
            .starts_with(fs::canonicalize(projection.storage_root()).unwrap()),
        "provider-facing view must remain inside canonical projection storage"
    );
    assert!(
        projection
            .add_dir
            .join(".claude/skills/arrow/SKILL.md")
            .is_file()
    );
}

#[test]
fn claude_projection_accepts_a_complete_plugin_namespace_from_claude_cache() {
    let root = Scratch::new();
    let home = root.join("home");
    let plugin = home.join(".claude/plugins/cache/claude-plugins-official/superpowers/6.3.0");
    fs::create_dir_all(plugin.join(".claude-plugin")).unwrap();
    fs::create_dir_all(plugin.join("skills/brainstorming")).unwrap();
    fs::create_dir_all(plugin.join("skills/systematic-debugging")).unwrap();
    fs::create_dir_all(home.join(".agents/skills")).unwrap();
    fs::write(
        plugin.join(".claude-plugin/plugin.json"),
        br#"{"name":"superpowers","version":"6.3.0"}"#,
    )
    .unwrap();
    fs::write(
        plugin.join("skills/brainstorming/SKILL.md"),
        b"brainstorming\n",
    )
    .unwrap();
    fs::write(
        plugin.join("skills/systematic-debugging/SKILL.md"),
        b"systematic debugging\n",
    )
    .unwrap();
    std::os::unix::fs::symlink(
        plugin.join("skills/brainstorming"),
        home.join(".agents/skills/brainstorming"),
    )
    .unwrap();
    std::os::unix::fs::symlink(
        plugin.join("skills/systematic-debugging"),
        home.join(".agents/skills/systematic-debugging"),
    )
    .unwrap();

    let projection =
        clroom::adapters::claude::projection::project(&home, &["superpowers".to_owned()]).unwrap();

    assert_eq!(projection.selected_global_skills, 2);
    assert!(
        projection
            .add_dir
            .join(".claude/skills/brainstorming/SKILL.md")
            .is_file()
    );
    assert!(
        projection
            .add_dir
            .join(".claude/skills/systematic-debugging/SKILL.md")
            .is_file()
    );
}

#[test]
fn claude_projections_are_session_scoped_and_drop_never_removes_skill_sources() {
    let (_root, _project, home, _bin, _capture) = fixture();
    let source = home.join(".claude/skills/arrow");

    let first =
        clroom::adapters::claude::projection::project(&home, &["arrow".to_owned()]).unwrap();
    let second =
        clroom::adapters::claude::projection::project(&home, &["arrow".to_owned()]).unwrap();
    let first_add_dir = first.add_dir.clone();
    let second_add_dir = second.add_dir.clone();

    assert_ne!(first_add_dir, second_add_dir);
    assert_eq!(
        fs::canonicalize(first_add_dir.join(".claude/skills/arrow")).unwrap(),
        fs::canonicalize(&source).unwrap()
    );
    assert_eq!(
        fs::canonicalize(second_add_dir.join(".claude/skills/arrow")).unwrap(),
        fs::canonicalize(&source).unwrap()
    );

    drop(first);
    assert!(!first_add_dir.exists());
    assert!(
        second_add_dir
            .join(".claude/skills/arrow/SKILL.md")
            .is_file()
    );
    assert!(source.join("SKILL.md").is_file());

    drop(second);
    assert!(!second_add_dir.exists());
    assert_eq!(fs::read(source.join("SKILL.md")).unwrap(), b"arrow\n");
}

#[test]
fn claude_projection_reaps_only_marked_dead_clroom_residue() {
    let (_root, _project, home, _bin, _capture) = fixture();
    let sequence = SCRATCH_SEQUENCE.fetch_add(7, Ordering::Relaxed);
    let dead_pid = i32::MAX as u32;
    let live_pid = std::process::id();
    let live_start = String::from_utf8(
        Command::new("/bin/ps")
            .args(["-p", &live_pid.to_string(), "-o", "lstart="])
            .output()
            .unwrap()
            .stdout,
    )
    .unwrap()
    .trim()
    .to_owned();
    let app_root = std::env::temp_dir().join("clroom");
    let base = app_root.join("claude-projections-v2");
    let active = base.join("active");
    let quarantine = base.join("quarantine");
    for path in [&app_root, &base, &active, &quarantine] {
        fs::create_dir_all(path).unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o700)).unwrap();
    }
    let dead = active.join(format!(
        "session-{dead_pid}-{}-0123456789abcdef0123456789abcdef",
        u64::MAX - sequence
    ));
    let live = active.join(format!(
        "session-{live_pid}-{}-11111111111111111111111111111111",
        u64::MAX - sequence - 1
    ));
    let corrupt = active.join(format!(
        "session-{dead_pid}-{}-22222222222222222222222222222222",
        u64::MAX - sequence - 2
    ));
    let mismatched = active.join(format!(
        "session-{dead_pid}-{}-33333333333333333333333333333333",
        u64::MAX - sequence - 3
    ));
    let short_suffix = active.join(format!("session-{dead_pid}-{}-0", u64::MAX - sequence - 4));
    let uppercase_suffix = active.join(format!(
        "session-{dead_pid}-{}-ABCDEFABCDEFABCDEFABCDEFABCDEFAB",
        u64::MAX - sequence - 5
    ));
    let oversized_pid = active.join(format!(
        "session-{}-{}-44444444444444444444444444444444",
        u32::MAX,
        u64::MAX - sequence - 6
    ));
    let public_marker = active.join(format!(
        "session-{dead_pid}-{}-55555555555555555555555555555555",
        u64::MAX - sequence - 7
    ));
    let quarantined = quarantine.join(format!(
        "session-{dead_pid}-{}-66666666666666666666666666666666",
        u64::MAX - sequence - 8
    ));
    let live_quarantine = quarantine.join(format!(
        "session-{live_pid}-{}-77777777777777777777777777777777",
        u64::MAX - sequence - 9
    ));
    let corrupt_quarantine = quarantine.join(format!(
        "session-{dead_pid}-{}-77777777777777777777777777777777",
        u64::MAX - sequence - 10
    ));
    let legacy = std::env::temp_dir().join(format!(
        "clroom-claude-projection-{dead_pid}-{}",
        u64::MAX - sequence - 6
    ));
    let residue = ProjectionResidue(vec![
        dead.clone(),
        live.clone(),
        corrupt.clone(),
        mismatched.clone(),
        short_suffix.clone(),
        uppercase_suffix.clone(),
        oversized_pid.clone(),
        public_marker.clone(),
        quarantined.clone(),
        live_quarantine.clone(),
        corrupt_quarantine.clone(),
        legacy.clone(),
    ]);

    for path in &residue.0 {
        let _ = fs::remove_dir_all(path);
    }

    for (path, pid) in [
        (&dead, dead_pid),
        (&live, live_pid),
        (&short_suffix, dead_pid),
        (&uppercase_suffix, dead_pid),
        (&oversized_pid, u32::MAX),
        (&public_marker, dead_pid),
        (&quarantined, dead_pid),
        (&live_quarantine, live_pid),
    ] {
        fs::create_dir_all(path.join("view/.claude/skills")).unwrap();
        let marker = path.join(".clroom-projection-owner-v2");
        let recorded_start = if pid == live_pid {
            live_start.as_str()
        } else {
            "synthetic-dead-start"
        };
        fs::write(
            &marker,
            format!(
                "active:{pid}:{}:{recorded_start}\n",
                path.file_name().unwrap().to_string_lossy(),
            ),
        )
        .unwrap();
        fs::set_permissions(
            &marker,
            fs::Permissions::from_mode(if path == &public_marker { 0o644 } else { 0o600 }),
        )
        .unwrap();
    }
    fs::create_dir_all(corrupt.join("view/.claude/skills")).unwrap();
    fs::create_dir_all(mismatched.join("view/.claude/skills")).unwrap();
    fs::write(
        mismatched.join(".clroom-projection-owner-v2"),
        format!(
            "active:{dead_pid}:session-1-1-88888888888888888888888888888888:synthetic-dead-start\n"
        ),
    )
    .unwrap();
    fs::set_permissions(
        mismatched.join(".clroom-projection-owner-v2"),
        fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    fs::create_dir_all(corrupt_quarantine.join("view/.claude/skills")).unwrap();
    fs::create_dir_all(legacy.join("view/.claude/skills")).unwrap();
    fs::write(
        legacy.join(".clroom-projection-owner-v1"),
        format!("{dead_pid}\n"),
    )
    .unwrap();

    let projection =
        clroom::adapters::claude::projection::project(&home, &["arrow".to_owned()]).unwrap();

    assert!(
        !dead.exists(),
        "a marked projection from a dead owner must be reaped"
    );
    assert!(
        live.exists(),
        "a live parallel projection must remain untouched"
    );
    assert!(
        corrupt.exists(),
        "an unrecognized active session must remain untouched"
    );
    assert!(
        mismatched.exists(),
        "a marker that is not bound to its session directory must remain untouched"
    );
    assert!(
        short_suffix.exists(),
        "a non-production random suffix must remain untouched"
    );
    assert!(
        uppercase_suffix.exists(),
        "an uppercase random suffix must remain untouched"
    );
    assert!(
        oversized_pid.exists(),
        "a PID outside positive pid_t range must remain untouched"
    );
    assert!(
        public_marker.exists(),
        "a projection with a non-private marker must remain untouched"
    );
    assert!(
        !quarantined.exists(),
        "a recognized quarantine residue must be retried and removed"
    );
    assert!(
        live_quarantine.exists(),
        "a live quarantined projection must remain untouched"
    );
    assert!(
        corrupt_quarantine.exists(),
        "an unrecognized quarantine residue must remain untouched"
    );
    assert!(
        legacy.exists(),
        "legacy flat projections must remain untouched during the versioned rollout"
    );
    assert!(home.join(".claude/skills/arrow/SKILL.md").is_file());

    drop(projection);
    drop(residue);
}

#[test]
fn claude_projection_survives_launcher_death_until_provider_exits() {
    let (_root, project, home, bin, capture) = fixture();
    let provider_pid_path = capture.with_extension("provider-pid");
    let projection_path = capture.with_extension("projection-path");
    fs::write(home.join(".clroom-hold-provider"), b"synthetic\n").unwrap();
    let mut launcher = ChildGuard(Some(
        Command::new(env!("CARGO_BIN_EXE_clroom"))
            .current_dir(&project)
            .env("PATH", &bin)
            .env("HOME", &home)
            .env("CLROOM_EXPECTED_HOME", &home)
            .env("CLROOM_PROJECT", &project)
            .env("CLROOM_CAPTURE_PROJECTION_PATH", &projection_path)
            .env("CLROOM_CAPTURE_PID_PATH", &provider_pid_path)
            .args([
                "claude",
                "--skill-set=arrow,superpowers:systematic-debugging",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap(),
    ));
    let provider_pid = wait_for_nonempty_file(&provider_pid_path)
        .parse::<u32>()
        .unwrap();
    let mut provider = ProcessGuard(Some(provider_pid));
    let live_projection = PathBuf::from(wait_for_nonempty_file(&projection_path));
    let live_session = live_projection
        .parent()
        .expect("projection view must have a session root")
        .to_path_buf();
    let residue = ProjectionResidue(vec![live_session.clone()]);

    assert!(live_projection.exists());
    assert_eq!(
        live_projection,
        fs::canonicalize(&live_projection).unwrap(),
        "provider-captured projection view must use canonical spelling"
    );
    assert_ne!(launcher.id(), provider_pid);
    let session_name = live_session.file_name().unwrap().to_string_lossy();
    let marker = live_session.join(".clroom-projection-owner-v2");
    let provider_start = String::from_utf8(
        Command::new("/bin/ps")
            .args(["-p", &provider_pid.to_string(), "-o", "lstart="])
            .output()
            .unwrap()
            .stdout,
    )
    .unwrap()
    .trim()
    .to_owned();
    assert_eq!(
        fs::read_to_string(&marker).unwrap(),
        format!("active:{provider_pid}:{session_name}:{provider_start}\n"),
        "the marker must bind the actual consumer PID to this exact session"
    );
    assert_eq!(
        fs::metadata(&marker).unwrap().permissions().mode() & 0o777,
        0o600,
        "the ownership marker must remain private"
    );
    assert!(signal_process(launcher.id(), "KILL"));
    launcher.wait_after_signal();
    fs::remove_file(home.join(".clroom-hold-provider")).unwrap();

    let trigger_capture = capture.with_extension("trigger");
    let trigger_config = capture.with_extension("trigger-config");
    let trigger = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .current_dir(&project)
        .env("PATH", &bin)
        .env("HOME", &home)
        .env("CLROOM_EXPECTED_HOME", &home)
        .env("CLROOM_PROJECT", &project)
        .env("CLROOM_CAPTURE_PATH", &trigger_capture)
        .env("CLROOM_CAPTURE_CONFIG_PATH", &trigger_config)
        .args([
            "claude",
            "--skill-set=arrow,superpowers:systematic-debugging",
        ])
        .output()
        .unwrap();

    assert_eq!(trigger.status.code(), Some(42));
    assert!(
        live_projection.exists(),
        "a later launch must not reap a live provider's projection after only its launcher dies"
    );

    provider.stop();
    let after_exit_capture = capture.with_extension("after-exit");
    let after_exit_config = capture.with_extension("after-exit-config");
    let after_exit = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .current_dir(&project)
        .env("PATH", &bin)
        .env("HOME", &home)
        .env("CLROOM_EXPECTED_HOME", &home)
        .env("CLROOM_PROJECT", &project)
        .env("CLROOM_CAPTURE_PATH", &after_exit_capture)
        .env("CLROOM_CAPTURE_CONFIG_PATH", &after_exit_config)
        .args([
            "claude",
            "--skill-set=arrow,superpowers:systematic-debugging",
        ])
        .output()
        .unwrap();

    assert_eq!(after_exit.status.code(), Some(42));
    assert!(
        !live_projection.exists(),
        "the next launch must reap the projection after the provider exits"
    );

    drop(residue);
}

fn wait_for_nonempty_file(path: &Path) -> String {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if let Ok(value) = fs::read_to_string(path)
            && !value.trim().is_empty()
        {
            return value.trim().to_owned();
        }
        assert!(Instant::now() < deadline, "timed out waiting for {path:?}");
        thread::sleep(Duration::from_millis(10));
    }
}

fn signal_process(pid: u32, signal: &str) -> bool {
    Command::new("/bin/kill")
        .args([format!("-{signal}"), pid.to_string()])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok_and(|status| status.success())
}

fn wait_for_process_exit(pid: u32) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while signal_process(pid, "0") {
        assert!(
            Instant::now() < deadline,
            "timed out waiting for process {pid} to exit"
        );
        thread::sleep(Duration::from_millis(10));
    }
}

#[test]
#[ignore = "requires an installed Claude Code CLI; performs no provider request"]
fn native_claude_accepts_the_materialized_skill_add_dir() {
    let claude = std::env::var_os("CLROOM_NATIVE_CLAUDE_BIN")
        .expect("set CLROOM_NATIVE_CLAUDE_BIN to the installed Claude executable");
    let (_root, _project, home, _bin, _capture) = fixture();
    let projection =
        clroom::adapters::claude::projection::project(&home, &["arrow".to_owned()]).unwrap();

    let output = Command::new(claude)
        .arg("--add-dir")
        .arg(&projection.add_dir)
        .arg("--version")
        .output()
        .unwrap();

    assert!(
        output.status.success(),
        "native Claude rejected the projected add-dir (status={:?})",
        output.status.code()
    );
}

#[test]
fn managed_policy_probe_reports_presence_without_reading_policy_contents() {
    use clroom::adapters::claude::managed::{Presence, probe_paths};

    let root = Scratch::new();
    let absent = root.join("absent-managed-policy.json");
    assert_eq!(probe_paths(&[absent]), Presence::Absent);

    let present = root.join("managed-policy.json");
    fs::write(&present, b"synthetic policy contents must not be parsed\n").unwrap();
    assert_eq!(probe_paths(&[present]), Presence::Present);

    let invalid = PathBuf::from(OsString::from_vec(b"invalid\0path".to_vec()));
    assert_eq!(probe_paths(&[invalid]), Presence::Unknown);
}

#[test]
fn claude_parent_environment_is_closed_and_child_scrub_is_enabled() {
    let (_root, project, home, bin, _capture) = fixture();
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .current_dir(&project)
        .env("PATH", &bin)
        .env("HOME", &home)
        .env("TERM", "xterm-256color")
        .env("LANG", "C.UTF-8")
        .env("UNRELATED_TOKEN", "synthetic")
        .env("UNRELATED_SECRET", "synthetic")
        .env("UNRELATED_KEY", "synthetic")
        .env("MCP_CONFIG", "synthetic")
        .args([
            "claude",
            "--skill-set=arrow,superpowers:systematic-debugging",
            "--clroom-env-probe",
        ])
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(42));
    let args = fs::read(home.join("capture")).unwrap();
    let args = args
        .split(|byte| *byte == 0)
        .filter(|argument| !argument.is_empty())
        .map(|argument| String::from_utf8_lossy(argument).into_owned())
        .collect::<Vec<_>>();
    assert!(
        args.iter()
            .any(|argument| argument.contains("failIfUnavailable")),
        "runtime settings must make Claude's inner sandbox fail closed"
    );
}

#[test]
fn claude_preserves_native_service_state_across_launches_and_keeps_ambient_inputs_out() {
    let (_root, project, home, bin, capture) = fixture();
    let config_capture = capture.with_extension("config");
    for _ in 0..2 {
        let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
            .current_dir(&project)
            .env("PATH", &bin)
            .env("HOME", &home)
            .env("CLROOM_EXPECTED_HOME", &home)
            .env("CLROOM_PROJECT", &project)
            .env("CLROOM_CAPTURE_PATH", &capture)
            .env("CLROOM_CAPTURE_CONFIG_PATH", &config_capture)
            .args([
                "claude",
                "--skill-set=arrow,superpowers,superpowers:systematic-debugging,@saved",
                "--model",
                "owner-choice",
            ])
            .output()
            .unwrap();

        assert_eq!(output.status.code(), Some(42));
        let argv = fs::read(&capture).unwrap();
        let args = argv
            .split(|byte| *byte == 0)
            .filter(|item| !item.is_empty())
            .map(|item| String::from_utf8(item.to_vec()).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(
            args[0..7],
            [
                "--setting-sources",
                "project,local",
                "--strict-mcp-config",
                "--settings",
                args[4].as_str(),
                "--add-dir",
                args[6].as_str(),
            ]
        );
        for forbidden in ["haiku", "low", "--effort"] {
            assert!(
                !args.iter().any(|argument| argument == forbidden),
                "launcher-injected Claude choice remained: {forbidden}"
            );
        }
        assert_eq!(
            args.iter()
                .filter(|arg| arg.as_str() == "--add-dir")
                .count(),
            1
        );
        assert_eq!(&args[args.len() - 2..], ["--model", "owner-choice"]);
        let projection = PathBuf::from(&args[6]);
        assert!(
            !projection.exists(),
            "projection must be removed after the child exits"
        );
        assert_eq!(fs::read_to_string(&config_capture).unwrap(), "unset");
    }
}

#[test]
fn claude_denies_provider_writes_to_selected_sources_and_projection_control() {
    let (_root, project, home, bin, capture) = fixture();
    let config_capture = capture.with_extension("config");
    let selected_source = home.join(".claude/skills/arrow/SKILL.md");
    fs::write(home.join(".clroom-probe-protected-writes"), b"synthetic\n").unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .current_dir(&project)
        .env("PATH", &bin)
        .env("HOME", &home)
        .env("CLROOM_EXPECTED_HOME", &home)
        .env("CLROOM_PROJECT", &project)
        .env("CLROOM_CAPTURE_PATH", &capture)
        .env("CLROOM_CAPTURE_CONFIG_PATH", &config_capture)
        .args([
            "claude",
            "--skill-set=arrow,superpowers:systematic-debugging",
        ])
        .output()
        .unwrap();

    assert_eq!(
        output.status.code(),
        Some(42),
        "selected skill sources and projection control must be read-only inside Claude"
    );
    assert_eq!(fs::read(&selected_source).unwrap(), b"arrow\n");
}

#[cfg(target_os = "macos")]
#[test]
fn interactive_claude_launch_keeps_the_clean_room_plaque_visible() {
    // Break caught: Claude enters its alternate screen and hides the launch
    // boundary instead of leaving the plaque visible above the live session.
    let (_root, project, home, bin, capture) = fixture();
    let config_capture = capture.with_extension("config");
    let output = Command::new("/usr/bin/expect")
        .args([
            "-c",
            concat!(
                "set timeout 5\n",
                "spawn -noecho $env(CLROOM_TEST_BIN) claude --skill-set=arrow,superpowers:systematic-debugging --version\n",
                "expect eof\n",
                "set child_status [wait]\n",
                "exit [lindex $child_status 3]\n",
            ),
        ])
        .current_dir(&project)
        .env("CLROOM_TEST_BIN", env!("CARGO_BIN_EXE_clroom"))
        .env("PATH", &bin)
        .env("HOME", &home)
        .env("CLROOM_EXPECTED_HOME", &home)
        .env("CLROOM_PROJECT", &project)
        .env("CLROOM_CAPTURE_PATH", &capture)
        .env("CLROOM_CAPTURE_CONFIG_PATH", &config_capture)
        .env("COLUMNS", "80")
        .env("TERM", "xterm-256color")
        .env_remove("NO_COLOR")
        .output()
        .unwrap();

    assert_eq!(
        output.status.code(),
        Some(42),
        "Claude launch did not preserve the visible boundary:\n{}",
        String::from_utf8_lossy(&output.stdout)
    );
    let transcript = String::from_utf8(output.stdout).unwrap().replace('\r', "");
    assert!(transcript.contains("CLEAN ROOM"));
    assert!(transcript.contains("Global instructions"));
    assert!(transcript.contains("Global skills"));
    assert!(transcript.contains("2 on"));
    assert!(transcript.contains("User settings"));
    assert!(transcript.contains("Auto memory"));
    assert!(transcript.contains("Project skills"));
    assert!(transcript.contains("1 on"));
    for codex_only in [
        "Global AGENTS.md",
        "Apps",
        "Hooks/plugins",
        "Dev prompt",
        "Notifications",
    ] {
        assert!(
            !transcript.contains(codex_only),
            "unexpected Codex-only plaque claim: {codex_only}"
        );
    }
}

#[cfg(target_os = "macos")]
#[test]
fn invalid_claude_identity_refuses_without_launch_contract_diagnostics() {
    // Break caught: a failed preflight either launches Claude or reintroduces
    // internal launch-contract diagnostics into the interactive transcript.
    let (_root, project, home, bin, capture) = fixture();
    let fake = bin.join("claude");
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
                "spawn -noecho $env(CLROOM_TEST_BIN) claude --version\n",
                "expect eof\n",
                "set child_status [wait]\n",
                "exit [lindex $child_status 3]\n",
            ),
        ])
        .current_dir(&project)
        .env("CLROOM_TEST_BIN", env!("CARGO_BIN_EXE_clroom"))
        .env("PATH", &bin)
        .env("HOME", &home)
        .env("COLUMNS", "80")
        .env("TERM", "xterm-256color")
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(2));
    let transcript = String::from_utf8(output.stdout).unwrap().replace('\r', "");
    assert!(transcript.contains("CLEAN ROOM"));
    for diagnostic in ["Boundary:", "Boundary controls:", "Managed:", "Model:"] {
        assert!(
            !transcript.contains(diagnostic),
            "interactive Claude launch leaked diagnostic {diagnostic:?}:\n{transcript}"
        );
    }
    assert!(!capture.exists());
}

#[cfg(target_os = "macos")]
#[test]
fn missing_claude_executable_refuses_without_launch_contract_diagnostics() {
    // Break caught: missing provider resolution reintroduces internal
    // launch-contract diagnostics instead of keeping them hidden.
    let (root, project, home, _bin, capture) = fixture();
    let empty_bin = root.join("empty-bin");
    fs::create_dir_all(&empty_bin).unwrap();
    let output = Command::new("/usr/bin/expect")
        .args([
            "-c",
            concat!(
                "set timeout 5\n",
                "spawn -noecho $env(CLROOM_TEST_BIN) claude --version\n",
                "expect eof\n",
                "set child_status [wait]\n",
                "exit [lindex $child_status 3]\n",
            ),
        ])
        .current_dir(&project)
        .env("CLROOM_TEST_BIN", env!("CARGO_BIN_EXE_clroom"))
        .env("PATH", &empty_bin)
        .env("HOME", &home)
        .env("COLUMNS", "80")
        .env("TERM", "xterm-256color")
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(2));
    let transcript = String::from_utf8(output.stdout).unwrap().replace('\r', "");
    assert!(transcript.contains("CLEAN ROOM"));
    for diagnostic in ["Boundary:", "Boundary controls:", "Managed:", "Model:"] {
        assert!(
            !transcript.contains(diagnostic),
            "interactive Claude launch leaked diagnostic {diagnostic:?}:\n{transcript}"
        );
    }
    assert!(!capture.exists());
}

#[test]
fn claude_rejects_unknown_or_unsafe_skill_selectors_before_child_birth() {
    for selector in ["", "missing", "escape", "../escape", "arrow:extra:part"] {
        let (_root, project, home, bin, capture) = fixture();
        let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
            .current_dir(&project)
            .env("PATH", &bin)
            .env("HOME", &home)
            .env("CLROOM_CAPTURE_PATH", &capture)
            .arg("claude")
            .arg(format!("--skill-set={selector}"))
            .arg("--version")
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(2), "selector={selector}");
        assert!(!capture.exists(), "selector={selector}");
    }
}

#[test]
fn claude_rejects_a_symlinked_global_skill_root_before_child_birth() {
    let (root, project, home, bin, capture) = fixture();
    let external_root = root.join("external-global-skills");
    fs::create_dir_all(external_root.join("arrow")).unwrap();
    fs::create_dir_all(external_root.join("systematic-debugging")).unwrap();
    fs::write(external_root.join("arrow/SKILL.md"), b"external arrow\n").unwrap();
    fs::write(
        external_root.join("systematic-debugging/SKILL.md"),
        b"external systematic debugging\n",
    )
    .unwrap();
    fs::remove_dir_all(home.join(".claude/skills")).unwrap();
    std::os::unix::fs::symlink(&external_root, home.join(".claude/skills")).unwrap();
    let config_capture = capture.with_extension("config");

    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .current_dir(&project)
        .env("PATH", &bin)
        .env("HOME", &home)
        .env("CLROOM_EXPECTED_HOME", &home)
        .env("CLROOM_PROJECT", &project)
        .env("CLROOM_CAPTURE_PATH", &capture)
        .env("CLROOM_CAPTURE_CONFIG_PATH", &config_capture)
        .args([
            "claude",
            "--skill-set=arrow,systematic-debugging",
            "--version",
        ])
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(2));
    assert!(!capture.exists());
    assert_eq!(
        fs::read(external_root.join("arrow/SKILL.md")).unwrap(),
        b"external arrow\n"
    );
}

#[test]
fn claude_rejects_a_symlinked_home_before_child_birth() {
    let (root, project, home, bin, capture) = fixture();
    let linked_home = root.join("linked-home");
    std::os::unix::fs::symlink(&home, &linked_home).unwrap();

    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .current_dir(&project)
        .env("PATH", &bin)
        .env("HOME", &linked_home)
        .env("CLROOM_CAPTURE_PATH", &capture)
        .args(["claude", "--skill-set=arrow", "--version"])
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(2));
    assert!(!capture.exists());
}

#[test]
fn claude_rejects_a_non_private_temp_root_before_child_birth() {
    let (root, project, home, bin, capture) = fixture();
    fs::set_permissions(&root.0, fs::Permissions::from_mode(0o755)).unwrap();
    let config_capture = capture.with_extension("config");

    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .current_dir(&project)
        .env("PATH", &bin)
        .env("HOME", &home)
        .env("TMPDIR", &root.0)
        .env("CLROOM_EXPECTED_HOME", &home)
        .env("CLROOM_PROJECT", &project)
        .env("CLROOM_CAPTURE_PATH", &capture)
        .env("CLROOM_CAPTURE_CONFIG_PATH", &config_capture)
        .args(["claude", "--skill-set=arrow", "--version"])
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(2));
    assert!(!capture.exists());
}

#[test]
fn claude_unavailable_is_a_local_error_without_auth_or_login_flow() {
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(["claude", "--help"])
        .env("PATH", "/definitely/not-a-clroom-command-path")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    assert_eq!(
        String::from_utf8(output.stderr).unwrap(),
        "LOCAL_CLAUDE_UNAVAILABLE: executable 'claude' not found; continue locally\n"
    );
}
