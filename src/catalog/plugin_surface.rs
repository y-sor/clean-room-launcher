use super::resource::{NativeKind, ResourceKind};
use serde::Serialize;
use serde_json::Value;
use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
};

const MAX_MANIFEST_BYTES: u64 = 128 * 1024;
const MAX_COMPONENT_FILE_BYTES: u64 = 1024 * 1024;
const MAX_SKILL_ENTRIES: usize = 512;
const AGENT_PLUGIN_SCHEMA: &str = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProviderPluginSemantics {
    Codex,
    Claude,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize)]
pub struct PluginComponent {
    /// Provider/manifest-owned component kind. This is open native data, not a
    /// closed CLROOM ontology.
    pub kind: ResourceKind,
    pub id: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PluginSurface {
    pub declared: Vec<PluginComponent>,
    pub effective: Vec<PluginComponent>,
    pub plugin_name: Option<String>,
    #[serde(skip)]
    pub activation_eligible: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PluginSurfaceError {
    Unavailable,
    InvalidManifest,
    UnsupportedManifest,
}

pub fn inspect_plugin_surface(
    provider: ProviderPluginSemantics,
    root: &Path,
) -> Result<PluginSurface, PluginSurfaceError> {
    let root = canonical_nonsymlink_directory(root).ok_or(PluginSurfaceError::Unavailable)?;
    match provider {
        ProviderPluginSemantics::Codex => inspect_codex(&root),
        ProviderPluginSemantics::Claude => inspect_claude(&root),
    }
}

fn inspect_codex(root: &Path) -> Result<PluginSurface, PluginSurfaceError> {
    let (_manifest_path, manifest) = codex_manifest(root)?;
    let plugin_name = manifest
        .get("name")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let mut declared = BTreeSet::new();
    let mut effective = BTreeSet::new();

    let skill_paths = manifest
        .get("skills")
        .and_then(manifest_paths)
        .filter(|paths| !paths.is_empty())
        .unwrap_or_else(|| vec!["./skills".to_owned()]);
    for skill in skill_components(root, &skill_paths) {
        declared.insert(skill.clone());
        effective.insert(skill);
    }

    match manifest.get("hooks").cloned() {
        Some(Value::Object(object)) => {
            for event in hook_events_from_value(&Value::Object(object)) {
                let component = component(ResourceKind::HookSet, &event);
                declared.insert(component.clone());
                effective.insert(component);
            }
        }
        Some(value @ Value::String(_)) | Some(value @ Value::Array(_)) => {
            let paths = manifest_paths(&value).unwrap_or_default();
            if paths.is_empty() {
                add_hook_file(root, "./hooks/hooks.json", &mut declared, &mut effective);
            } else {
                for path in paths {
                    add_hook_file(root, &path, &mut declared, &mut effective);
                }
            }
        }
        Some(_) | None => {
            add_hook_file(root, "./hooks/hooks.json", &mut declared, &mut effective);
        }
    }

    add_mcp_components(root, manifest.get("mcpServers"), &mut declared, &mut effective);
    add_app_components(root, manifest.get("apps"), &mut declared, &mut effective);

    Ok(surface(declared, effective, plugin_name, false))
}

fn inspect_claude(root: &Path) -> Result<PluginSurface, PluginSurfaceError> {
    let manifest = claude_manifest(root)?;
    let plugin_name = manifest
        .as_ref()
        .and_then(|value| value.get("name"))
        .and_then(Value::as_str)
        .map(str::to_owned);
    let custom_skills = manifest
        .as_ref()
        .and_then(|value| value.get("skills"))
        .is_some();
    let mut declared = BTreeSet::new();
    let mut effective = BTreeSet::new();

    let (default_skills, default_skills_complete) = claude_skill_components(root);
    for skill in &default_skills {
        declared.insert(skill.clone());
        effective.insert(skill.clone());
    }

    if custom_skills {
        let item = component(ResourceKind::Skill, "manifest");
        declared.insert(item.clone());
        effective.insert(item);
    } else if default_skills.is_empty()
        && safe_regular_file(&root.join("SKILL.md"), MAX_COMPONENT_FILE_BYTES).is_some()
    {
        let item = component(ResourceKind::Skill, "root");
        declared.insert(item.clone());
        effective.insert(item);
    }
    add_recursive_markdown_components(
        root,
        "./commands",
        ResourceKind::Command,
        &mut declared,
        &mut effective,
    );
    add_recursive_markdown_components(
        root,
        "./agents",
        ResourceKind::Agent,
        &mut declared,
        &mut effective,
    );

    for (relative, kind) in [
        ("./hooks/hooks.json", ResourceKind::HookSet),
        ("./.mcp.json", ResourceKind::McpServer),
        ("./.lsp.json", ResourceKind::LspServer),
        ("./monitors/monitors.json", ResourceKind::Monitor),
    ] {
        mark_component_path_presence(root, relative, kind, &mut declared, &mut effective);
    }

    if let Some(hooks) = manifest.as_ref().and_then(|value| value.get("hooks")) {
        for event in hook_events_from_value(hooks) {
            let component = component(ResourceKind::HookSet, &event);
            declared.insert(component.clone());
            effective.insert(component);
        }
    }
    add_hook_file(root, "./hooks/hooks.json", &mut declared, &mut effective);
    add_mcp_components(root, None, &mut declared, &mut effective);
    add_named_json_components(
        root,
        "./.lsp.json",
        ResourceKind::LspServer,
        &mut declared,
        &mut effective,
    );
    add_monitor_components(root, &mut declared, &mut effective);
    add_plugin_executables(root, &mut declared, &mut effective);

    // The v0.4 activation qualifier must fail closed on every provider component
    // class whose runtime behavior is not proven by the read-only skill seam.
    // Custom manifest paths can replace default locations, so field presence is
    // itself meaningful even when this bounded inventory does not enumerate the
    // custom file's contents.
    for (field, kind) in [
        ("commands", ResourceKind::Command),
        ("agents", ResourceKind::Agent),
        ("hooks", ResourceKind::HookSet),
        ("mcpServers", ResourceKind::McpServer),
        ("lspServers", ResourceKind::LspServer),
        ("workflows", NativeKind::new("workflow").expect("static kind")),
        ("outputStyles", NativeKind::new("output_style").expect("static kind")),
        ("userConfig", ResourceKind::SettingsOverlay),
        ("channels", NativeKind::new("channel").expect("static kind")),
        ("dependencies", NativeKind::new("dependency").expect("static kind")),
    ] {
        if manifest.as_ref().and_then(|value| value.get(field)).is_some() {
            let item = component(kind, "manifest");
            declared.insert(item.clone());
            effective.insert(item);
        }
    }
    if manifest
        .as_ref()
        .and_then(|value| value.get("experimental"))
        .and_then(Value::as_object)
        .is_some_and(|experimental| experimental.contains_key("monitors"))
    {
        let item = component(ResourceKind::Monitor, "manifest");
        declared.insert(item.clone());
        effective.insert(item);
    }
    if manifest
        .as_ref()
        .and_then(|value| value.get("experimental"))
        .and_then(Value::as_object)
        .is_some_and(|experimental| experimental.contains_key("themes"))
    {
        let item = component(NativeKind::new("theme").expect("static kind"), "manifest");
        declared.insert(item.clone());
        effective.insert(item);
    }

    for (relative, kind) in [
        ("./workflows", NativeKind::new("workflow").expect("static kind")),
        (
            "./output-styles",
            NativeKind::new("output_style").expect("static kind"),
        ),
        ("./themes", NativeKind::new("theme").expect("static kind")),
    ] {
        if resolve_relative(root, relative).is_some() {
            let item = component(kind, "default");
            declared.insert(item.clone());
            effective.insert(item);
        }
    }

    if root.join("settings.json").is_file()
        || manifest
            .as_ref()
            .and_then(|value| value.get("settings"))
            .is_some()
    {
        let component = component(ResourceKind::SettingsOverlay, "default");
        declared.insert(component.clone());
        effective.insert(component);
    }

    let activation_eligible = plugin_name.is_some()
        && !custom_skills
        && default_skills_complete
        && !default_skills.is_empty()
        && effective
            .iter()
            .all(|component| component.kind == ResourceKind::Skill);

    Ok(surface(
        declared,
        effective,
        plugin_name,
        activation_eligible,
    ))
}

fn claude_manifest(root: &Path) -> Result<Option<Value>, PluginSurfaceError> {
    let manifest_path = root.join(".claude-plugin/plugin.json");
    let manifest = match read_json(&manifest_path, MAX_MANIFEST_BYTES) {
        Ok(value) => value,
        Err(PluginSurfaceError::Unavailable) => return Ok(None),
        Err(error) => return Err(error),
    };
    let Some(object) = manifest.as_object() else {
        return Err(PluginSurfaceError::InvalidManifest);
    };
    let Some(name) = object.get("name").and_then(Value::as_str) else {
        return Err(PluginSurfaceError::InvalidManifest);
    };
    if !valid_claude_plugin_name(name) {
        return Err(PluginSurfaceError::InvalidManifest);
    }
    Ok(Some(manifest))
}

fn valid_claude_plugin_name(value: &str) -> bool {
    if value.is_empty() || value.len() > 256 {
        return false;
    }
    value.split('-').all(|segment| {
        !segment.is_empty()
            && segment
                .bytes()
                .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
    })
}

fn codex_manifest(root: &Path) -> Result<(PathBuf, Value), PluginSurfaceError> {
    let root_manifest = root.join("plugin.json");
    if let Ok(value) = read_json(&root_manifest, MAX_MANIFEST_BYTES) {
        if value.get("$schema").and_then(Value::as_str) == Some(AGENT_PLUGIN_SCHEMA) {
            return Err(PluginSurfaceError::UnsupportedManifest);
        }
        if value
            .get("$schema")
            .and_then(Value::as_str)
            .is_some_and(|schema| schema.starts_with("https://agent-plugins.org/schemas/"))
        {
            return Err(PluginSurfaceError::UnsupportedManifest);
        }
    }

    for relative in [
        ".codex-plugin/plugin.json",
        ".claude-plugin/plugin.json",
        ".cursor-plugin/plugin.json",
    ] {
        let path = root.join(relative);
        match read_json(&path, MAX_MANIFEST_BYTES) {
            Ok(value) => return Ok((path, value)),
            Err(PluginSurfaceError::Unavailable) => continue,
            Err(error) => return Err(error),
        }
    }
    Err(PluginSurfaceError::InvalidManifest)
}

fn skill_components(root: &Path, paths: &[String]) -> Vec<PluginComponent> {
    let mut names = BTreeSet::new();
    let mut visited = 0usize;
    for relative in paths {
        let Some(skill_root) = resolve_relative(root, relative) else {
            continue;
        };
        collect_skills(root, &skill_root, &mut names, &mut visited, 0);
        if visited >= MAX_SKILL_ENTRIES {
            break;
        }
    }
    names
        .into_iter()
        .map(|name| component(ResourceKind::Skill, &name))
        .collect()
}

fn collect_skills(
    plugin_root: &Path,
    directory: &Path,
    names: &mut BTreeSet<String>,
    visited: &mut usize,
    depth: usize,
) {
    if *visited >= MAX_SKILL_ENTRIES || depth > 6 {
        return;
    }
    let Some(directory) = canonical_nonsymlink_directory(directory) else {
        return;
    };
    if !directory.starts_with(plugin_root) {
        return;
    }
    if safe_regular_file(&directory.join("SKILL.md"), MAX_COMPONENT_FILE_BYTES).is_some()
        && let Some(name) = directory.file_name().and_then(|name| name.to_str())
        && valid_public_id(name)
    {
        names.insert(name.to_owned());
    }
    let Ok(entries) = fs::read_dir(directory) else {
        return;
    };
    for entry in entries.flatten() {
        *visited += 1;
        if *visited >= MAX_SKILL_ENTRIES {
            break;
        }
        if entry.file_type().is_ok_and(|kind| kind.is_dir()) {
            collect_skills(plugin_root, &entry.path(), names, visited, depth + 1);
        }
    }
}

fn mark_component_path_presence(
    root: &Path,
    relative: &str,
    kind: ResourceKind,
    declared: &mut BTreeSet<PluginComponent>,
    effective: &mut BTreeSet<PluginComponent>,
) {
    let Some(raw_relative) = relative.strip_prefix("./") else {
        return;
    };
    match fs::symlink_metadata(root.join(raw_relative)) {
        Ok(_) => {
            let item = component(kind, "default");
            declared.insert(item.clone());
            effective.insert(item);
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => {
            let item = component(kind, "unreadable-default");
            declared.insert(item.clone());
            effective.insert(item);
        }
    }
}

fn add_hook_file(
    root: &Path,
    relative: &str,
    declared: &mut BTreeSet<PluginComponent>,
    effective: &mut BTreeSet<PluginComponent>,
) {
    let Some(path) = resolve_relative(root, relative) else {
        return;
    };
    let Ok(value) = read_json(&path, MAX_COMPONENT_FILE_BYTES) else {
        return;
    };
    for event in hook_events_from_value(&value) {
        let component = component(ResourceKind::HookSet, &event);
        declared.insert(component.clone());
        effective.insert(component);
    }
}

fn hook_events_from_value(value: &Value) -> Vec<String> {
    value
        .get("hooks")
        .and_then(Value::as_object)
        .or_else(|| value.as_object())
        .into_iter()
        .flat_map(|hooks| hooks.keys())
        .filter(|event| valid_public_id(event))
        .cloned()
        .collect()
}

fn claude_skill_components(root: &Path) -> (Vec<PluginComponent>, bool) {
    let skill_root = root.join("skills");
    let metadata = match fs::symlink_metadata(&skill_root) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return (Vec::new(), true);
        }
        Err(_) => return (Vec::new(), false),
    };
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return (Vec::new(), false);
    }
    let Ok(entries) = fs::read_dir(&skill_root) else {
        return (Vec::new(), false);
    };

