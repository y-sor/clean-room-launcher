use crate::{
    adapters::identity::ProviderIdentity,
    catalog::{
        provider_inventory::{self, Provider},
        resource::ResourceKind,
        selection::{SelectionRequest, SelectionTarget},
    },
    core::inventory::sha256_hex,
};
use serde::de::{DeserializeSeed, IgnoredAny, MapAccess, Visitor};
use std::{
    collections::BTreeSet,
    fmt,
    fs::{self, File},
    io::Read,
    path::{Path, PathBuf},
};

const MAX_CONFIG_BYTES: u64 = 1024 * 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct McpActivationPlan {
    id: String,
    source_path: PathBuf,
    source_digest: String,
    command: String,
    args: Vec<String>,
    env_vars: Vec<String>,
    cwd: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ActivationError {
    UnsupportedRequest,
    ProviderTupleNotQualified,
    MultipleMcp,
    MixedSelection,
    UnknownMcp,
    InvalidSource,
    LiteralEnvironment,
    UnadmittedEnvironment(String),
    UnsupportedEnvironmentReference,
    UnsupportedField(String),
    InvalidIdentityField,
    RelativeWorkingDirectory,
    StateChanged,
}

impl McpActivationPlan {
    pub fn id(&self) -> &str {
        &self.id
    }

    pub fn provider_config_args(&self) -> Vec<String> {
        let mut fields = vec![format!("command={}", toml_string(&self.command))];
        if !self.args.is_empty() {
            fields.push(format!("args={}", toml_string_array(&self.args)));
        }
        if !self.env_vars.is_empty() {
            fields.push(format!("env_vars={}", toml_string_array(&self.env_vars)));
        }
        if let Some(cwd) = &self.cwd {
            fields.push(format!("cwd={}", toml_string(cwd)));
        }
        vec![
            "-c".to_owned(),
            format!(
                "mcp_servers={{{}={{{}}}}}",
                toml_string(&self.id),
                fields.join(",")
            ),
        ]
    }

    pub fn revalidate(&self) -> Result<(), ActivationError> {
        let source = read_source(&self.source_path)?;
        if sha256_hex(source.as_bytes()) != self.source_digest {
            return Err(ActivationError::StateChanged);
        }
        Ok(())
    }
}

pub fn plan(
    ambient_codex_home: &Path,
    request: &SelectionRequest,
    identity: &ProviderIdentity,
    pass_env: &[String],
) -> Result<Option<McpActivationPlan>, ActivationError> {
    let Some(id) = selected_mcp(request)? else {
        return Ok(None);
    };
    if identity.provider_id != "codex"
        || !provider_inventory::clean_launch_exact_tuple(
            Provider::Codex,
            identity.version,
            &identity.os,
            &identity.arch,
        )
    {
        return Err(ActivationError::ProviderTupleNotQualified);
    }

    let source_path = ambient_codex_home.join("config.toml");
    let source = read_source(&source_path)?;
    let source_digest = sha256_hex(source.as_bytes());
    let server = selected_server(&source, &id)?.ok_or(ActivationError::UnknownMcp)?;

    for key in server.keys() {
        if !matches!(key.as_str(), "command" | "args" | "env_vars" | "cwd") {
            if key == "env" {
                return Err(ActivationError::LiteralEnvironment);
            }
            return Err(ActivationError::UnsupportedField(key.clone()));
        }
    }

    let command = server
        .get("command")
        .and_then(toml::Value::as_str)
        .filter(|value| valid_identity_field(value, false))
        .ok_or(ActivationError::InvalidIdentityField)?
        .to_owned();

    let args = match server.get("args") {
        None => Vec::new(),
        Some(value) => value
            .as_array()
            .ok_or(ActivationError::InvalidIdentityField)?
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .filter(|value| valid_identity_field(value, true))
                    .map(str::to_owned)
                    .ok_or(ActivationError::InvalidIdentityField)
            })
            .collect::<Result<Vec<_>, _>>()?,
    };

    let admitted = pass_env.iter().map(String::as_str).collect::<BTreeSet<_>>();
    let env_vars = match server.get("env_vars") {
        None => Vec::new(),
        Some(value) => {
            let values = value
                .as_array()
                .ok_or(ActivationError::UnsupportedEnvironmentReference)?;
            let mut names = Vec::with_capacity(values.len());
            for value in values {
                let name = value
                    .as_str()
                    .filter(|name| valid_env_name(name))
                    .ok_or(ActivationError::UnsupportedEnvironmentReference)?;
                if !admitted.contains(name) {
                    return Err(ActivationError::UnadmittedEnvironment(name.to_owned()));
                }
                if !names.iter().any(|existing| existing == name) {
                    names.push(name.to_owned());
                }
            }
            names
        }
    };

    let cwd = match server.get("cwd") {
        None => None,
        Some(value) => {
            let cwd = value
                .as_str()
                .filter(|value| valid_identity_field(value, false))
                .ok_or(ActivationError::InvalidIdentityField)?;
            if !Path::new(cwd).is_absolute() {
                return Err(ActivationError::RelativeWorkingDirectory);
            }
            Some(cwd.to_owned())
        }
    };

    Ok(Some(McpActivationPlan {
        id,
        source_path,
        source_digest,
        command,
        args,
        env_vars,
        cwd,
    }))
}


