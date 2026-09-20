#[allow(dead_code)]
pub(crate) mod consent;
mod dispatch;
mod doctor;
mod help;
mod info;
mod launch_contract;
mod output;
mod parser;
mod process;
mod resource_options;
mod screen;
mod skill_sets;
mod starts;
#[allow(dead_code)] // T8 is the first user-flow consumer; T7 seals the store and its TDD contract.
pub(crate) mod state;
mod zero_auth;

use std::io::{IsTerminal, Write};
use std::path::PathBuf;
use std::process::ExitCode;

use clroom::adapters::claude::{
    activation::{self as claude_activation, ActivationError as ClaudeActivationError},
    isolation::{IsolationError as ClaudeIsolationError, plan as plan_claude},
    projection::{ProjectionError, project},
};
use clroom::catalog::selection::SelectionRequest;
use clroom::adapters::codex::{
    activation::{self as codex_activation, ActivationError as CodexActivationError},
    isolation::{IsolationError, IsolationInputs, plan_with_skills},
};

pub fn run(invoked_as: &str, args: impl IntoIterator<Item = String>) -> ExitCode {
    if std::env::var_os(process::INTERNAL_PROVIDER_CHAIN_GUARD).is_some() {
        eprintln!(
            "CLROOM_PROVIDER_RECURSION_REFUSED: provider resolution returned to CLROOM; remove the CLROOM executable from the provider PATH"
        );
        return ExitCode::from(2);
    }
    let mut source = args.into_iter().peekable();
    if source
        .peek()
        .is_some_and(|argument| argument == "--clroom-installer-smoke")
    {
        source.next();
        return if source.next().is_none() {
            ExitCode::SUCCESS
        } else {
            eprintln!("CLROOM_INSTALLER_SMOKE_INVALID: unexpected arguments");
            ExitCode::from(2)
        };
    }
    if invoked_as == "clroom-codex" {
        return run_codex(&mut source);
    }
    if invoked_as == "clroom-claude" {
        return run_claude(&mut source);
    }
    let Some(first) = (match next_argument(&mut source) {
        Ok(argument) => argument,
        Err(exit) => return exit,
    }) else {
        return run_local(invoked_as, Vec::new());
    };
    if matches!(first.as_str(), "--version" | "-V") {
        println!("clroom {}", env!("CARGO_PKG_VERSION"));
        return ExitCode::SUCCESS;
    }
    if first == "codex" {
        return run_codex(&mut source);
    }
    if first == "claude" {
        return run_claude(&mut source);
    }
    if let Some(exit) = external_prefix(&first) {
        return exit;
    }
    if first == "--output"
        && let Some(format) = (match next_argument(&mut source) {
            Ok(argument) => argument,
            Err(exit) => return exit,
        })
    {
        if format != "json" {
            return run_local(invoked_as, vec![first, format]);
        }
        let mut local_args = vec![first, format];
        if let Some(command) = match next_argument(&mut source) {
            Ok(argument) => argument,
            Err(exit) => return exit,
        } {
            if let Some(exit) = external_prefix(&command) {
                return exit;
            }
            let collect_tail = command == "info";
            local_args.push(command);
            if collect_tail {
                while let Some(argument) = match next_argument(&mut source) {
                    Ok(argument) => argument,
                    Err(exit) => return exit,
                } {
                    local_args.push(argument);
                }
            }
        }
        return run_local(invoked_as, local_args);
    }

    match local_prefix(first, &mut source) {
        Ok(args) => run_local(invoked_as, args),
        Err(exit) => exit,
    }
}