    let mut names = BTreeSet::new();
    let mut visited = 0usize;
    let mut complete = true;
    for entry_result in entries {
        visited += 1;
        if visited > MAX_SKILL_ENTRIES {
            complete = false;
            break;
        }
        let entry = match entry_result {
            Ok(entry) => entry,
            Err(_) => {
                complete = false;
                continue;
            }
        };
        let file_type = match entry.file_type() {
            Ok(file_type) => file_type,
            Err(_) => {
                complete = false;
                continue;
            }
        };
        if file_type.is_symlink() {
            complete = false;
            continue;
        }
        if !file_type.is_dir() {
            continue;
        }
        let directory = entry.path();
        let Some(directory) = canonical_nonsymlink_directory(&directory) else {
            complete = false;
            continue;
        };
        if !directory.starts_with(root) {
            complete = false;
            continue;
        }

        let skill_file = directory.join("SKILL.md");
        let skill_metadata = match fs::symlink_metadata(&skill_file) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
            Err(_) => {
                complete = false;
                continue;
            }
        };
        if skill_metadata.file_type().is_symlink()
            || !skill_metadata.is_file()
            || skill_metadata.len() > MAX_COMPONENT_FILE_BYTES
            || fs::read(&skill_file).is_err()
        {
            complete = false;
            continue;
        }

        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            complete = false;
            continue;
        };
        if valid_public_id(&name) {
            names.insert(name);
        } else {
            complete = false;
        }
    }

    (
        names
            .into_iter()
            .map(|name| component(ResourceKind::Skill, &name))
            .collect(),
        complete,
    )
}

