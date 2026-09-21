use crate::{
    adapters::identity::ProviderIdentity,
    catalog::{
        provider_inventory::{self, PluginInventory, Provider},
        resource::{QualificationState, ResourceKind, SelectionState},
        selection::{plan_selection, SelectionError, SelectionRequest, SelectionTarget},
    },
    core::inventory::{inventory, sha256_hex, AdmittedRoot, SourceRecord},
};
use serde_json::Value as JsonValue;
use std::{
    fs,
    io::Write,
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::{Component, Path, PathBuf},
};

const LOGICAL_PREFIX: &str = "plugin";
const LEGACY_MCP_CONFIG: &str = ".mcp.json";
const DIGEST_PLUGIN_ROOT: &str = "${PLUGIN_ROOT}";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PluginActivationPlan {
    plugin_id: String,
    mcp_server_ids: Vec<String>,
    root: PathBuf,
    relative_store_path: PathBuf,
    source_digest: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ActivationError {
    UnsupportedRequest,
    ProviderTupleNotQualified,
    Selection(SelectionError),
    MultiplePlugins,
    StateChanged,
    InvalidSource,
    ProjectionFailed,
}

impl PluginActivationPlan {
    pub fn plugin_id(&self) -> &str {
        &self.plugin_id
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn relative_store_path(&self) -> &Path {
        &self.relative_store_path
    }

    pub fn source_digest(&self) -> &str {
        &self.source_digest
    }

    pub fn provider_config_args(&self) -> Result<Vec<String>, ActivationError> {
        let plugin_key = toml_basic_string(&self.plugin_id)?;
        let mcp_servers = self
            .mcp_server_ids
            .iter()
            .map(|id| Ok(format!("{}={{enabled=true}}", toml_basic_string(id)?)))
            .collect::<Result<Vec<_>, ActivationError>>()?;
        let mut plugin_config = "enabled=true".to_owned();
        if !mcp_servers.is_empty() {
            plugin_config.push_str(",mcp_servers={");
            plugin_config.push_str(&mcp_servers.join(","));
            plugin_config.push('}');
        }
        Ok(vec![
            "-c".to_owned(),
            "features.plugins=true".to_owned(),
            "-c".to_owned(),
            format!("plugins={{{plugin_key}={{{plugin_config}}}}}"),
        ])
    }

    pub fn revalidate(
        &self,
        home: &Path,
        ambient_codex_home: &Path,
    ) -> Result<(), ActivationError> {
        let inventory = provider_inventory::inspect_plugin(
            Provider::Codex,
            home,
            Some(ambient_codex_home),
            &self.plugin_id,
            true,
        );
        if inventory.root.as_deref() != Some(self.root.as_path())
            || inventory.entry.selection != SelectionState::Selectable
            || inventory.entry.qualification != QualificationState::Qualified
            || !inventory.conflicts.is_empty()
        {
            return Err(ActivationError::StateChanged);
        }
        if mcp_server_ids(&inventory) != self.mcp_server_ids {
            return Err(ActivationError::StateChanged);
        }
        if relative_store_path(ambient_codex_home, &self.root).as_deref()
            != Some(self.relative_store_path.as_path())
            || bundle_digest(&self.root)? != self.source_digest
        {
            return Err(ActivationError::StateChanged);
        }
        Ok(())
    }

    pub fn project_into(&self, shadow_home: &Path) -> Result<PathBuf, ActivationError> {
        let destination = shadow_home
            .join("plugins/cache")
            .join(&self.relative_store_path);
        if fs::symlink_metadata(&destination).is_ok() {
            return Err(ActivationError::ProjectionFailed);
        }

        let result = (|| {
            let records = bundle_records(&self.root)?;
            if digest_records(&self.root, &records)? != self.source_digest {
                return Err(ActivationError::StateChanged);
            }
            write_records(&destination, &self.root, &records)?;
            rebase_legacy_mcp_paths(&self.root, &destination)?;
            if bundle_digest(&self.root)? != self.source_digest
                || bundle_digest(&destination)? != self.source_digest
            {
                return Err(ActivationError::StateChanged);
            }
            make_tree_read_only(&destination)?;
            if bundle_digest(&destination)? != self.source_digest {
                return Err(ActivationError::ProjectionFailed);
            }
            Ok(())
        })();

        if let Err(error) = result {
            cleanup_created_projection(shadow_home, &destination);
            return Err(error);
        }
        Ok(destination)
    }
}

pub fn plan(
    home: &Path,
    ambient_codex_home: &Path,
    request: &SelectionRequest,
    identity: &ProviderIdentity,
) -> Result<Option<PluginActivationPlan>, ActivationError> {
    if request.is_empty() {
        return Ok(None);
    }
    if identity.provider_id != "codex"
        || !provider_inventory::plugin_activation_exact_tuple(
            Provider::Codex,
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
                Provider::Codex,
                home,
                Some(ambient_codex_home),
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
        plan_selection("codex", request, &resources).map_err(ActivationError::Selection)?;

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
    activation_from_inventory(ambient_codex_home, inventory)
}

pub fn bundle_digest(root: &Path) -> Result<String, ActivationError> {
    let records = bundle_records(root)?;
    digest_records(root, &records)
}

pub fn projection_marker_digest_matches(
    root: &Path,
    expected_digest: &str,
) -> Result<bool, ActivationError> {
    let records = bundle_records(root)?;
    if digest_records(root, &records)? == expected_digest {
        return Ok(true);
    }
    Ok(digest_records_legacy_v1(root, &records)? == expected_digest)
}

fn bundle_records(root: &Path) -> Result<Vec<SourceRecord>, ActivationError> {
    inventory(&[AdmittedRoot::new(root, LOGICAL_PREFIX)])
        .map_err(|_| ActivationError::InvalidSource)
}

fn digest_records(root: &Path, records: &[SourceRecord]) -> Result<String, ActivationError> {
    let mut bytes = Vec::new();
    for record in records {
        let relative = record
            .logical_path
            .strip_prefix("plugin/")
            .ok_or(ActivationError::InvalidSource)?;
        let metadata = fs::symlink_metadata(root.join(relative))
            .map_err(|_| ActivationError::InvalidSource)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(ActivationError::InvalidSource);
        }
        let executable = metadata.mode() & 0o111;
        let (content_sha, content_len) = digest_record_metadata(root, relative, record)?;
        bytes.extend_from_slice(record.logical_path.as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(content_sha.as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(content_len.as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(format!("{executable:o}").as_bytes());
        bytes.push(b'\n');
    }
    Ok(sha256_hex(&bytes))
}

fn digest_records_legacy_v1(
    root: &Path,
    records: &[SourceRecord],
) -> Result<String, ActivationError> {
    let mut bytes = Vec::new();
    for record in records {
        let relative = record
            .logical_path
            .strip_prefix("plugin/")
            .ok_or(ActivationError::InvalidSource)?;
        let metadata = fs::symlink_metadata(root.join(relative))
            .map_err(|_| ActivationError::InvalidSource)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(ActivationError::InvalidSource);
        }
        let executable = metadata.mode() & 0o111;
        bytes.extend_from_slice(record.logical_path.as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(record.sha256.as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(record.byte_len.to_string().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(format!("{executable:o}").as_bytes());
        bytes.push(b'\n');
    }
    Ok(sha256_hex(&bytes))
}

fn digest_record_metadata(
    root: &Path,
    relative: &str,
    record: &SourceRecord,
) -> Result<(String, String), ActivationError> {
    if relative != LEGACY_MCP_CONFIG {
        return Ok((record.sha256.clone(), record.byte_len.to_string()));
    }
    let Some(mut document) = parse_legacy_mcp_document(record.content()) else {
        return Ok((record.sha256.clone(), record.byte_len.to_string()));
    };
    normalize_legacy_mcp_paths(root, None, &mut document)?;
    let content = serde_json::to_vec(&document).map_err(|_| ActivationError::InvalidSource)?;
    Ok((sha256_hex(&content), content.len().to_string()))
}

fn parse_legacy_mcp_document(bytes: &[u8]) -> Option<JsonValue> {
    match serde_json::from_slice::<JsonValue>(bytes).ok()? {
        value @ JsonValue::Object(_) => Some(value),
        _ => None,
    }
}

fn legacy_mcp_servers_mut(
    document: &mut JsonValue,
) -> Option<&mut serde_json::Map<String, JsonValue>> {
    if document.get("mcpServers").is_some() {
        document.get_mut("mcpServers")?.as_object_mut()
    } else {
        document.as_object_mut()
    }
}

fn normalize_legacy_mcp_paths(
    root: &Path,
    replacement_root: Option<&Path>,
    document: &mut JsonValue,
) -> Result<bool, ActivationError> {
    let canonical_root = fs::canonicalize(root).map_err(|_| ActivationError::InvalidSource)?;
    let replacement_root = replacement_root
        .map(fs::canonicalize)
        .transpose()
        .map_err(|_| ActivationError::ProjectionFailed)?;
    let Some(servers) = legacy_mcp_servers_mut(document) else {
        return Ok(false);
    };
    let mut changed = false;
    for server in servers.values_mut() {
        let Some(server) = server.as_object_mut() else {
            continue;
        };
        for field in ["command", "cwd"] {
            let Some(raw) = server.get_mut(field).and_then(|value| value.as_str()).map(str::to_owned)
            else {
                continue;
            };
            let Some(rewritten) = normalize_in_root_absolute_path(
                &canonical_root,
                replacement_root.as_deref(),
                &raw,
            )? else {
                continue;
            };
            server.insert(field.to_owned(), JsonValue::String(rewritten));
            changed = true;
        }
    }
    Ok(changed)
}

fn normalize_in_root_absolute_path(
    canonical_root: &Path,
    replacement_root: Option<&Path>,
    raw: &str,
) -> Result<Option<String>, ActivationError> {
    let candidate = Path::new(raw);
    if !candidate.is_absolute() {
        return Ok(None);
    }
    let canonical = match fs::canonicalize(candidate) {
        Ok(path) => path,
        Err(_) if candidate.starts_with(canonical_root) => {
            return Err(ActivationError::InvalidSource);
        }
        Err(_) => return Ok(None),
    };
    if !canonical.starts_with(canonical_root) {
        return Ok(None);
    }
    let relative = canonical
        .strip_prefix(canonical_root)
        .map_err(|_| ActivationError::InvalidSource)?;
    let rewritten = match replacement_root {
        Some(root) if relative.as_os_str().is_empty() => root.display().to_string(),
        Some(root) => root.join(relative).display().to_string(),
        None if relative.as_os_str().is_empty() => DIGEST_PLUGIN_ROOT.to_owned(),
        None => format!("{DIGEST_PLUGIN_ROOT}/{}", relative.display()),
    };
    Ok(Some(rewritten))
}

fn rebase_legacy_mcp_paths(
    source_root: &Path,
    destination_root: &Path,
) -> Result<(), ActivationError> {
    let path = destination_root.join(LEGACY_MCP_CONFIG);
    let metadata = match fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(_) => return Err(ActivationError::ProjectionFailed),
    };
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(ActivationError::InvalidSource);
    }
    let bytes = fs::read(&path).map_err(|_| ActivationError::ProjectionFailed)?;
    let Some(mut document) = parse_legacy_mcp_document(&bytes) else {
        return Ok(());
    };
    if !normalize_legacy_mcp_paths(source_root, Some(destination_root), &mut document)? {
        return Ok(());
    }
    let content = serde_json::to_vec(&document).map_err(|_| ActivationError::ProjectionFailed)?;
    let mut file = fs::OpenOptions::new()
        .write(true)
        .truncate(true)
        .open(&path)
        .map_err(|_| ActivationError::ProjectionFailed)?;
    file.write_all(&content)
        .and_then(|_| file.sync_all())
        .map_err(|_| ActivationError::ProjectionFailed)
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
    ambient_codex_home: &Path,
    inventory: &PluginInventory,
) -> Result<Option<PluginActivationPlan>, ActivationError> {
    let root = inventory
        .root
        .clone()
        .ok_or(ActivationError::StateChanged)?;
    let relative_store_path =
        relative_store_path(ambient_codex_home, &root).ok_or(ActivationError::InvalidSource)?;
    let source_digest = bundle_digest(&root)?;
    Ok(Some(PluginActivationPlan {
        plugin_id: inventory.entry.resource.id.clone(),
        mcp_server_ids: mcp_server_ids(inventory),
        root,
        relative_store_path,
        source_digest,
    }))
}

fn mcp_server_ids(inventory: &PluginInventory) -> Vec<String> {
    let mut ids = inventory
        .effective_components
        .iter()
        .filter(|component| component.kind == ResourceKind::McpServer)
        .map(|component| component.id.clone())
        .collect::<Vec<_>>();
    ids.sort();
    ids.dedup();
    ids
}

fn toml_basic_string(value: &str) -> Result<String, ActivationError> {
    let mut encoded = String::with_capacity(value.len() + 2);
    encoded.push('"');
    for character in value.chars() {
        match character {
            '"' => encoded.push_str("\\\""),
            '\\' => encoded.push_str("\\\\"),
            '\u{08}' => encoded.push_str("\\b"),
            '\u{0c}' => encoded.push_str("\\f"),
            '\n' => encoded.push_str("\\n"),
            '\r' => encoded.push_str("\\r"),
            '\t' => encoded.push_str("\\t"),
            character if character.is_control() => return Err(ActivationError::InvalidSource),
            character => encoded.push(character),
        }
    }
    encoded.push('"');
    Ok(encoded)
}

fn relative_store_path(ambient_codex_home: &Path, root: &Path) -> Option<PathBuf> {
    let cache = fs::canonicalize(ambient_codex_home.join("plugins/cache")).ok()?;
    let relative = root.strip_prefix(&cache).ok()?;
    let parts = relative.components().collect::<Vec<_>>();
    if parts.len() != 3
        || parts
            .iter()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return None;
    }
    Some(relative.to_path_buf())
}

fn write_records(
    destination: &Path,
    source_root: &Path,
    records: &[SourceRecord],
) -> Result<(), ActivationError> {
    fs::create_dir_all(destination).map_err(|_| ActivationError::ProjectionFailed)?;
    fs::set_permissions(destination, fs::Permissions::from_mode(0o700))
        .map_err(|_| ActivationError::ProjectionFailed)?;

    for record in records {
        let relative = record
            .logical_path
            .strip_prefix("plugin/")
            .ok_or(ActivationError::InvalidSource)?;
        let source_metadata = fs::symlink_metadata(source_root.join(relative))
            .map_err(|_| ActivationError::StateChanged)?;
        if source_metadata.file_type().is_symlink() || !source_metadata.is_file() {
            return Err(ActivationError::StateChanged);
        }
        let executable = source_metadata.mode() & 0o111;
        let path = destination.join(relative);
        let parent = path.parent().ok_or(ActivationError::InvalidSource)?;
        fs::create_dir_all(parent).map_err(|_| ActivationError::ProjectionFailed)?;
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600 | executable)
            .open(&path)
            .map_err(|_| ActivationError::ProjectionFailed)?;
        file.write_all(record.content())
            .map_err(|_| ActivationError::ProjectionFailed)?;
        file.sync_all()
            .map_err(|_| ActivationError::ProjectionFailed)?;
    }
    Ok(())
}

fn cleanup_created_projection(shadow_home: &Path, root: &Path) {
    let Ok(metadata) = fs::symlink_metadata(root) else {
        return;
    };
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return;
    }
    if make_directories_owner_writable(root).is_err() || fs::remove_dir_all(root).is_err() {
        return;
    }

    let cache_root = shadow_home.join("plugins/cache");
    let Some(plugin_root) = root.parent() else {
        return;
    };
    let Some(marketplace_root) = plugin_root.parent() else {
        return;
    };
    for path in [plugin_root, marketplace_root] {
        if !path.starts_with(&cache_root) {
            return;
        }
        match fs::remove_dir(path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::DirectoryNotEmpty => break,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => break,
        }
    }
}

fn make_directories_owner_writable(root: &Path) -> Result<(), ActivationError> {
    let metadata = fs::symlink_metadata(root).map_err(|_| ActivationError::ProjectionFailed)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(ActivationError::ProjectionFailed);
    }
    fs::set_permissions(root, fs::Permissions::from_mode(0o700))
        .map_err(|_| ActivationError::ProjectionFailed)?;
    for entry in fs::read_dir(root).map_err(|_| ActivationError::ProjectionFailed)? {
        let entry = entry.map_err(|_| ActivationError::ProjectionFailed)?;
        let metadata =
            fs::symlink_metadata(entry.path()).map_err(|_| ActivationError::ProjectionFailed)?;
        if metadata.file_type().is_symlink() {
            return Err(ActivationError::ProjectionFailed);
        }
        if metadata.is_dir() {
            make_directories_owner_writable(&entry.path())?;
        } else if !metadata.is_file() {
            return Err(ActivationError::ProjectionFailed);
        }
    }
    Ok(())
}

fn make_tree_read_only(root: &Path) -> Result<(), ActivationError> {
    let metadata = fs::symlink_metadata(root).map_err(|_| ActivationError::ProjectionFailed)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(ActivationError::ProjectionFailed);
    }
    let entries = fs::read_dir(root)
        .map_err(|_| ActivationError::ProjectionFailed)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| ActivationError::ProjectionFailed)?;
    for entry in entries {
        let path = entry.path();
        let metadata =
            fs::symlink_metadata(&path).map_err(|_| ActivationError::ProjectionFailed)?;
        if metadata.file_type().is_symlink() {
            return Err(ActivationError::ProjectionFailed);
        }
        if metadata.is_dir() {
            make_tree_read_only(&path)?;
        } else if metadata.is_file() {
            let executable = metadata.permissions().mode() & 0o111;
            fs::set_permissions(&path, fs::Permissions::from_mode(0o444 | executable))
                .map_err(|_| ActivationError::ProjectionFailed)?;
        } else {
            return Err(ActivationError::ProjectionFailed);
        }
    }
    fs::set_permissions(root, fs::Permissions::from_mode(0o555))
        .map_err(|_| ActivationError::ProjectionFailed)
}