fn run_codex(source: &mut impl Iterator<Item = String>) -> ExitCode {
    let first = match next_argument(source) {
        Ok(argument) => argument,
        Err(exit) => return exit,
    };
    if first
        .as_deref()
        .is_some_and(|argument| matches!(argument, "login" | "logout"))
    {
        return external_refusal(parser::Command::Provider, false);
    }
    let mut args = first.into_iter().collect::<Vec<_>>();
    while let Some(argument) = match next_argument(source) {
        Ok(argument) => argument,
        Err(exit) => return exit,
    } {
        args.push(argument);
    }
    let prepared = match resource_options::prepare(resource_options::Provider::Codex, &args) {
        Ok(prepared) => prepared,
        Err(message) => {
            eprintln!("{message}");
            return ExitCode::from(2);
        }
    };
    let (selection_terms, provider_args, pass_env) =
        match select_codex_options(&prepared.provider_args) {
        Ok(options) => options,
        Err(message) => {
            eprintln!("{message}");
            return ExitCode::from(2);
        }
    };
    match launch_isolated_codex(
        &selection_terms,
        &provider_args,
        &pass_env,
        &prepared.request,
    ) {
        Ok(exit) => exit,
        Err(message) => {
            eprintln!("{message}");
            ExitCode::from(2)
        }
    }
}

fn run_claude(source: &mut impl Iterator<Item = String>) -> ExitCode {
    let first = match next_argument(source) {
        Ok(argument) => argument,
        Err(exit) => return exit,
    };
    if first
        .as_deref()
        .is_some_and(|argument| matches!(argument, "auth" | "login" | "logout"))
    {
        return external_refusal(parser::Command::Provider, false);
    }
    let mut args = first.into_iter().collect::<Vec<_>>();
    while let Some(argument) = match next_argument(source) {
        Ok(argument) => argument,
        Err(exit) => return exit,
    } {
        args.push(argument);
    }
    let prepared = match resource_options::prepare(resource_options::Provider::Claude, &args) {
        Ok(prepared) => prepared,
        Err(message) => {
            eprintln!("{message}");
            return ExitCode::from(2);
        }
    };
    let (selection_terms, provider_args, pass_env) =
        match select_provider_options(&prepared.provider_args) {
        Ok(options) => options,
        Err(message) => {
            eprintln!("{message}");
            return ExitCode::from(2);
        }
    };
    match launch_isolated_claude(
        &selection_terms,
        &provider_args,
        &pass_env,
        &prepared.request,
    ) {
        Ok(exit) => exit,
        Err(message) => {
            eprintln!("{message}");
            ExitCode::from(2)
        }
    }
}