fn selected_server(source: &str, selected_id: &str) -> Result<Option<toml::Table>, ActivationError> {
    let deserializer =
        toml::de::Deserializer::parse(source).map_err(|_| ActivationError::InvalidSource)?;
    RootSeed { selected_id }
        .deserialize(deserializer)
        .map_err(|_| ActivationError::InvalidSource)
}

struct RootSeed<'a> {
    selected_id: &'a str,
}

impl<'de> DeserializeSeed<'de> for RootSeed<'_> {
    type Value = Option<toml::Table>;

    fn deserialize<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        deserializer.deserialize_map(RootVisitor {
            selected_id: self.selected_id,
        })
    }
}

struct RootVisitor<'a> {
    selected_id: &'a str,
}

impl<'de> Visitor<'de> for RootVisitor<'_> {
    type Value = Option<toml::Table>;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a Codex config table")
    }

    fn visit_map<M>(self, mut map: M) -> Result<Self::Value, M::Error>
    where
        M: MapAccess<'de>,
    {
        let mut selected = None;
        while let Some(key) = map.next_key::<String>()? {
            if key == "mcp_servers" {
                selected = map.next_value_seed(McpServersSeed {
                    selected_id: self.selected_id,
                })?;
            } else {
                map.next_value::<IgnoredAny>()?;
            }
        }
        Ok(selected)
    }
}

struct McpServersSeed<'a> {
    selected_id: &'a str,
}

impl<'de> DeserializeSeed<'de> for McpServersSeed<'_> {
    type Value = Option<toml::Table>;

    fn deserialize<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        deserializer.deserialize_map(McpServersVisitor {
            selected_id: self.selected_id,
        })
    }
}

struct McpServersVisitor<'a> {
    selected_id: &'a str,
}

impl<'de> Visitor<'de> for McpServersVisitor<'_> {
    type Value = Option<toml::Table>;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("an MCP server table")
    }

    fn visit_map<M>(self, mut map: M) -> Result<Self::Value, M::Error>
    where
        M: MapAccess<'de>,
    {
        let mut selected = None;
        while let Some(key) = map.next_key::<String>()? {
            if key == self.selected_id {
                selected = Some(map.next_value::<toml::Table>()?);
            } else {
                map.next_value::<IgnoredAny>()?;
            }
        }
        Ok(selected)
    }
}