fn add_recursive_markdown_components(
    root: &Path,
    relative: &str,
    kind: ResourceKind,
    declared: &mut BTreeSet<PluginComponent>,
    effective: &mut BTreeSet<PluginComponent>,
) {
    let Some(raw_relative) = relative.strip_prefix("./") else {
        let item = component(kind, "invalid-component-root");
        declared.insert(item.clone());
        effective.insert(item);
        return;
    };
    let raw_directory = root.join(raw_relative);
    match fs::symlink_metadata(&raw_directory) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return,
        Err(_) => {
            let item = component(kind, "unreadable-component-root");
            declared.insert(item.clone());
            effective.insert(item);
            return;
        }
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_dir() => {
            let item = component(kind, "symlink-or-invalid-component-root");
            declared.insert(item.clone());
            effective.insert(item);
            return;
        }
        Ok(_) => {}
    }
    let Some(directory) = resolve_relative(root, relative) else {
        let item = component(kind, "component-root-escape");
        declared.insert(item.clone());
        effective.insert(item);
        return;
    };
    let mut visited = 0usize;
    collect_markdown_components(
        root,
        &directory,
        &directory,
        kind,
        declared,
        effective,
        &mut visited,
        0,
    );
}

fn collect_markdown_components(
    plugin_root: &Path,
    component_root: &Path,
    directory: &Path,
    kind: ResourceKind,
    declared: &mut BTreeSet<PluginComponent>,
    effective: &mut BTreeSet<PluginComponent>,
    visited: &mut usize,
    depth: usize,
) {
    if *visited >= MAX_SKILL_ENTRIES || depth > 6 {
        let item = component(kind, "inventory-overflow");
        declared.insert(item.clone());
        effective.insert(item);
        return;
    }
    let Some(directory) = canonical_nonsymlink_directory(directory) else {
        let item = component(kind, "symlink-or-invalid-directory");
        declared.insert(item.clone());
        effective.insert(item);
        return;
    };
    if !directory.starts_with(plugin_root) {
        let item = component(kind, "path-escape");
        declared.insert(item.clone());
        effective.insert(item);
        return;
    }
    let Ok(entries) = fs::read_dir(&directory) else {
        let item = component(kind, "unreadable-directory");
        declared.insert(item.clone());
        effective.insert(item);
        return;
    };
    for entry_result in entries {
        *visited += 1;
        if *visited >= MAX_SKILL_ENTRIES {
            let item = component(kind, "inventory-overflow");
            declared.insert(item.clone());
            effective.insert(item);
            return;
        }
        let entry = match entry_result {
            Ok(entry) => entry,
            Err(_) => {
                let item = component(kind, "unreadable-entry");
                declared.insert(item.clone());
                effective.insert(item);
                continue;
            }
        };
        let path = entry.path();
        let Ok(file_type) = entry.file_type() else {
            let item = component(kind, "unreadable-entry");
            declared.insert(item.clone());
            effective.insert(item);
            continue;
        };
        if file_type.is_symlink() {
            let item = component(kind, "symlink-entry");
            declared.insert(item.clone());
            effective.insert(item);
            continue;
        }
        if file_type.is_dir() {
            collect_markdown_components(
                plugin_root,
                component_root,
                &path,
                kind,
                declared,
                effective,
                visited,
                depth + 1,
            );
            continue;
        }
        if !file_type.is_file() || path.extension().and_then(|value| value.to_str()) != Some("md") {
            continue;
        }
        let id = path
            .strip_prefix(component_root)
            .ok()
            .and_then(|relative| relative.to_str())
            .and_then(|value| value.strip_suffix(".md"))
            .filter(|value| valid_public_id(value))
            .or_else(|| path.file_stem().and_then(|value| value.to_str()))
            .unwrap_or("markdown-component");
        let item = component(kind, id);
        declared.insert(item.clone());
        effective.insert(item);
    }
}

