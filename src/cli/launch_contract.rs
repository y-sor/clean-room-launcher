use std::{collections::BTreeSet, path::Path};

use clroom::adapters::claude::managed::Presence;

const CODEX_CLEAN_DEFAULTS: &[&str] = &[
    "-c",
    "features.apps=false",
    "-c",
    "features.hooks=false",
    "-c",
    "features.plugins=false",
    "-c",
    "features.remote_plugin=false",
    "-c",
    "developer_instructions=\"\"",
    "-c",
    "notify=[]",
    "-c",
    "shell_environment_policy.inherit=\"none\"",
    "-c",
    "shell_environment_policy.include_only=[\"PATH\",\"HOME\",\"TMPDIR\",\"TERM\",\"COLORTERM\",\"LANG\",\"LC_ALL\",\"LC_CTYPE\",\"TZ\"]",
    "-c",
    "shell_environment_policy.ignore_default_excludes=false",
];

const CODEX_INCLUDE_ONLY_DEFAULTS: &[&str] = &[
    "PATH",
    "HOME",
    "TMPDIR",
    "TERM",
    "COLORTERM",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
];

const CLAUDE_CLEAN_DEFAULTS: &[&str] = &[
    "--setting-sources",
    "project,local",
    "--strict-mcp-config",
    "--settings",
    "{\"sandbox\":{\"enabled\":true,\"failIfUnavailable\":true,\"allowUnsandboxedCommands\":false,\"excludedCommands\":[]}}",
];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Provider {
    Codex,
    Claude,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum CodexInvocation {
    Exec(usize),
    Diagnostic,
    Interactive,
}

pub(crate) fn classify_codex_invocation(args: &[String]) -> CodexInvocation {
    match args.first().map(String::as_str) {
        Some("exec" | "e") => CodexInvocation::Exec(0),
        Some("--help" | "-h" | "--version" | "-V") => CodexInvocation::Diagnostic,
        _ => CodexInvocation::Interactive,
    }
}

#[allow(dead_code)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BoundaryState {
    Clean,
    Expanded,
    Unknown,
    NotLaunchable,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaunchContract {
    pub provider: Provider,
    pub argv: Vec<String>,
    pub boundary: BoundaryState,
    pub boundary_controls: Vec<&'static str>,
    pub managed: Option<Presence>,
    pub user_or_provider_model_choice: bool,
}

impl LaunchContract {
    pub fn codex(user_args: &[String]) -> Self {
        Self::codex_with_pass_env(user_args, &[])
    }

    pub fn codex_with_pass_env(user_args: &[String], pass_env: &[String]) -> Self {
        let requested = pass_env.iter().map(String::as_str).collect::<BTreeSet<_>>();
        let include_only = CODEX_INCLUDE_ONLY_DEFAULTS
            .iter()
            .copied()
            .chain(requested)
            .map(|name| format!("\"{name}\""))
            .collect::<Vec<_>>()
            .join(",");
        let include_only = format!("shell_environment_policy.include_only=[{include_only}]");
        let mut argv = CODEX_CLEAN_DEFAULTS
            .iter()
            .map(|argument| {
                if argument.starts_with("shell_environment_policy.include_only=") {
                    include_only.clone()
                } else {
                    (*argument).to_owned()
                }
            })
            .collect::<Vec<_>>();
        argv.extend_from_slice(user_args);
        if let CodexInvocation::Exec(index) = classify_codex_invocation(user_args) {
            let has_clean_user_config_flag = user_args
                .iter()
                .take_while(|argument| argument.as_str() != "--")
                .any(|argument| argument == "--ignore-user-config");
            if !has_clean_user_config_flag {
                let insert_at = CODEX_CLEAN_DEFAULTS.len() + index + 1;
                argv.insert(insert_at, "--ignore-user-config".to_owned());
            }
        }
        let (boundary, boundary_controls, model_choice) =
            analyze(Provider::Codex, user_args, !pass_env.is_empty());
        Self {
            provider: Provider::Codex,
            argv,
            boundary,
            boundary_controls,
            managed: None,
            user_or_provider_model_choice: model_choice,
        }
    }

    #[cfg(test)]
    pub fn claude(user_args: &[String], add_dir: &Path, managed: Presence) -> Self {
        Self::claude_with_pass_env(user_args, add_dir, managed, &[])
    }

    pub fn claude_with_pass_env(
        user_args: &[String],
        add_dir: &Path,
        managed: Presence,
        pass_env: &[String],
    ) -> Self {
        let mut argv = CLAUDE_CLEAN_DEFAULTS
            .iter()
            .map(|argument| (*argument).to_owned())
            .collect::<Vec<_>>();
        argv.push("--add-dir".to_owned());
        argv.push(add_dir.as_os_str().to_string_lossy().into_owned());
        argv.extend_from_slice(user_args);
        let (mut boundary, boundary_controls, model_choice) =
            analyze(Provider::Claude, user_args, !pass_env.is_empty());
        if boundary == BoundaryState::Clean && managed != Presence::Absent {
            boundary = BoundaryState::Unknown;
        }
        Self {
            provider: Provider::Claude,
            argv,
            boundary,
            boundary_controls,
            managed: Some(managed),
            user_or_provider_model_choice: model_choice,
        }
    }

    pub fn add_codex_plugin_activation(&mut self, activation_args: &[String]) {
        if self.provider != Provider::Codex || activation_args.is_empty() {
            return;
        }
        let insert_at = CODEX_CLEAN_DEFAULTS.len();
        self.argv
            .splice(insert_at..insert_at, activation_args.iter().cloned());
        self.boundary = BoundaryState::Expanded;
        if !self.boundary_controls.contains(&"plugin") {
            self.boundary_controls.push("plugin");
        }
    }

    pub fn add_claude_plugin_activation(&mut self, activation_args: &[String]) {
        if self.provider != Provider::Claude || activation_args.is_empty() {
            return;
        }
        let insert_at = self
            .argv
            .iter()
            .position(|argument| argument == "--")
            .unwrap_or(self.argv.len());
        self.argv
            .splice(insert_at..insert_at, activation_args.iter().cloned());
        self.boundary = BoundaryState::Expanded;
        if !self.boundary_controls.contains(&"plugin") {
            self.boundary_controls.push("plugin");
        }
    }

    #[cfg(test)]
    pub fn boundary_label(&self) -> &'static str {
        match self.boundary {
            BoundaryState::Clean => "clean",
            BoundaryState::Expanded => "boundary expanded",
            BoundaryState::Unknown if self.managed != Some(Presence::Absent) => "managed/unknown",
            BoundaryState::Unknown => "unknown",
            BoundaryState::NotLaunchable => "not launchable",
        }
    }

    #[cfg(test)]
    pub fn managed_label(&self) -> Option<&'static str> {
        self.managed.map(|managed| match managed {
            Presence::Present => "present",
            Presence::Absent => "absent",
            Presence::Unknown => "unknown",
        })
    }
}