fn selected_mcp(request: &SelectionRequest) -> Result<Option<String>, ActivationError> {
    let mut selected = Vec::new();
    let mut other = false;
    let mut mcp_excluded = false;

    for target in &request.includes {
        match target {
            SelectionTarget::Exact { kind, id } if *kind == ResourceKind::McpServer => {
                selected.push(id.clone());
            }
            _ => other = true,
        }
    }
    for target in &request.excludes {
        match target {
            SelectionTarget::Exact { kind, .. } if *kind == ResourceKind::McpServer => {
                mcp_excluded = true;
            }
            _ => other = true,
        }
    }

    if selected.is_empty() {
        if mcp_excluded {
            return Err(ActivationError::UnsupportedRequest);
        }
        return Ok(None);
    }
    if selected.len() != 1 {
        return Err(ActivationError::MultipleMcp);
    }
    if mcp_excluded {
        return Err(ActivationError::UnsupportedRequest);
    }
    if other {
        return Err(ActivationError::MixedSelection);
    }
    Ok(selected.pop())
}

fn read_source(path: &Path) -> Result<String, ActivationError> {
    let path_before = fs::symlink_metadata(path).map_err(|_| ActivationError::InvalidSource)?;
    if path_before.file_type().is_symlink()
        || !path_before.is_file()
        || path_before.len() > MAX_CONFIG_BYTES
    {
        return Err(ActivationError::InvalidSource);
    }

    let mut file = File::open(path).map_err(|_| ActivationError::InvalidSource)?;
    let handle_before = file.metadata().map_err(|_| ActivationError::InvalidSource)?;
    if !same_file_state(&path_before, &handle_before) {
        return Err(ActivationError::InvalidSource);
    }

    let mut bytes = Vec::with_capacity(handle_before.len() as usize);
    (&mut file)
        .take(MAX_CONFIG_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| ActivationError::InvalidSource)?;
    if bytes.len() as u64 > MAX_CONFIG_BYTES {
        return Err(ActivationError::InvalidSource);
    }

    let handle_after = file.metadata().map_err(|_| ActivationError::InvalidSource)?;
    let path_after = fs::symlink_metadata(path).map_err(|_| ActivationError::StateChanged)?;
    if path_after.file_type().is_symlink()
        || !same_file_state(&handle_before, &handle_after)
        || !same_file_state(&handle_after, &path_after)
        || handle_after.len() != bytes.len() as u64
    {
        return Err(ActivationError::StateChanged);
    }

    String::from_utf8(bytes).map_err(|_| ActivationError::InvalidSource)
}

#[cfg(unix)]
fn same_file_state(left: &fs::Metadata, right: &fs::Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;
    left.dev() == right.dev()
        && left.ino() == right.ino()
        && left.len() == right.len()
        && left.mtime() == right.mtime()
        && left.mtime_nsec() == right.mtime_nsec()
        && left.ctime() == right.ctime()
        && left.ctime_nsec() == right.ctime_nsec()
}

#[cfg(not(unix))]
fn same_file_state(left: &fs::Metadata, right: &fs::Metadata) -> bool {
    left.len() == right.len() && left.modified().ok() == right.modified().ok()
}

fn valid_identity_field(value: &str, allow_empty: bool) -> bool {
    (allow_empty || !value.is_empty()) && !value.contains(' ') && !value.contains('$')
}

fn valid_env_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 128
        && name.bytes().enumerate().all(|(index, byte)| {
            (byte.is_ascii_uppercase() || byte == b'_') || (index > 0 && byte.is_ascii_digit())
        })
}

fn toml_string(value: &str) -> String {
    toml::Value::String(value.to_owned()).to_string()
}

fn toml_string_array(values: &[String]) -> String {
    toml::Value::Array(
        values
            .iter()
            .cloned()
            .map(toml::Value::String)
            .collect(),
    )
    .to_string()
}

#[cfg(test)]
mod tests {
    use super::{plan, ActivationError};
    use crate::{
        adapters::identity::ProviderIdentity,
        catalog::selection::SelectionRequest,
    };
    use std::{
        fs,
        path::{Path, PathBuf},
        sync::atomic::{AtomicU64, Ordering},
    };

    static SEQUENCE: AtomicU64 = AtomicU64::new(0);

