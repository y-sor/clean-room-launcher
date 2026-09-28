use crate::{
    adapters::identity::ProviderIdentity,
    catalog::{
        provider_inventory::{self, Provider},
        resource::ResourceKind,
        selection::{SelectionRequest, SelectionTarget},
    },
    core::inventory::sha256_hex,
};
use std::{
    collections::BTreeSet,
    fs::{self, File},
    io::Read,
    path::{Path, PathBuf},
};
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;

const MAX_CONFIG_BYTES: u64 = 1024 * 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct McpActivationPlan {
    id: String,
    source_path: PathBuf,
    source_digest: String,
    definition: StdioDefinition,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct StdioDefinition {
    command: String,
    args: Vec<String>,
    env_vars: Vec<String>,
    cwd: Option<PathBuf>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ActivationError {
    UnsupportedRequest,
    ProviderTupleNotQualified,
    MultipleServers,
    MixedResources,
    SourceUnavailable,
    InvalidSource,
    UnknownServer,
    UnsupportedTransport,
    UnsupportedField,
    LiteralEnvironment,
    EnvironmentNotAdmitted,
    DisabledServer,
    StateChanged,
}

impl McpActivationPlan {
    pub fn id(&self) -> &str {
        &self.id
    }

    pub fn provider_config_args(&self) -> Vec<String> {
        let mut fields = vec![format!("command={}", toml_basic_string(&self.definition.command))];
        if !self.definition.args.is_empty() {
            fields.push(format!(
                "args=[{}]",
                self.definition
                    .args
                    .iter()
                    .map(|value| toml_basic_string(value))
                    .collect::<Vec<_>>()
                    .join(",")
            ));
        }
        if !self.definition.env_vars.is_empty() {
            fields.push(format!(
                "env_vars=[{}]",
                self.definition
                    .env_vars
                    .iter()
                    .map(|value| toml_basic_string(value))
                    .collect::<Vec<_>>()
                    .join(",")
            ));
        }
        if let Some(cwd) = self.definition.cwd.as_ref() {
            fields.push(format!(
                "cwd={}",
                toml_basic_string(&cwd.to_string_lossy())
            ));
        }
        vec![
            "-c".to_owned(),
            format!(
                "mcp_servers={{{}={{{}}}}}",
                toml_basic_string(&self.id),
                fields.join(",")
            ),
        ]
    }

    pub fn revalidate(&self, pass_env: &[String]) -> Result<(), ActivationError> {
        let (digest, definition) =
            load_definition(&self.source_path, &self.id, pass_env)?;
        if digest != self.source_digest || definition != self.definition {
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
    if request.is_empty() {
        return Ok(None);
    }
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
    plan_for_source(ambient_codex_home, request, pass_env)
}

fn plan_for_source(
    ambient_codex_home: &Path,
    request: &SelectionRequest,
    pass_env: &[String],
) -> Result<Option<McpActivationPlan>, ActivationError> {
    if !request.excludes.is_empty() {
        return Err(ActivationError::UnsupportedRequest);
    }
    let mut ids = Vec::new();
    for target in &request.includes {
        match target {
            SelectionTarget::Exact { kind, id } if *kind == ResourceKind::McpServer => {
                ids.push(id.clone());
            }
            SelectionTarget::Exact { .. } => return Err(ActivationError::MixedResources),
            SelectionTarget::All => return Err(ActivationError::UnsupportedRequest),
        }
    }
    if ids.is_empty() {
        return Ok(None);
    }
    if ids.len() != 1 {
        return Err(ActivationError::MultipleServers);
    }
    let id = ids.pop().expect("one MCP id");
    let source_path = ambient_codex_home.join("config.toml");
    let (source_digest, definition) = load_definition(&source_path, &id, pass_env)?;
    Ok(Some(McpActivationPlan {
        id,
        source_path,
        source_digest,
        definition,
    }))
}

fn load_definition(
    source_path: &Path,
    id: &str,
    pass_env: &[String],
) -> Result<(String, StdioDefinition), ActivationError> {
    let bytes = read_stable_regular_file(source_path)?;
    let source_digest = sha256_hex(&bytes);
    let text = std::str::from_utf8(&bytes).map_err(|_| ActivationError::InvalidSource)?;
    let document: toml::Value =
        toml::from_str(text).map_err(|_| ActivationError::InvalidSource)?;
    let root = document.as_table().ok_or(ActivationError::InvalidSource)?;
    let servers = root
        .get("mcp_servers")
        .and_then(toml::Value::as_table)
        .ok_or(ActivationError::UnknownServer)?;
    let server = servers
        .get(id)
        .and_then(toml::Value::as_table)
        .ok_or(ActivationError::UnknownServer)?;

    let allowed = BTreeSet::from(["command", "args", "env", "env_vars", "cwd", "enabled", "url"]);
    if server.keys().any(|key| !allowed.contains(key.as_str())) {
        return Err(ActivationError::UnsupportedField);
    }
    if server.contains_key("env") {
        return Err(ActivationError::LiteralEnvironment);
    }

    let command = server
        .get("command")
        .and_then(toml::Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or(ActivationError::UnsupportedTransport)?
        .to_owned();
    if server.contains_key("url") {
        return Err(ActivationError::UnsupportedTransport);
    }

    let args = match server.get("args") {
        None => Vec::new(),
        Some(value) => value
            .as_array()
            .ok_or(ActivationError::UnsupportedField)?
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(str::to_owned)
                    .ok_or(ActivationError::UnsupportedField)
            })
            .collect::<Result<Vec<_>, _>>()?,
    };

    let admitted = pass_env.iter().map(String::as_str).collect::<BTreeSet<_>>();
    let env_vars = match server.get("env_vars") {
        None => Vec::new(),
        Some(value) => value
            .as_array()
            .ok_or(ActivationError::UnsupportedField)?
            .iter()
            .map(|value| {
                let name = value.as_str().ok_or(ActivationError::UnsupportedField)?;
                if !valid_env_name(name) || !admitted.contains(name) {
                    return Err(ActivationError::EnvironmentNotAdmitted);
                }
                Ok(name.to_owned())
            })
            .collect::<Result<Vec<_>, _>>()?,
    };

    if server
        .get("enabled")
        .is_some_and(|value| value.as_bool() != Some(true))
    {
        return Err(ActivationError::DisabledServer);
    }

    let cwd = server
        .get("cwd")
        .map(|value| {
            let raw = value.as_str().ok_or(ActivationError::UnsupportedField)?;
            let path = PathBuf::from(raw);
            let resolved = if path.is_absolute() {
                path
            } else {
                source_path
                    .parent()
                    .ok_or(ActivationError::InvalidSource)?
                    .join(path)
            };
            let canonical =
                fs::canonicalize(resolved).map_err(|_| ActivationError::InvalidSource)?;
            if !fs::metadata(&canonical)
                .is_ok_and(|metadata| metadata.is_dir())
            {
                return Err(ActivationError::InvalidSource);
            }
            Ok(canonical)
        })
        .transpose()?;

    Ok((
        source_digest,
        StdioDefinition {
            command,
            args,
            env_vars,
            cwd,
        },
    ))
}

fn read_stable_regular_file(path: &Path) -> Result<Vec<u8>, ActivationError> {
    let path_before = fs::symlink_metadata(path).map_err(|_| ActivationError::SourceUnavailable)?;
    if path_before.file_type().is_symlink()
        || !path_before.is_file()
        || path_before.len() > MAX_CONFIG_BYTES
    {
        return Err(ActivationError::InvalidSource);
    }
    let mut file = File::open(path).map_err(|_| ActivationError::SourceUnavailable)?;
    let before = file.metadata().map_err(|_| ActivationError::InvalidSource)?;
    if !same_file(&path_before, &before) {
        return Err(ActivationError::InvalidSource);
    }
    let mut bytes = Vec::with_capacity(before.len() as usize);
    (&mut file)
        .take(MAX_CONFIG_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| ActivationError::InvalidSource)?;
    if bytes.len() as u64 > MAX_CONFIG_BYTES {
        return Err(ActivationError::InvalidSource);
    }
    let after = file.metadata().map_err(|_| ActivationError::InvalidSource)?;
    let path_after = fs::symlink_metadata(path).map_err(|_| ActivationError::StateChanged)?;
    if path_after.file_type().is_symlink()
        || !same_file(&before, &after)
        || !same_file(&after, &path_after)
        || after.len() != bytes.len() as u64
    {
        return Err(ActivationError::StateChanged);
    }
    Ok(bytes)
}

#[cfg(unix)]
fn same_file(left: &fs::Metadata, right: &fs::Metadata) -> bool {
    left.dev() == right.dev()
        && left.ino() == right.ino()
        && left.len() == right.len()
        && left.mtime() == right.mtime()
        && left.mtime_nsec() == right.mtime_nsec()
        && left.ctime() == right.ctime()
        && left.ctime_nsec() == right.ctime_nsec()
}

#[cfg(not(unix))]
fn same_file(left: &fs::Metadata, right: &fs::Metadata) -> bool {
    left.len() == right.len() && left.modified().ok() == right.modified().ok()
}

fn valid_env_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 128
        && name.bytes().enumerate().all(|(index, byte)| {
            byte.is_ascii_uppercase() || byte == b'_' || (index > 0 && byte.is_ascii_digit())
        })
}

fn toml_basic_string(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len() + 2);
    escaped.push('"');
    for character in value.chars() {
        match character {
            '"' => escaped.push_str("\\\""),
            '\\' => escaped.push_str("\\\\"),
            '\u{0008}' => escaped.push_str("\\b"),
            '\t' => escaped.push_str("\\t"),
            '\n' => escaped.push_str("\\n"),
            '\u{000c}' => escaped.push_str("\\f"),
            '\r' => escaped.push_str("\\r"),
            character if character <= '\u{001f}' || character == '\u{007f}' => {
                escaped.push_str(&format!("\\u{:04X}", character as u32));
            }
            character => escaped.push(character),
        }
    }
    escaped.push('"');
    escaped
}

#[cfg(test)]
mod tests {
    use super::{plan_for_source, ActivationError};
    use crate::catalog::selection::SelectionRequest;
    use std::{
        fs,
        path::{Path, PathBuf},
        sync::atomic::{AtomicU64, Ordering},
    };

    static SEQUENCE: AtomicU64 = AtomicU64::new(0);

    fn fixture(config: &str) -> (PathBuf, SelectionRequest) {
        let root = std::env::temp_dir().join(format!(
            "clroom-mcp-activation-{}-{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("config.toml"), config).unwrap();
        let mut request = SelectionRequest::default();
        request.include_value("mcp:fixture").unwrap();
        (root, request)
    }

    fn cleanup(root: &Path) {
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn exact_stdio_reference_only_server_projects_one_session_override() {
        let (root, request) = fixture(
            r#"
[mcp_servers.sibling]
command = "/usr/bin/false"

[mcp_servers.fixture]
command = "/usr/bin/env"
args = ["python3", "server.py"]
env_vars = ["CLROOM_MCP_ALLOWED"]
"#,
        );
        let plan = plan_for_source(
            &root,
            &request,
            &["CLROOM_MCP_ALLOWED".to_owned()],
        )
        .unwrap()
        .unwrap();
        let args = plan.provider_config_args();
        assert_eq!(plan.id(), "fixture");
        assert_eq!(args[0], "-c");
        assert!(args[1].contains("mcp_servers={"));
        assert!(args[1].contains("\"fixture\""));
        assert!(!args[1].contains("sibling"));
        assert!(!args[1].contains("CLROOM_MCP_BLOCKED"));
        cleanup(&root);
    }

    #[test]
    fn literal_env_and_unadmitted_reference_fail_closed() {
        let (root, request) = fixture(
            r#"
[mcp_servers.fixture]
command = "/usr/bin/env"
env = { TOKEN = "secret" }
"#,
        );
        assert_eq!(
            plan_for_source(&root, &request, &[]),
            Err(ActivationError::LiteralEnvironment)
        );
        cleanup(&root);

        let (root, request) = fixture(
            r#"
[mcp_servers.fixture]
command = "/usr/bin/env"
env_vars = ["CLROOM_MCP_ALLOWED"]
"#,
        );
        assert_eq!(
            plan_for_source(&root, &request, &[]),
            Err(ActivationError::EnvironmentNotAdmitted)
        );
        cleanup(&root);
    }

    #[test]
    fn remote_env_shape_unknown_fields_and_http_fail_closed() {
        for config in [
            r#"
[mcp_servers.fixture]
command = "/usr/bin/env"
env_vars = [{ name = "TOKEN", source = "remote" }]
"#,
            r#"
[mcp_servers.fixture]
command = "/usr/bin/env"
startup_timeout_sec = 5
"#,
            r#"
[mcp_servers.fixture]
url = "https://example.invalid/mcp"
"#,
        ] {
            let (root, request) = fixture(config);
            assert!(plan_for_source(&root, &request, &[]).is_err());
            cleanup(&root);
        }
    }

    #[test]
    fn source_change_after_planning_is_refused() {
        let (root, request) = fixture(
            r#"
[mcp_servers.fixture]
command = "/usr/bin/true"
"#,
        );
        let plan = plan_for_source(&root, &request, &[]).unwrap().unwrap();
        fs::write(
            root.join("config.toml"),
            r#"
[mcp_servers.fixture]
command = "/usr/bin/false"
"#,
        )
        .unwrap();
        assert_eq!(plan.revalidate(&[]), Err(ActivationError::StateChanged));
        cleanup(&root);
    }
}