#[cfg(test)]
mod tests {
    use super::{
        bundle_digest, bundle_records, digest_records_legacy_v1, plan,
        projection_marker_digest_matches, toml_basic_string, ActivationError, PluginActivationPlan,
    };
    use crate::{
        adapters::identity::ProviderIdentity,
        catalog::{provider_inventory::CODEX_PLUGIN_ACTIVATION_EXACT, selection::SelectionRequest},
    };
    use std::{
        fs,
        path::PathBuf,
        sync::atomic::{AtomicU64, Ordering},
    };

    static SEQUENCE: AtomicU64 = AtomicU64::new(0);

    fn fixture() -> (PathBuf, PathBuf, PathBuf) {
        let root = std::env::temp_dir().join(format!(
            "clroom-codex-activation-{}-{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = fs::remove_dir_all(&root);
        let home = root.join("home");
        let codex_home = home.join(".codex");
        let plugin = codex_home.join("plugins/cache/openai-bundled/codex-app-tools/0.1.4");
        fs::create_dir_all(plugin.join(".codex-plugin")).unwrap();
        fs::create_dir_all(plugin.join("skills/review")).unwrap();
        fs::write(
            plugin.join(".codex-plugin/plugin.json"),
            r#"{"name":"codex-app-tools","skills":["./skills"]}"#,
        )
        .unwrap();
        fs::write(
            plugin.join(".mcp.json"),
            r#"{"mcpServers":{"alpha.server":{"command":"node","args":[]},"zeta":{"command":"node","args":[]}}}"#,
        )
        .unwrap();
        fs::write(plugin.join("skills/review/SKILL.md"), "fixture\n").unwrap();
        (home, codex_home, plugin)
    }

    fn identity(version: (u64, u64, u64)) -> ProviderIdentity {
        ProviderIdentity {
            provider_id: "codex".to_owned(),
            real_executable: PathBuf::from("/usr/local/bin/codex"),
            artifact_digest: "0".repeat(64),
            version,
            os: "macos".to_owned(),
            arch: "aarch64".to_owned(),
            interpreter: None,
        }
    }

    #[test]
    fn exact_qualified_plugin_plans_projection_and_session_config() {
        let (home, codex_home, plugin) = fixture();
        let mut request = SelectionRequest::default();
        request
            .include_value("plugin:codex-app-tools@openai-bundled")
            .unwrap();

        let activation = plan(
            &home,
            &codex_home,
            &request,
            &identity(CODEX_PLUGIN_ACTIVATION_EXACT),
        )
        .unwrap()
        .unwrap();

        assert_eq!(activation.root(), fs::canonicalize(&plugin).unwrap());
        assert_eq!(
            activation.relative_store_path(),
            PathBuf::from("openai-bundled/codex-app-tools/0.1.4")
        );
        assert_eq!(activation.source_digest(), bundle_digest(&plugin).unwrap());
        assert_eq!(
            activation.provider_config_args().unwrap(),
            vec![
                "-c",
                "features.plugins=true",
                "-c",
                "plugins={\"codex-app-tools@openai-bundled\"={enabled=true,mcp_servers={\"alpha.server\"={enabled=true},\"zeta\"={enabled=true}}}}",
            ]
        );
        assert_eq!(activation.revalidate(&home, &codex_home), Ok(()));

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn provider_drift_refuses_before_selection() {
        let (home, codex_home, _) = fixture();
        let mut request = SelectionRequest::default();
        request
            .include_value("plugin:codex-app-tools@openai-bundled")
            .unwrap();
        let drifted = (
            CODEX_PLUGIN_ACTIVATION_EXACT.0,
            CODEX_PLUGIN_ACTIVATION_EXACT.1,
            CODEX_PLUGIN_ACTIVATION_EXACT.2 + 1,
        );

        assert_eq!(
            plan(&home, &codex_home, &request, &identity(drifted)),
            Err(ActivationError::ProviderTupleNotQualified)
        );
        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn provider_owned_dots_remain_single_plugin_and_mcp_keys() {
        let activation = PluginActivationPlan {
            plugin_id: "vendor.plugin@openai-bundled".to_owned(),
            mcp_server_ids: vec!["server.one".to_owned()],
            root: PathBuf::new(),
            relative_store_path: PathBuf::new(),
            source_digest: String::new(),
        };

        assert_eq!(
            activation.provider_config_args().unwrap(),
            vec![
                "-c",
                "features.plugins=true",
                "-c",
                "plugins={\"vendor.plugin@openai-bundled\"={enabled=true,mcp_servers={\"server.one\"={enabled=true}}}}",
            ]
        );
    }

    #[test]
    fn zero_mcp_plugins_receive_only_exact_plugin_enablement() {
        let activation = PluginActivationPlan {
            plugin_id: "codex-app-tools@openai-bundled".to_owned(),
            mcp_server_ids: Vec::new(),
            root: PathBuf::new(),
            relative_store_path: PathBuf::new(),
            source_digest: String::new(),
        };

        let args = activation.provider_config_args().unwrap();
        assert_eq!(
            args[3],
            "plugins={\"codex-app-tools@openai-bundled\"={enabled=true}}"
        );
        assert!(!args[3].contains("mcp_servers"));
        assert!(!args[3].contains("marketplaces"));
    }

    #[test]
    fn provider_id_escaping_is_deterministic_and_control_safe() {
        assert_eq!(
            toml_basic_string("vendor\\\\plugin\"name"),
            Ok("\"vendor\\\\\\\\plugin\\\"name\"".to_owned())
        );
        assert_eq!(
            toml_basic_string("line\nfeed"),
            Ok("\"line\\nfeed\"".to_owned())
        );
        assert_eq!(
            toml_basic_string("bad\u{0001}"),
            Err(ActivationError::InvalidSource)
        );
    }

    #[test]
    fn mcp_component_drift_is_refused_during_revalidation() {
        let (home, codex_home, plugin) = fixture();
        let mut request = SelectionRequest::default();
        request
            .include_value("plugin:codex-app-tools@openai-bundled")
            .unwrap();
        let activation = plan(
            &home,
            &codex_home,
            &request,
            &identity(CODEX_PLUGIN_ACTIVATION_EXACT),
        )
        .unwrap()
        .unwrap();
        fs::write(
            plugin.join(".mcp.json"),
            r#"{"mcpServers":{"alpha.server":{"command":"node","args":[]},"other.server":{"command":"node","args":[]}}}"#,
        )
        .unwrap();

        assert_eq!(
            activation.revalidate(&home, &codex_home),
            Err(ActivationError::StateChanged)
        );
        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn projection_preserves_execute_bits_while_removing_write_bits() {
        use std::os::unix::fs::PermissionsExt;

        let (home, codex_home, plugin) = fixture();
        let executable = plugin.join("bin/tool");
        fs::create_dir_all(executable.parent().unwrap()).unwrap();
        fs::write(&executable, "#!/bin/sh\nexit 0\n").unwrap();
        fs::set_permissions(&executable, fs::Permissions::from_mode(0o755)).unwrap();

        let mut request = SelectionRequest::default();
        request
            .include_value("plugin:codex-app-tools@openai-bundled")
            .unwrap();
        let activation = plan(
            &home,
            &codex_home,
            &request,
            &identity(CODEX_PLUGIN_ACTIVATION_EXACT),
        )
        .unwrap()
        .unwrap();

        let shadow = home.join("shadow");
        fs::create_dir_all(&shadow).unwrap();
        let projected = activation.project_into(&shadow).unwrap();
        let mode = fs::metadata(projected.join("bin/tool"))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(mode & 0o222, 0);
        assert_eq!(mode & 0o111, 0o111);
        assert_eq!(
            activation.source_digest(),
            bundle_digest(&projected).unwrap()
        );

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn projection_rebases_in_root_legacy_mcp_paths_and_preserves_semantic_digest() {
        use std::os::unix::fs::PermissionsExt;

        let (home, codex_home, plugin) = fixture();
        let launcher = plugin.join("scripts/launch_codex_app_tools_mcp");
        fs::create_dir_all(launcher.parent().unwrap()).unwrap();
        fs::write(&launcher, "#!/bin/sh\nexit 0\n").unwrap();
        fs::set_permissions(&launcher, fs::Permissions::from_mode(0o755)).unwrap();
        fs::write(plugin.join("server.mjs"), "export {};\n").unwrap();
        let canonical_plugin = fs::canonicalize(&plugin).unwrap();
        fs::write(
            plugin.join(".mcp.json"),
            serde_json::to_vec(&serde_json::json!({
                "mcpServers": {
                    "codex_app": {
                        "command": launcher,
                        "cwd": canonical_plugin,
                        "args": ["./server.mjs"]
                    },
                    "system": {
                        "command": "/usr/bin/env",
                        "args": []
                    }
                }
            }))
            .unwrap(),
        )
        .unwrap();

        let mut request = SelectionRequest::default();
        request
            .include_value("plugin:codex-app-tools@openai-bundled")
            .unwrap();
        let activation = plan(
            &home,
            &codex_home,
            &request,
            &identity(CODEX_PLUGIN_ACTIVATION_EXACT),
        )
        .unwrap()
        .unwrap();

        let shadow = home.join("shadow");
        fs::create_dir_all(&shadow).unwrap();
        let projected = activation.project_into(&shadow).unwrap();
        let projected_root = fs::canonicalize(&projected).unwrap();
        let projected_mcp: serde_json::Value =
            serde_json::from_slice(&fs::read(projected.join(".mcp.json")).unwrap()).unwrap();
        let codex_app = &projected_mcp["mcpServers"]["codex_app"];
        assert_eq!(
            codex_app["command"].as_str(),
            Some(projected_root.join("scripts/launch_codex_app_tools_mcp").to_str().unwrap())
        );
        assert_eq!(
            codex_app["cwd"].as_str(),
            Some(projected_root.to_str().unwrap())
        );
        assert_eq!(
            projected_mcp["mcpServers"]["system"]["command"].as_str(),
            Some("/usr/bin/env")
        );
        assert_eq!(
            activation.source_digest(),
            bundle_digest(&projected).unwrap()
        );
        assert_eq!(
            fs::metadata(projected.join("scripts/launch_codex_app_tools_mcp"))
                .unwrap()
                .permissions()
                .mode()
                & 0o111,
            0o111
        );

        let source_mcp = fs::read_to_string(plugin.join(".mcp.json")).unwrap();
        assert!(source_mcp.contains(canonical_plugin.to_str().unwrap()));
        assert!(!source_mcp.contains(projected_root.to_str().unwrap()));

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn legacy_projection_marker_digest_is_cleanup_compatible_but_tamper_still_refuses() {
        let (home, _codex_home, plugin) = fixture();
        let launcher = plugin.join("scripts/launch_codex_app_tools_mcp");
        fs::create_dir_all(launcher.parent().unwrap()).unwrap();
        fs::write(&launcher, "#!/bin/sh\nexit 0\n").unwrap();
        fs::write(plugin.join("server.mjs"), "export {};\n").unwrap();
        let canonical_plugin = fs::canonicalize(&plugin).unwrap();
        fs::write(
            plugin.join(".mcp.json"),
            format!(
                "{{\n  \"mcpServers\": {{\n    \"codex_app\": {{\n      \"command\": {:?},\n      \"cwd\": {:?},\n      \"args\": [\"./server.mjs\"]\n    }}\n  }}\n}}\n",
                launcher.display().to_string(),
                canonical_plugin.display().to_string(),
            ),
        )
        .unwrap();

        let records = bundle_records(&plugin).unwrap();
        let legacy_digest = digest_records_legacy_v1(&plugin, &records).unwrap();
        assert_ne!(legacy_digest, bundle_digest(&plugin).unwrap());
        assert_eq!(
            projection_marker_digest_matches(&plugin, &legacy_digest),
            Ok(true)
        );

        fs::write(plugin.join("skills/review/SKILL.md"), "tampered\n").unwrap();
        assert_eq!(
            projection_marker_digest_matches(&plugin, &legacy_digest),
            Ok(false)
        );

        let _ = fs::remove_dir_all(home.parent().unwrap());
    }

    #[test]
    fn source_change_after_planning_is_refused() {
        let (home, codex_home, plugin) = fixture();
        let mut request = SelectionRequest::default();
        request
            .include_value("plugin:codex-app-tools@openai-bundled")
            .unwrap();
        let activation = plan(
            &home,
            &codex_home,
            &request,
            &identity(CODEX_PLUGIN_ACTIVATION_EXACT),
        )
        .unwrap()
        .unwrap();
        fs::write(plugin.join("skills/review/SKILL.md"), "changed\n").unwrap();

        assert_eq!(
            activation.revalidate(&home, &codex_home),
            Err(ActivationError::StateChanged)
        );
        let _ = fs::remove_dir_all(home.parent().unwrap());
    }
}
