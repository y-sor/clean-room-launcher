use super::SHADOW_STATE_DIR;
use std::{
    collections::{BTreeMap, BTreeSet},
    env, fs,
    path::{Path, PathBuf},
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IsolationPlan {
    pub profile: String,
    pub project: PathBuf,
    pub selected_global_skills: usize,
    pub selected_global_skill_paths: Vec<(String, PathBuf)>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IsolationInputs {
    pub home: PathBuf,
    pub codex_home: PathBuf,
}

/// Qualified Codex skill sources. Filesystem residue outside these sources is
/// intentionally not an inventory input.
pub const CODEX_SKILL_SOURCE_MAP: &[(&str, &str)] = &[
    (
        "REPO",
        "$CWD/.agents/skills and ancestors through $REPO_ROOT/.agents/skills",
    ),
    ("USER", "$HOME/.agents/skills and $CODEX_HOME/skills"),
    (
        "ADMIN",
        "/private/etc/codex/skills from the system config layer",
    ),
    (
        "SYSTEM",
        "$CODEX_HOME/skills/.system (provider-owned embedded skills)",
    ),
    (
        "PLUGIN",
        "provider-owned effective config plus PluginStore; not inventoried by CLROOM",
    ),
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IsolationError {
    UnsupportedPlatform,
    InvalidProject,
    InvalidExecutable,
    InvalidHome,
    InvalidCodexHome,
    InvalidSkillSelector(String),
    UnknownSkillSelector(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct GlobalSkill {
    name: String,
    namespace: Option<String>,
    source_precedence: usize,
    entry_path: PathBuf,
    canonical_path: PathBuf,
    is_symlink: bool,
    selectable: bool,
}

#[derive(Debug, Default)]
struct SkillSelection {
    canonical_paths: BTreeSet<PathBuf>,
    allowed_paths: BTreeSet<PathBuf>,
    logical_skills: BTreeSet<(Option<String>, String)>,
}

pub fn plan(
    project: &Path,
    executable: &Path,
    inputs: &IsolationInputs,
) -> Result<IsolationPlan, IsolationError> {
    plan_with_skills(project, executable, inputs, &[])
}

pub fn plan_with_skills(
    project: &Path,
    executable: &Path,
    inputs: &IsolationInputs,
    selectors: &[String],
) -> Result<IsolationPlan, IsolationError> {
    if env::consts::OS != "macos" || env::consts::ARCH != "aarch64" {
        return Err(IsolationError::UnsupportedPlatform);
    }

    let project = canonical_directory(project).ok_or(IsolationError::InvalidProject)?;
    validate_executable(executable)?;

    let home = safe_ambient_root(&inputs.home).ok_or(IsolationError::InvalidHome)?;
    let codex_home =
        safe_ambient_root(&inputs.codex_home).ok_or(IsolationError::InvalidCodexHome)?;

    let denied_files = [
        codex_home.join("AGENTS.md"),
        codex_home.join("AGENTS.override.md"),
        codex_home.join("config.toml"),
    ];
    let denied_roots = [
        codex_home.join("skills"),
        codex_home.join("plugins"),
        codex_home.join("hooks"),
        home.join(".agents/skills"),
    ];
    let provider_skill_roots = [
        codex_home.join("skills/.system"),
        PathBuf::from("/private/etc/codex/skills"),
    ];
    let shadow_home = codex_home.join(SHADOW_STATE_DIR).join("home");
    let shadow_plugin_cache = shadow_home.join("plugins/cache");
    let shadow_plugin_marker = shadow_home.join(".clroom-plugin-projection-v1");
    let credential_roots = [
        home.join(".ssh"),
        home.join(".aws"),
        home.join(".config/gcloud"),
        home.join(".azure"),
    ];
    let mut inventory = discover_global_skills(&[
        (codex_home.join("skills"), false),
        (home.join(".agents/skills"), true),
    ]);
    for skill in &mut inventory {
        if skill.is_symlink
            && skill.selectable
            && denied_files
                .iter()
                .chain(denied_roots.iter())
                .chain(credential_roots.iter())
                .any(|protected| {
                    skill.canonical_path.starts_with(protected)
                        || protected.starts_with(&skill.canonical_path)
                })
        {
            skill.selectable = false;
        }
    }
    let selection = resolve_skill_selectors(selectors, &inventory)?;
    let mut denied_subpaths = denied_roots.iter().cloned().collect::<BTreeSet<_>>();
    denied_subpaths.extend(
        inventory
            .iter()
            .map(|skill| skill.canonical_path.clone())
            .filter(|path| !path.starts_with(&project)),
    );

    let mut profile = String::from("(version 1)\n(allow default)\n");
    profile.push_str("(deny file-read*");
    for path in &denied_files {
        profile.push_str("\n  (literal \"");
        profile.push_str(&escape_scheme_path(path)?);
        profile.push_str("\")");
    }
    for path in denied_subpaths {
        profile.push_str("\n  (subpath \"");
        profile.push_str(&escape_scheme_path(&path)?);
        profile.push_str("\")");
    }
    for path in &credential_roots {
        profile.push_str("\n  (subpath \"");
        profile.push_str(&escape_scheme_path(path)?);
        profile.push_str("\")");
    }
    profile.push_str(")\n");
    profile.push_str("(allow file-read*");
    for root in &provider_skill_roots {
        profile.push_str("\n  (literal \"");
        profile.push_str(&escape_scheme_path(root)?);
        profile.push_str("\")");
        profile.push_str("\n  (subpath \"");
        profile.push_str(&escape_scheme_path(root)?);
        profile.push_str("\")");
    }
    profile.push_str(")\n");
    profile.push_str("(allow file-read-metadata");
    for path in &denied_files {
        profile.push_str("\n  (literal \"");
        profile.push_str(&escape_scheme_path(path)?);
        profile.push_str("\")");
    }
    profile.push_str(")\n");
    profile.push_str("(deny file-write*");
    for path in &denied_files {
        profile.push_str("\n  (literal \"");
        profile.push_str(&escape_scheme_path(path)?);
        profile.push_str("\")");
    }
    profile.push_str("\n  (literal \"");
    profile.push_str(&escape_scheme_path(&shadow_plugin_marker)?);
    profile.push_str("\")");
    profile.push_str("\n  (subpath \"");
    profile.push_str(&escape_scheme_path(&shadow_plugin_cache)?);
    profile.push_str("\")");
    for path in denied_roots
        .iter()
        .chain(provider_skill_roots.iter())
        .chain(credential_roots.iter())
    {
        profile.push_str("\n  (subpath \"");
        profile.push_str(&escape_scheme_path(path)?);
        profile.push_str("\")");
    }
    profile.push_str(")\n");
    profile.push_str("(allow file-read-metadata");
    for root in &provider_skill_roots {
        profile.push_str("\n  (subpath \"");
        profile.push_str(&escape_scheme_path(root)?);
        profile.push_str("\")");
    }
    profile.push_str(")\n");
    if !selection.allowed_paths.is_empty() {
        profile.push_str("(allow file-read-metadata");
        for root in &denied_roots {
            profile.push_str("\n  (subpath \"");
            profile.push_str(&escape_scheme_path(root)?);
            profile.push_str("\")");
        }
        profile.push_str(")\n");
        profile.push_str("(allow file-read*");
        for root in &denied_roots {
            profile.push_str("\n  (literal \"");
            profile.push_str(&escape_scheme_path(root)?);
            profile.push_str("\")");
        }
        for path in selection.allowed_paths {
            profile.push_str("\n  (literal \"");
            profile.push_str(&escape_scheme_path(&path)?);
            profile.push_str("\")");
            profile.push_str("\n  (subpath \"");
            profile.push_str(&escape_scheme_path(&path)?);
            profile.push_str("\")");
        }
        profile.push_str(")\n");
    }

    Ok(IsolationPlan {
        profile,
        project,
        selected_global_skills: selection.logical_skills.len(),
        selected_global_skill_paths: selection
            .canonical_paths
            .into_iter()
            .filter_map(|path| {
                let name = path.file_name()?.to_str()?.to_owned();
                Some((name, path))
            })
            .collect(),
    })
}

fn discover_global_skills(roots: &[(PathBuf, bool)]) -> Vec<GlobalSkill> {
    let mut inventory = Vec::new();
    for (source_precedence, (root, allow_symlink_entries)) in roots.iter().enumerate() {
        let Ok(root_metadata) = fs::symlink_metadata(root) else {
            continue;
        };
        if root_metadata.file_type().is_symlink() || !root_metadata.is_dir() {
            continue;
        }
        let Ok(canonical_root) = fs::canonicalize(root) else {
            continue;
        };
        let Ok(entries) = fs::read_dir(root) else {
            continue;
        };
        for entry in entries.flatten() {
            let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
                continue;
            };
            let entry_path = entry.path();
            let Ok(entry_metadata) = fs::symlink_metadata(&entry_path) else {
                continue;
            };
            let entry_is_symlink = entry_metadata.file_type().is_symlink();
            if !entry_is_symlink && !entry_metadata.is_dir() {
                continue;
            }
            if entry_is_symlink
                && !fs::metadata(&entry_path).is_ok_and(|metadata| metadata.is_dir())
            {
                continue;
            }
            if name == ".system"
                || !valid_skill_name(&name)
                || !fs::metadata(entry_path.join("SKILL.md"))
                    .is_ok_and(|metadata| metadata.is_file())
            {
                continue;
            }
            let Ok(canonical_path) = fs::canonicalize(&entry_path) else {
                continue;
            };
            if !entry_is_symlink && !canonical_path.starts_with(&canonical_root) {
                continue;
            }
            if !fs::metadata(&canonical_path).is_ok_and(|metadata| metadata.is_dir()) {
                continue;
            }
            inventory.push(GlobalSkill {
                namespace: None,
                name,
                source_precedence,
                entry_path,
                canonical_path,
                is_symlink: entry_is_symlink,
                selectable: !entry_is_symlink || *allow_symlink_entries,
            });
        }
    }
    inventory.sort_by(|left, right| {
        (
            &left.name,
            &left.namespace,
            left.source_precedence,
            &left.canonical_path,
        )
            .cmp(&(
                &right.name,
                &right.namespace,
                right.source_precedence,
                &right.canonical_path,
            ))
    });
    inventory
}

fn resolve_skill_selectors(
    selectors: &[String],
    inventory: &[GlobalSkill],
) -> Result<SkillSelection, IsolationError> {
    let mut selection = SkillSelection::default();
    let mut winners = BTreeMap::new();
    for selector in selectors {
        validate_selector(selector)?;

        let matched = if let Some((namespace, name)) = selector.split_once(':') {
            inventory
                .iter()
                .filter(|skill| {
                    skill.selectable
                        && skill.namespace.as_deref() == Some(namespace)
                        && skill.name == name
                })
                .collect::<Vec<_>>()
        } else {
            inventory
                .iter()
                .filter(|skill| {
                    skill.selectable
                        && (skill.name == *selector
                            || skill.namespace.as_deref() == Some(selector.as_str()))
                })
                .collect::<Vec<_>>()
        };

        if matched.is_empty() {
            return Err(IsolationError::UnknownSkillSelector(selector.clone()));
        }
        for skill in matched {
            winners
                .entry((skill.namespace.clone(), skill.name.clone()))
                .or_insert(skill);
        }
    }

    for (logical_skill, skill) in winners {
        selection.logical_skills.insert(logical_skill);
        selection
            .canonical_paths
            .insert(skill.canonical_path.clone());
        selection.allowed_paths.insert(skill.entry_path.clone());
        selection.allowed_paths.insert(skill.canonical_path.clone());
    }
    Ok(selection)
}

fn validate_selector(selector: &str) -> Result<(), IsolationError> {
    let mut parts = selector.split(':');
    let first = parts.next().unwrap_or_default();
    let second = parts.next();
    if !valid_skill_name(first)
        || second.is_some_and(|part| !valid_skill_name(part))
        || parts.next().is_some()
    {
        return Err(IsolationError::InvalidSkillSelector(selector.to_owned()));
    }
    Ok(())
}

fn valid_skill_name(name: &str) -> bool {
    !name.is_empty()
        && name.chars().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.')
        })
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

fn safe_ambient_root(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute() || path.as_os_str().is_empty() || path.to_str().is_none() {
        return None;
    }
    if path
        .components()
        .any(|component| matches!(component, std::path::Component::ParentDir))
    {
        return None;
    }
    let path = path.to_str()?;
    let normalized = if let Some(suffix) = path.strip_prefix("/var/") {
        format!("/private/var/{suffix}")
    } else if let Some(suffix) = path.strip_prefix("/tmp/") {
        format!("/private/tmp/{suffix}")
    } else if path == "/var" {
        "/private/var".to_owned()
    } else if path == "/tmp" {
        "/private/tmp".to_owned()
    } else {
        path.to_owned()
    };
    Some(PathBuf::from(normalized))
}

fn validate_executable(executable: &Path) -> Result<(), IsolationError> {
    if !executable.is_absolute() {
        return Err(IsolationError::InvalidExecutable);
    }
    let metadata = fs::metadata(executable).map_err(|_| IsolationError::InvalidExecutable)?;
    if !metadata.is_file() {
        return Err(IsolationError::InvalidExecutable);
    }
    Ok(())
}

fn escape_scheme_path(path: &Path) -> Result<String, IsolationError> {
    let value = path.to_str().ok_or(IsolationError::InvalidHome)?;
    Ok(value.replace('\\', "\\\\").replace('"', "\\\""))
}


#[cfg(all(test, target_os = "macos", target_arch = "aarch64"))]
mod tests {
    use super::{plan, IsolationInputs, SHADOW_STATE_DIR};
    use std::{
        fs,
        os::unix::fs::PermissionsExt,
        path::PathBuf,
        sync::atomic::{AtomicU64, Ordering},
    };

    static SEQUENCE: AtomicU64 = AtomicU64::new(0);

    #[test]
    fn sandbox_profile_write_denial_tracks_active_shadow_generation() {
        let root = std::env::temp_dir().join(format!(
            "clroom-codex-isolation-shadow-{}-{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        let project = root.join("project");
        let home = root.join("home");
        let codex_home = home.join(".codex");
        let executable = root.join("codex");
        fs::create_dir_all(&project).unwrap();
        fs::create_dir_all(&codex_home).unwrap();
        fs::write(&executable, b"#!/bin/sh\nexit 0\n").unwrap();
        fs::set_permissions(&executable, fs::Permissions::from_mode(0o700)).unwrap();

        let plan = plan(
            &project,
            &executable,
            &IsolationInputs {
                home: home.clone(),
                codex_home: codex_home.clone(),
            },
        )
        .unwrap();

        let active_cache = codex_home
            .join(SHADOW_STATE_DIR)
            .join("home/plugins/cache")
            .to_string_lossy()
            .into_owned();
        let legacy_cache = codex_home
            .join(".clroom-clean-state-v1").join("home/plugins/cache")
            .to_string_lossy()
            .into_owned();

        assert!(plan.profile.contains(&active_cache));
        assert!(!plan.profile.contains(&legacy_cache));

        let _ = fs::remove_dir_all(root);
    }
}
