#[path = "cli/argv_passthrough.rs"]
mod argv_passthrough;
#[path = "cli/claude_launch.rs"]
mod claude_launch;
#[allow(clippy::duplicate_mod)] // Real cli::run is imported to test lazy argv consumption.
#[path = "../src/cli/mod.rs"]
mod cli_entry;
#[path = "cli/codex_workspace_conflict.rs"]
mod codex_workspace_conflict;
#[allow(clippy::duplicate_mod)] // consent.rs is also nested under the real CLI module above.
#[path = "cli/consent_security.rs"]
mod consent_security;
#[path = "cli/doctor.rs"]
mod doctor;
#[path = "cli/entrypoint_parity.rs"]
mod entrypoint_parity;
#[path = "cli/first_screen.rs"]
mod first_screen;
#[path = "cli/foreground_process.rs"]
mod foreground_process;
#[path = "cli/help.rs"]
mod help;
#[path = "cli/info.rs"]
mod info;
#[path = "cli/isolated_codex_launch.rs"]
mod isolated_codex_launch;
#[path = "cli/isolated_launch_screen.rs"]
mod isolated_launch_screen;
#[path = "cli/isolated_real_codex.rs"]
mod isolated_real_codex;
#[path = "cli/local_codex_launch.rs"]
mod local_codex_launch;
#[path = "cli/minimum_real_launch.rs"]
mod minimum_real_launch;
#[path = "cli/non_tty_json.rs"]
mod non_tty_json;
#[path = "cli/presets.rs"]
mod presets;
#[path = "cli/saved_start_call_path.rs"]
mod saved_start_call_path;
#[path = "cli/saved_starts.rs"]
mod saved_starts;
#[path = "../src/cli/state.rs"]
#[allow(dead_code)]
#[allow(clippy::duplicate_mod)] // state.rs is also nested under the real CLI module above.
mod state;
#[path = "../src/cli/zero_auth.rs"]
#[allow(dead_code)]
mod zero_auth;