fn analyze(
    provider: Provider,
    args: &[String],
    environment_expanded: bool,
) -> (BoundaryState, Vec<&'static str>, bool) {
    let mut controls = Vec::new();
    if environment_expanded {
        controls.push("environment");
    }
    let mut unknown = false;
    let mut model_choice = false;
    let mut index = 0;
    while index < args.len() {
        let argument = args[index].as_str();
        if argument == "--" {
            break;
        }
        let lower = argument.to_ascii_lowercase();
        let mut recognized = true;
        let control = match provider {
            Provider::Codex => match argument {
                "--yolo" => {
                    unknown = true;
                    None
                }
                "-c" | "--config" => Some("config"),
                "--profile" | "-p" => Some("profile"),
                "--add-dir" => Some("add-dir"),
                "--sandbox" | "-s" => Some("sandbox"),
                "--ask-for-approval" | "-a" => Some("approval"),
                "--config-file" | "--instructions" | "--project-doc" => Some("instructions/config"),
                "--mcp-server" => Some("mcp"),
                "--plugin" => Some("plugin"),
                "--hook" => Some("hook"),
                "--enable" => Some("feature"),
                "--model" | "-m" => {
                    model_choice = true;
                    None
                }
                _ if lower.starts_with("--enable=") => Some("feature"),
                _ => {
                    recognized = false;
                    None
                }
            },
            Provider::Claude => match argument {
                "--setting-sources" | "--settings" => Some("setting-sources"),
                "--mcp-config" => Some("mcp"),
                "--add-dir" => Some("add-dir"),
                "--permission-mode"
                | "--dangerously-skip-permissions"
                | "--allow-dangerously-skip-permissions" => Some("permissions/sandbox"),
                "--plugin-dir" | "--plugin-url" | "--agents" | "--hooks" => {
                    Some("plugin/hook/agent")
                }
                "--chrome" => Some("browser"),
                "--no-chrome" => None,
                "--model" => {
                    model_choice = true;
                    None
                }
                "--agent" => {
                    unknown = true;
                    None
                }
                _ => {
                    recognized = false;
                    None
                }
            },
        };
        if let Some(control) = control
            && !controls.contains(&control)
        {
            controls.push(control);
        }
        if !recognized
            && argument.starts_with('-')
            && (provider == Provider::Claude
                || [
                    "config",
                    "setting",
                    "mcp",
                    "plugin",
                    "hook",
                    "instruction",
                    "sandbox",
                    "permission",
                    "add-dir",
                    "profile",
                    "approval",
                ]
                .iter()
                .any(|word| lower.contains(word)))
        {
            unknown = true;
        }
        if matches!(
            argument,
            "-c" | "--config"
                | "--profile"
                | "-p"
                | "--add-dir"
                | "--sandbox"
                | "-s"
                | "--ask-for-approval"
                | "-a"
                | "--config-file"
                | "--instructions"
                | "--project-doc"
                | "--mcp-server"
                | "--plugin"
                | "--hook"
                | "--enable"
                | "--model"
                | "-m"
                | "--setting-sources"
                | "--settings"
                | "--mcp-config"
                | "--permission-mode"
                | "--plugin-dir"
                | "--plugin-url"
                | "--agents"
                | "--hooks"
                | "--agent"
        ) {
            index += 1;
        }
        index += 1;
    }
    let boundary = if !controls.is_empty() {
        BoundaryState::Expanded
    } else if unknown {
        BoundaryState::Unknown
    } else {
        BoundaryState::Clean
    };
    (boundary, controls, model_choice)
}