fn launch_isolated_codex(
    selection_terms: &[String],
    provider_args: &[String],
    pass_env: &[String],
    resource_request: &SelectionRequest,
) -> Result<ExitCode, String> {
    let home = std::env::var_os("HOME").map(PathBuf::from).ok_or_else(|| {
        "CLROOM_ISOLATION_INVALID: HOME is unavailable; continue locally".to_owned()
    })?;
    let selectors = skill_sets::expand(&selection_terms, &home)?;
    let inputs = IsolationInputs {
        codex_home: std::env::var_os("CODEX_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".codex")),
        home: home.clone(),
    };
    let project = std::env::current_dir().map_err(|_| {
        "CLROOM_ISOLATION_INVALID: current project is unavailable; continue locally".to_owned()
    })?;
    let mut contract = if pass_env.is_empty() {
        launch_contract::LaunchContract::codex(provider_args)
    } else {
        launch_contract::LaunchContract::codex_with_pass_env(provider_args, pass_env)
    };
    let executable = match process::resolve_codex_executable() {
        Ok(executable) => executable,
        Err(error) => {
            contract.boundary = launch_contract::BoundaryState::NotLaunchable;
            if std::io::stderr().is_terminal() {
                let feature_state = screen::PlaqueFeatureState::from_provider_args(&provider_args);
                eprintln!(
                    "{}",
                    screen::render_isolated_preview(&project, selectors.len(), feature_state)
                        .join("\n")
                );
            }
            return Err(error);
        }
    };
    let plan = plan_with_skills(&project, &executable, &inputs, &selectors)
        .map_err(isolation_error_message)?;
    let identity = match process::preflight_codex(&executable, provider_args) {
        Ok(identity) => identity,
        Err(error) => {
            contract.boundary = launch_contract::BoundaryState::NotLaunchable;
            if std::io::stderr().is_terminal() {
                let feature_state = screen::PlaqueFeatureState::from_provider_args(&provider_args);
                eprintln!(
                    "{}",
                    screen::render_isolated_preview(
                        &plan.project,
                        plan.selected_global_skills,
                        feature_state,
                    )
                    .join("\n")
                );
            }
            return Err(error);
        }
    };
    let invocation = launch_contract::classify_codex_invocation(&provider_args);
    let activation = if resource_request.is_empty() {
        None
    } else {
        if invocation != launch_contract::CodexInvocation::Interactive {
            return Err(
                "CLROOM_RESOURCE_NOT_SELECTABLE: v0.4.1 Codex whole-plugin activation is qualified only for interactive launch; continue locally"
                    .to_owned(),
            );
        }
        codex_activation::plan(&home, &inputs.codex_home, resource_request, &identity)
            .map_err(codex_activation_error_message)?
    };
    if let Some(activation) = activation.as_ref() {
        activation
            .revalidate(&home, &inputs.codex_home)
            .map_err(codex_activation_error_message)?;
    }
    let state = if invocation == launch_contract::CodexInvocation::Interactive {
        Some(process::prepare_codex_state(
            &home,
            &inputs.codex_home,
            &plan.selected_global_skill_paths,
            activation.as_ref(),
        )?)
    } else {
        None
    };
    if let Some(activation) = activation.as_ref() {
        activation
            .revalidate(&home, &inputs.codex_home)
            .map_err(codex_activation_error_message)?;
        contract.add_codex_plugin_activation(&activation.provider_config_args());
    }
    if std::io::stderr().is_terminal() {
        let feature_state = screen::PlaqueFeatureState::from_provider_args(&provider_args);
        eprintln!(
            "{}",
            screen::render_isolated_preview(
                &plan.project,
                plan.selected_global_skills,
                feature_state,
            )
            .join("\n")
        );
    }
    process::launch_isolated_codex(
        &plan,
        &executable,
        &contract,
        &identity,
        pass_env,
        &home,
        &inputs.codex_home,
        state.as_ref(),
        activation.as_ref(),
    )
}

fn launch_isolated_claude(
    selection_terms: &[String],
    provider_args: &[String],
    pass_env: &[String],
    resource_request: &SelectionRequest,
) -> Result<ExitCode, String> {
    let home = std::env::var_os("HOME").map(PathBuf::from).ok_or_else(|| {
        "CLROOM_CLAUDE_ISOLATION_INVALID: HOME is unavailable; continue locally".to_owned()
    })?;
    let selectors = skill_sets::expand(selection_terms, &home)?;
    let current_project = std::env::current_dir().map_err(|_| {
        "CLROOM_CLAUDE_ISOLATION_INVALID: current project is unavailable; continue locally"
            .to_owned()
    })?;
    let mut projection = project(&home, &selectors).map_err(projection_error_message)?;
    let mut contract = launch_contract::LaunchContract::claude_with_pass_env(
        provider_args,
        &projection.add_dir,
        clroom::adapters::claude::managed::probe(),
        pass_env,
    );
    let executable = match process::resolve_claude_executable() {
        Ok(executable) => executable,
        Err(error) => {
            contract.boundary = launch_contract::BoundaryState::NotLaunchable;
            if std::io::stderr().is_terminal() {
                eprintln!(
                    "{}",
                    screen::render_claude_preview(
                        &current_project,
                        projection.selected_global_skills,
                    )
                    .join("\n")
                );
            }
            return Err(error);
        }
    };

    if resource_request.is_empty() {
        let isolation = plan_claude(
            &current_project,
            &executable,
            &home,
            projection.storage_root(),
            &projection.add_dir,
            projection.denied_source_paths(),
            projection.allowed_source_paths(),
        )
        .map_err(claude_isolation_error_message)?;
        let identity = match process::preflight_claude(&executable) {
            Ok(identity) => identity,
            Err(error) => {
                contract.boundary = launch_contract::BoundaryState::NotLaunchable;
                if std::io::stderr().is_terminal() {
                    eprintln!(
                        "{}",
                        screen::render_claude_preview(
                            &current_project,
                            projection.selected_global_skills,
                        )
                        .join("\n")
                    );
                }
                return Err(error);
            }
        };
        if std::io::stderr().is_terminal() {
            eprintln!(
                "{}",
                screen::render_claude_preview(
                    &current_project,
                    projection.selected_global_skills,
                )
                .join("\n")
            );
        }
        return process::launch_claude(
            &isolation,
            &mut projection,
            &executable,
            &contract,
            &identity,
            pass_env,
        );
    }

    let identity = match process::preflight_claude(&executable) {
        Ok(identity) => identity,
        Err(error) => {
            contract.boundary = launch_contract::BoundaryState::NotLaunchable;
            return Err(error);
        }
    };
    let activation = claude_activation::plan(&home, resource_request, &identity)
        .map_err(claude_activation_error_message)?;

    let mut allowed_source_paths = projection.allowed_source_paths().to_vec();
    if let Some(activation) = activation.as_ref() {
        activation
            .revalidate(&home)
            .map_err(claude_activation_error_message)?;
        allowed_source_paths.push(activation.root().to_path_buf());
    }

    let isolation = plan_claude(
        &current_project,
        &executable,
        &home,
        projection.storage_root(),
        &projection.add_dir,
        projection.denied_source_paths(),
        &allowed_source_paths,
    )
    .map_err(claude_isolation_error_message)?;

    if let Some(activation) = activation.as_ref() {
        activation
            .revalidate(&home)
            .map_err(claude_activation_error_message)?;
        contract.add_claude_plugin_activation(&activation.provider_args());
    }

    if std::io::stderr().is_terminal() {
        eprintln!(
            "{}",
            screen::render_claude_preview(
                &current_project,
                projection.selected_global_skills,
            )
            .join("\n")
        );
    }
    process::launch_claude(
        &isolation,
        &mut projection,
        &executable,
        &contract,
        &identity,
        pass_env,
    )
}

fn select_provider_options(
    args: &[String],
) -> Result<(Vec<String>, Vec<String>, Vec<String>), String> {
    let mut pass_env = Vec::new();
    let mut provider_selection_args = Vec::with_capacity(args.len());
    let mut launcher_options = true;
    for argument in args {
        if launcher_options && argument == "--" {
            launcher_options = false;
            provider_selection_args.push(argument.clone());
        } else if launcher_options && argument == "--pass-env" {
            return Err(
                "CLROOM_ENV_SELECTOR_INVALID: invalid environment name; use --pass-env=NAME"
                    .to_owned(),
            );
        } else if launcher_options && let Some(name) = argument.strip_prefix("--pass-env=") {
            if !valid_pass_env_name(name) {
                return Err(
                    "CLROOM_ENV_SELECTOR_INVALID: invalid environment name; use --pass-env=NAME"
                        .to_owned(),
                );
            }
            if !pass_env.iter().any(|selected| selected == name) {
                pass_env.push(name.to_owned());
            }
        } else {
            provider_selection_args.push(argument.clone());
        }
    }
    let (selectors, provider_args) = select_global_skills(&provider_selection_args)?;
    Ok((selectors, provider_args, pass_env))
}

fn select_global_skills(args: &[String]) -> Result<(Vec<String>, Vec<String>), String> {
    let mut selectors = None;
    let mut provider_args = Vec::with_capacity(args.len());
    let mut launcher_options = true;
    for argument in args {
        if launcher_options && argument == "--" {
            launcher_options = false;
            provider_args.push(argument.clone());
        } else if launcher_options && argument == "--skill-set" {
            return Err("CLROOM_SKILL_SELECTOR_INVALID: invalid skill selector; use --skill-set=name[,namespace:name,@set]".to_owned());
        } else if launcher_options && let Some(value) = argument.strip_prefix("--skill-set=") {
            if selectors.is_some() {
                return Err("CLROOM_SKILL_SELECTOR_INVALID: invalid skill selector; use one --skill-set= option".to_owned());
            }
            selectors = Some(value.split(',').map(str::to_owned).collect());
        } else {
            provider_args.push(argument.clone());
        }
    }
    Ok((selectors.unwrap_or_default(), provider_args))
}

fn select_codex_options(
    args: &[String],
) -> Result<(Vec<String>, Vec<String>, Vec<String>), String> {
    let mut pass_env = Vec::new();
    let mut provider_selection_args = Vec::with_capacity(args.len());
    let mut launcher_options = true;
    for argument in args {
        if launcher_options && argument == "--" {
            launcher_options = false;
            provider_selection_args.push(argument.clone());
        } else if launcher_options && argument == "--pass-env" {
            return Err(
                "CLROOM_ENV_SELECTOR_INVALID: invalid environment name; use --pass-env=NAME"
                    .to_owned(),
            );
        } else if launcher_options && let Some(name) = argument.strip_prefix("--pass-env=") {
            if !valid_pass_env_name(name) {
                return Err(
                    "CLROOM_ENV_SELECTOR_INVALID: invalid environment name; use --pass-env=NAME"
                        .to_owned(),
                );
            }
            if !pass_env.iter().any(|selected| selected == name) {
                pass_env.push(name.to_owned());
            }
        } else {
            provider_selection_args.push(argument.clone());
        }
    }
    let (selectors, provider_args) = select_global_skills(&provider_selection_args)?;
    Ok((selectors, provider_args, pass_env))
}

fn valid_pass_env_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 128
        && name.bytes().enumerate().all(|(index, byte)| {
            (byte.is_ascii_uppercase() || byte == b'_') || (index > 0 && byte.is_ascii_digit())
        })
}

