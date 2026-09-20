use clroom::adapters::codex::activation::{self, PluginActivationPlan};
use std::{
    fs,
    io::Write,
    os::unix::fs::{OpenOptionsExt, PermissionsExt, symlink},
    path::{Component, Path, PathBuf},
};

const APP_SUPPORT_DIR: &str = ".clroom-clean-state-v1";
const STATE_MARKER: &str = ".clroom-state-v1";
const STATE_MARKER_BYTES: &[u8] = b"clroom-state-v1\n";
const PLUGIN_PROJECTION_MARKER: &str = ".clroom-plugin-projection-v1";
const PLUGIN_PROJECTION_HEADER: &str = "clroom-plugin-projection-v1";
const PROVIDER_AUTH_FILES: &[&str] = &["auth.json", ".credentials.json"];
const EXPECTED_PROVIDER_FILES: &[&str] = &[
    ".sandbox_migration",
    "config.toml",
    "history.jsonl",
    "installation_id",
    "models_cache.json",
    "session_index.jsonl",
    "version.json",
];
const EXPECTED_PROVIDER_DIRECTORIES: &[&str] = &[
    "sessions",
    "archived_sessions",
    "logs",
    "shell_snapshots",
    "thread-writer-locks",
    "tmp",
];
const INITIALIZED_CAPABILITY_PROVIDER_DIRECTORIES: &[&str] = &["cache", "plugins"];

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct CodexState {
    pub(crate) root: PathBuf,
    pub(crate) shadow_home: PathBuf,
    pub(crate) sqlite_home: PathBuf,
}

pub(super) fn prepare(
    home: &Path,
    ambient_codex_home: &Path,
    selected_global_skill_paths: &[(String, PathBuf)],
    plugin_activation: Option<&PluginActivationPlan>,
) -> Result<CodexState, String> {
    let auth_files = PROVIDER_AUTH_FILES
        .iter()
        .map(|name| (name, ambient_codex_home.join(name)))
        .filter(|(_, path)| fs::metadata(path).is_ok_and(|metadata| metadata.is_file()))
        .collect::<Vec<_>>();
    if auth_files.is_empty() {
        return Err("CLROOM_CODEX_AUTH_UNAVAILABLE".to_owned());
    }

    let root = ambient_codex_home.join(APP_SUPPORT_DIR);
    let shadow_home = root.join("home");
    // Keep Codex's durable SQLite state in the existing provider home while
    // projecting only a clean configuration view into shadow_home.
    let sqlite_home = ambient_codex_home.to_owned();
    ensure_private_directory(&root)?;
    ensure_private_directory(&shadow_home)?;
    let initialized = read_state_marker(&shadow_home)?;
    validate_shadow_entries(&shadow_home, initialized)?;
    if !initialized {
        create_state_marker(&shadow_home)?;
    }
    project_selected_skills(
        &shadow_home,
        ambient_codex_home,
        home,
        selected_global_skill_paths,
    )?;
    reconcile_plugin_projection(&shadow_home, plugin_activation)?;

    for (name, ambient_auth) in auth_files {
        let auth_link = shadow_home.join(name);
        match fs::symlink_metadata(&auth_link) {
            Ok(metadata) if metadata.file_type().is_symlink() => {
                if fs::read_link(&auth_link).ok().as_deref() != Some(ambient_auth.as_path()) {
                    return Err("CLROOM_CODEX_AUTH_REFERENCE_INVALID".to_owned());
                }
            }
            Ok(_) => return Err("CLROOM_CODEX_STATE_DIRTY".to_owned()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                symlink(&ambient_auth, &auth_link)
                    .map_err(|_| "CLROOM_CODEX_AUTH_REFERENCE_FAILED".to_owned())?;
            }
            Err(_) => return Err("CLROOM_CODEX_AUTH_REFERENCE_INVALID".to_owned()),
        }
    }

    Ok(CodexState {
        root,
        shadow_home,
        sqlite_home,
    })
}

fn ensure_private_directory(path: &Path) -> Result<(), String> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            return Err("CLROOM_CODEX_STATE_DIR_INVALID".to_owned());
        }
        Ok(metadata) if !metadata.is_dir() => {
            return Err("CLROOM_CODEX_STATE_DIR_INVALID".to_owned());
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            fs::create_dir_all(path)
                .map_err(|_| "CLROOM_CODEX_STATE_DIR_CREATE_FAILED".to_owned())?;
        }
        Err(_) => return Err("CLROOM_CODEX_STATE_DIR_INVALID".to_owned()),
    }
    fs::set_permissions(path, fs::Permissions::from_mode(0o700))
        .map_err(|_| "CLROOM_CODEX_STATE_PERMISSIONS_FAILED".to_owned())?;
    let metadata = fs::metadata(path).map_err(|_| "CLROOM_CODEX_STATE_DIR_INVALID".to_owned())?;
    if metadata.permissions().mode() & 0o077 != 0 {
        return Err("CLROOM_CODEX_STATE_PERMISSIONS_REFUSED".to_owned());
    }
    Ok(())
}

