#![cfg(target_os = "macos")]

use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    process::Command,
    sync::atomic::{AtomicU64, Ordering},
};

static TEST_SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct Scratch(PathBuf);

impl Scratch {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "clroom-workspace-conflict-{}-{}",
            std::process::id(),
            TEST_SEQUENCE.fetch_add(1, Ordering::Relaxed)
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

fn fake_codex(bin: &Path, sentinel: &Path) {
    fs::create_dir_all(bin).unwrap();
    let executable = bin.join("codex");
    fs::write(
        &executable,
        format!(
            "#!/bin/sh\nprintf 'provider-born\\n' > '{}'\nprintf '0.154.0\\n'\nexit 0\n",
            sentinel.display()
        ),
    )
    .unwrap();
    fs::set_permissions(&executable, fs::Permissions::from_mode(0o700)).unwrap();
}

#[test]
fn home_directory_collision_refuses_before_provider_probe() {
    let root = Scratch::new();
    let home = root.join("home");
    let codex_home = home.join(".codex");
    let bin = root.join("bin");
    let sentinel = root.join("provider-born");
    fs::create_dir_all(&codex_home).unwrap();
    fs::write(codex_home.join("config.toml"), b"model = \"synthetic\"\n").unwrap();
    fake_codex(&bin, &sentinel);

    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .current_dir(&home)
        .env("HOME", &home)
        .env("CODEX_HOME", &codex_home)
        .env("PATH", &bin)
        // The workspace boundary is the subject of this test; an unsafe
        // --yolo argument is intentionally rejected earlier by argument validation.
        .args(["codex"])
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(2));
    let stderr = String::from_utf8(output.stderr).unwrap();
    assert!(stderr.contains("CLROOM_WORKSPACE_CONFLICT"));
    assert!(stderr.contains("cd to the project you want to work in"));
    assert!(!stderr.contains(home.to_str().unwrap()));
    assert!(!stderr.contains(codex_home.to_str().unwrap()));
    assert!(!sentinel.exists(), "Codex was probed before the workspace guard");
}

#[test]
fn custom_codex_home_collision_refuses_before_provider_probe() {
    let root = Scratch::new();
    let home = root.join("home");
    let project = root.join("project");
    let codex_home = project.join(".codex");
    let bin = root.join("bin");
    let sentinel = root.join("provider-born");
    fs::create_dir_all(&home).unwrap();
    fs::create_dir_all(&codex_home).unwrap();
    fake_codex(&bin, &sentinel);

    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .current_dir(&project)
        .env("HOME", &home)
        .env("CODEX_HOME", &codex_home)
        .env("PATH", &bin)
        .args(["codex"])
        .output()
        .unwrap();

    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8(output.stderr)
        .unwrap()
        .contains("CLROOM_WORKSPACE_CONFLICT"));
    assert!(!sentinel.exists(), "Codex was probed before the workspace guard");
}