fn isolation_error_message(error: IsolationError) -> String {
    match error {
        IsolationError::InvalidSkillSelector(selector) => format!(
            "CLROOM_SKILL_SELECTOR_INVALID: invalid skill selector '{selector}'; use --skill-set=name[,namespace:name,@set]"
        ),
        IsolationError::UnknownSkillSelector(selector) => format!(
            "CLROOM_SKILL_SELECTOR_UNKNOWN: unknown skill selector '{selector}'; continue locally"
        ),
        _ => "CLROOM_ISOLATION_INVALID: current project or context boundary is invalid; continue locally".to_owned(),
    }
}

fn projection_error_message(error: ProjectionError) -> String {
    match error {
        ProjectionError::InvalidSelector(selector) => format!(
            "CLROOM_SKILL_SELECTOR_INVALID: invalid skill selector '{selector}'; use --skill-set=name[,namespace:name,@set]"
        ),
        ProjectionError::UnknownSelector(selector) => format!(
            "CLROOM_SKILL_SELECTOR_UNKNOWN: unknown skill selector '{selector}'; continue locally"
        ),
        ProjectionError::NameCollision(name) => format!(
            "CLROOM_SKILL_SELECTOR_AMBIGUOUS: selected Claude skills collide at native name '{name}'; choose one source"
        ),
        ProjectionError::Unavailable => {
            "CLROOM_CLAUDE_ISOLATION_INVALID: session-only skill projection is unavailable; continue locally".to_owned()
        }
    }
}