fn add_named_json_components(
    root: &Path,
    relative: &str,
    kind: ResourceKind,
    declared: &mut BTreeSet<PluginComponent>,
    effective: &mut BTreeSet<PluginComponent>,
) {
    let Some(path) = resolve_relative(root, relative) else {
        return;
    };
    let Ok(value) = read_json(&path, MAX_COMPONENT_FILE_BYTES) else {
        return;
    };
    let Some(entries) = value.as_object() else {
        return;
    };
    for id in entries.keys().filter(|id| valid_public_id(id)) {
        let item = component(kind, id);
        declared.insert(item.clone());
        effective.insert(item);
    }
}

fn add_monitor_components(
    root: &Path,
    declared: &mut BTreeSet<PluginComponent>,
    effective: &mut BTreeSet<PluginComponent>,
) {
    let Some(path) = resolve_relative(root, "./monitors/monitors.json") else {
        return;
    };
    let Ok(value) = read_json(&path, MAX_COMPONENT_FILE_BYTES) else {
        return;
    };
    let Some(entries) = value.as_array() else {
        return;
    };
    for entry in entries {
        let Some(id) = entry
            .get("name")
            .and_then(Value::as_str)
            .filter(|id| valid_public_id(id))
        else {
            continue;
        };
        let item = component(ResourceKind::Monitor, id);
        declared.insert(item.clone());
        effective.insert(item);
    }
}