    fn fixture(config: &str) -> (PathBuf, ProviderIdentity) {
        let root = std::env::temp_dir().join(format!(
            "clroom-codex-mcp-{}-{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        let codex_home = root.join(".codex");
        fs::create_dir_all(&codex_home).unwrap();
        fs::write(codex_home.join("config.toml"), config).unwrap();
        (
            root,
            ProviderIdentity {
                provider_id: "codex".to_owned(),
                real_executable: PathBuf::from("/usr/bin/codex"),
                artifact_digest: "0".repeat(64),
                version: (0, 159, 0),
                os: "macos".to_owned(),
                arch: "aarch64".to_owned(),
                interpreter: None,
            },
        )
    }

    fn request(value: &str) -> SelectionRequest {
        let mut request = SelectionRequest::default();
        request.include_value(value).unwrap();
        request
    }

    fn cleanup(root: &Path) {
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn exact_stdio_server_builds_one_reference_only_override() {
        let (root, identity) = fixture(
            r#"[mcp_servers.docs]
command = "/usr/bin/docs-mcp"
args = ["--stdio"]
env_vars = ["DOCS_TOKEN"]
cwd = "/tmp"
"#,
        );
        let plan = plan(
            &root.join(".codex"),
            &request("mcp:docs"),
            &identity,
            &["DOCS_TOKEN".to_owned()],
        )
        .unwrap()
        .unwrap();

        assert_eq!(plan.id(), "docs");
        let args = plan.provider_config_args();
        assert_eq!(args[0], "-c");
        assert!(args[1].contains(r#""docs""#));
        assert!(args[1].contains("DOCS_TOKEN"));
        assert!(!args[1].contains("secret"));
        cleanup(&root);
    }

    #[test]
    fn unrelated_mcp_values_are_not_selected() {
        let (root, identity) = fixture(
            r#"[mcp_servers.sibling]
command = "sibling-mcp"
env = { SECRET = "must-not-be-selected" }
http_headers = { Authorization = "literal" }

[mcp_servers.docs]
command = "docs-mcp"
"#,
        );
        let plan = plan(&root.join(".codex"), &request("mcp:docs"), &identity, &[])
            .unwrap()
            .unwrap();

        assert_eq!(plan.id(), "docs");
        assert!(!plan.provider_config_args()[1].contains("must-not-be-selected"));
        assert!(!plan.provider_config_args()[1].contains("Authorization"));
        cleanup(&root);
    }

    #[test]
    fn literal_environment_is_refused() {
        let (root, identity) = fixture(
            r#"[mcp_servers.docs]
command = "docs-mcp"
env = { DOCS_TOKEN = "literal-secret" }
"#,
        );
        assert_eq!(
            plan(&root.join(".codex"), &request("mcp:docs"), &identity, &[]),
            Err(ActivationError::LiteralEnvironment)
        );
        cleanup(&root);
    }

    #[test]
    fn unadmitted_environment_reference_is_refused() {
        let (root, identity) = fixture(
            r#"[mcp_servers.docs]
command = "docs-mcp"
env_vars = ["DOCS_TOKEN"]
"#,
        );
        assert_eq!(
            plan(&root.join(".codex"), &request("mcp:docs"), &identity, &[]),
            Err(ActivationError::UnadmittedEnvironment(
                "DOCS_TOKEN".to_owned()
            ))
        );
        cleanup(&root);
    }

    #[test]
    fn structured_environment_reference_is_refused() {
        let (root, identity) = fixture(
            r#"[mcp_servers.docs]
command = "docs-mcp"
env_vars = [{ name = "DOCS_TOKEN", source = "shell" }]
"#,
        );
        assert_eq!(
            plan(
                &root.join(".codex"),
                &request("mcp:docs"),
                &identity,
                &["DOCS_TOKEN".to_owned()],
            ),
            Err(ActivationError::UnsupportedEnvironmentReference)
        );
        cleanup(&root);
    }

    #[test]
    fn http_and_unknown_fields_are_refused() {
        for (config, expected) in [
            (
                r#"[mcp_servers.docs]
url = "https://example.invalid/mcp"
"#,
                ActivationError::UnsupportedField("url".to_owned()),
            ),
            (
                r#"[mcp_servers.docs]
command = "docs-mcp"
required = true
"#,
                ActivationError::UnsupportedField("required".to_owned()),
            ),
        ] {
            let (root, identity) = fixture(config);
            assert_eq!(
                plan(&root.join(".codex"), &request("mcp:docs"), &identity, &[]),
                Err(expected)
            );
            cleanup(&root);
        }
    }

    #[test]
    fn relative_cwd_and_interpolation_are_refused() {
        for (config, expected) in [
            (
                r#"[mcp_servers.docs]
command = "docs-mcp"
cwd = "./tools"
"#,
                ActivationError::RelativeWorkingDirectory,
            ),
            (
                r#"[mcp_servers.docs]
command = "${MCP_BIN}"
"#,
                ActivationError::InvalidIdentityField,
            ),
        ] {
            let (root, identity) = fixture(config);
            assert_eq!(
                plan(&root.join(".codex"), &request("mcp:docs"), &identity, &[]),
                Err(expected)
            );
            cleanup(&root);
        }
    }

    #[test]
    fn multiple_mixed_excluded_and_wrong_tuple_are_refused() {
        let (root, identity) = fixture(
            r#"[mcp_servers.docs]
command = "docs-mcp"
[mcp_servers.other]
command = "other-mcp"
"#,
        );

        assert_eq!(
            plan(
                &root.join(".codex"),
                &request("mcp:docs,other"),
                &identity,
                &[],
            ),
            Err(ActivationError::MultipleMcp)
        );

        let mut mixed = request("mcp:docs");
        mixed.include_value("plugin:demo@bundled").unwrap();
        assert_eq!(
            plan(&root.join(".codex"), &mixed, &identity, &[]),
            Err(ActivationError::MixedSelection)
        );

        let mut excluded = SelectionRequest::default();
        excluded.exclude_value("mcp:docs").unwrap();
        assert_eq!(
            plan(&root.join(".codex"), &excluded, &identity, &[]),
            Err(ActivationError::UnsupportedRequest)
        );

        let wrong = ProviderIdentity {
            provider_id: identity.provider_id.clone(),
            real_executable: identity.real_executable.clone(),
            artifact_digest: identity.artifact_digest.clone(),
            version: (0, 158, 0),
            os: identity.os.clone(),
            arch: identity.arch.clone(),
            interpreter: identity.interpreter.clone(),
        };
        assert_eq!(
            plan(&root.join(".codex"), &request("mcp:docs"), &wrong, &[]),
            Err(ActivationError::ProviderTupleNotQualified)
        );
        cleanup(&root);
    }

    #[cfg(unix)]
    #[test]
    fn symlink_source_is_refused() {
        use std::os::unix::fs::symlink;

        let (root, identity) = fixture(
            r#"[mcp_servers.docs]
command = "docs-mcp"
"#,
        );
        let config = root.join(".codex/config.toml");
        let real = root.join("real-config.toml");
        fs::rename(&config, &real).unwrap();
        symlink(&real, &config).unwrap();
        assert_eq!(
            plan(&root.join(".codex"), &request("mcp:docs"), &identity, &[]),
            Err(ActivationError::InvalidSource)
        );
        cleanup(&root);
    }

    #[test]
    fn oversized_source_is_refused() {
        let (root, identity) = fixture("");
        fs::write(
            root.join(".codex/config.toml"),
            vec![b'a'; super::MAX_CONFIG_BYTES as usize + 1],
        )
        .unwrap();
        assert_eq!(
            plan(&root.join(".codex"), &request("mcp:docs"), &identity, &[]),
            Err(ActivationError::InvalidSource)
        );
        cleanup(&root);
    }

    #[test]
    fn source_change_after_planning_is_refused() {
        let (root, identity) = fixture(
            r#"[mcp_servers.docs]
command = "docs-mcp"
"#,
        );
        let plan = plan(&root.join(".codex"), &request("mcp:docs"), &identity, &[])
            .unwrap()
            .unwrap();
        fs::write(
            root.join(".codex/config.toml"),
            "[mcp_servers.docs]\ncommand = \"changed\"\n",
        )
        .unwrap();
        assert_eq!(plan.revalidate(), Err(ActivationError::StateChanged));
        cleanup(&root);
    }
}
