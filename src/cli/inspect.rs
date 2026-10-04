use std::path::PathBuf;

use clroom::adapters::codex::isolation::{IsolationInputs, plan_with_skills};

use super::{
    codex_resolved_launch_error_message, isolation_error_message, launch_contract, output, process,
    resource_options, select_codex_options, skill_sets,
};

pub fn run(args: &[String], mode: output::Mode) -> Result<String, String> {
    let Some(provider) = args.first() else {
        return Err("INSPECT_PROVIDER_REQUIRED: use inspect codex [CODEX_ARGS...]".to_owned());
    };
    if provider != "codex" {
        return Err(
            "INSPECT_PROVIDER_UNAVAILABLE: effective launch inspection is available for Codex in v0.5.0"
                .to_owned(),
        );
    }

    let prepared =
        resource_options::prepare(resource_options::Provider::Codex, &args[1..])?;
    let (selection_terms, provider_args, pass_env) =
        select_codex_options(&prepared.provider_args)?;

    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .ok_or_else(|| "CLROOM_ISOLATION_INVALID: HOME is unavailable; continue locally".to_owned())?;
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
    let contract = if pass_env.is_empty() {
        launch_contract::LaunchContract::codex(&provider_args)
    } else {
        launch_contract::LaunchContract::codex_with_pass_env(&provider_args, &pass_env)
    };
    let executable = process::resolve_codex_executable()?;
    let isolation = plan_with_skills(&project, &executable, &inputs, &selectors)
        .map_err(isolation_error_message)?;
    let identity = process::preflight_codex(&executable, &provider_args)?;

    let invocation = launch_contract::classify_codex_invocation(&provider_args);
    if !prepared.request.is_empty()
        && invocation != launch_contract::CodexInvocation::Interactive
    {
        return Err(
            "CLROOM_RESOURCE_NOT_SELECTABLE: Codex resource activation is qualified only for interactive launch; continue locally"
                .to_owned(),
        );
    }

    let resolved = launch_contract::ResolvedLaunch::resolve_codex(
        contract,
        identity,
        isolation,
        &home,
        &inputs.codex_home,
        &prepared.request,
        &pass_env,
        provider_args.len(),
    )
    .map_err(codex_resolved_launch_error_message)?;

    if resolved.mcp_activation().is_some()
        && !launch_contract::codex_top_level_interactive(&provider_args)
    {
        return Err(
            "CLROOM_RESOURCE_NOT_SELECTABLE: standalone Codex MCP activation is qualified only for top-level interactive launch; provider subcommands are refused"
                .to_owned(),
        );
    }

    resolved
        .revalidate_codex_sources(&home, &inputs.codex_home)
        .map_err(codex_resolved_launch_error_message)?;
    if resolved.mcp_activation().is_some() {
        process::preflight_codex_project_mcp_layers(&resolved.isolation().project)?;
    }

    let summary = resolved.summary();
    match mode {
        output::Mode::Human => Ok(render_human(&summary)),
        output::Mode::Json => serde_json::to_string_pretty(&summary)
            .map_err(|_| "INSPECT_SERIALIZATION_FAILED".to_owned()),
    }
}

fn render_human(summary: &launch_contract::ResolvedLaunchSummary) -> String {
    let mut lines = vec![
        format!(
            "Resolved launch: {} {} / {} / {}",
            summary.provider, summary.provider_version, summary.os, summary.arch
        ),
        format!("Boundary: {}", summary.boundary),
    ];

    if summary.boundary_controls.is_empty() {
        lines.push("Boundary controls: none".to_owned());
    } else {
        lines.push(format!(
            "Boundary controls: {}",
            summary.boundary_controls.join(", ")
        ));
    }

    if summary.resources.is_empty() {
        lines.push("Resources: none".to_owned());
    } else {
        lines.push("Resources:".to_owned());
        for resource in &summary.resources {
            let qualification = resource
                .qualification
                .map(|value| format!(", qualification={value}"))
                .unwrap_or_default();
            lines.push(format!(
                "  {}:{} — {} ({reason}{qualification})",
                resource.kind,
                resource.id,
                resource.decision,
                reason = resource.reason,
            ));
        }
    }

    if summary.selected_global_skills.is_empty() {
        lines.push("Global skills: none".to_owned());
    } else {
        lines.push(format!(
            "Global skills: {}",
            summary.selected_global_skills.join(", ")
        ));
    }

    if summary.pass_env.is_empty() {
        lines.push("Pass env: none".to_owned());
    } else {
        lines.push(format!("Pass env names: {}", summary.pass_env.join(", ")));
    }

    lines.push(format!(
        "Provider argv: {} element(s), values redacted",
        summary.provider_argv.element_count
    ));
    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::render_human;
    use super::super::launch_contract::{
        ResolvedLaunchSummary, ResolvedProviderArgSummary, ResolvedResourceSummary,
    };

    #[test]
    fn human_summary_exposes_names_and_reasons_not_provider_values() {
        let summary = ResolvedLaunchSummary {
            schema_version: "clroom.resolved-launch.v1",
            provider: "codex",
            provider_version: "0.160.0".to_owned(),
            os: "macos".to_owned(),
            arch: "aarch64".to_owned(),
            resources: vec![ResolvedResourceSummary {
                kind: "mcp",
                id: "review".to_owned(),
                decision: "selected",
                reason: "explicit-selection",
                qualification: Some("qualified"),
            }],
            selected_global_skills: vec!["rust".to_owned()],
            pass_env: vec!["REVIEW_TOKEN".to_owned()],
            boundary: "boundary expanded",
            boundary_controls: vec!["environment", "mcp"],
            provider_argv: ResolvedProviderArgSummary {
                element_count: 2,
                values_exposed: false,
            },
        };

        let human = render_human(&summary);
        assert!(human.contains("mcp:review"));
        assert!(human.contains("explicit-selection"));
        assert!(human.contains("REVIEW_TOKEN"));
        assert!(human.contains("values redacted"));
        assert!(!human.contains("secret-value"));
        assert!(!human.contains("/private/"));
    }
}