fn add_plugin_executables(
    root: &Path,
    declared: &mut BTreeSet<PluginComponent>,
    effective: &mut BTreeSet<PluginComponent>,
) {
    let Some(directory) = resolve_relative(root, "./bin") else {
        return;
    };
    let Ok(entries) = fs::read_dir(directory) else {
        return;
    };
    for entry in entries.flatten() {
        if !entry.file_type().is_ok_and(|file_type| file_type.is_file()) {
            continue;
        }
        let name = entry.file_name();
        let Some(id) = name.to_str().map(str::to_owned) else {
            continue;
        };
        if !valid_public_id(&id) {
            continue;
        }
        let item = component(ResourceKind::PluginExecutable, &id);
        declared.insert(item.clone());
        effective.insert(item);
    }
}

fn add_mcp_components(
    root: &Path,
    declared_value: Option<&Value>,
    declared: &mut BTreeSet<PluginComponent>,
    effective: &mut BTreeSet<PluginComponent>,
) {
    let value = match declared_value {
        Some(Value::Object(object)) => Some(Value::Object(object.clone())),
        Some(Value::String(path)) => resolve_relative(root, path)
            .and_then(|path| read_json(&path, MAX_COMPONENT_FILE_BYTES).ok()),
        Some(_) => None,
        None => read_json(&root.join(".mcp.json"), MAX_COMPONENT_FILE_BYTES).ok(),
    };
    let Some(value) = value else {
        return;
    };
    let servers = value
        .get("mcpServers")
        .and_then(Value::as_object)
        .or_else(|| value.as_object());
    let Some(servers) = servers else {
        return;
    };
    for name in servers.keys().filter(|name| valid_public_id(name)) {
        let component = component(ResourceKind::McpServer, name);
        declared.insert(component.clone());
        effective.insert(component);
    }
}