fn claude_isolation_error_message(_: ClaudeIsolationError) -> String {
    "CLROOM_CLAUDE_ISOLATION_INVALID: current project or context boundary is invalid; continue locally"
        .to_owned()
}

fn codex_activation_error_message(error: CodexActivationError) -> String {
    match error {
        CodexActivationError::ProviderTupleNotQualified => {
            "CLROOM_RESOURCE_NOT_SELECTABLE: installed Codex version/platform is not qualified for v0.4.1 plugin activation; continue locally".to_owned()
        }
        CodexActivationError::MultiplePlugins => {
            "CLROOM_RESOURCE_MULTI_SELECT_UNAVAILABLE_IN_V0_4: v0.4.1 admits one exact Codex plugin per launch".to_owned()
        }
        CodexActivationError::StateChanged => {
            "CLROOM_RESOURCE_STATE_CHANGED: selected Codex plugin changed before launch; retry".to_owned()
        }
        CodexActivationError::UnsupportedRequest => {
            "CLROOM_RESOURCE_NOT_SELECTABLE: only exact Codex whole-plugin selection is available in v0.4.1; continue locally".to_owned()
        }
        CodexActivationError::InvalidSource => {
            "CLROOM_RESOURCE_NOT_SELECTABLE: selected Codex plugin source is invalid; continue locally".to_owned()
        }
        CodexActivationError::ProjectionFailed => {
            "CLROOM_CODEX_PLUGIN_PROJECTION_FAILED: selected Codex plugin could not be projected safely; continue locally".to_owned()
        }
        CodexActivationError::Selection(selection) => format!(
            "{}: selected Codex plugin is unavailable or unqualified; continue locally",
            selection.code()
        ),
    }
}