#[cfg(test)]
mod tests {
    use super::{BoundaryState, CODEX_CLEAN_DEFAULTS, LaunchContract, Presence};
    use std::path::Path;

    #[test]
    fn normal_codex_launch_keeps_plugins_apps_and_hooks_disabled() {
        let contract = LaunchContract::codex(&[]);

        for feature in [
            "features.plugins=false",
            "features.apps=false",
            "features.hooks=false",
        ] {
            assert!(
                contract
                    .argv
                    .windows(2)
                    .any(|pair| { pair[0] == "-c" && pair[1] == feature })
            );
        }
        assert_eq!(contract.boundary, BoundaryState::Clean);
    }

    #[test]
    fn explicit_plugin_enable_is_boundary_expanded_without_changing_clean_defaults() {
        let user_args = ["--enable".to_owned(), "plugins".to_owned()];
        let contract = LaunchContract::codex(&user_args);

        assert_eq!(contract.boundary, BoundaryState::Expanded);
        assert_eq!(contract.boundary_controls, vec!["feature"]);
        assert_eq!(contract.boundary_label(), "boundary expanded");
        assert_eq!(
            &contract.argv[..CODEX_CLEAN_DEFAULTS.len()],
            CODEX_CLEAN_DEFAULTS
                .iter()
                .map(|argument| (*argument).to_owned())
                .collect::<Vec<_>>()
        );
        assert_eq!(&contract.argv[CODEX_CLEAN_DEFAULTS.len()..], user_args);
        assert!(
            contract
                .argv
                .windows(2)
                .any(|pair| { pair[0] == "-c" && pair[1] == "features.plugins=false" })
        );
    }