fn add_app_components(
    root: &Path,
    declared_value: Option<&Value>,
    declared: &mut BTreeSet<PluginComponent>,
    effective: &mut BTreeSet<PluginComponent>,
) {
    let value = match declared_value.and_then(Value::as_str) {
        Some(path) => resolve_relative(root, path)
            .and_then(|path| read_json(&path, MAX_COMPONENT_FILE_BYTES).ok()),
        None => read_json(&root.join(".app.json"), MAX_COMPONENT_FILE_BYTES).ok(),
    };
    let Some(value) = value else {
        return;
    };
    let candidates: Vec<&Value> = match &value {
        Value::Array(items) => items.iter().collect(),
        Value::Object(object) => object
            .get("apps")
            .and_then(Value::as_array)
            .map(|items| items.iter().collect())
            .unwrap_or_else(|| vec![&value]),
        _ => Vec::new(),
    };
    for candidate in candidates {
        let id = candidate
            .get("id")
            .or_else(|| candidate.get("connectorId"))
            .and_then(Value::as_str);
        if let Some(id) = id.filter(|id| valid_public_id(id)) {
            let component = component(ResourceKind::AppConnector, id);
            declared.insert(component.clone());
            effective.insert(component);
        }
    }
}

fn manifest_paths(value: &Value) -> Option<Vec<String>> {
    match value {
        Value::String(path) if valid_relative_manifest_path(path) => Some(vec![path.clone()]),
        Value::Array(paths) => Some(
            paths
                .iter()
                .filter_map(Value::as_str)
                .filter(|path| valid_relative_manifest_path(path))
                .map(str::to_owned)
                .collect(),
        ),
        _ => None,
    }
}

fn resolve_relative(root: &Path, relative: &str) -> Option<PathBuf> {
    if !valid_relative_manifest_path(relative) {
        return None;
    }
    let candidate = root.join(relative.strip_prefix("./")?);
    let canonical = fs::canonicalize(candidate).ok()?;
    canonical.starts_with(root).then_some(canonical)
}

fn valid_relative_manifest_path(value: &str) -> bool {
    value.starts_with("./")
        && value.len() > 2
        && !value.split(['/', '\\']).any(|component| component == "..")
}

fn read_json(path: &Path, max_bytes: u64) -> Result<Value, PluginSurfaceError> {
    let Some(bytes) = safe_regular_file(path, max_bytes) else {
        return Err(PluginSurfaceError::Unavailable);
    };
    serde_json::from_slice(&bytes).map_err(|_| PluginSurfaceError::InvalidManifest)
}

fn safe_regular_file(path: &Path, max_bytes: u64) -> Option<Vec<u8>> {
    let metadata = fs::symlink_metadata(path).ok()?;
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() > max_bytes {
        return None;
    }
    fs::read(path).ok()
}

fn canonical_nonsymlink_directory(path: &Path) -> Option<PathBuf> {
    let metadata = fs::symlink_metadata(path).ok()?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return None;
    }
    fs::canonicalize(path).ok()
}

fn component(kind: ResourceKind, id: &str) -> PluginComponent {
    PluginComponent {
        kind,
        id: id.to_owned(),
    }
}

fn surface(
    declared: BTreeSet<PluginComponent>,
    effective: BTreeSet<PluginComponent>,
    plugin_name: Option<String>,
    activation_eligible: bool,
) -> PluginSurface {
    PluginSurface {
        declared: declared.into_iter().collect(),
        effective: effective.into_iter().collect(),
        plugin_name,
        activation_eligible,
    }
}

fn valid_public_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .chars()
            .all(|character| character.is_ascii_graphic() && !matches!(character, ',' | ':'))
}

#[cfg(test)]
mod tests {
    use super::{inspect_plugin_surface, PluginComponent, ProviderPluginSemantics};
    use crate::catalog::resource::ResourceKind;
    use std::{
        fs,
        path::PathBuf,
        sync::atomic::{AtomicU64, Ordering},
    };

    static SEQUENCE: AtomicU64 = AtomicU64::new(0);