fn read_state_marker(shadow_home: &Path) -> Result<bool, String> {
    let marker = shadow_home.join(STATE_MARKER);
    match fs::symlink_metadata(&marker) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            Err("CLROOM_CODEX_STATE_DIRTY".to_owned())
        }
        Ok(_) => match fs::read(&marker) {
            Ok(bytes) if bytes == STATE_MARKER_BYTES => Ok(true),
            _ => Err("CLROOM_CODEX_STATE_DIRTY".to_owned()),
        },
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(_) => Err("CLROOM_CODEX_STATE_DIRTY".to_owned()),
    }
}

fn create_state_marker(shadow_home: &Path) -> Result<(), String> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;

    let marker = shadow_home.join(STATE_MARKER);
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&marker)
        .map_err(|_| "CLROOM_CODEX_STATE_MARKER_FAILED".to_owned())?;
    file.write_all(STATE_MARKER_BYTES)
        .map_err(|_| "CLROOM_CODEX_STATE_MARKER_FAILED".to_owned())
}

fn validate_shadow_entries(shadow_home: &Path, initialized: bool) -> Result<(), String> {
    let entries = fs::read_dir(shadow_home)
        .map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
    let legacy_state = !initialized
        && entries.iter().any(|entry| {
            entry.file_name().to_str() == Some(".sandbox_migration")
        });
    for entry in entries {
        let name = entry
            .file_name()
            .to_str()
            .map(str::to_owned)
            .ok_or_else(|| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
        if matches!(
            name.as_str(),
            STATE_MARKER | "auth.json" | ".credentials.json" | "skills"
        ) {
            continue;
        }
        if name == PLUGIN_PROJECTION_MARKER {
            let metadata = fs::symlink_metadata(entry.path())
                .map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err("CLROOM_CODEX_STATE_DIRTY".to_owned());
            }
            continue;
        }
        let initialized_capability_directory =
            INITIALIZED_CAPABILITY_PROVIDER_DIRECTORIES.contains(&name.as_str());
        let expected_directory = if EXPECTED_PROVIDER_FILES.contains(&name.as_str()) {
            Some(false)
        } else if EXPECTED_PROVIDER_DIRECTORIES.contains(&name.as_str())
            || initialized_capability_directory
        {
            Some(true)
        } else {
            None
        };
        let Some(expected_directory) = expected_directory else {
            return Err("CLROOM_CODEX_STATE_DIRTY".to_owned());
        };
        if !initialized && (initialized_capability_directory || !legacy_state) {
            return Err("CLROOM_CODEX_STATE_DIRTY".to_owned());
        }
        let metadata = fs::symlink_metadata(entry.path())
            .map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
        if metadata.file_type().is_symlink() || metadata.is_dir() != expected_directory {
            return Err("CLROOM_CODEX_STATE_DIRTY".to_owned());
        }
    }
    Ok(())
}

fn reconcile_plugin_projection(
    shadow_home: &Path,
    activation: Option<&PluginActivationPlan>,
) -> Result<(), String> {
    cleanup_previous_plugin_projection(shadow_home)?;
    let cache_root = shadow_home.join("plugins/cache");

    if activation.is_none() {
        return Ok(());
    }

    ensure_empty_plugin_cache(&cache_root)?;
    let activation = activation.expect("checked above");
    let projected = activation
        .project_into(shadow_home)
        .map_err(plugin_projection_error)?;
    verify_projected_plugin(shadow_home, activation, &projected)?;
    write_plugin_projection_marker(shadow_home, activation)?;
    Ok(())
}

