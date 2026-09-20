use std::{
    env, fs,
    path::{Path, PathBuf},
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IsolationPlan {
    pub profile: String,
    pub project: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IsolationError {
    UnsupportedPlatform,
    InvalidProject,
    InvalidExecutable,
    InvalidHome,
    InvalidAllowedPath,
}

pub fn plan(
    project: &Path,
    executable: &Path,
    home: &Path,
    projection_root: &Path,
    projection_view: &Path,
    denied_source_paths: &[PathBuf],
    allowed_source_paths: &[PathBuf],
) -> Result<IsolationPlan, IsolationError> {
    if env::consts::OS != "macos" || env::consts::ARCH != "aarch64" {
        return Err(IsolationError::UnsupportedPlatform);
    }

    let project = canonical_directory(project).ok_or(IsolationError::InvalidProject)?;
    validate_executable(executable)?;
    let home = safe_root(home).ok_or(IsolationError::InvalidHome)?;
    let projection_root = safe_allowed_directory(projection_root, &project)
        .ok_or(IsolationError::InvalidAllowedPath)?;
    let projection_view = safe_allowed_directory(projection_view, &project)
        .ok_or(IsolationError::InvalidAllowedPath)?;
    if !projection_view.starts_with(&projection_root) {
        return Err(IsolationError::InvalidAllowedPath);
    }
    let projection_session_root = projection_view
        .parent()
        .ok_or(IsolationError::InvalidAllowedPath)?;
    let projection_active_root = projection_session_root
        .parent()
        .ok_or(IsolationError::InvalidAllowedPath)?;
    if projection_active_root.parent() != Some(projection_root.as_path()) {
        return Err(IsolationError::InvalidAllowedPath);
    }
    let allowed_source_paths = allowed_source_paths
        .iter()
        .map(|path| safe_allowed_path(path, &project))
        .collect::<Result<Vec<_>, _>>()?;

    let denied_read_roots = vec![
        home.join(".claude"),
        home.join(".agents/skills"),
        home.join(".codex/skills"),
        home.join(".codex/plugins/cache"),
        home.join(".ssh"),
        home.join(".aws"),
        home.join(".config/gcloud"),
        home.join(".azure"),
    ];
    // Claude Code 2.1.278's built-in agents-md walks AGENTS.md and
    // .claude/AGENTS.md through ancestor directories. CLROOM treats the
    // current directory as the selected project boundary: instructions above
    // it are ambient/global for this launch, while files at or below it remain
    // project context.
    let denied_read_files = external_ancestor_instruction_files(&project);
    let mut denied_write_roots = vec![
        home.join(".claude/skills"),
        home.join(".agents/skills"),
        home.join(".codex/skills"),
        home.join(".codex/plugins/cache"),
        home.join(".claude/plugins/cache"),
        projection_root.clone(),
        home.join(".ssh"),
        home.join(".aws"),
        home.join(".config/gcloud"),
        home.join(".azure"),
    ];
    let denied_write_files = [
        home.join(".claude/CLAUDE.md"),
        home.join(".claude/settings.json"),
        home.join(".claude/settings.local.json"),
    ];
    denied_write_roots.extend(allowed_source_paths.iter().cloned());

    let mut profile = String::from("(version 1)\n(allow default)\n");
    profile.push_str("(deny file-read*");
    for path in &denied_read_roots {
        push_subpath(&mut profile, path)?;
    }
    for path in &denied_read_files {
        push_literal(&mut profile, path)?;
    }
    for path in denied_source_paths {
        push_literal(&mut profile, path)?;
        push_subpath(&mut profile, path)?;
    }
    profile.push_str(")\n");
    // Claude 2.1.257+ validates --add-dir ancestry with metadata reads. Keep
    // projection contents denied at the shared root, then reopen metadata only
    // for the storage/active entries and this session's subtree.
    for operation in ["file-read-data", "file-read-xattr", "file-read-metadata"] {
        profile.push_str(&format!("(deny {operation}"));
        push_subpath(&mut profile, &projection_root)?;
        profile.push_str(")\n");
    }
    profile.push_str("(deny file-write*");
    for path in &denied_write_files {
        push_literal(&mut profile, path)?;
    }
    for path in &denied_write_roots {
        push_literal(&mut profile, path)?;
        push_subpath(&mut profile, path)?;
    }
    profile.push_str(")\n");

    // Metadata/listing of denied roots is intentionally not reopened.  The
    // projected view and explicit source files are the only readable seams.
    profile.push_str("(allow file-read-metadata");
    push_literal(&mut profile, &projection_view)?;
    push_subpath(&mut profile, &projection_view)?;
    profile.push_str(")\n");
    profile.push_str("(allow file-read*");
    push_literal(&mut profile, &projection_view)?;
    push_subpath(&mut profile, &projection_view)?;
    if !allowed_source_paths.is_empty() {
        for path in &allowed_source_paths {
            push_literal(&mut profile, path)?;
            push_subpath(&mut profile, path)?;
        }
    }
    profile.push_str(")\n");

    profile.push_str("(allow file-read-metadata");
    push_literal(&mut profile, &projection_root)?;
    push_literal(&mut profile, &projection_active_root)?;
    push_subpath(&mut profile, projection_session_root)?;
    profile.push_str(")\n");

    Ok(IsolationPlan { profile, project })
}

fn external_ancestor_instruction_files(project: &Path) -> Vec<PathBuf> {
    project
        .ancestors()
        .skip(1)
        .flat_map(|directory| {
            [
                directory.join("AGENTS.md"),
                directory.join(".claude/AGENTS.md"),
            ]
        })
        .collect()
}

fn safe_allowed_directory(path: &Path, project: &Path) -> Option<PathBuf> {
    let canonical = canonical_directory(path)?;
    (!canonical.starts_with(project)).then(|| normalize_private_path(&canonical))
}

fn canonical_directory(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute() {
        return None;
    }
    let metadata = fs::symlink_metadata(path).ok()?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return None;
    }
    fs::canonicalize(path).ok()
}

fn validate_executable(executable: &Path) -> Result<(), IsolationError> {
    if !executable.is_absolute()
        || !fs::metadata(executable).is_ok_and(|metadata| metadata.is_file())
    {
        return Err(IsolationError::InvalidExecutable);
    }
    Ok(())
}

fn safe_root(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute() || path.as_os_str().is_empty() || path.to_str().is_none() {
        return None;
    }
    if path
        .components()
        .any(|component| matches!(component, std::path::Component::ParentDir))
    {
        return None;
    }
    let metadata = fs::symlink_metadata(path).ok()?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return None;
    }
    fs::canonicalize(path)
        .ok()
        .map(|canonical| normalize_private_path(&canonical))
}