    fn fixture() -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "clroom-superpowers-6-3-0-{}-{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join(".codex-plugin")).unwrap();
        fs::create_dir_all(root.join(".claude-plugin")).unwrap();
        fs::create_dir_all(root.join("skills/brainstorming")).unwrap();
        fs::create_dir_all(root.join("hooks")).unwrap();
        fs::create_dir_all(root.join("agents/review")).unwrap();
        fs::create_dir_all(root.join("commands/tools")).unwrap();
        fs::write(root.join("skills/brainstorming/SKILL.md"), "fixture\n").unwrap();
        fs::write(
            root.join(".codex-plugin/plugin.json"),
            r#"{"name":"superpowers","version":"6.3.0","skills":"./skills/","hooks":{}}"#,
        )
        .unwrap();
        fs::write(
            root.join(".claude-plugin/plugin.json"),
            r#"{"name":"superpowers","version":"6.3.0","hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"fixture-inline"}]}]}}"#,
        )
        .unwrap();
        fs::write(
            root.join("hooks/hooks.json"),
            r#"{"hooks":{"PostToolUse":[{"hooks":[{"type":"command","command":"fixture"}]}]}}"#,
        )
        .unwrap();
        fs::write(root.join("agents/review/security.md"), "fixture\n").unwrap();
        fs::write(root.join("commands/tools/inspect.md"), "fixture\n").unwrap();
        fs::write(root.join(".lsp.json"), r#"{"rust":{"command":"rust-analyzer"}}"#).unwrap();
        root
    }

    fn has(surface: &[PluginComponent], kind: ResourceKind, id: &str) -> bool {
        surface
            .iter()
            .any(|component| component.kind == kind && component.id == id)
    }