pub(super) fn verify_plugin_projection(
    shadow_home: &Path,
    activation: &PluginActivationPlan,
) -> Result<(), String> {
    let marker = read_plugin_projection_marker(shadow_home)?
        .ok_or_else(|| "CLROOM_CODEX_PLUGIN_PROJECTION_MISSING".to_owned())?;
    if marker.0 != activation.relative_store_path() || marker.1 != activation.source_digest() {
        return Err("CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned());
    }
    let projected = shadow_home
        .join("plugins/cache")
        .join(activation.relative_store_path());
    verify_projected_plugin(shadow_home, activation, &projected)
}

fn verify_projected_plugin(
    shadow_home: &Path,
    activation: &PluginActivationPlan,
    projected: &Path,
) -> Result<(), String> {
    let cache_root = shadow_home.join("plugins/cache");
    if !cache_contains_only(&cache_root, activation.relative_store_path()) {
        return Err("CLROOM_CODEX_PLUGIN_SIBLING_PRESENT".to_owned());
    }
    if activation::bundle_digest(projected).map_err(plugin_projection_error)?
        != activation.source_digest()
    {
        return Err("CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned());
    }
    verify_tree_read_only(projected)?;
    Ok(())
}

fn cleanup_previous_plugin_projection(shadow_home: &Path) -> Result<(), String> {
    let Some((relative, digest)) = read_plugin_projection_marker(shadow_home)? else {
        return Ok(());
    };
    let cache_root = shadow_home.join("plugins/cache");
    let projected = cache_root.join(&relative);
    if activation::bundle_digest(&projected).map_err(plugin_projection_error)? != digest {
        return Err("CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned());
    }
    make_tree_owner_writable(&projected)?;
    fs::remove_dir_all(&projected)
        .map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_CLEANUP_FAILED".to_owned())?;
    remove_empty_plugin_ancestors(&cache_root, &relative)?;
    fs::remove_file(shadow_home.join(PLUGIN_PROJECTION_MARKER))
        .map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_CLEANUP_FAILED".to_owned())?;
    Ok(())
}

fn ensure_empty_plugin_cache(cache_root: &Path) -> Result<(), String> {
    match fs::symlink_metadata(cache_root) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_dir() => {
            Err("CLROOM_CODEX_STATE_DIRTY".to_owned())
        }
        Ok(_) => {
            let mut entries = fs::read_dir(cache_root)
                .map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
            if entries.next().transpose().map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?.is_some() {
                Err("CLROOM_CODEX_PLUGIN_SIBLING_PRESENT".to_owned())
            } else {
                Ok(())
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err("CLROOM_CODEX_STATE_DIRTY".to_owned()),
    }
}

fn write_plugin_projection_marker(
    shadow_home: &Path,
    activation: &PluginActivationPlan,
) -> Result<(), String> {
    let relative = activation
        .relative_store_path()
        .to_str()
        .ok_or_else(|| "CLROOM_CODEX_PLUGIN_PROJECTION_INVALID".to_owned())?;
    let marker = shadow_home.join(PLUGIN_PROJECTION_MARKER);
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(marker)
        .map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_MARKER_FAILED".to_owned())?;
    writeln!(
        file,
        "{PLUGIN_PROJECTION_HEADER}\n{relative}\n{}",
        activation.source_digest()
    )
    .map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_MARKER_FAILED".to_owned())?;
    file.sync_all()
        .map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_MARKER_FAILED".to_owned())
}

fn read_plugin_projection_marker(
    shadow_home: &Path,
) -> Result<Option<(PathBuf, String)>, String> {
    let marker = shadow_home.join(PLUGIN_PROJECTION_MARKER);
    match fs::symlink_metadata(&marker) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            return Err("CLROOM_CODEX_PLUGIN_PROJECTION_MARKER_INVALID".to_owned());
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err("CLROOM_CODEX_PLUGIN_PROJECTION_MARKER_INVALID".to_owned()),
    }
    let bytes = fs::read(&marker)
        .map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_MARKER_INVALID".to_owned())?;
    let text = std::str::from_utf8(&bytes)
        .map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_MARKER_INVALID".to_owned())?;
    let mut lines = text.lines();
    if lines.next() != Some(PLUGIN_PROJECTION_HEADER) {
        return Err("CLROOM_CODEX_PLUGIN_PROJECTION_MARKER_INVALID".to_owned());
    }
    let relative = lines
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| "CLROOM_CODEX_PLUGIN_PROJECTION_MARKER_INVALID".to_owned())?;
    let digest = lines
        .next()
        .map(str::to_owned)
        .ok_or_else(|| "CLROOM_CODEX_PLUGIN_PROJECTION_MARKER_INVALID".to_owned())?;
    if lines.next().is_some()
        || digest.len() != 64
        || !digest.bytes().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        || relative.components().count() != 3
        || relative
            .components()
            .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err("CLROOM_CODEX_PLUGIN_PROJECTION_MARKER_INVALID".to_owned());
    }
    Ok(Some((relative, digest)))
}

fn cache_contains_only(cache_root: &Path, relative: &Path) -> bool {
    let parts = relative.components().collect::<Vec<_>>();
    if parts.len() != 3 {
        return false;
    }
    let mut current = cache_root.to_path_buf();
    for part in parts {
        let Ok(entries) = fs::read_dir(&current)
            .and_then(|entries| entries.collect::<Result<Vec<_>, _>>())
        else {
            return false;
        };
        if entries.len() != 1 || entries[0].file_name() != part.as_os_str() {
            return false;
        }
        let path = entries[0].path();
        let Ok(metadata) = fs::symlink_metadata(&path) else {
            return false;
        };
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return false;
        }
        current = path;
    }
    true
}