fn safe_allowed_path(path: &Path, project: &Path) -> Result<PathBuf, IsolationError> {
    if !path.is_absolute() || path.starts_with(project) {
        return Err(IsolationError::InvalidAllowedPath);
    }
    Ok(normalize_private_path(path))
}

fn normalize_private_path(path: &Path) -> PathBuf {
    let Some(value) = path.to_str() else {
        return path.to_path_buf();
    };
    if let Some(suffix) = value.strip_prefix("/var/") {
        PathBuf::from(format!("/private/var/{suffix}"))
    } else if let Some(suffix) = value.strip_prefix("/tmp/") {
        PathBuf::from(format!("/private/tmp/{suffix}"))
    } else {
        path.to_path_buf()
    }
}

fn push_literal(profile: &mut String, path: &Path) -> Result<(), IsolationError> {
    profile.push_str("\n  (literal \"");
    profile.push_str(&escape_path(path)?);
    profile.push_str("\")");
    Ok(())
}

fn push_subpath(profile: &mut String, path: &Path) -> Result<(), IsolationError> {
    profile.push_str("\n  (subpath \"");
    profile.push_str(&escape_path(path)?);
    profile.push_str("\")");
    Ok(())
}

fn escape_path(path: &Path) -> Result<String, IsolationError> {
    let value = path.to_str().ok_or(IsolationError::InvalidAllowedPath)?;
    Ok(value.replace('\\', "\\\\").replace('"', "\\\""))
}


#[cfg(all(test, target_os = "macos", target_arch = "aarch64"))]
mod tests {
    use super::plan;
    use std::{
        fs,
        os::unix::fs::symlink,
        path::{Path, PathBuf},
        process::{Command, Stdio},
        sync::atomic::{AtomicU64, Ordering},
    };

    static SEQUENCE: AtomicU64 = AtomicU64::new(0);

    struct Fixture {
        root: PathBuf,
        project: PathBuf,
        home: PathBuf,
        projection_root: PathBuf,
        projection_view: PathBuf,
        selected: PathBuf,
        sibling: PathBuf,
        outside: PathBuf,
    }

