use crate::adapters::identity::ProviderIdentity;
use crate::catalog::{
    provider_inventory::{self, PluginInventory, Provider},
    resource::{QualificationState, ResourceKind, SelectionState},
    selection::{plan_selection, SelectionError, SelectionRequest, SelectionTarget},
};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PluginActivationPlan {
    plugin_id: String,
    root: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ActivationError {
    UnsupportedRequest,
    ProviderTupleNotQualified,
    Selection(SelectionError),
    MultiplePlugins,
    StateChanged,
}

impl PluginActivationPlan {
    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn provider_args(&self) -> Vec<String> {
        vec![
            "--plugin-dir".to_owned(),
            self.root.to_string_lossy().into_owned(),
        ]
    }

    pub fn revalidate(&self, home: &Path) -> Result<(), ActivationError> {
        let inventory = provider_inventory::inspect_plugin(
            Provider::Claude,
            home,
            None,
            &self.plugin_id,
            true,
        );
        if inventory.root.as_deref() == Some(self.root.as_path())
            && inventory.entry.selection == SelectionState::Selectable
            && inventory.entry.qualification == QualificationState::Qualified
            && inventory.conflicts.is_empty()
        {
            Ok(())
        } else {
            Err(ActivationError::StateChanged)
        }
    }
}

pub fn plan(
    home: &Path,
    request: &SelectionRequest,
    identity: &ProviderIdentity,
) -> Result<Option<PluginActivationPlan>, ActivationError> {
    if request.is_empty() {
        return Ok(None);
    }
    if identity.provider_id != "claude"
        || !provider_inventory::plugin_activation_exact_tuple(
            Provider::Claude,
            identity.version,
            &identity.os,
            &identity.arch,
        )
    {
        return Err(ActivationError::ProviderTupleNotQualified);
    }

    let plugin_ids = exact_plugin_ids(request)?;
    let inventories = plugin_ids
        .iter()
        .map(|plugin_id| {
            provider_inventory::inspect_plugin(
                Provider::Claude,
                home,
                None,
                plugin_id,
                true,
            )
        })
        .collect::<Vec<_>>();
    let resources = inventories
        .iter()
        .map(|inventory| inventory.entry.clone())
        .collect::<Vec<_>>();
    let selection =
        plan_selection("claude", request, &resources).map_err(ActivationError::Selection)?;

    if selection.selected.is_empty() {
        return Ok(None);
    }
    if selection.selected.len() != 1 {
        return Err(ActivationError::MultiplePlugins);
    }

    let selected = &selection.selected[0].id;
    let inventory = inventories
        .iter()
        .find(|inventory| inventory.entry.resource.canonical() == *selected)
        .ok_or(ActivationError::StateChanged)?;
    activation_from_inventory(inventory)
}

fn exact_plugin_ids(request: &SelectionRequest) -> Result<Vec<String>, ActivationError> {
    let mut ids = request
        .includes
        .iter()
        .chain(request.excludes.iter())
        .map(|target| match target {
            SelectionTarget::Exact { kind, id } if *kind == ResourceKind::Plugin => Ok(id.clone()),
            _ => Err(ActivationError::UnsupportedRequest),
        })
        .collect::<Result<Vec<_>, _>>()?;
    ids.sort();
    ids.dedup();
    Ok(ids)
}

fn activation_from_inventory(
    inventory: &PluginInventory,
) -> Result<Option<PluginActivationPlan>, ActivationError> {
    let root = inventory
        .root
        .clone()
        .ok_or(ActivationError::StateChanged)?;
    Ok(Some(PluginActivationPlan {
        plugin_id: inventory.entry.resource.id.clone(),
        root,
    }))
}

#[cfg(test)]
mod tests {
    use super::{plan, ActivationError};
    use crate::{
        adapters::identity::ProviderIdentity,
        catalog::{
            provider_inventory::CLAUDE_PLUGIN_ACTIVATION_EXACT,
            selection::{SelectionError, SelectionRequest},
        },
    };
    use std::{
        fs,
        path::PathBuf,
        sync::atomic::{AtomicU64, Ordering},
    };
    #[cfg(unix)]
    use std::os::unix::fs::symlink;

    static SEQUENCE: AtomicU64 = AtomicU64::new(0);

    fn fixture() -> (PathBuf, PathBuf) {
        let root = std::env::temp_dir().join(format!(
            "clroom-claude-activation-{}-{}",
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

    fn identity(version: (u64, u64, u64)) -> ProviderIdentity {
        ProviderIdentity {
            provider_id: "claude".to_owned(),
            real_executable: PathBuf::from("/usr/local/bin/claude"),
            artifact_digest: "0".repeat(64),
            version,
            os: "macos".to_owned(),
            arch: "aarch64".to_owned(),
            interpreter: None,
        }
    }

    #[test]
    fn exact_qualified_plugin_plans_provider_owned_activation() {
        let (home, plugin) = fixture();
        let mut request = SelectionRequest::default();
        request.include_value("plugin:superpowers@example").unwrap();

        let activation = plan(&home, &request, &identity(CLAUDE_PLUGIN_ACTIVATION_EXACT))
            .unwrap()
            .unwrap();
        let canonical_plugin = fs::canonicalize(&plugin).unwrap();
        assert_eq!(activation.root(), canonical_plugin.as_path());
        assert_eq!(
            activation.provider_args(),
            vec![
                "--plugin-dir".to_owned(),
                canonical_plugin.to_string_lossy().into_owned(),
            ]
        );
        assert_eq!(activation.revalidate(&home), Ok(()));

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn hook_bearing_plugin_fails_closed_before_activation() {
        let (home, plugin) = fixture();
        fs::write(
            plugin.join(".claude-plugin/plugin.json"),
            r#"{"name":"superpowers","version":"6.3.0","hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"fixture"}]}]}}"#,
        )
        .unwrap();
        let mut request = SelectionRequest::default();
        request.include_value("plugin:superpowers@example").unwrap();

        assert!(matches!(
            plan(
                &home,
                &request,
                &identity(CLAUDE_PLUGIN_ACTIVATION_EXACT)
            ),
            Err(ActivationError::Selection(SelectionError::NotSelectable(_)))
        ));

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn provider_drift_refuses_before_selection() {
        let (home, _) = fixture();
        let mut request = SelectionRequest::default();
        request.include_value("plugin:superpowers@example").unwrap();
        let drifted = (
            CLAUDE_PLUGIN_ACTIVATION_EXACT.0,
            CLAUDE_PLUGIN_ACTIVATION_EXACT.1,
            CLAUDE_PLUGIN_ACTIVATION_EXACT.2 + 1,
        );

        assert_eq!(
            plan(&home, &request, &identity(drifted)),
            Err(ActivationError::ProviderTupleNotQualified)
        );

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn surface_change_after_planning_is_refused() {
        let (home, plugin) = fixture();
        let mut request = SelectionRequest::default();
        request.include_value("plugin:superpowers@example").unwrap();
        let activation = plan(
            &home,
            &request,
            &identity(CLAUDE_PLUGIN_ACTIVATION_EXACT),
        )
        .unwrap()
        .unwrap();

        let nested_agent = plugin.join("agents/review/security.md");
        fs::create_dir_all(nested_agent.parent().unwrap()).unwrap();
        fs::write(&nested_agent, "fixture\n").unwrap();

        assert_eq!(
            activation.revalidate(&home),
            Err(ActivationError::StateChanged)
        );

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[cfg(unix)]
    #[test]
    fn symlink_root_replacement_after_planning_is_refused() {
        let (home, plugin) = fixture();
        let mut request = SelectionRequest::default();
        request.include_value("plugin:superpowers@example").unwrap();
        let activation = plan(&home, &request, &identity(CLAUDE_PLUGIN_ACTIVATION_EXACT))
            .unwrap()
            .unwrap();

        let outside = home.parent().unwrap().join("replacement");
        fs::create_dir_all(&outside).unwrap();
        fs::remove_dir_all(&plugin).unwrap();
        symlink(&outside, &plugin).unwrap();

        assert_eq!(
            activation.revalidate(&home),
            Err(ActivationError::StateChanged)
        );

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn more_than_one_selected_plugin_is_refused_for_v0_4_0() {
        let (home, _) = fixture();
        let second = home.join(".claude/plugins/cache/example/other/1.0.0");
        fs::create_dir_all(second.join(".claude-plugin")).unwrap();
        fs::create_dir_all(second.join("skills/other")).unwrap();
        fs::write(
            second.join(".claude-plugin/plugin.json"),
            r#"{"name":"other","version":"1.0.0"}"#,
        )
        .unwrap();
        fs::write(second.join("skills/other/SKILL.md"), "fixture\n").unwrap();
        let registry = home.join(".claude/plugins/installed_plugins.json");
        let first = home.join(".claude/plugins/cache/example/superpowers/6.3.0");
        fs::write(
            &registry,
            format!(
                r#"{{"plugins":{{"superpowers@example":[{{"installPath":"{}"}}],"other@example":[{{"installPath":"{}"}}]}}}}"#,
                first.display(),
                second.display()
            ),
        )
        .unwrap();

        let mut request = SelectionRequest::default();
        request
            .include_value("plugin:superpowers@example,other@example")
            .unwrap();
        assert_eq!(
            plan(&home, &request, &identity(CLAUDE_PLUGIN_ACTIVATION_EXACT)),
            Err(ActivationError::MultiplePlugins)
        );

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }
}
