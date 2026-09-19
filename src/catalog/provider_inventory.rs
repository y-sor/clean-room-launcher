use crate::adapters::{
    claude::plugin_state as claude_plugins, codex::plugin_state as codex_plugins,
};
use crate::catalog::plugin_surface::{
    inspect_plugin_surface, PluginComponent, PluginSurfaceError, ProviderPluginSemantics,
};
use crate::catalog::resource::{
    ActivationPolicy, DiscoveryState, EnablementState, InstallationState, QualificationState,
    ResourceId, ResourceInfo, ResourceKind, ResourceOrigin, SelectionState,
};
use std::path::{Path, PathBuf};

pub const CODEX_CLEAN_EXACT: (u64, u64, u64) = (0, 154, 0);
pub const CLAUDE_CLEAN_EXACT: (u64, u64, u64) = (2, 1, 272);
pub const CLAUDE_PLUGIN_ACTIVATION_EXACT: (u64, u64, u64) = (2, 1, 273);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Provider {
    Codex,
    Claude,
}

impl Provider {
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "codex" => Some(Self::Codex),
            "claude" => Some(Self::Claude),
            _ => None,
        }
    }

    pub fn id(self) -> &'static str {
        match self {
            Self::Codex => "codex",
            Self::Claude => "claude",
        }
    }

    pub fn display(self) -> &'static str {
        match self {
            Self::Codex => "Codex",
            Self::Claude => "Claude Code",
        }
    }

    pub fn clean_launch_exact_version(self) -> (u64, u64, u64) {
        match self {
            Self::Codex => CODEX_CLEAN_EXACT,
            Self::Claude => CLAUDE_CLEAN_EXACT,
        }
    }

    fn plugin_semantics(self) -> ProviderPluginSemantics {
        match self {
            Self::Codex => ProviderPluginSemantics::Codex,
            Self::Claude => ProviderPluginSemantics::Claude,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PluginInventory {
    pub entry: ResourceInfo,
    pub root: Option<PathBuf>,
    pub declared_components: Vec<PluginComponent>,
    pub effective_components: Vec<PluginComponent>,
    pub conflicts: Vec<String>,
}

pub fn clean_launch_exact_tuple(
    provider: Provider,
    version: (u64, u64, u64),
    os: &str,
    arch: &str,
) -> bool {
    os == "macos"
        && arch == "aarch64"
        && version == provider.clean_launch_exact_version()
}

pub fn plugin_activation_exact_tuple(
    provider: Provider,
    version: (u64, u64, u64),
    os: &str,
    arch: &str,
) -> bool {
    os == "macos"
        && arch == "aarch64"
        && provider == Provider::Claude
        && version == CLAUDE_PLUGIN_ACTIVATION_EXACT
}

pub fn valid_plugin_key(provider: Provider, value: &str) -> bool {
    let Some((plugin, marketplace)) = value.rsplit_once('@') else {
        return false;
    };
    valid_plugin_segment(plugin, true)
        && valid_plugin_segment(marketplace, matches!(provider, Provider::Claude))
}

pub fn inspect_plugin(
    provider: Provider,
    home: &Path,
    codex_home: Option<&Path>,
    plugin_id: &str,
    activation_tuple_qualified: bool,
) -> PluginInventory {
    inspect_plugin_with_home(
        provider,
        Some(home),
        codex_home,
        plugin_id,
        activation_tuple_qualified,
    )
}

pub fn inspect_plugin_with_home(
    provider: Provider,
    home: Option<&Path>,
    codex_home: Option<&Path>,
    plugin_id: &str,
    activation_tuple_qualified: bool,
) -> PluginInventory {
    let installation = home
        .map(|home| locate_plugin(provider, home, codex_home, plugin_id))
        .unwrap_or(LocatedPlugin::InvalidState);
    let (installation_state, discovery, root, mut conflicts, mut reason_code) = match installation {
        LocatedPlugin::Installed(root) => (
            InstallationState::Installed,
            DiscoveryState::Discoverable,
            Some(root),
            Vec::new(),
            "PLUGIN_ACTIVATION_V04",
        ),
        LocatedPlugin::NotInstalled => (
            InstallationState::NotInstalled,
            DiscoveryState::Unknown,
            None,
            vec!["PLUGIN_NOT_INSTALLED".to_owned()],
            "PLUGIN_NOT_INSTALLED",
        ),
        LocatedPlugin::Ambiguous => (
            InstallationState::Installed,
            DiscoveryState::Discoverable,
            None,
            vec!["PLUGIN_INSTALLATION_AMBIGUOUS".to_owned()],
            "PLUGIN_INSTALLATION_AMBIGUOUS",
        ),
        LocatedPlugin::InvalidState => (
            InstallationState::Unknown,
            DiscoveryState::Unknown,
            None,
            vec!["PLUGIN_INSTALLATION_STATE_INVALID".to_owned()],
            "PLUGIN_INSTALLATION_STATE_INVALID",
        ),
    };

    let (declared_components, effective_components, manifest_name, activation_surface_eligible) =
        root.as_deref()
            .map(|root| inspect_plugin_surface(provider.plugin_semantics(), root))
            .map(|result| match result {
                Ok(surface) => (
                    surface.declared,
                    surface.effective,
                    surface.plugin_name,
                    surface.activation_eligible,
                ),
                Err(error) => {
                    let blocker = plugin_surface_error_code(error).to_owned();
                    reason_code = plugin_surface_error_code(error);
                    conflicts.push(blocker);
                    (Vec::new(), Vec::new(), None, false)
                }
            })
            .unwrap_or_default();

    let expected_plugin_name = plugin_id.rsplit_once('@').map(|(name, _)| name);
    let activation_identity_qualified = provider != Provider::Claude
        || manifest_name.as_deref() == expected_plugin_name;
    let activation_identity_blocker = if provider != Provider::Claude
        || activation_identity_qualified
    {
        None
    } else if manifest_name.is_none() {
        Some("PLUGIN_IDENTITY_UNPROVEN")
    } else {
        Some("PLUGIN_IDENTITY_MISMATCH")
    };
    if installation_state == InstallationState::Installed
        && root.is_some()
        && conflicts.is_empty()
        && let Some(blocker) = activation_identity_blocker
    {
        reason_code = blocker;
        conflicts.push(blocker.to_owned());
    }

    let activation_surface_qualified = activation_surface_eligible
        && !effective_components.is_empty()
        && effective_components
            .iter()
            .all(|component| component.kind == ResourceKind::Skill);
    let activation_qualified = provider == Provider::Claude
        && activation_tuple_qualified
        && activation_identity_qualified
        && activation_surface_qualified
        && installation_state == InstallationState::Installed
        && root.is_some()
        && conflicts.is_empty();

    if installation_state == InstallationState::Installed && conflicts.is_empty() && !activation_qualified
    {
        let blocker = if !activation_tuple_qualified {
            "PROVIDER_TUPLE_NOT_QUALIFIED"
        } else if let Some(blocker) = activation_identity_blocker {
            blocker
        } else if !activation_surface_qualified {
            "PLUGIN_ACTIVATION_SURFACE_UNQUALIFIED"
        } else {
            "PLUGIN_ACTIVATION_UNAVAILABLE"
        };
        conflicts.push(blocker.to_owned());
    }

    PluginInventory {
        entry: ResourceInfo {
            resource: ResourceId::new(provider.id(), ResourceKind::Plugin, plugin_id)
                .expect("validated selector target must remain a valid resource id"),
            origin: ResourceOrigin::Unknown,
            discovery,
            installation: installation_state,
            provider_enablement: EnablementState::Unknown,
            selection: if activation_qualified {
                SelectionState::Selectable
            } else {
                SelectionState::NotSelectable
            },
            qualification: if activation_qualified {
                QualificationState::Qualified
            } else {
                QualificationState::Unqualified
            },
            required_dependencies: Vec::new(),
            activation_policy: ActivationPolicy::AtomicBundle,
            reason_code: Some(reason_code.to_owned()),
        },
        root,
        declared_components,
        effective_components,
        conflicts,
    }
}

fn valid_plugin_segment(value: &str, allow_dots: bool) -> bool {
    if value.is_empty() || allow_dots && matches!(value, "." | "..") {
        return false;
    }
    if allow_dots && (value.starts_with('.') || value.ends_with('.') || value.contains("..")) {
        return false;
    }
    value.chars().all(|character| {
        character.is_ascii_alphanumeric()
            || matches!(character, '-' | '_')
            || allow_dots && character == '.'
    })
}

enum LocatedPlugin {
    Installed(PathBuf),
    NotInstalled,
    Ambiguous,
    InvalidState,
}

fn locate_plugin(
    provider: Provider,
    home: &Path,
    codex_home: Option<&Path>,
    plugin_id: &str,
) -> LocatedPlugin {
    if !valid_plugin_key(provider, plugin_id) {
        return LocatedPlugin::InvalidState;
    }
    match provider {
        Provider::Codex => {
            let codex_home = codex_home
                .map(Path::to_path_buf)
                .unwrap_or_else(|| home.join(".codex"));
            match codex_plugins::locate(&codex_home, plugin_id) {
                codex_plugins::PluginInstallation::Installed(root) => LocatedPlugin::Installed(root),
                codex_plugins::PluginInstallation::NotInstalled => LocatedPlugin::NotInstalled,
                codex_plugins::PluginInstallation::Ambiguous => LocatedPlugin::Ambiguous,
                codex_plugins::PluginInstallation::InvalidState => LocatedPlugin::InvalidState,
            }
        }
        Provider::Claude => match claude_plugins::locate(home, plugin_id) {
            claude_plugins::PluginInstallation::Installed(root) => LocatedPlugin::Installed(root),
            claude_plugins::PluginInstallation::NotInstalled => LocatedPlugin::NotInstalled,
            claude_plugins::PluginInstallation::Ambiguous => LocatedPlugin::Ambiguous,
            claude_plugins::PluginInstallation::InvalidState => LocatedPlugin::InvalidState,
        },
    }
}

fn plugin_surface_error_code(error: PluginSurfaceError) -> &'static str {
    match error {
        PluginSurfaceError::Unavailable => "PLUGIN_SURFACE_UNAVAILABLE",
        PluginSurfaceError::InvalidManifest => "PLUGIN_MANIFEST_INVALID",
        PluginSurfaceError::UnsupportedManifest => "PLUGIN_MANIFEST_UNSUPPORTED",
    }
}

#[cfg(test)]
mod tests {
    use super::{
        clean_launch_exact_tuple, inspect_plugin, plugin_activation_exact_tuple, Provider,
        CLAUDE_CLEAN_EXACT, CLAUDE_PLUGIN_ACTIVATION_EXACT, CODEX_CLEAN_EXACT,
    };
    use crate::catalog::resource::{QualificationState, ResourceKind, SelectionState};
    use std::{
        fs,
        sync::atomic::{AtomicU64, Ordering},
    };

    static SEQUENCE: AtomicU64 = AtomicU64::new(0);

    fn fixture() -> (std::path::PathBuf, std::path::PathBuf) {
        let root = std::env::temp_dir().join(format!(
            "clroom-provider-inventory-{}-{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = fs::remove_dir_all(&root);
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
        fs::write(
            home.join(".claude/plugins/installed_plugins.json"),
            format!(
                r#"{{"plugins":{{"superpowers@example":[{{"installPath":"{}"}}]}}}}"#,
                plugin.display()
            ),
        )
        .unwrap();
        (home, plugin)
    }

    #[test]
    fn claude_plugin_selectability_is_bound_to_exact_provider_tuple() {
        let (home, plugin) = fixture();
        let qualified = inspect_plugin(
            Provider::Claude,
            &home,
            None,
            "superpowers@example",
            true,
        );
        let canonical_plugin = fs::canonicalize(&plugin).unwrap();
        assert_eq!(qualified.root.as_deref(), Some(canonical_plugin.as_path()));
        assert_eq!(qualified.entry.selection, SelectionState::Selectable);
        assert_eq!(qualified.entry.qualification, QualificationState::Qualified);
        assert!(qualified.conflicts.is_empty());

        let drifted = inspect_plugin(
            Provider::Claude,
            &home,
            None,
            "superpowers@example",
            false,
        );
        assert_eq!(drifted.entry.selection, SelectionState::NotSelectable);
        assert_eq!(drifted.entry.qualification, QualificationState::Unqualified);
        assert!(
            drifted
                .conflicts
                .iter()
                .any(|reason| reason == "PROVIDER_TUPLE_NOT_QUALIFIED")
        );

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn manifestless_claude_plugin_surface_is_observed_but_not_selectable() {
        let (home, plugin) = fixture();
        fs::remove_file(plugin.join(".claude-plugin/plugin.json")).unwrap();

        let inventory = inspect_plugin(
            Provider::Claude,
            &home,
            None,
            "superpowers@example",
            true,
        );

        assert!(inventory
            .effective_components
            .iter()
            .any(|component| component.kind == ResourceKind::Skill));
        assert_eq!(inventory.entry.selection, SelectionState::NotSelectable);
        assert_eq!(inventory.entry.qualification, QualificationState::Unqualified);
        assert!(inventory
            .conflicts
            .iter()
            .any(|reason| reason == "PLUGIN_IDENTITY_UNPROVEN"));

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn root_skill_surface_is_observed_but_not_activation_qualified() {
        let (home, plugin) = fixture();
        fs::remove_file(plugin.join(".claude-plugin/plugin.json")).unwrap();
        fs::remove_dir_all(plugin.join("skills")).unwrap();
        fs::write(plugin.join("SKILL.md"), "fixture\n").unwrap();

        let inventory = inspect_plugin(
            Provider::Claude,
            &home,
            None,
            "superpowers@example",
            true,
        );

        assert!(inventory
            .effective_components
            .iter()
            .any(|component| component.kind == ResourceKind::Skill));
        assert_eq!(inventory.entry.selection, SelectionState::NotSelectable);
        assert_eq!(inventory.entry.qualification, QualificationState::Unqualified);

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn manifest_identity_mismatch_is_not_activation_qualified() {
        let (home, plugin) = fixture();
        fs::write(
            plugin.join(".claude-plugin/plugin.json"),
            r#"{"name":"other","version":"6.3.0"}"#,
        )
        .unwrap();

        let inventory = inspect_plugin(
            Provider::Claude,
            &home,
            None,
            "superpowers@example",
            true,
        );

        assert_eq!(inventory.entry.selection, SelectionState::NotSelectable);
        assert_eq!(inventory.entry.qualification, QualificationState::Unqualified);
        assert!(
            inventory
                .conflicts
                .iter()
                .any(|reason| reason == "PLUGIN_IDENTITY_MISMATCH")
        );

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn nested_agent_and_command_surfaces_are_not_activation_qualified() {
        for (relative, expected_kind) in [
            ("agents/review/security.md", ResourceKind::Agent),
            ("commands/tools/inspect.md", ResourceKind::Command),
        ] {
            let (home, plugin) = fixture();
            let path = plugin.join(relative);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(&path, "fixture\n").unwrap();

            let inventory = inspect_plugin(
                Provider::Claude,
                &home,
                None,
                "superpowers@example",
                true,
            );

            assert_eq!(inventory.entry.selection, SelectionState::NotSelectable);
            assert_eq!(inventory.entry.qualification, QualificationState::Unqualified);
            assert!(
                inventory
                    .effective_components
                    .iter()
                    .any(|component| component.kind == expected_kind)
            );
            assert!(
                inventory
                    .conflicts
                    .iter()
                    .any(|reason| reason == "PLUGIN_ACTIVATION_SURFACE_UNQUALIFIED")
            );

            let _ = fs::remove_dir_all(home.parent().unwrap());
        }
    }

    #[test]
    fn hook_bearing_claude_plugin_is_observed_but_not_activation_qualified() {
        let (home, plugin) = fixture();
        fs::write(
            plugin.join(".claude-plugin/plugin.json"),
            r#"{"name":"superpowers","version":"6.3.0","hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"fixture"}]}]}}"#,
        )
        .unwrap();

        let inventory = inspect_plugin(
            Provider::Claude,
            &home,
            None,
            "superpowers@example",
            true,
        );

        assert_eq!(inventory.entry.selection, SelectionState::NotSelectable);
        assert_eq!(
            inventory.entry.qualification,
            QualificationState::Unqualified
        );
        assert!(
            inventory
                .effective_components
                .iter()
                .any(|component| component.kind == ResourceKind::HookSet)
        );
        assert!(
            inventory
                .conflicts
                .iter()
                .any(|reason| reason == "PLUGIN_ACTIVATION_SURFACE_UNQUALIFIED")
        );

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn clean_launch_and_plugin_activation_tuples_are_behavior_specific() {
        assert!(clean_launch_exact_tuple(
            Provider::Claude,
            CLAUDE_CLEAN_EXACT,
            "macos",
            "aarch64"
        ));
        assert!(!clean_launch_exact_tuple(
            Provider::Claude,
            CLAUDE_PLUGIN_ACTIVATION_EXACT,
            "macos",
            "aarch64"
        ));
        assert!(plugin_activation_exact_tuple(
            Provider::Claude,
            CLAUDE_PLUGIN_ACTIVATION_EXACT,
            "macos",
            "aarch64"
        ));
        assert!(!plugin_activation_exact_tuple(
            Provider::Claude,
            CLAUDE_CLEAN_EXACT,
            "macos",
            "aarch64"
        ));
        assert!(!plugin_activation_exact_tuple(
            Provider::Claude,
            CLAUDE_PLUGIN_ACTIVATION_EXACT,
            "linux",
            "aarch64"
        ));
        assert!(!plugin_activation_exact_tuple(
            Provider::Codex,
            CODEX_CLEAN_EXACT,
            "macos",
            "aarch64"
        ));
    }
}