    #[test]
    fn superpowers_6_3_provider_semantics_do_not_flatten_package_contents() {
        let root = fixture();
        let codex = inspect_plugin_surface(ProviderPluginSemantics::Codex, &root).unwrap();
        let claude = inspect_plugin_surface(ProviderPluginSemantics::Claude, &root).unwrap();

        assert!(has(&codex.effective, ResourceKind::Skill, "brainstorming"));
        assert!(!has(
            &codex.effective,
            ResourceKind::HookSet,
            "SessionStart"
        ));
        assert!(has(
            &claude.effective,
            ResourceKind::Skill,
            "brainstorming"
        ));
        assert!(has(
            &claude.effective,
            ResourceKind::HookSet,
            "SessionStart"
        ));
        assert!(has(
            &claude.effective,
            ResourceKind::HookSet,
            "PostToolUse"
        ));
        assert!(has(
            &claude.effective,
            ResourceKind::Agent,
            "review/security"
        ));
        assert!(has(
            &claude.effective,
            ResourceKind::Command,
            "tools/inspect"
        ));
        assert!(has(&claude.effective, ResourceKind::LspServer, "rust"));
        assert!(claude
            .effective
            .iter()
            .any(|item| item.kind == ResourceKind::HookSet && item.id == "manifest"));
        assert!(!codex
            .effective
            .iter()
            .any(|item| matches!(item.kind.as_str(), "mcp" | "app")));
        assert!(!claude
            .effective
            .iter()
            .any(|item| matches!(item.kind.as_str(), "mcp" | "app")));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn claude_root_skill_is_observed_but_not_activation_eligible() {
        let root = fixture();
        fs::remove_dir_all(root.join("skills")).unwrap();
        fs::remove_file(root.join(".claude-plugin/plugin.json")).unwrap();
        fs::write(root.join("SKILL.md"), "fixture\n").unwrap();

        let claude = inspect_plugin_surface(ProviderPluginSemantics::Claude, &root).unwrap();
        assert!(has(&claude.effective, ResourceKind::Skill, "root"));
        assert_eq!(claude.plugin_name, None);
        assert!(!claude.activation_eligible);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn claude_manifestless_default_skill_is_observed_but_not_activation_eligible() {
        let root = fixture();
        fs::remove_file(root.join(".claude-plugin/plugin.json")).unwrap();

        let claude = inspect_plugin_surface(ProviderPluginSemantics::Claude, &root).unwrap();
        assert!(has(
            &claude.effective,
            ResourceKind::Skill,
            "brainstorming"
        ));
        assert_eq!(claude.plugin_name, None);
        assert!(!claude.activation_eligible);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn claude_matching_manifest_default_skill_is_activation_eligible() {
        let root = fixture();
        fs::remove_dir_all(root.join("hooks")).unwrap();
        fs::remove_dir_all(root.join("agents")).unwrap();
        fs::remove_dir_all(root.join("commands")).unwrap();
        fs::remove_file(root.join(".lsp.json")).unwrap();
        fs::write(
            root.join(".claude-plugin/plugin.json"),
            r#"{"name":"superpowers","version":"6.3.0"}"#,
        )
        .unwrap();

        let claude = inspect_plugin_surface(ProviderPluginSemantics::Claude, &root).unwrap();
        assert_eq!(claude.plugin_name.as_deref(), Some("superpowers"));
        assert_eq!(claude.effective.len(), 1);
        assert_eq!(claude.effective[0].kind, ResourceKind::Skill);
        assert_eq!(claude.effective[0].id, "brainstorming");
        assert!(claude.activation_eligible);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn claude_nested_skill_is_not_auto_discovered_beyond_one_level() {
        let root = fixture();
        fs::remove_dir_all(root.join("skills")).unwrap();
        fs::create_dir_all(root.join("skills/group/nested")).unwrap();
        fs::write(root.join("skills/group/nested/SKILL.md"), "fixture\n").unwrap();

        let claude = inspect_plugin_surface(ProviderPluginSemantics::Claude, &root).unwrap();
        assert!(!claude
            .effective
            .iter()
            .any(|component| component.kind == ResourceKind::Skill));

        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn claude_symlinked_skill_entry_makes_activation_ineligible() {
        use std::os::unix::fs::symlink;

        let root = fixture();
        fs::remove_dir_all(root.join("hooks")).unwrap();
        fs::remove_dir_all(root.join("agents")).unwrap();
        fs::remove_dir_all(root.join("commands")).unwrap();
        fs::remove_file(root.join(".lsp.json")).unwrap();
        fs::write(
            root.join(".claude-plugin/plugin.json"),
            r#"{"name":"superpowers","version":"6.3.0"}"#,
        )
        .unwrap();

        let external = root.parent().unwrap().join(format!(
            "clroom-external-skill-{}",
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = fs::remove_dir_all(&external);
        fs::create_dir_all(&external).unwrap();
        fs::write(external.join("SKILL.md"), "external\n").unwrap();
        symlink(&external, root.join("skills/external")).unwrap();

        let claude = inspect_plugin_surface(ProviderPluginSemantics::Claude, &root).unwrap();
        assert!(claude
            .effective
            .iter()
            .any(|component| component.kind == ResourceKind::Skill));
        assert!(!claude.activation_eligible);

        let _ = fs::remove_dir_all(root);
        let _ = fs::remove_dir_all(external);
    }

    #[cfg(unix)]
    #[test]
    fn claude_symlinked_mcp_config_is_observed_fail_closed() {
        use std::os::unix::fs::symlink;

        let root = fixture();
        let target = root.join("config/mcp.json");
        fs::create_dir_all(target.parent().unwrap()).unwrap();
        fs::write(&target, r#"{"mcpServers":{}}"#).unwrap();
        symlink(&target, root.join(".mcp.json")).unwrap();

        let claude = inspect_plugin_surface(ProviderPluginSemantics::Claude, &root).unwrap();
        assert!(has(
            &claude.effective,
            ResourceKind::McpServer,
            "default"
        ));

        let _ = fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn claude_symlinked_command_root_is_observed_fail_closed() {
        use std::os::unix::fs::symlink;

        let root = fixture();
        fs::remove_dir_all(root.join("commands")).unwrap();
        let target = root.join("command-target");
        fs::create_dir_all(&target).unwrap();
        fs::write(target.join("inspect.md"), "fixture\n").unwrap();
        symlink(&target, root.join("commands")).unwrap();

        let claude = inspect_plugin_surface(ProviderPluginSemantics::Claude, &root).unwrap();
        assert!(has(
            &claude.effective,
            ResourceKind::Command,
            "symlink-or-invalid-component-root"
        ));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn claude_manifest_requires_provider_kebab_case_name() {
        for invalid in [
            "",
            "bad\\nname",
            "bad/name",
            "BadName",
            "provider_name",
            "-leading",
            "trailing-",
            "double--dash",
            "bad\nname",
            "bad\u{202e}name",
        ] {
            let root = fixture();
            fs::write(
                root.join(".claude-plugin/plugin.json"),
                serde_json::json!({"name": invalid}).to_string(),
            )
            .unwrap();
            assert_eq!(
                inspect_plugin_surface(ProviderPluginSemantics::Claude, &root),
                Err(super::PluginSurfaceError::InvalidManifest)
            );
            let _ = fs::remove_dir_all(root);
        }

        let root = fixture();
        fs::write(
            root.join(".claude-plugin/plugin.json"),
            r#"{"name":"provider-name-2"}"#,
        )
        .unwrap();
        assert!(inspect_plugin_surface(ProviderPluginSemantics::Claude, &root).is_ok());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn codex_absent_hooks_manifest_field_uses_default_hook_file() {
        let root = fixture();
        fs::write(
            root.join(".codex-plugin/plugin.json"),
            r#"{"name":"superpowers","version":"6.3.0","skills":"./skills/"}"#,
        )
        .unwrap();
        let codex = inspect_plugin_surface(ProviderPluginSemantics::Codex, &root).unwrap();
        assert!(has(
            &codex.effective,
            ResourceKind::HookSet,
            "PostToolUse"
        ));
        let _ = fs::remove_dir_all(root);
    }
}