fn claude_activation_error_message(error: ClaudeActivationError) -> String {
    match error {
        ClaudeActivationError::ProviderTupleNotQualified => {
            "CLROOM_RESOURCE_NOT_SELECTABLE: installed Claude version/platform is not qualified for v0.4.0 plugin activation; continue locally".to_owned()
        }
        ClaudeActivationError::MultiplePlugins => {
            "CLROOM_RESOURCE_MULTI_SELECT_UNAVAILABLE_IN_V0_4: v0.4.0 admits one exact Claude plugin per launch".to_owned()
        }
        ClaudeActivationError::StateChanged => {
            "CLROOM_RESOURCE_STATE_CHANGED: selected Claude plugin changed before launch; retry".to_owned()
        }
        ClaudeActivationError::UnsupportedRequest => {
            "CLROOM_RESOURCE_NOT_SELECTABLE: only exact Claude whole-plugin selection is available in v0.4.0; continue locally".to_owned()
        }
        ClaudeActivationError::Selection(selection) => format!(
            "{}: selected Claude plugin is unavailable or unqualified; continue locally",
            selection.code()
        ),
    }
}

fn next_argument(source: &mut impl Iterator<Item = String>) -> Result<Option<String>, ExitCode> {
    match source.next() {
        Some(argument) if zero_auth::is_sensitive_argument(&argument) => {
            eprintln!("{}", zero_auth::ARGUMENT_REFUSAL);
            Err(ExitCode::from(2))
        }
        argument => Ok(argument),
    }
}

fn local_prefix(
    first: String,
    source: &mut impl Iterator<Item = String>,
) -> Result<Vec<String>, ExitCode> {
    if first == "info" {
        let mut args = vec![first];
        while let Some(argument) = next_argument(source)? {
            args.push(argument);
        }
        return Ok(args);
    }
    let additional = match first.as_str() {
        "help" | "--help" | "-h" | "explain" | "inspect" => 1,
        "doctor" | "start" => 2,
        _ => 0,
    };
    let mut args = vec![first];
    for _ in 0..additional {
        let Some(argument) = next_argument(source)? else {
            break;
        };
        args.push(argument);
    }
    Ok(args)
}

fn external_prefix(command: &str) -> Option<ExitCode> {
    let spec = help::resolve(command)?;
    if !matches!(
        spec.command,
        parser::Command::Provider | parser::Command::Generic
    ) {
        return None;
    }
    // Zero-auth closes the generic route at its boundary. Inspecting even the
    // nominal executable would consume a credential-shaped value in that slot.
    Some(external_refusal(spec.command, true))
}

fn external_refusal(command: parser::Command, generic_executable_present: bool) -> ExitCode {
    match dispatch::run(command, generic_executable_present) {
        Ok(exit) => exit,
        Err(message) => {
            eprintln!("{message}");
            ExitCode::from(2)
        }
    }
}

