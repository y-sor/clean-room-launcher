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

pub fn prepare(provider: Provider, args: &[String]) -> Result<Prepared, String> {
    let mut request = SelectionRequest::default();
    let mut provider_args = Vec::with_capacity(args.len() + 1);
    let mut launcher_options = true;
    let mut raw_chrome_override = false;
    let mut raw_plugin_activation = false;

    for argument in args {
        if launcher_options && argument == "--" {
            launcher_options = false;
            provider_args.push(argument.clone());
        } else if launcher_options && matches!(argument.as_str(), "--with" | "--without") {
            return Err(invalid_selector());
        } else if launcher_options && let Some(value) = argument.strip_prefix("--with=") {
            request
                .include_value(value)
                .map_err(selection_error_message)?;
        } else if launcher_options && let Some(value) = argument.strip_prefix("--without=") {
            request
                .exclude_value(value)
                .map_err(selection_error_message)?;
        } else {
            if launcher_options {
                if provider == Provider::Claude {
                    if matches!(argument.as_str(), "--chrome" | "--no-chrome") {
                        raw_chrome_override = true;
                    }
                    if matches!(argument.as_str(), "--plugin-dir" | "--plugin-url")
                        || argument.starts_with("--plugin-dir=")
                        || argument.starts_with("--plugin-url=")
                    {
                        raw_plugin_activation = true;
                    }
                } else if provider == Provider::Codex
                    && (matches!(
                        argument.as_str(),
                        "-c"
                            | "--config"
                            | "--profile"
                            | "-p"
                            | "--enable"
                            | "--disable"
                            | "--plugin"
                    )
                        || argument.starts_with("-c=")
                        || argument.starts_with("-p=")
                        || argument.starts_with("--config=")
                        || argument.starts_with("--profile=")
                        || argument.starts_with("--enable=")
                        || argument.starts_with("--disable=")
                        || argument.starts_with("--plugin="))
                {
                    raw_plugin_activation = true;
                }
            }
            provider_args.push(argument.clone());
        }
    }

    if request
        .includes
        .iter()
        .chain(request.excludes.iter())
        .any(|target| matches!(target, SelectionTarget::All))
    {
        return Err(
            "CLROOM_RESOURCE_ALL_UNAVAILABLE_IN_V0_4: --with=all/--without=all is unavailable in v0.4.x"
                .to_owned(),
        );
    }

    let unsupported_exact = request
        .includes
        .iter()
        .chain(request.excludes.iter())
        .any(|target| match target {
            SelectionTarget::Exact { kind, .. } => *kind != ResourceKind::Plugin,
            SelectionTarget::All => false,
        });
    if unsupported_exact {
        return Err(
            "CLROOM_RESOURCE_NOT_SELECTABLE: only exact qualified whole-plugin selection is available in v0.4.x; continue locally"
                .to_owned(),
        );
    }

    if !request.is_empty() && raw_plugin_activation {
        return Err(
            "CLROOM_RESOURCE_ACTIVATION_CONFLICT: raw provider plugin/config activation controls cannot be combined with CLROOM --with/--without selection"
                .to_owned(),
        );
    }

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

fn invalid_selector() -> String {
    "CLROOM_RESOURCE_SELECTOR_INVALID: invalid resource selector".to_owned()
}

fn selection_error_message(_error: SelectionError) -> String {
    invalid_selector()
}

#[cfg(test)]
mod tests {
    use super::{prepare, Provider};
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
    fn unsupported_resource_kinds_and_all_remain_closed_in_v0_4_x() {
        for (provider, selector, code) in [
            (
                Provider::Codex,
                "--without=mcp:local-tools",
                "CLROOM_RESOURCE_NOT_SELECTABLE:",
            ),
            (
                Provider::Claude,
                "--without=mcp:local-tools",
                "CLROOM_RESOURCE_NOT_SELECTABLE:",
            ),
            (
                Provider::Claude,
                "--with=all",
                "CLROOM_RESOURCE_ALL_UNAVAILABLE_IN_V0_4:",
            ),
        ] {
            let error = prepare(provider, &strings(&[selector])).unwrap_err();
            assert!(error.starts_with(code), "{error}");
        }

        let all_error =
            prepare(Provider::Claude, &strings(&["--with=all"])).unwrap_err();
        assert!(all_error.contains("unavailable in v0.4.x"), "{all_error}");
        assert!(!all_error.contains("unavailable in v0.4.0"), "{all_error}");
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
    fn raw_codex_plugin_or_config_controls_conflict_only_before_terminator() {
        for flag in [
            "-c",
            "--config",
            "--profile",
            "-p",
            "--enable",
            "--disable",
            "--plugin",
            "-c=features.plugins=false",
            "-p=ambient",
            "--config=features.plugins=false",
            "--profile=ambient",
            "--enable=plugins",
            "--disable=plugins",
            "--plugin=ambient",
        ] {
            let error = prepare(
                Provider::Codex,
                &strings(&[
                    "--with=plugin:codex-app-tools@openai-bundled",
                    flag,
                    "synthetic",
                ]),
            )
            .unwrap_err();
            assert!(
                error.starts_with("CLROOM_RESOURCE_ACTIVATION_CONFLICT:"),
                "{flag}: {error}"
            );
        }

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
        for flag in [
            "--plugin-dir",
            "--plugin-url",
            "--plugin-dir=/tmp/plugin",
            "--plugin-url=https://example.invalid/plugin.zip",
        ] {
            let error = prepare(
                Provider::Claude,
                &strings(&["--with=plugin:review-tools@team", flag]),
            )
            .unwrap_err();
            assert!(
                error.starts_with("CLROOM_RESOURCE_ACTIVATION_CONFLICT:"),
                "{flag}: {error}"
            );
        }

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
    fn malformed_or_unknown_selectors_fail_with_stable_code() {
        for selector in ["--with", "--without", "--with=", "--with=capability"] {
            let error = prepare(Provider::Claude, &strings(&[selector])).unwrap_err();
            assert!(error.starts_with("CLROOM_RESOURCE_SELECTOR_INVALID:"));
        }
    }
}