fn verify_tree_read_only(root: &Path) -> Result<(), String> {
    let metadata =
        fs::symlink_metadata(root).map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned())?;
    if metadata.file_type().is_symlink()
        || !metadata.is_dir()
        || metadata.permissions().mode() & 0o222 != 0
    {
        return Err("CLROOM_CODEX_PLUGIN_PROJECTION_WRITABLE".to_owned());
    }
    for entry in fs::read_dir(root)
        .map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned())?
    {
        let entry = entry.map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned())?;
        let metadata = fs::symlink_metadata(entry.path())
            .map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned())?;
        if metadata.file_type().is_symlink() || metadata.permissions().mode() & 0o222 != 0 {
            return Err("CLROOM_CODEX_PLUGIN_PROJECTION_WRITABLE".to_owned());
        }
        if metadata.is_dir() {
            verify_tree_read_only(&entry.path())?;
        } else if !metadata.is_file() {
            return Err("CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned());
        }
    }
    Ok(())
}

fn make_tree_owner_writable(root: &Path) -> Result<(), String> {
    let metadata =
        fs::symlink_metadata(root).map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned())?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err("CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned());
    }
    fs::set_permissions(root, fs::Permissions::from_mode(0o700))
        .map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_CLEANUP_FAILED".to_owned())?;
    for entry in fs::read_dir(root)
        .map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_CLEANUP_FAILED".to_owned())?
    {
        let entry =
            entry.map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_CLEANUP_FAILED".to_owned())?;
        let metadata = fs::symlink_metadata(entry.path())
            .map_err(|_| "CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned())?;
        if metadata.file_type().is_symlink() {
            return Err("CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned());
        }
        if metadata.is_dir() {
            make_tree_owner_writable(&entry.path())?;
        } else if !metadata.is_file() {
            return Err("CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED".to_owned());
        }
    }
    Ok(())
}

fn remove_empty_plugin_ancestors(cache_root: &Path, relative: &Path) -> Result<(), String> {
    let plugin = relative.parent().ok_or_else(|| "CLROOM_CODEX_PLUGIN_PROJECTION_INVALID".to_owned())?;
    let marketplace = plugin.parent().ok_or_else(|| "CLROOM_CODEX_PLUGIN_PROJECTION_INVALID".to_owned())?;
    for path in [cache_root.join(plugin), cache_root.join(marketplace), cache_root.to_path_buf()] {
        match fs::remove_dir(&path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::DirectoryNotEmpty => break,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err("CLROOM_CODEX_PLUGIN_PROJECTION_CLEANUP_FAILED".to_owned()),
        }
    }
    Ok(())
}

fn plugin_projection_error(error: activation::ActivationError) -> String {
    match error {
        activation::ActivationError::StateChanged => {
            "CLROOM_CODEX_PLUGIN_SOURCE_CHANGED".to_owned()
        }
        activation::ActivationError::InvalidSource => {
            "CLROOM_CODEX_PLUGIN_SOURCE_INVALID".to_owned()
        }
        activation::ActivationError::ProjectionFailed => {
            "CLROOM_CODEX_PLUGIN_PROJECTION_FAILED".to_owned()
        }
        _ => "CLROOM_CODEX_PLUGIN_PROJECTION_INVALID".to_owned(),
    }
}

fn project_selected_skills(
    shadow_home: &Path,
    ambient_codex_home: &Path,
    home: &Path,
    selected_global_skill_paths: &[(String, PathBuf)],
) -> Result<(), String> {
    let skills_root = shadow_home.join("skills");
    if selected_global_skill_paths.is_empty() {
        if let Ok(entries) = fs::read_dir(&skills_root) {
            for entry in entries {
                let entry = entry.map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
                let name = entry
                    .file_name()
                    .to_str()
                    .map(str::to_owned)
                    .ok_or_else(|| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
                if name == ".system" {
                    let metadata = fs::symlink_metadata(entry.path())
                        .map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
                    if metadata.file_type().is_symlink() || !metadata.is_dir() {
                        return Err("CLROOM_CODEX_STATE_DIRTY".to_owned());
                    }
                    continue;
                }
                let target = fs::read_link(entry.path())
                    .map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
                if target.starts_with(ambient_codex_home) || target.starts_with(home) {
                    fs::remove_file(entry.path())
                        .map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
                } else {
                    return Err("CLROOM_CODEX_STATE_DIRTY".to_owned());
                }
            }
        }
        return Ok(());
    }
    ensure_private_directory(&skills_root)?;
    let selected = selected_global_skill_paths
        .iter()
        .map(|(name, path)| (name.as_str(), path.as_path()))
        .collect::<std::collections::BTreeMap<_, _>>();
    for entry in fs::read_dir(&skills_root).map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())? {
        let entry = entry.map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            return Err("CLROOM_CODEX_STATE_DIRTY".to_owned());
        };
        if name == ".system" {
            let metadata = fs::symlink_metadata(entry.path())
                .map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err("CLROOM_CODEX_STATE_DIRTY".to_owned());
            }
            continue;
        }
        let target =
            fs::read_link(entry.path()).map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
        if selected
            .get(name.as_str())
            .is_some_and(|path| *path == target)
        {
            continue;
        }
        if target.starts_with(ambient_codex_home) || target.starts_with(home) {
            fs::remove_file(entry.path()).map_err(|_| "CLROOM_CODEX_STATE_DIRTY".to_owned())?;
        } else {
            return Err("CLROOM_CODEX_STATE_DIRTY".to_owned());
        }
    }
    for (name, source) in selected_global_skill_paths {
        let link = skills_root.join(name);
        if fs::symlink_metadata(&link).is_err() {
            symlink(source, &link)
                .map_err(|_| "CLROOM_CODEX_SKILL_PROJECTION_FAILED".to_owned())?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        os::unix::fs::{PermissionsExt, symlink},
        path::PathBuf,
        sync::atomic::{AtomicU64, Ordering},
    };

    use clroom::{
        adapters::{
            codex::activation,
            identity::ProviderIdentity,
        },
        catalog::{
            provider_inventory::CODEX_PLUGIN_ACTIVATION_EXACT,
            selection::SelectionRequest,
        },
    };

    use super::{prepare, PLUGIN_PROJECTION_MARKER, STATE_MARKER};

    static TEST_SEQUENCE: AtomicU64 = AtomicU64::new(0);

    struct Scratch(PathBuf);

    impl Scratch {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "clroom-codex-state-test-{}-{}",
                std::process::id(),
                TEST_SEQUENCE.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&root).unwrap();
            Self(root)
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn creates_stable_private_clean_home_with_auth_reference() {
        let scratch = Scratch::new();
        let home = scratch.0.join("home");
        fs::create_dir_all(&home).unwrap();
        let ambient_codex_home = home.join(".codex");
        fs::create_dir_all(&ambient_codex_home).unwrap();
        fs::write(ambient_codex_home.join("auth.json"), b"synthetic auth state").unwrap();
        assert!(fs::metadata(ambient_codex_home.join("auth.json")).is_ok());

        let first = prepare(&home, &ambient_codex_home, &[], None).unwrap();
        let second = prepare(&home, &ambient_codex_home, &[], None).unwrap();

        assert_eq!(first, second);
        assert!(first.shadow_home.join("auth.json").is_symlink());
        assert!(!first.shadow_home.join("config.toml").exists());
        assert!(!first.shadow_home.join("skills").exists());
        assert!(!first.shadow_home.join("plugins").exists());
        assert!(!first.shadow_home.join("hooks").exists());
        assert_eq!(
            fs::metadata(&first.root).unwrap().permissions().mode() & 0o077,
            0
        );
    }

    #[test]
    fn refuses_ambient_auth_without_creating_provider_state() {
        let scratch = Scratch::new();
        let home = scratch.0.join("home");
        fs::create_dir_all(&home).unwrap();
        let ambient_codex_home = home.join(".codex");
        fs::create_dir_all(&ambient_codex_home).unwrap();

        let error = prepare(&home, &ambient_codex_home, &[], None).unwrap_err();

        assert_eq!(error, "CLROOM_CODEX_AUTH_UNAVAILABLE");
        assert!(
            !ambient_codex_home.join(".clroom-clean-state-v1").exists()
        );
    }

    #[test]
    fn refuses_preexisting_shadow_config_instead_of_deleting_it() {
        let scratch = Scratch::new();
        let home = scratch.0.join("home");
        fs::create_dir_all(&home).unwrap();
        let ambient_codex_home = home.join(".codex");
        fs::create_dir_all(&ambient_codex_home).unwrap();
        fs::write(ambient_codex_home.join("auth.json"), b"synthetic auth state").unwrap();
        let shadow_home = ambient_codex_home.join(".clroom-clean-state-v1/home");
        fs::create_dir_all(&shadow_home).unwrap();
        fs::write(shadow_home.join("config.toml"), b"owner state").unwrap();

        let error = prepare(&home, &ambient_codex_home, &[], None).unwrap_err();

        assert_eq!(error, "CLROOM_CODEX_STATE_DIRTY");
        assert_eq!(
            fs::read(shadow_home.join("config.toml")).unwrap(),
            b"owner state"
        );
    }

    #[test]
    fn refreshes_only_clroom_skill_links_across_launches() {
        let scratch = Scratch::new();
        let home = scratch.0.join("home");
        fs::create_dir_all(&home).unwrap();
        let ambient_codex_home = home.join(".codex");
        let source = home.join(".agents/skills/arrow");
        fs::create_dir_all(&ambient_codex_home).unwrap();
        fs::create_dir_all(&source).unwrap();
        fs::write(ambient_codex_home.join("auth.json"), b"synthetic auth state").unwrap();
        fs::write(source.join("SKILL.md"), b"selected").unwrap();

        let selected = [("arrow".to_owned(), source.clone())];
        let first = prepare(&home, &ambient_codex_home, &selected, None).unwrap();
        let second = prepare(&home, &ambient_codex_home, &selected, None).unwrap();
        assert!(second.shadow_home.join("skills/arrow").is_symlink());
        let clean = prepare(&home, &ambient_codex_home, &[], None).unwrap();

        assert_eq!(first, second);
        assert!(!clean.shadow_home.join("skills/arrow").exists());
    }

    #[test]
    fn accepts_expected_provider_state_after_initial_clean_launch() {
        let scratch = Scratch::new();
        let home = scratch.0.join("home");
        fs::create_dir_all(&home).unwrap();
        let ambient_codex_home = home.join(".codex");
        fs::create_dir_all(&ambient_codex_home).unwrap();
        fs::write(ambient_codex_home.join("auth.json"), b"synthetic auth state").unwrap();

        let state = prepare(&home, &ambient_codex_home, &[], None).unwrap();
        fs::write(state.shadow_home.join("config.toml"), b"provider state").unwrap();
        fs::create_dir_all(state.shadow_home.join("sessions")).unwrap();

        let resumed = prepare(&home, &ambient_codex_home, &[], None).unwrap();

        assert_eq!(resumed, state);
    }

    #[test]
    fn initialized_shadow_accepts_codex_plugin_capability_state() {
        let scratch = Scratch::new();
        let home = scratch.0.join("home");
        fs::create_dir_all(&home).unwrap();
        let ambient_codex_home = home.join(".codex");
        fs::create_dir_all(&ambient_codex_home).unwrap();
        fs::write(ambient_codex_home.join("auth.json"), b"synthetic auth state").unwrap();

        let state = prepare(&home, &ambient_codex_home, &[], None).unwrap();
        let cache_catalog = state.shadow_home.join("cache/remote_plugin_catalog");
        let plugin_cache = state.shadow_home.join("plugins/cache");
        let plugin_data = state.shadow_home.join("plugins/data");
        let install_staging = state
            .shadow_home
            .join("plugins/.remote-plugin-install-staging");
        for directory in [
            &cache_catalog,
            &plugin_cache,
            &plugin_data,
            &install_staging,
        ] {
            fs::create_dir_all(directory).unwrap();
        }
        fs::write(cache_catalog.join("catalog.json"), b"provider-owned cache").unwrap();
        fs::write(
            plugin_data.join("state.json"),
            b"provider-owned plugin state",
        )
        .unwrap();

        let resumed = prepare(&home, &ambient_codex_home, &[], None).unwrap();

        assert_eq!(resumed, state);
        assert_eq!(
            fs::read(cache_catalog.join("catalog.json")).unwrap(),
            b"provider-owned cache"
        );
        assert_eq!(
            fs::read(plugin_data.join("state.json")).unwrap(),
            b"provider-owned plugin state"
        );
    }

    #[test]
    fn uninitialized_shadow_rejects_plugin_capability_state() {
        let scratch = Scratch::new();
        let home = scratch.0.join("home");
        fs::create_dir_all(&home).unwrap();
        let ambient_codex_home = home.join(".codex");
        let shadow_home = ambient_codex_home.join(".clroom-clean-state-v1/home");
        fs::create_dir_all(shadow_home.join("cache")).unwrap();
        fs::create_dir_all(shadow_home.join("plugins")).unwrap();
        fs::write(shadow_home.join(".sandbox_migration"), b"legacy marker").unwrap();
        fs::create_dir_all(&ambient_codex_home).unwrap();
        fs::write(
            ambient_codex_home.join("auth.json"),
            b"synthetic auth state",
        )
        .unwrap();

        let error = prepare(&home, &ambient_codex_home, &[], None).unwrap_err();

        assert_eq!(error, "CLROOM_CODEX_STATE_DIRTY");
    }

    #[test]
    fn initialized_shadow_rejects_plugin_root_symlink() {
        let scratch = Scratch::new();
        let home = scratch.0.join("home");
        let plugin_source = scratch.0.join("provider-plugins");
        fs::create_dir_all(&home).unwrap();
        fs::create_dir_all(plugin_source.join("cache")).unwrap();
        let ambient_codex_home = home.join(".codex");
        fs::create_dir_all(&ambient_codex_home).unwrap();
        fs::write(
            ambient_codex_home.join("auth.json"),
            b"synthetic auth state",
        )
        .unwrap();

        let state = prepare(&home, &ambient_codex_home, &[], None).unwrap();
        symlink(&plugin_source, state.shadow_home.join("plugins")).unwrap();

        let error = prepare(&home, &ambient_codex_home, &[], None).unwrap_err();

        assert_eq!(error, "CLROOM_CODEX_STATE_DIRTY");
    }

    #[test]
    fn initialized_shadow_rejects_cache_root_wrong_type() {
        let scratch = Scratch::new();
        let home = scratch.0.join("home");
        fs::create_dir_all(&home).unwrap();
        let ambient_codex_home = home.join(".codex");
        fs::create_dir_all(&ambient_codex_home).unwrap();
        fs::write(
            ambient_codex_home.join("auth.json"),
            b"synthetic auth state",
        )
        .unwrap();

        let state = prepare(&home, &ambient_codex_home, &[], None).unwrap();
        fs::write(state.shadow_home.join("cache"), b"not a directory").unwrap();

        let error = prepare(&home, &ambient_codex_home, &[], None).unwrap_err();

        assert_eq!(error, "CLROOM_CODEX_STATE_DIRTY");
    }

    #[test]
    fn accepts_normal_codex_legacy_entries_with_exact_types() {
        let scratch = Scratch::new();
        let home = scratch.0.join("home");
        fs::create_dir_all(&home).unwrap();
        let ambient_codex_home = home.join(".codex");
        fs::create_dir_all(&ambient_codex_home).unwrap();
        fs::write(
            ambient_codex_home.join("auth.json"),
            b"synthetic auth state",
        )
        .unwrap();

        let state = prepare(&home, &ambient_codex_home, &[], None).unwrap();
        fs::create_dir_all(state.shadow_home.join("skills/.system")).unwrap();
        for name in [
            ".sandbox_migration",
            "config.toml",
            "history.jsonl",
            "installation_id",
            "models_cache.json",
            "session_index.jsonl",
            "version.json",
        ] {
            fs::write(state.shadow_home.join(name), b"provider state").unwrap();
        }
        for name in [
            "sessions",
            "archived_sessions",
            "logs",
            "shell_snapshots",
            "thread-writer-locks",
            "tmp",
        ] {
            fs::create_dir(state.shadow_home.join(name)).unwrap();
        }
        fs::remove_file(state.shadow_home.join(STATE_MARKER)).unwrap();

        let resumed = prepare(&home, &ambient_codex_home, &[], None).unwrap();

        assert_eq!(resumed, state);
    }

    fn plugin_activation_fixture(
        scratch: &Scratch,
    ) -> (PathBuf, PathBuf, activation::PluginActivationPlan) {
        let home = scratch.0.join("plugin-home");
        let ambient_codex_home = home.join(".codex");
        let plugin = ambient_codex_home.join(
            "plugins/cache/openai-bundled/codex-app-tools/0.1.4",
        );
        fs::create_dir_all(plugin.join(".codex-plugin")).unwrap();
        fs::create_dir_all(plugin.join("skills/review")).unwrap();
        fs::write(ambient_codex_home.join("auth.json"), b"synthetic auth state").unwrap();
        fs::write(
            plugin.join(".codex-plugin/plugin.json"),
            r#"{"name":"codex-app-tools","skills":["./skills"]}"#,
        )
        .unwrap();
        fs::write(plugin.join("skills/review/SKILL.md"), b"fixture\n").unwrap();

        let mut request = SelectionRequest::default();
        request
            .include_value("plugin:codex-app-tools@openai-bundled")
            .unwrap();
        let identity = ProviderIdentity {
            provider_id: "codex".to_owned(),
            real_executable: PathBuf::from("/usr/local/bin/codex"),
            artifact_digest: "0".repeat(64),
            version: CODEX_PLUGIN_ACTIVATION_EXACT,
            os: "macos".to_owned(),
            arch: "aarch64".to_owned(),
            interpreter: None,
        };
        let activation = activation::plan(
            &home,
            &ambient_codex_home,
            &request,
            &identity,
        )
        .unwrap()
        .unwrap();
        (home, ambient_codex_home, activation)
    }

    #[test]
    fn selected_plugin_projection_is_exact_read_only_and_following_clean_removes_it() {
        let scratch = Scratch::new();
        let (home, ambient_codex_home, activation) = plugin_activation_fixture(&scratch);

        let selected = prepare(
            &home,
            &ambient_codex_home,
            &[],
            Some(&activation),
        )
        .unwrap();
        let projected = selected
            .shadow_home
            .join("plugins/cache")
            .join(activation.relative_store_path());

        assert_eq!(
            activation::bundle_digest(&projected).unwrap(),
            activation.source_digest()
        );
        assert_eq!(
            fs::metadata(&projected).unwrap().permissions().mode() & 0o222,
            0
        );
        assert!(selected.shadow_home.join(PLUGIN_PROJECTION_MARKER).is_file());

        let clean = prepare(&home, &ambient_codex_home, &[], None).unwrap();
        assert!(!projected.exists());
        assert!(!clean.shadow_home.join(PLUGIN_PROJECTION_MARKER).exists());
        assert!(
            !clean.shadow_home.join("plugins/cache").exists()
                || fs::read_dir(clean.shadow_home.join("plugins/cache"))
                    .unwrap()
                    .next()
                    .is_none()
        );
    }

    #[test]
    fn selected_plugin_refuses_unknown_sibling_in_shadow_cache() {
        let scratch = Scratch::new();
        let (home, ambient_codex_home, activation) = plugin_activation_fixture(&scratch);
        let state = prepare(&home, &ambient_codex_home, &[], None).unwrap();
        fs::create_dir_all(
            state
                .shadow_home
                .join("plugins/cache/other-market/sibling/1.0.0"),
        )
        .unwrap();

        let error = prepare(
            &home,
            &ambient_codex_home,
            &[],
            Some(&activation),
        )
        .unwrap_err();

        assert_eq!(error, "CLROOM_CODEX_PLUGIN_SIBLING_PRESENT");
        assert!(
            state
                .shadow_home
                .join("plugins/cache/other-market/sibling/1.0.0")
                .exists()
        );
    }

    #[test]
    fn symlinked_projection_marker_is_refused_without_following_it() {
        let scratch = Scratch::new();
        let home = scratch.0.join("marker-home");
        let ambient_codex_home = home.join(".codex");
        fs::create_dir_all(&ambient_codex_home).unwrap();
        fs::write(ambient_codex_home.join("auth.json"), b"synthetic auth state").unwrap();
        let state = prepare(&home, &ambient_codex_home, &[], None).unwrap();
        let outside = scratch.0.join("outside-marker");
        fs::write(&outside, b"outside\n").unwrap();
        symlink(&outside, state.shadow_home.join(PLUGIN_PROJECTION_MARKER)).unwrap();

        let error = prepare(&home, &ambient_codex_home, &[], None).unwrap_err();

        assert_eq!(error, "CLROOM_CODEX_STATE_DIRTY");
        assert_eq!(fs::read(outside).unwrap(), b"outside\n");
    }

    #[test]
    fn tampered_owned_projection_is_preserved_and_refused_not_deleted() {
        let scratch = Scratch::new();
        let (home, ambient_codex_home, activation) = plugin_activation_fixture(&scratch);
        let state = prepare(
            &home,
            &ambient_codex_home,
            &[],
            Some(&activation),
        )
        .unwrap();
        let projected_file = state
            .shadow_home
            .join("plugins/cache")
            .join(activation.relative_store_path())
            .join("skills/review/SKILL.md");
        fs::set_permissions(&projected_file, fs::Permissions::from_mode(0o600)).unwrap();
        fs::write(&projected_file, b"tampered\n").unwrap();

        let error = prepare(&home, &ambient_codex_home, &[], None).unwrap_err();

        assert_eq!(error, "CLROOM_CODEX_PLUGIN_PROJECTION_CHANGED");
        assert_eq!(fs::read(projected_file).unwrap(), b"tampered\n");
    }

    #[test]
    fn rejects_foreign_shadow_entries_after_initial_clean_launch() {
        let scratch = Scratch::new();
        let home = scratch.0.join("home");
        fs::create_dir_all(&home).unwrap();
        let ambient_codex_home = home.join(".codex");
        fs::create_dir_all(&ambient_codex_home).unwrap();
        fs::write(
            ambient_codex_home.join("auth.json"),
            b"synthetic auth state",
        )
        .unwrap();

        let state = prepare(&home, &ambient_codex_home, &[], None).unwrap();
        fs::write(state.shadow_home.join("foreign.txt"), b"unexpected").unwrap();

        let error = prepare(&home, &ambient_codex_home, &[], None).unwrap_err();

        assert_eq!(error, "CLROOM_CODEX_STATE_DIRTY");
    }
}