    impl Fixture {
        fn create() -> Self {
            let root = std::env::temp_dir().join(format!(
                "clroom-claude-plugin-isolation-{}-{}",
                std::process::id(),
                SEQUENCE.fetch_add(1, Ordering::Relaxed)
            ));
            let _ = fs::remove_dir_all(&root);
            let project = root.join("project");
            let home = root.join("home");
            let projection_root = root.join("projections");
            let projection_view = projection_root.join("active/session-test/view");
            let selected = home.join(".claude/plugins/cache/example/selected/1.0.0");
            let sibling = home.join(".claude/plugins/cache/example/sibling/1.0.0");
            let outside = home.join(".ssh/canary");
            for directory in [
                &project,
                &projection_view,
                &selected,
                &sibling,
                outside.parent().unwrap(),
            ] {
                fs::create_dir_all(directory).unwrap();
            }
            fs::write(selected.join("selected.txt"), "selected\n").unwrap();
            fs::write(sibling.join("sibling.txt"), "sibling\n").unwrap();
            fs::write(&outside, "outside\n").unwrap();
            symlink(&outside, selected.join("escape")).unwrap();
            Self {
                root,
                project,
                home,
                projection_root,
                projection_view,
                selected,
                sibling,
                outside,
            }
        }

        fn cleanup(self) {
            let _ = fs::remove_dir_all(self.root);
        }
    }

    fn sandbox_status(profile: &str, program: &str, argument: &Path) -> std::process::ExitStatus {
        Command::new("/usr/bin/sandbox-exec")
            .args(["-p", profile, "--", program])
            .arg(argument)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .unwrap()
    }

    fn fixture_plan(fixture: &Fixture) -> super::IsolationPlan {
        let selected = fs::canonicalize(&fixture.selected).unwrap();
        plan(
            &fixture.project,
            Path::new("/bin/cat"),
            &fixture.home,
            &fixture.projection_root,
            &fixture.projection_view,
            &[],
            &[selected],
        )
        .unwrap()
    }

    #[test]
    fn external_ancestor_agents_are_denied_but_project_agents_remain_readable() {
        let fixture = Fixture::create();
        let workspace = fixture.home.join("workspace");
        let project = workspace.join("project");
        fs::create_dir_all(project.join(".claude")).unwrap();
        fs::create_dir_all(workspace.join(".claude")).unwrap();

        let home_agents = fixture.home.join("AGENTS.md");
        let workspace_agents = workspace.join("AGENTS.md");
        let workspace_hidden_agents = workspace.join(".claude/AGENTS.md");
        let project_agents = project.join("AGENTS.md");
        let project_hidden_agents = project.join(".claude/AGENTS.md");
        for path in [
            &home_agents,
            &workspace_agents,
            &workspace_hidden_agents,
            &project_agents,
            &project_hidden_agents,
        ] {
            fs::write(path, "instruction\n").unwrap();
        }

        let selected = fs::canonicalize(&fixture.selected).unwrap();
        let plan = plan(
            &project,
            Path::new("/bin/cat"),
            &fixture.home,
            &fixture.projection_root,
            &fixture.projection_view,
            &[],
            &[selected],
        )
        .unwrap();

        for path in [&home_agents, &workspace_agents, &workspace_hidden_agents] {
            assert!(!sandbox_status(&plan.profile, "/bin/cat", path).success());
        }
        for path in [&project_agents, &project_hidden_agents] {
            assert!(sandbox_status(&plan.profile, "/bin/cat", path).success());
        }

        fixture.cleanup();
    }

    #[test]
    fn selected_plugin_root_is_readable_but_sibling_remains_denied() {
        let fixture = Fixture::create();
        let plan = fixture_plan(&fixture);

        assert!(
            sandbox_status(&plan.profile, "/bin/cat", &fixture.selected.join("selected.txt"))
                .success()
        );
        assert!(
            !sandbox_status(&plan.profile, "/bin/cat", &fixture.sibling.join("sibling.txt"))
                .success()
        );

        fixture.cleanup();
    }

    #[test]
    fn selected_plugin_root_remains_write_denied() {
        let fixture = Fixture::create();
        let plan = fixture_plan(&fixture);
        let written = fixture.selected.join("written-by-provider");

        assert!(!sandbox_status(&plan.profile, "/usr/bin/touch", &written).success());
        assert!(!written.exists());

        fixture.cleanup();
    }

    #[test]
    fn nested_symlink_cannot_escape_selected_plugin_read_seam() {
        let fixture = Fixture::create();
        let plan = fixture_plan(&fixture);

        assert!(fixture.outside.exists());
        assert!(
            !sandbox_status(&plan.profile, "/bin/cat", &fixture.selected.join("escape")).success()
        );

        fixture.cleanup();
    }
}
