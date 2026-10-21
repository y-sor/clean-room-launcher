use clroom::catalog::{
    resource::ResourceKind,
    selection::{SelectionError, SelectionRequest, SelectionTarget},
};

pub use clroom::catalog::provider_inventory::Provider;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Prepared {
    pub request: SelectionRequest,
    pub provider_args: Vec<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum NativeOptionArity {
    One,
    Optional,
    Many,
}

pub fn prepare(provider: Provider, args: &[String]) -> Result<Prepared, String> {
    let mut request = SelectionRequest::default();
    let mut provider_args = Vec::with_capacity(args.len() + 1);
    let mut launcher_options = true;
    let mut subcommand_args = false;
    let mut raw_chrome_override = false;
    let mut index = 0;

    while index < args.len() {
        let argument = &args[index];
        if subcommand_args {
            provider_args.push(argument.clone());
            index += 1;
        } else if launcher_options && argument == "--" {
            launcher_options = false;
            provider_args.push(argument.clone());
            index += 1;
        } else if launcher_options && matches!(argument.as_str(), "--with" | "--without") {
            return Err(invalid_selector());
        } else if launcher_options && let Some(value) = argument.strip_prefix("--with=") {
            request
                .include_value(value)
                .map_err(selection_error_message)?;
            index += 1;
        } else if launcher_options && let Some(value) = argument.strip_prefix("--without=") {
            request
                .exclude_value(value)
                .map_err(selection_error_message)?;
            index += 1;
        } else {
            if launcher_options && provider == Provider::Claude {
                if matches!(argument.as_str(), "--chrome" | "--no-chrome") {
                    raw_chrome_override = true;
                }
            }
            provider_args.push(argument.clone());
            index += 1;
            if launcher_options && native_subcommand(provider, argument) {
                subcommand_args = true;
            }
            if launcher_options && !argument.contains('=') {
                if let Some(arity) = native_option_arity(provider, argument) {
                    let mut consumed = 0;
                    while let Some(value) = args.get(index) {
                        if consumed > 0 && arity != NativeOptionArity::Many {
                            break;
                        }
                        if arity == NativeOptionArity::Optional && value.starts_with('-') {
                            break;
                        }
                        if arity == NativeOptionArity::Many && value.starts_with('-') {
                            break;
                        }
                        provider_args.push(value.clone());
                        index += 1;
                        consumed += 1;
                        if arity != NativeOptionArity::Many {
                            break;
                        }
                    }
                    if consumed == 0 && arity == NativeOptionArity::One {
                        return Err(missing_native_value(provider, argument));
                    }
                }
            }
        }
    }

    if request
        .includes
        .iter()
        .chain(request.excludes.iter())
        .any(|target| matches!(target, SelectionTarget::All))
    {
        return Err(
            "CLROOM_RESOURCE_ALL_UNAVAILABLE: --with=all/--without=all is not available in this bounded selector"
                .to_owned(),
        );
    }

    let unsupported_exact = request
        .includes
        .iter()
        .chain(request.excludes.iter())
        .any(|target| match target {
            SelectionTarget::Exact { kind, .. } if *kind == ResourceKind::Plugin => false,
            SelectionTarget::Exact { kind, .. }
                if provider == Provider::Codex && *kind == ResourceKind::McpServer =>
            {
                false
            }
            SelectionTarget::Exact { .. } => true,
            SelectionTarget::All => false,
        });
    if unsupported_exact {
        return Err(match provider {
            Provider::Codex => "CLROOM_RESOURCE_NOT_SELECTABLE: only exact qualified whole-plugin or standalone MCP selection is available; continue locally",
            Provider::Claude => "CLROOM_RESOURCE_NOT_SELECTABLE: only exact qualified whole-plugin selection is available; continue locally",
        }
        .to_owned());
    }

    validate_native_composition(provider, &request, &provider_args)?;

    if provider == Provider::Claude && !raw_chrome_override {
        // Claude can persist its native Chrome integration in provider-owned state.
        // A clean launch closes that ambient input unless the caller explicitly
        // supplies the provider-native override for this invocation.
        provider_args.insert(0, "--no-chrome".to_owned());
    }

    Ok(Prepared {
        request,
        provider_args,
    })
}

fn native_option_arity(provider: Provider, argument: &str) -> Option<NativeOptionArity> {
    match provider {
        Provider::Codex => {
            if matches!(argument, "--image") {
                Some(NativeOptionArity::Many)
            } else if matches!(
                argument,
                "--config" | "-c" | "--profile" | "-p" | "--enable" | "--disable"
                    | "--plugin" | "--config-file" | "--remote" | "--remote-auth-token-env"
                    | "--model" | "-m" | "--local-provider" | "--sandbox" | "-s"
                    | "--ask-for-approval" | "-a" | "--cd" | "-C" | "--add-dir"
                    | "--instructions" | "--project-doc"
            ) {
                Some(NativeOptionArity::One)
            } else {
                None
            }
        }
        Provider::Claude => {
            if matches!(
                argument,
                "--add-dir" | "--allowedTools" | "--allowed-tools" | "--agents" | "--betas"
                    | "--disallowedTools" | "--disallowed-tools" | "--file" | "--mcp-config"
                    | "--tools"
            ) {
                Some(NativeOptionArity::Many)
            } else if matches!(
                argument,
                "--cloud" | "--debug" | "-d" | "--from-pr" | "--prompt-suggestions"
                    | "--remote-control" | "--resume" | "-r" | "--teleport" | "--tmux"
                    | "--worktree" | "-w"
            ) {
                Some(NativeOptionArity::Optional)
            } else if matches!(
                argument,
                "--agent" | "--append-system-prompt" | "--append-system-prompt-file"
                    | "--autocompact" | "--debug-file" | "--effort" | "--environment"
                    | "--fallback-model" | "--input-format" | "--json-schema" | "--max-budget-usd"
                    | "--model" | "--name" | "--output-format" | "--permission-mode"
                    | "--permission-prompts" | "--permission-prompt-tool" | "--plugin-dir"
                    | "--plugin-url" | "--remote-control-session-name-prefix" | "--session-id"
                    | "--setting-sources" | "--settings" | "--system-prompt"
                    | "--system-prompt-snapshot"
            ) {
                Some(NativeOptionArity::One)
            } else {
                None
            }
        }
    }
}

fn native_option_takes_value(provider: Provider, argument: &str) -> bool {
    native_option_arity(provider, argument).is_some()
}

fn native_subcommand(provider: Provider, argument: &str) -> bool {
    match provider {
        Provider::Codex => super::launch_contract::is_codex_subcommand(argument),
        Provider::Claude => matches!(
            argument,
            "agents"
                | "attach"
                | "auth"
                | "auto-mode"
                | "doctor"
                | "gateway"
                | "import"
                | "install"
                | "logs"
                | "mcp"
                | "plugin"
                | "plugins"
                | "purge"
                | "respawn"
                | "rm"
                | "setup-token"
                | "stop"
                | "kill"
                | "ultrareview"
                | "update"
                | "upgrade"
        ),
    }
}

fn missing_native_value(provider: Provider, option: &str) -> String {
    let provider_name = match provider {
        Provider::Codex => "Codex",
        Provider::Claude => "Claude",
    };
    format!(
        "CLROOM_NATIVE_ARGUMENT_INVALID: {provider_name} option {option} requires a value"
    )
}

fn validate_native_composition(
    provider: Provider,
    request: &SelectionRequest,
    args: &[String],
) -> Result<(), String> {
    let selected_plugins = request
        .includes
        .iter()
        .filter_map(|target| match target {
            SelectionTarget::Exact { kind, id } if *kind == ResourceKind::Plugin => Some(id),
            _ => None,
        })
        .collect::<Vec<_>>();
    let selected_mcp = request
        .includes
        .iter()
        .filter_map(|target| match target {
            SelectionTarget::Exact { kind, id } if *kind == ResourceKind::McpServer => Some(id),
            _ => None,
        })
        .collect::<Vec<_>>();

    let mut index = 0;
    let mut codex_exec = false;
    while index < args.len() {
        let argument = args[index].as_str();
        let mut value_consumed = false;
        if argument == "--" {
            break;
        }
        if native_subcommand(provider, argument) {
            // Codex exec (including exec resume) launches an agent; its native
            // security and configuration flags remain subject to validation.
            // Other provider management subcommands retain their own grammar.
            if provider != Provider::Codex
                || (!codex_exec && !matches!(argument, "exec" | "e"))
            {
                break;
            }
            codex_exec = true;
            index += 1;
            continue;
        }

        match provider {
            Provider::Codex => {
                if matches!(
                    argument,
                    "--dangerously-bypass-approvals-and-sandbox"
                        | "--dangerously-bypass-hook-trust"
                        | "--approve-for-me"
                        | "--yolo"
                ) || argument.starts_with("--dangerously-bypass-approvals-and-sandbox=")
                    || argument.starts_with("--dangerously-bypass-hook-trust=")
                    || argument.starts_with("--approve-for-me=")
                    || argument.starts_with("--yolo=")
                {
                    return Err(
                        "CLROOM_ISOLATION_CONFLICT: Codex dangerous bypass flags cannot be composed through CLROOM"
                            .to_owned(),
                    );
                }
                if !request.is_empty()
                    && (argument == "--remote" || argument.starts_with("--remote="))
                {
                    return Err(
                        "CLROOM_RESOURCE_COMPOSITION_UNKNOWN: Codex remote launch changes the boundary of selected local resources"
                            .to_owned(),
                    );
                }
                let sandbox_value = if matches!(argument, "--sandbox" | "-s") {
                    args.get(index + 1).map(String::as_str)
                } else if let Some(value) = argument.strip_prefix("-s") {
                    Some(value.strip_prefix('=').unwrap_or(value))
                } else {
                    argument
                        .split_once('=')
                        .filter(|(option, _)| matches!(*option, "--sandbox" | "-s"))
                        .map(|(_, value)| value)
                };
                if sandbox_value == Some("danger-full-access") {
                    return Err(
                        "CLROOM_ISOLATION_CONFLICT: Codex full-access sandbox cannot be composed through CLROOM"
                            .to_owned(),
                    );
                }
                let approval_value = if matches!(argument, "--ask-for-approval" | "-a") {
                    args.get(index + 1).map(String::as_str)
                } else if let Some(value) = argument.strip_prefix("-a") {
                    Some(value.strip_prefix('=').unwrap_or(value))
                } else {
                    argument
                        .split_once('=')
                        .filter(|(option, _)| matches!(*option, "--ask-for-approval" | "-a"))
                        .map(|(_, value)| value)
                };
                if approval_value == Some("never") {
                    return Err(
                        "CLROOM_ISOLATION_CONFLICT: Codex approval bypass cannot be composed through CLROOM"
                            .to_owned(),
                    );
                }
                if !request.is_empty()
                    && (matches!(argument, "--profile" | "-p" | "--config-file")
                    || argument.starts_with("--profile=")
                    || (argument.starts_with("-p") && argument.len() > 2)
                    || argument.starts_with("--config-file="))
                {
                    return Err(format!(
                        "CLROOM_RESOURCE_COMPOSITION_UNKNOWN: Codex {argument} changes the configuration source for selected resources"
                    ));
                }
                if !selected_plugins.is_empty()
                    && (argument == "--plugin" || argument.starts_with("--plugin="))
                {
                    return Err(resource_conflict("selected Codex plugin"));
                }
                if matches!(argument, "--config" | "-c") {
                    let value = if argument == "-c" || argument == "--config" {
                        index += 1;
                        value_consumed = true;
                        args.get(index).map(String::as_str).unwrap_or_default()
                    } else {
                        argument.split_once('=').map_or("", |(_, value)| value)
                    };
                    validate_codex_config_override(value, &selected_plugins, &selected_mcp)?;
                } else if let Some((option, value)) = argument.split_once('=')
                    && matches!(option, "-c" | "--config")
                {
                    validate_codex_config_override(value, &selected_plugins, &selected_mcp)?;
                } else if let Some(value) = argument.strip_prefix("-c")
                    && !value.is_empty()
                {
                    validate_codex_config_override(value, &selected_plugins, &selected_mcp)?;
                } else if matches!(argument, "--enable" | "--disable") {
                    index += 1;
                    value_consumed = true;
                    let value = args.get(index).map(String::as_str).unwrap_or_default();
                    if argument == "--disable"
                        && selected_plugins.len() > 0
                        && matches!(value, "plugins" | "plugin")
                    {
                        return Err(resource_conflict("selected Codex plugin feature"));
                    }
                } else if let Some(value) = argument.strip_prefix("--disable=")
                    && !selected_plugins.is_empty()
                    && matches!(value, "plugins" | "plugin")
                {
                    return Err(resource_conflict("selected Codex plugin feature"));
                }
            }
            Provider::Claude => {
                if !selected_plugins.is_empty()
                    && (argument == "--mcp-config" || argument.starts_with("--mcp-config="))
                {
                    return Err(
                        "CLROOM_RESOURCE_COMPOSITION_UNKNOWN: Claude MCP config changes the source set for the selected plugin"
                            .to_owned(),
                    );
                }
                if matches!(
                    argument,
                    "--dangerously-skip-permissions" | "--allow-dangerously-skip-permissions"
                ) || argument.starts_with("--dangerously-skip-permissions=")
                    || argument.starts_with("--allow-dangerously-skip-permissions=")
                {
                    return Err(
                        "CLROOM_ISOLATION_CONFLICT: Claude permission bypass flags cannot be composed through CLROOM"
                            .to_owned(),
                    );
                }
                if !request.is_empty() && argument == "--bare" {
                    return Err(
                        "CLROOM_RESOURCE_COMPOSITION_UNKNOWN: Claude bare mode changes selected-resource trust behavior"
                            .to_owned(),
                    );
                }
                let permission_mode = if argument == "--permission-mode" {
                    args.get(index + 1).map(String::as_str)
                } else {
                    argument.strip_prefix("--permission-mode=")
                };
                if permission_mode
                    .is_some_and(|value| value == "bypassPermissions")
                {
                    return Err(
                        "CLROOM_ISOLATION_CONFLICT: Claude permission mode cannot bypass selected-resource policy"
                            .to_owned(),
                    );
                }
                if !selected_plugins.is_empty()
                    && (matches!(argument, "--plugin-dir" | "--plugin-url")
                        || argument.starts_with("--plugin-dir=")
                        || argument.starts_with("--plugin-url="))
                {
                    return Err(resource_conflict("selected Claude plugin"));
                }
                if argument == "--settings" || argument.starts_with("--settings=") {
                    return Err(
                        "CLROOM_RESOURCE_COMPOSITION_UNKNOWN: Claude --settings may override managed or sandbox-related launch policy"
                            .to_owned(),
                    );
                }
                if argument == "--setting-sources" || argument.starts_with("--setting-sources=") {
                    let value = if argument == "--setting-sources" {
                        index += 1;
                        value_consumed = true;
                        args.get(index).map(String::as_str).unwrap_or_default()
                    } else {
                        argument.split_once('=').map_or("", |(_, value)| value)
                    };
                    if !request.is_empty()
                        && value.split(',').any(|source| source.trim() == "user")
                    {
                        return Err(
                            "CLROOM_RESOURCE_COMPOSITION_CONFLICT: Claude user settings would reopen personal-global resources"
                                .to_owned(),
                        );
                    }
                }
            }
        }

        if !value_consumed
            && native_option_takes_value(provider, argument)
            && !argument.contains('=')
        {
            index += 1;
        }
        index += 1;
    }

    Ok(())
}

fn validate_codex_config_override(
    value: &str,
    selected_plugins: &[&String],
    selected_mcp: &[&String],
) -> Result<(), String> {
    let Some((key, setting)) = value.split_once('=') else {
        return Err(
            "CLROOM_NATIVE_ARGUMENT_INVALID: Codex -c/--config requires key=value".to_owned(),
        );
    };
    let key = key.trim();
    if key.is_empty() {
        return Err("CLROOM_NATIVE_ARGUMENT_INVALID: Codex config key is empty".to_owned());
    }
    // Resolve TOML dotted and quoted keys semantically, not by textual prefix:
    // mcp_servers."docs".enabled and "sandbox_mode" are native valid forms.
    let parsed_key = toml::from_str::<toml::Value>(&format!("{key} = true")).map_err(|_| {
        "CLROOM_NATIVE_ARGUMENT_INVALID: Codex config key is invalid".to_owned()
    })?;
    let plugin_selected = !selected_plugins.is_empty();
    let feature_override = parsed_key.get("features");
    let selected_plugin_conflict = plugin_selected
        && (parsed_key.get("plugins").is_some()
            || feature_override.is_some_and(|features| {
                !features.is_table() || features.get("plugins").is_some()
            }));
    let selected_mcp_conflict = !selected_mcp.is_empty()
        && parsed_key.get("mcp_servers").is_some_and(|servers| {
            !servers.is_table()
                || selected_mcp
                    .iter()
                    .any(|id| servers.get(id.as_str()).is_some())
        });
    if selected_plugin_conflict || selected_mcp_conflict {
        return Err(resource_conflict("selected Codex resource"));
    }

    if ["sandbox_mode", "approval_policy", "shell_environment_policy"]
        .iter()
        .any(|key| parsed_key.get(key).is_some())
    {
        return Err(
            "CLROOM_RESOURCE_COMPOSITION_CONFLICT: Codex config cannot override CLROOM isolation or approval controls"
                .to_owned(),
        );
    }
    Ok(())
}

fn resource_conflict(resource: &str) -> String {
    format!(
        "CLROOM_RESOURCE_COMPOSITION_CONFLICT: native arguments may override the {resource}; remove the conflicting override or change the selected resource"
    )
}

pub(super) fn validate_plugin_mcp_config(
    args: &[String],
    selected_mcp_ids: &[String],
) -> Result<(), String> {
    if selected_mcp_ids.is_empty() {
        return Ok(());
    }
    let mut index = 0;
    while index < args.len() {
        let argument = args[index].as_str();
        if argument == "--" {
            break;
        }
        if native_subcommand(Provider::Codex, argument) {
            break;
        }
        let mut value_consumed = false;
        let value = if matches!(argument, "-c" | "--config") {
            index += 1;
            value_consumed = true;
            args.get(index).map(String::as_str)
        } else {
            argument
                .split_once('=')
                .filter(|(option, _)| matches!(*option, "-c" | "--config"))
                .map(|(_, value)| value)
        };
        if let Some(value) = value
            && assignment_contains_selected_mcp(value, selected_mcp_ids)
        {
            return Err(resource_conflict("plugin-bundled MCP server"));
        }
        index += 1;
        if !value_consumed
            && native_option_takes_value(Provider::Codex, argument)
            && !argument.contains('=')
        {
            index += 1;
        }
    }
    Ok(())
}

fn assignment_contains_selected_mcp(value: &str, selected_mcp_ids: &[String]) -> bool {
    let Some((key, setting)) = value.split_once('=') else {
        return false;
    };
    if key.trim() != "mcp_servers" && !key.trim().starts_with("mcp_servers.") {
        return false;
    }
    let Ok(parsed) = toml::from_str::<toml::Value>(&format!("{} = {}", key.trim(), setting.trim()))
    else {
        return true;
    };
    let Some(servers) = parsed.get("mcp_servers").and_then(toml::Value::as_table) else {
        return false;
    };
    selected_mcp_ids.iter().any(|id| servers.contains_key(id))
}

fn invalid_selector() -> String {
    "CLROOM_RESOURCE_SELECTOR_INVALID: invalid resource selector".to_owned()
}

fn selection_error_message(_error: SelectionError) -> String {
    invalid_selector()
}

#[cfg(test)]
mod tests {
    use super::{prepare, validate_plugin_mcp_config, Provider};
    use clroom::catalog::{
        resource::ResourceKind,
        selection::SelectionTarget,
    };

    fn strings(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| (*value).to_owned()).collect()
    }

    #[test]
    fn claude_clean_default_disables_ambient_native_chrome_state() {
        assert_eq!(
            prepare(Provider::Claude, &strings(&["--model", "sonnet"]))
                .unwrap()
                .provider_args,
            strings(&["--no-chrome", "--model", "sonnet"])
        );
    }

    #[test]
    fn raw_claude_chrome_override_is_not_shadowed_by_clean_default() {
        for flag in ["--chrome", "--no-chrome"] {
            let args = strings(&[flag, "--model", "sonnet"]);
            assert_eq!(
                prepare(Provider::Claude, &args).unwrap().provider_args,
                args
            );
        }
    }

    #[test]
    fn provider_terminator_keeps_later_arguments_literal() {
        let args = strings(&["--", "--chrome"]);
        assert_eq!(
            prepare(Provider::Claude, &args).unwrap().provider_args,
            strings(&["--no-chrome", "--", "--chrome"])
        );
    }

    #[test]
    fn claude_exact_plugin_is_preserved_as_structured_selection() {
        let prepared = prepare(
            Provider::Claude,
            &strings(&["--with=plugin:review-tools@team", "--model", "sonnet"]),
        )
        .unwrap();

        assert_eq!(
            prepared.request.includes.iter().collect::<Vec<_>>(),
            vec![&SelectionTarget::Exact {
                kind: ResourceKind::Plugin,
                id: "review-tools@team".to_owned(),
            }]
        );
        assert_eq!(
            prepared.provider_args,
            strings(&["--no-chrome", "--model", "sonnet"])
        );
    }

    #[test]
    fn unsupported_resource_kinds_and_all_remain_closed() {
        for (provider, selector, code) in [
            (
                Provider::Claude,
                "--without=mcp:local-tools",
                "CLROOM_RESOURCE_NOT_SELECTABLE:",
            ),
            (
                Provider::Claude,
                "--with=all",
                "CLROOM_RESOURCE_ALL_UNAVAILABLE:",
            ),
        ] {
            let error = prepare(provider, &strings(&[selector])).unwrap_err();
            assert!(error.starts_with(code), "{error}");
        }

        let all_error =
            prepare(Provider::Claude, &strings(&["--with=all"])).unwrap_err();
        assert!(
            all_error.contains("not available in this bounded selector"),
            "{all_error}"
        );
        assert!(!all_error.contains("v0.4.x"), "{all_error}");
    }

    #[test]
    fn codex_exact_mcp_is_preserved_as_structured_selection() {
        let prepared = prepare(
            Provider::Codex,
            &strings(&["--with=mcp:local-tools", "--model", "gpt-5"]),
        )
        .unwrap();

        assert_eq!(
            prepared.request.includes.iter().collect::<Vec<_>>(),
            vec![&SelectionTarget::Exact {
                kind: ResourceKind::McpServer,
                id: "local-tools".to_owned(),
            }]
        );
        assert_eq!(prepared.provider_args, strings(&["--model", "gpt-5"]));
    }

    #[test]
    fn codex_plugin_and_mcp_are_preserved_in_one_structured_request() {
        let prepared = prepare(
            Provider::Codex,
            &strings(&[
                "--with=plugin:codex-app-tools@openai-bundled",
                "--with=mcp:local-tools",
                "--model",
                "gpt-5",
            ]),
        )
        .unwrap();

        assert!(prepared.request.includes.contains(&SelectionTarget::Exact {
            kind: ResourceKind::Plugin,
            id: "codex-app-tools@openai-bundled".to_owned(),
        }));
        assert!(prepared.request.includes.contains(&SelectionTarget::Exact {
            kind: ResourceKind::McpServer,
            id: "local-tools".to_owned(),
        }));
        assert_eq!(prepared.provider_args, strings(&["--model", "gpt-5"]));
    }

    #[test]
    fn codex_exact_plugin_is_preserved_as_structured_selection() {
        let prepared = prepare(
            Provider::Codex,
            &strings(&[
                "--with=plugin:codex-app-tools@openai-bundled",
                "--model",
                "gpt-5",
            ]),
        )
        .unwrap();

        assert_eq!(
            prepared.request.includes.iter().collect::<Vec<_>>(),
            vec![&SelectionTarget::Exact {
                kind: ResourceKind::Plugin,
                id: "codex-app-tools@openai-bundled".to_owned(),
            }]
        );
        assert_eq!(prepared.provider_args, strings(&["--model", "gpt-5"]));
    }

    #[test]
    fn codex_disjoint_config_composes_with_selected_plugin() {
        let prepared = prepare(
            Provider::Codex,
            &strings(&[
                "--with=plugin:codex-app-tools@openai-bundled",
                "-c",
                "model='example'",
            ]),
        )
        .unwrap();

        assert_eq!(
            prepared.provider_args,
            strings(&["-c", "model='example'"])
        );
    }

    #[test]
    fn codex_composes_independent_native_config_and_rejects_exact_conflicts() {
        for (native, code) in [
            (strings(&["-c", "features.plugins=false"]), "COMPOSITION_CONFLICT:"),
            (strings(&["--config=plugins={}"]), "COMPOSITION_CONFLICT:"),
            (strings(&["--disable", "plugins"]), "COMPOSITION_CONFLICT:"),
            (strings(&["--plugin", "ambient"]), "COMPOSITION_CONFLICT:"),
            (strings(&["--profile", "ambient"]), "COMPOSITION_UNKNOWN:"),
            (strings(&["-p=ambient"]), "COMPOSITION_UNKNOWN:"),
            (strings(&["--config-file", "outside.toml"]), "COMPOSITION_UNKNOWN:"),
        ] {
            let mut args = vec!["--with=plugin:codex-app-tools@openai-bundled".to_owned()];
            args.extend(native);
            let error = prepare(Provider::Codex, &args).unwrap_err();
            assert!(error.contains(code), "{args:?}: {error}");
        }

        let independent = prepare(
            Provider::Codex,
            &strings(&[
                "--with=plugin:codex-app-tools@openai-bundled",
                "-c",
                "model='example'",
                "--config=reasoning_effort='high'",
                "--enable",
                "unified_exec",
            ]),
        )
        .unwrap();
        assert_eq!(
            independent.provider_args,
            strings(&[
                "-c",
                "model='example'",
                "--config=reasoning_effort='high'",
                "--enable",
                "unified_exec",
            ])
        );

        let selector_like_value = prepare(
            Provider::Codex,
            &strings(&[
                "--with=plugin:codex-app-tools@openai-bundled",
                "-c",
                "--with=literal-native-value",
            ]),
        )
        .unwrap();
        assert_eq!(
            selector_like_value.provider_args,
            strings(&["-c", "--with=literal-native-value"])
        );

        let subcommand_args = strings(&[
            "exec",
            "--with=literal-subcommand-argument",
            "prompt",
        ]);
        let subcommand = prepare(Provider::Codex, &subcommand_args).unwrap();
        assert!(subcommand.request.is_empty());
        assert_eq!(subcommand.provider_args, subcommand_args);

        let codex_command_args = strings(&[
            "features",
            "--dangerously-bypass-approvals-and-sandbox",
        ]);
        assert_eq!(
            prepare(Provider::Codex, &codex_command_args)
                .unwrap()
                .provider_args,
            codex_command_args
        );

        let claude_command_args = strings(&["mcp", "add", "--setting-sources=user"]);
        assert_eq!(
            prepare(Provider::Claude, &claude_command_args)
                .unwrap()
                .provider_args,
            strings(&[
                "--no-chrome",
                "mcp",
                "add",
                "--setting-sources=user"
            ])
        );

        let missing_value = prepare(Provider::Codex, &strings(&["--with=plugin:x@y", "-c"]))
            .unwrap_err();
        assert!(missing_value.starts_with("CLROOM_NATIVE_ARGUMENT_INVALID:"));

        let exact_mcp_conflict = prepare(
            Provider::Codex,
            &strings(&[
                "--with=mcp:local-tools",
                "-c",
                "mcp_servers.local-tools={command=\"false\"}",
            ]),
        )
        .unwrap_err();
        assert!(exact_mcp_conflict.contains("COMPOSITION_CONFLICT:"));

        let independent_mcp = prepare(
            Provider::Codex,
            &strings(&[
                "--with=mcp:local-tools",
                "-c",
                "mcp_servers.host-owned={command=\"false\"}",
            ]),
        )
        .unwrap();
        assert_eq!(
            independent_mcp.provider_args,
            strings(&["-c", "mcp_servers.host-owned={command=\"false\"}"])
        );

        let nested_exact_mcp_conflict = prepare(
            Provider::Codex,
            &strings(&[
                "--with=mcp:local-tools",
                "-c",
                "mcp_servers.local-tools.enabled=false",
            ]),
        )
        .unwrap_err();
        assert!(nested_exact_mcp_conflict.contains("COMPOSITION_CONFLICT:"));

        let literal = prepare(
            Provider::Codex,
            &strings(&[
                "--with=plugin:codex-app-tools@openai-bundled",
                "--",
                "-c",
                "features.plugins=false",
            ]),
        )
        .unwrap();
        assert_eq!(
            literal.provider_args,
            strings(&["--", "-c", "features.plugins=false"])
        );
    }

    #[test]
    fn raw_claude_plugin_activation_conflicts_only_before_terminator() {
        for args in [
            strings(&["--plugin-dir", "/tmp/plugin"]),
            strings(&["--plugin-url", "https://example.invalid/plugin.zip"]),
            strings(&["--plugin-dir=/tmp/plugin"]),
            strings(&["--plugin-url=https://example.invalid/plugin.zip"]),
        ] {
            let mut invocation = vec!["--with=plugin:review-tools@team".to_owned()];
            invocation.extend(args);
            let error = prepare(Provider::Claude, &invocation).unwrap_err();
            assert!(error.contains("COMPOSITION_CONFLICT:"), "{invocation:?}: {error}");
        }

        let settings_conflict = prepare(
            Provider::Claude,
            &strings(&[
                "--with=plugin:review-tools@team",
                "--settings",
                "settings.json",
            ]),
        )
        .unwrap_err();
        assert!(settings_conflict.contains("COMPOSITION_UNKNOWN:"));

        let ambient_settings_conflict = prepare(
            Provider::Claude,
            &strings(&[
                "--with=plugin:review-tools@team",
                "--setting-sources",
                "user,project,local",
            ]),
        )
        .unwrap_err();
        assert!(ambient_settings_conflict.contains("personal-global"));

        let attached_settings_conflict = prepare(
            Provider::Claude,
            &strings(&[
                "--with=plugin:review-tools@team",
                "--setting-sources=user,project,local",
            ]),
        )
        .unwrap_err();
        assert!(attached_settings_conflict.contains("personal-global"));

        let mcp_source_conflict = prepare(
            Provider::Claude,
            &strings(&[
                "--with=plugin:review-tools@team",
                "--mcp-config",
                "host-mcp.json",
            ]),
        )
        .unwrap_err();
        assert!(mcp_source_conflict.contains("COMPOSITION_UNKNOWN:"));

        let literal = prepare(
            Provider::Claude,
            &strings(&[
                "--with=plugin:review-tools@team",
                "--",
                "--plugin-dir",
                "/tmp/literal",
            ]),
        )
        .unwrap();
        assert_eq!(
            literal.provider_args,
            strings(&["--no-chrome", "--", "--plugin-dir", "/tmp/literal"])
        );

        let raw_only = prepare(
            Provider::Claude,
            &strings(&["--plugin-dir", "/tmp/provider-owned"]),
        )
        .unwrap();
        assert_eq!(
            raw_only.provider_args,
            strings(&["--no-chrome", "--plugin-dir", "/tmp/provider-owned"])
        );
    }

    #[test]
    fn supported_native_value_arities_preserve_selector_like_values_and_arguments() {
        let codex = prepare(
            Provider::Codex,
            &strings(&[
                "--with=plugin:codex-app-tools@openai-bundled",
                "--model",
                "--with=literal-model-value",
                "--image",
                "one.png",
                "two.png",
            ]),
        )
        .unwrap();
        assert_eq!(
            codex.provider_args,
            strings(&[
                "--model",
                "--with=literal-model-value",
                "--image",
                "one.png",
                "two.png",
            ])
        );

        let claude = prepare(
            Provider::Claude,
            &strings(&[
                "--with=plugin:review-tools@team",
                "--append-system-prompt",
                "--with=literal-prompt-value",
                "--tools",
                "Read",
                "Write",
            ]),
        )
        .unwrap();
        assert_eq!(
            claude.provider_args,
            strings(&[
                "--no-chrome",
                "--append-system-prompt",
                "--with=literal-prompt-value",
                "--tools",
                "Read",
                "Write",
            ])
        );
    }

    #[test]
    fn dangerous_native_security_overrides_fail_closed() {
        for args in [
            strings(&["--dangerously-bypass-approvals-and-sandbox"]),
            strings(&["--dangerously-bypass-hook-trust"]),
            strings(&["--approve-for-me"]),
            strings(&["--yolo"]),
            strings(&["--sandbox=danger-full-access"]),
            strings(&["-s=danger-full-access"]),
            strings(&["--ask-for-approval=never"]),
            strings(&["-a=never"]),
        ] {
            let error = prepare(Provider::Codex, &args).unwrap_err();
            assert!(error.starts_with("CLROOM_ISOLATION_CONFLICT:"), "{error}");
        }
        for args in [
            strings(&["--dangerously-skip-permissions"]),
            strings(&["--allow-dangerously-skip-permissions"]),
        ] {
            let error = prepare(Provider::Claude, &args).unwrap_err();
            assert!(error.starts_with("CLROOM_ISOLATION_CONFLICT:"), "{error}");
        }
        for (provider, args) in [
            (
                Provider::Codex,
                strings(&["--with=plugin:x@y", "--sandbox", "danger-full-access"]),
            ),
            (
                Provider::Claude,
                strings(&["--with=plugin:x@y", "--permission-mode", "bypassPermissions"]),
            ),
            (Provider::Claude, strings(&["--permission-mode=bypassPermissions"])),
        ] {
            let error = prepare(provider, &args).unwrap_err();
            assert!(error.starts_with("CLROOM_ISOLATION_CONFLICT:"), "{error}");
        }
    }

    #[test]
    fn plugin_bundled_mcp_overrides_are_compared_by_exact_server_id() {
        let selected = vec!["docs".to_owned()];
        let conflict = validate_plugin_mcp_config(
            &strings(&["-c", "mcp_servers.\"docs\".enabled=false"]),
            &selected,
        )
        .unwrap_err();
        assert!(conflict.contains("plugin-bundled MCP server"));

        validate_plugin_mcp_config(
            &strings(&["--config=mcp_servers.host-owned={command=\"false\"}"]),
            &selected,
        )
        .unwrap();
        validate_plugin_mcp_config(
            &strings(&["--", "-c", "mcp_servers.docs.enabled=false"]),
            &selected,
        )
        .unwrap();
    }

    #[test]
    fn codex_exec_security_flags_and_short_attached_forms_fail_closed() {
        for args in [
            strings(&["exec", "--dangerously-bypass-approvals-and-sandbox"]),
            strings(&["exec", "resume", "--yolo"]),
            strings(&["-m", "gpt-5", "exec", "--ask-for-approval=never"]),
            strings(&["exec", "-sdanger-full-access"]),
            strings(&["exec", "-anever"]),
            strings(&["exec", "-c", "shell_environment_policy.filters.PATH='include'"]),
            strings(&["-csandbox_mode='danger-full-access'"]),
        ] {
            let error = prepare(Provider::Codex, &args).unwrap_err();
            assert!(
                error.starts_with("CLROOM_ISOLATION_CONFLICT:")
                    || error.starts_with("CLROOM_RESOURCE_COMPOSITION_CONFLICT:"),
                "{args:?}: {error}"
            );
        }
        let literal = strings(&["exec", "--", "--yolo"]);
        assert_eq!(prepare(Provider::Codex, &literal).unwrap().provider_args, literal);
    }

    #[test]
    fn toml_quoted_and_nested_resource_keys_fail_closed() {
        for config in [
            "features={plugins=false}",
            "mcp_servers.\\\"docs\\\".enabled=false",
            "\\\"sandbox_mode\\\"='danger-full-access'",
            "shell_environment_policy.filters.PATH='include'",
        ] {
            let args = strings(&[
                "--with=plugin:codex-app-tools@openai-bundled",
                "--with=mcp:docs",
                "-c",
                config,
            ]);
            let error = prepare(Provider::Codex, &args).unwrap_err();
            assert!(error.contains("COMPOSITION_CONFLICT:"), "{config}: {error}");
        }
        let disjoint = strings(&[
            "--with=plugin:codex-app-tools@openai-bundled",
            "-c",
            "features.unified_exec=true",
        ]);
        assert!(prepare(Provider::Codex, &disjoint).is_ok());
    }

    #[test]
    fn claude_dont_ask_preserves_deny_without_prompt_native_intent() {
        let args = strings(&["--permission-mode=dontAsk"]);
        assert_eq!(
            prepare(Provider::Claude, &args).unwrap().provider_args,
            strings(&["--no-chrome", "--permission-mode=dontAsk"])
        );
        assert!(prepare(
            Provider::Claude,
            &strings(&["--allow-dangerously-skip-permissions=true"])
        )
        .is_err());
    }

    #[test]
    fn malformed_or_unknown_selectors_fail_with_stable_code() {
        for selector in ["--with", "--without", "--with=", "--with=capability"] {
            let error = prepare(Provider::Claude, &strings(&[selector])).unwrap_err();
            assert!(error.starts_with("CLROOM_RESOURCE_SELECTOR_INVALID:"));
        }
    }
}
