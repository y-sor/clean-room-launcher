use serde::{Serialize, Serializer};

const MAX_NATIVE_KIND_BYTES: usize = 64;

/// Provider/standard-owned native kind label.
///
/// This is intentionally open: adding a future upstream kind must not require a
/// CLROOM kernel enum change. The associated constants below are convenience
/// spellings for kinds currently used by qualified adapters and public selector
/// grammar; they are not an exhaustive taxonomy.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct NativeKind {
    bytes: [u8; MAX_NATIVE_KIND_BYTES],
    len: u8,
}

#[allow(non_upper_case_globals)]
impl NativeKind {
    pub const Skill: Self = Self::from_static("skill");
    pub const Command: Self = Self::from_static("command");
    pub const Plugin: Self = Self::from_static("plugin");
    pub const McpServer: Self = Self::from_static("mcp");
    pub const HookSet: Self = Self::from_static("hook");
    pub const Agent: Self = Self::from_static("agent");
    pub const AppConnector: Self = Self::from_static("app");
    pub const LspServer: Self = Self::from_static("lsp");
    pub const Monitor: Self = Self::from_static("monitor");
    pub const PluginExecutable: Self = Self::from_static("bin");
    pub const SettingsOverlay: Self = Self::from_static("settings");

    const fn from_static(value: &str) -> Self {
        let source = value.as_bytes();
        let mut bytes = [0u8; MAX_NATIVE_KIND_BYTES];
        let mut index = 0usize;
        while index < source.len() {
            bytes[index] = source[index];
            index += 1;
        }
        Self {
            bytes,
            len: source.len() as u8,
        }
    }

    pub fn new(value: &str) -> Result<Self, NativeKindError> {
        if !valid_native_kind(value) {
            return Err(NativeKindError);
        }
        let mut bytes = [0u8; MAX_NATIVE_KIND_BYTES];
        bytes[..value.len()].copy_from_slice(value.as_bytes());
        Ok(Self {
            bytes,
            len: value.len() as u8,
        })
    }

    pub fn as_str(&self) -> &str {
        // Construction accepts ASCII graphic input only, so UTF-8 validity is an invariant.
        std::str::from_utf8(&self.bytes[..usize::from(self.len)])
            .expect("validated native kind must remain UTF-8")
    }
}

impl Serialize for NativeKind {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(self.as_str())
    }
}

/// Compatibility alias for the v0.3 implementation while call sites migrate to
/// native-first naming. Unlike the old enum, this type is open to arbitrary
/// validated provider/standard kinds.
pub type ResourceKind = NativeKind;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NativeKindError;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DiscoveryState {
    Discoverable,
    NotDiscoverable,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InstallationState {
    Installed,
    NotInstalled,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EnablementState {
    Enabled,
    Disabled,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SelectionState {
    Selectable,
    NotSelectable,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum QualificationState {
    Qualified,
    Unqualified,
    Unsupported,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceOrigin {
    User,
    Project,
    Managed,
    ProviderBundled,
    Plugin,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ActivationPolicy {
    Standalone,
    AtomicBundle,
    ProviderNative,
    ObservationOnly,
    Unsupported,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize)]
pub struct NativeReference {
    pub provider: String,
    pub kind: NativeKind,
    pub id: String,
}

impl NativeReference {
    pub fn new(provider: &str, kind: NativeKind, id: &str) -> Result<Self, NativeReferenceError> {
        if !valid_component(provider) || !valid_component(id) {
            return Err(NativeReferenceError);
        }
        Ok(Self {
            provider: provider.to_owned(),
            kind,
            id: id.to_owned(),
        })
    }

    pub fn canonical(&self) -> String {
        format!("{}:{}:{}", self.provider, self.kind.as_str(), self.id)
    }
}

/// Compatibility alias while the rest of the v0.3 branch migrates terminology.
pub type ResourceId = NativeReference;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NativeReferenceError;
pub type ResourceIdError = NativeReferenceError;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct NativeEntryInfo {
    #[serde(rename = "native")]
    pub resource: NativeReference,
    pub origin: ResourceOrigin,
    pub discovery: DiscoveryState,
    pub installation: InstallationState,
    pub provider_enablement: EnablementState,
    pub selection: SelectionState,
    pub qualification: QualificationState,
    pub required_dependencies: Vec<String>,
    pub activation_policy: ActivationPolicy,
    pub reason_code: Option<String>,
}

/// Compatibility alias while call sites migrate to native-first naming.
pub type ResourceInfo = NativeEntryInfo;

fn valid_component(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .chars()
            .all(|character| character.is_ascii_graphic() && !matches!(character, ',' | ':'))
}

fn valid_native_kind(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_NATIVE_KIND_BYTES
        && value
            .chars()
            .all(|character| character.is_ascii_graphic() && !matches!(character, ',' | ':'))
}

#[cfg(test)]
mod tests {
    use super::{NativeKind, NativeReference, ResourceId, ResourceKind};

    #[test]
    fn canonical_ids_remain_stable_for_current_selector_kinds() {
        let id = ResourceId::new(
            "codex",
            ResourceKind::Plugin,
            "example@openai-bundled",
        )
        .unwrap();
        assert_eq!(id.canonical(), "codex:plugin:example@openai-bundled");
    }

    #[test]
    fn ids_refuse_whitespace_control_and_selector_delimiters() {
        for invalid in ["", "two words", "bad,member", "bad:member", "line\nbreak"] {
            assert!(ResourceId::new("codex", ResourceKind::Plugin, invalid).is_err());
        }
        for invalid_kind in ["", "future kind", "bad:kind", "bad,kind"] {
            assert!(NativeKind::new(invalid_kind).is_err());
        }
    }

    #[test]
    fn future_provider_kind_requires_no_kernel_enum_change() {
        let kind = NativeKind::new("future_widget").unwrap();
        let native = NativeReference::new("future-provider", kind, "alpha").unwrap();
        assert_eq!(kind.as_str(), "future_widget");
        assert_eq!(native.canonical(), "future-provider:future_widget:alpha");
        assert_eq!(serde_json::to_value(kind).unwrap(), "future_widget");
    }
}
