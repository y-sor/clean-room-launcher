pub mod activation;
pub mod context_canaries;
pub mod environment;
pub mod identity;
pub mod isolation;
pub mod placement;
pub mod plugin_state;

/// Active CLROOM-owned Codex shadow-state generation.
pub const SHADOW_STATE_DIR: &str = ".clroom-clean-state-v2";