    #[test]
    fn codex_owned_plugin_activation_overrides_clean_plugin_default_only_for_selected_path() {
        let mut contract = LaunchContract::codex(&["--model".to_owned(), "gpt-5".to_owned()]);
        contract.add_codex_plugin_activation(&[
            "-c".to_owned(),
            "features.plugins=true".to_owned(),
            "-c".to_owned(),
            "plugins.\"codex-app-tools@openai-bundled\".enabled=true".to_owned(),
        ]);

        let plugin_false = contract
            .argv
            .windows(2)
            .position(|pair| pair[0] == "-c" && pair[1] == "features.plugins=false")
            .unwrap();
        let plugin_true = contract
            .argv
            .windows(2)
            .position(|pair| pair[0] == "-c" && pair[1] == "features.plugins=true")
            .unwrap();
        assert!(plugin_true > plugin_false);
        assert!(
            contract
                .argv
                .windows(2)
                .any(|pair| pair[0] == "-c"
                    && pair[1] == "features.remote_plugin=false")
        );
        assert_eq!(contract.boundary, BoundaryState::Expanded);
        assert!(contract.boundary_controls.contains(&"plugin"));
    }

    #[test]
    fn claude_context_and_tool_flags_are_unknown() {
        for flag in ["--system-prompt", "--append-system-prompt", "--tools"] {
            let contract = LaunchContract::claude(
                &[flag.to_owned(), "synthetic".to_owned()],
                Path::new("/tmp/view"),
                Presence::Absent,
            );
            assert_eq!(contract.boundary, BoundaryState::Unknown, "flag={flag}");
        }
    }

    #[test]
    fn claude_browser_flag_expands_boundary_and_disable_is_clean() {
        let enabled = LaunchContract::claude(
            &["--chrome".to_owned()],
            Path::new("/tmp/view"),
            Presence::Absent,
        );
        assert_eq!(enabled.boundary, BoundaryState::Expanded);
        assert_eq!(enabled.boundary_controls, vec!["browser"]);

        let disabled = LaunchContract::claude(
            &["--no-chrome".to_owned()],
            Path::new("/tmp/view"),
            Presence::Absent,
        );
        assert_eq!(disabled.boundary, BoundaryState::Clean);
        assert!(disabled.boundary_controls.is_empty());
    }

    #[test]
    fn unsafe_provider_shortcuts_are_unknown() {
        let codex = LaunchContract::codex(&["--yolo".to_owned()]);
        assert_eq!(codex.boundary, BoundaryState::Unknown);
        let claude = LaunchContract::claude(
            &["--agent".to_owned()],
            Path::new("/tmp/view"),
            Presence::Absent,
        );
        assert_eq!(claude.boundary, BoundaryState::Unknown);
    }

    #[test]
    fn codex_exec_gets_native_clean_user_config_suppression_after_subcommand() {
        let contract = LaunchContract::codex(&["exec".to_owned(), "prompt".to_owned()]);
        let position = contract
            .argv
            .iter()
            .position(|argument| argument == "--ignore-user-config")
            .unwrap();
        assert_eq!(contract.argv[position - 1], "exec");
    }

    #[test]
    fn codex_exec_does_not_duplicate_user_supplied_clean_user_config_suppression() {
        let contract = LaunchContract::codex(&[
            "exec".to_owned(),
            "--ignore-user-config".to_owned(),
            "prompt".to_owned(),
        ]);
        assert_eq!(
            contract
                .argv
                .iter()
                .filter(|argument| argument.as_str() == "--ignore-user-config")
                .count(),
            1
        );
    }