fn run_local(invoked_as: &str, args: Vec<String>) -> ExitCode {
    let (output_mode, args) = match output::select(args) {
        Ok(selection) => selection,
        Err(message) => {
            eprintln!("{message}");
            return ExitCode::from(2);
        }
    };
    if matches!(output_mode, output::Mode::Json) {
        if args.is_empty() {
            println!("{}", output::guided_json());
            return ExitCode::SUCCESS;
        }
        if args.first().is_some_and(|argument| argument == "info") {
            return match info::run(&args[1..], output::Mode::Json) {
                Ok(report) => {
                    println!("{report}");
                    ExitCode::SUCCESS
                }
                Err(message) => {
                    eprintln!("{message}");
                    ExitCode::from(2)
                }
            };
        }
        eprintln!(
            "OUTPUT_UNSUPPORTED_FOR_COMMAND: {}; use human output",
            args[0]
        );
        return ExitCode::from(2);
    }
    match help::respond(&args, invoked_as) {
        Ok(Some(output)) => {
            println!("{output}");
            return ExitCode::SUCCESS;
        }
        Ok(None) => {}
        Err(message) => {
            eprintln!("{message}");
            return ExitCode::from(2);
        }
    }
    let command = match parser::parse(&args) {
        Ok(command) => command,
        Err(message) => {
            eprintln!("{message}");
            return ExitCode::from(2);
        }
    };

    match command {
        parser::Command::Help => unreachable!("help is handled before parsing"),
        parser::Command::Guided => {
            let screen = screen::render_unqualified(screen::PrepareReady { provider: "Codex" });
            println!("{}", screen.join("\n"));
            if output::stdin_is_terminal() && std::io::stdout().is_terminal() {
                if std::io::stdout().flush().is_err() {
                    eprintln!("INTERACTIVE_OUTPUT_FAILED");
                    return ExitCode::from(2);
                }
                match screen::read_unqualified_action() {
                    Ok(screen::UnqualifiedAction::LaunchCodex) => {
                        return run_codex(&mut std::iter::empty());
                    }
                    Ok(screen::UnqualifiedAction::Stop) => {}
                    Err(_) => {
                        eprintln!("INTERACTIVE_INPUT_FAILED");
                        return ExitCode::from(2);
                    }
                }
            }
        }
        parser::Command::Info => match info::run(&args[1..], output::Mode::Human) {
            Ok(report) => println!("{report}"),
            Err(message) => {
                eprintln!("{message}");
                return ExitCode::from(2);
            }
        },
        parser::Command::Doctor => match doctor::run(&args[1..]) {
            Ok(report) => println!("{report}"),
            Err(message) => {
                eprintln!("{message}");
                return ExitCode::from(2);
            }
        },
        parser::Command::Starts => match starts::run(&args) {
            Ok(output) => println!("{output}"),
            Err(message) => {
                eprintln!("{message}");
                return ExitCode::from(2);
            }
        },
        parser::Command::Provider | parser::Command::Generic => {
            unreachable!("external commands refuse before tail collection")
        }
        command => return run_launcher_owned_local(invoked_as, command),
    }

    ExitCode::SUCCESS
}

fn run_launcher_owned_local(invoked_as: &str, command: parser::Command) -> ExitCode {
    let command = match command {
        parser::Command::Status => "status",
        parser::Command::Scan => "scan",
        parser::Command::Init => "init",
        parser::Command::Prepare => "prepare",
        parser::Command::Check => "check",
        parser::Command::Explain => "explain",
        parser::Command::Inspect => "inspect",
        _ => unreachable!("only unavailable local lifecycle commands reach this boundary"),
    };
    eprintln!(
        "LOCAL_LIFECYCLE_UNAVAILABLE: {command} is not implemented in this build; use {invoked_as} codex for the minimum isolated launch"
    );
    ExitCode::from(2)
}
