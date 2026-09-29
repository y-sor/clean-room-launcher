use serde::{
    de::{IgnoredAny, MapAccess, Visitor},
    Deserialize, Deserializer,
};
use std::fmt;

#[derive(Deserialize)]
pub(super) struct ProbeEnvelope {
    #[serde(default)]
    pub(super) id: Option<i64>,
    #[serde(default)]
    pub(super) result: Option<ProbeResult>,
    #[serde(default)]
    pub(super) error: Option<IgnoredAny>,
}

#[derive(Deserialize)]
pub(super) struct ProbeResult {
    #[serde(default)]
    pub(super) layers: Option<Vec<ProbeLayer>>,
}

#[derive(Deserialize)]
pub(super) struct ProbeLayer {
    pub(super) name: ProbeLayerName,
    #[serde(rename = "disabledReason", default)]
    pub(super) disabled_reason: Option<IgnoredAny>,
    #[serde(default)]
    pub(super) config: McpPresence,
}

#[derive(Deserialize)]
pub(super) struct ProbeLayerName {
    #[serde(rename = "type")]
    pub(super) kind: String,
}

#[derive(Default)]
pub(super) struct McpPresence(pub(super) bool);

impl<'de> Deserialize<'de> for McpPresence {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct PresenceVisitor;

        impl<'de> Visitor<'de> for PresenceVisitor {
            type Value = McpPresence;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a config object")
            }

            fn visit_map<M>(self, mut map: M) -> Result<Self::Value, M::Error>
            where
                M: MapAccess<'de>,
            {
                let mut has_mcp = false;
                while let Some(key) = map.next_key::<String>()? {
                    if key == "mcp_servers" {
                        has_mcp = true;
                    }
                    map.next_value::<IgnoredAny>()?;
                }
                Ok(McpPresence(has_mcp))
            }
        }

        deserializer.deserialize_map(PresenceVisitor)
    }
}

pub(super) fn evaluate(envelope: ProbeEnvelope) -> Result<(), String> {
    if envelope.error.is_some() {
        return Err(failed());
    }
    let layers = envelope
        .result
        .and_then(|result| result.layers)
        .ok_or_else(failed)?;
    let mut selected_session_present = false;
    for layer in layers {
        if layer.disabled_reason.is_some() || !layer.config.0 {
            continue;
        }
        if layer.name.kind == "sessionFlags" {
            selected_session_present = true;
            continue;
        }
        return Err(
            "CLROOM_CODEX_MCP_LAYER_CONFLICT: another enabled Codex config layer contains MCP servers; standalone restore refuses sibling MCP activation"
                .to_owned(),
        );
    }
    if !selected_session_present {
        return Err(
            "CLROOM_CODEX_MCP_PREFLIGHT_FAILED: selected MCP was not present in the Codex session config layer; continue locally"
                .to_owned(),
        );
    }
    Ok(())
}

pub(super) fn failed() -> String {
    "CLROOM_CODEX_MCP_PREFLIGHT_FAILED: Codex config-layer preflight did not produce safe evidence; continue locally".to_owned()
}

#[cfg(test)]
mod tests {
    use super::{evaluate, ProbeEnvelope};

    fn check(json: &str) -> Result<(), String> {
        let response: ProbeEnvelope = serde_json::from_str(json).unwrap();
        evaluate(response)
    }

    #[test]
    fn selected_session_without_siblings_passes() {
        assert!(check(
            r#"{"id":2,"result":{"layers":[{"name":{"type":"sessionFlags"},"config":{"mcp_servers":{"selected":{"command":"fixture"}}}}]}}"#
        )
        .is_ok());
    }

    #[test]
    fn enabled_non_session_mcp_layer_is_refused() {
        let error = check(
            r#"{"id":2,"result":{"layers":[{"name":{"type":"project"},"config":{"mcp_servers":{"ambient":{"command":"fixture"}}}},{"name":{"type":"sessionFlags"},"config":{"mcp_servers":{"selected":{"command":"fixture"}}}}]}}"#
        )
        .unwrap_err();
        assert!(error.starts_with("CLROOM_CODEX_MCP_LAYER_CONFLICT:"));
    }

    #[test]
    fn disabled_project_mcp_layer_does_not_block_selected_session() {
        assert!(check(
            r#"{"id":2,"result":{"layers":[{"name":{"type":"project"},"disabledReason":"project is untrusted","config":{"mcp_servers":{"ambient":{"command":"fixture"}}}},{"name":{"type":"sessionFlags"},"config":{"mcp_servers":{"selected":{"command":"fixture"}}}}]}}"#
        )
        .is_ok());
    }

    #[test]
    fn missing_selected_session_layer_fails_closed() {
        let error = check(
            r#"{"id":2,"result":{"layers":[{"name":{"type":"user"},"config":{"model":"synthetic"}}]}}"#
        )
        .unwrap_err();
        assert!(error.starts_with("CLROOM_CODEX_MCP_PREFLIGHT_FAILED:"));
    }
}