    #[test]
    fn claude_owned_plugin_activation_is_inserted_before_provider_terminator() {
        let mut contract = LaunchContract::claude(
            &[
                "--model".to_owned(),
                "sonnet".to_owned(),
                "--".to_owned(),
                "--plugin-dir".to_owned(),
                "literal".to_owned(),
            ],
            Path::new("/tmp/view"),
            Presence::Absent,
        );
        contract.add_claude_plugin_activation(&[
            "--plugin-dir".to_owned(),
            "/tmp/selected".to_owned(),
        ]);

        let terminator = contract
            .argv
            .iter()
            .position(|argument| argument == "--")
            .unwrap();
        assert_eq!(
            &contract.argv[terminator - 2..terminator],
            &["--plugin-dir".to_owned(), "/tmp/selected".to_owned()]
        );
        assert_eq!(contract.argv[terminator + 1], "--plugin-dir");
        assert_eq!(contract.boundary, BoundaryState::Expanded);
        assert!(contract.boundary_controls.contains(&"plugin"));
    }

    #[test]
    fn raw_claude_plugin_url_is_classified_as_plugin_control() {
        let contract = LaunchContract::claude(
            &[
                "--plugin-url".to_owned(),
                "https://example.invalid/plugin.zip".to_owned(),
            ],
            Path::new("/tmp/view"),
            Presence::Absent,
        );
        assert_eq!(contract.boundary, BoundaryState::Expanded);
        assert_eq!(contract.boundary_controls, vec!["plugin/hook/agent"]);
    }

    #[test]
    fn claude_pass_env_expands_contract_without_forwarding_launcher_options() {
        let contract = LaunchContract::claude_with_pass_env(
            &["--model".to_owned(), "sonnet".to_owned()],
            Path::new("/tmp/view"),
            Presence::Absent,
            &["RUNNER_HANDLE".to_owned(), "RUNNER_HANDLE".to_owned()],
        );
        assert_eq!(contract.boundary, BoundaryState::Expanded);
        assert_eq!(contract.boundary_controls, vec!["environment"]);
        assert!(
            !contract
                .argv
                .iter()
                .any(|argument| argument.starts_with("--pass-env"))
        );
        assert!(
            contract
                .argv
                .ends_with(&["--model".to_owned(), "sonnet".to_owned()])
        );
    }

    #[test]
    fn codex_exec_inserts_suppression_before_literal_after_terminator() {
        let contract = LaunchContract::codex(&[
            "exec".to_owned(),
            "--".to_owned(),
            "--ignore-user-config".to_owned(),
        ]);
        let terminator = contract
            .argv
            .iter()
            .position(|argument| argument == "--")
            .unwrap();
        assert_eq!(
            contract.argv[..terminator]
                .iter()
                .filter(|argument| argument.as_str() == "--ignore-user-config")
                .count(),
            1
        );
        assert_eq!(contract.argv[terminator + 1], "--ignore-user-config");
    }

    #[test]
    fn codex_invocation_classification_is_fail_closed_for_interactive_paths() {
        use super::{CodexInvocation, classify_codex_invocation};

        assert_eq!(
            classify_codex_invocation(&["exec".to_owned(), "prompt".to_owned()]),
            CodexInvocation::Exec(0)
        );
        assert_eq!(
            classify_codex_invocation(&[
                "--profile".to_owned(),
                "safe".to_owned(),
                "exec".to_owned(),
                "prompt".to_owned(),
            ]),
            CodexInvocation::Interactive
        );
        assert_eq!(
            classify_codex_invocation(&["resume".to_owned(), "thread".to_owned()]),
            CodexInvocation::Interactive
        );
        assert_eq!(
            classify_codex_invocation(&["--help".to_owned()]),
            CodexInvocation::Diagnostic
        );
    }
}
