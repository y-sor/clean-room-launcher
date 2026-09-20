#[path = "../../src/cli/launch_contract.rs"]
#[allow(dead_code)]
mod launch_contract;
#[path = "../../src/cli/screen.rs"]
#[allow(dead_code)]
mod screen;

use std::{
    fs,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

struct TempProject(PathBuf);

impl TempProject {
    fn new(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let project =
            std::env::temp_dir().join(format!("clroom-{label}-{}-{nonce}", std::process::id()));
        fs::create_dir_all(&project).unwrap();
        Self(project)
    }

    fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for TempProject {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn package_version_label() -> String {
    format!("v{}", env!("CARGO_PKG_VERSION"))
}

fn with_package_version(value: &str) -> String {
    value.replace("{VERSION}", env!("CARGO_PKG_VERSION"))
}

fn assert_project_supports_centered(output: &str) {
    let support_columns = |line: &str, support: char| {
        line.chars()
            .enumerate()
            .filter_map(|(column, glyph)| (glyph == support).then_some(column))
            .collect::<Vec<_>>()
    };
    let main_line = output.lines().find(|line| line.contains('╥')).unwrap();
    let project_line = output.lines().find(|line| line.contains('╨')).unwrap();
    let main_supports = support_columns(main_line, '╥');
    let project_supports = support_columns(project_line, '╨');

    assert_eq!(main_supports, project_supports);
    assert_eq!(main_supports.len(), 2);
    let plaque_left = main_line.chars().position(|glyph| glyph == '╰').unwrap();
    let plaque_right = main_line.chars().position(|glyph| glyph == '╯').unwrap();
    assert_eq!(
        main_supports[0] + main_supports[1],
        plaque_left + plaque_right
    );
}

#[test]
fn isolated_preview_renders_the_accepted_plain_launch_receipt() {
    // Break caught: the approved receipt geometry, spacing, or boundary claims drift.
    let output = screen::render_isolated_preview_for(
        Path::new("/private/tmp/clroom-preview-project"),
        0,
        screen::PlaqueFeatureState::default(),
        screen::RenderContext {
            width: 100,
            interactive: true,
            plain: true,
        },
    )
    .join("\n");

    let expected = with_package_version(
        "\n\n\n\
╓──○──╖ ╭─ CLEAN ROOM ─ v{VERSION} ─────────╮\n\
║░░░░░║⠒│                               │\n\
║░░░░░║⠒│     Global AGENTS.md  off     │\n\
║░░░░░║⠒│     Global skills     off     │\n\
║░░░░░║⠒│     Apps              off     │\n\
║░░░░░║⠒│     Hooks/plugins     off     │\n\
║░░░░░║⠒│     Dev prompt        off     │\n\
║░░░░░║⠒│     Notifications     off     │\n\
║░░░░░║⠒│                               │\n\
╙──○──╜ ╰───────────────────────────────╯\n",
    );
    assert_eq!(output, expected);
}

#[test]
fn isolated_preview_styles_only_the_visual_hierarchy() {
    // Break caught: ANSI styling changes the receipt text or its five-cell inset.
    let output = screen::render_isolated_preview_for(
        Path::new("/tmp/project"),
        0,
        screen::PlaqueFeatureState::default(),
        screen::RenderContext {
            width: 100,
            interactive: true,
            plain: false,
        },
    )
    .join("\n");

    assert!(output.starts_with("\n\n\n\u{1b}[2m╓──○──╖\u{1b}[0m "));
    assert!(output.contains(&with_package_version(
        "\u{1b}[1;36mCLEAN ROOM\u{1b}[0m\u{1b}[2m ─ v{VERSION} ─────────╮\u{1b}[0m"
    )));
    assert!(output.contains("\u{1b}[2m╙──○──╜ ╰───────────────────────────────╯\u{1b}[0m"));
    assert!(
        output.contains("\u{1b}[2m║░░░░░║⠒│\u{1b}[0m     \u{1b}[1mGlobal AGENTS.md\u{1b}[0m  off")
    );
    assert!(!output.contains("/tmp/project"));
}

#[test]
fn isolated_preview_top_frame_reaches_the_same_visible_width_at_narrow_and_wide_sizes() {
    let render = |width| {
        screen::render_isolated_preview_for(
            Path::new("/tmp/project"),
            0,
            screen::PlaqueFeatureState::default(),
            screen::RenderContext {
                width,
                interactive: true,
                plain: true,
            },
        )
        .into_iter()
        .find(|line| line.contains("CLEAN ROOM"))
        .unwrap()
    };

    assert_eq!(render(40).chars().count(), render(100).chars().count());
    assert_eq!(render(40).chars().count(), 41);
}

#[test]
fn isolated_preview_reports_the_number_of_selected_global_skills() {
    // Break caught: the plaque claims every global skill is off even though
    // this one launch admitted an explicit selection.
    let output = screen::render_isolated_preview_for(
        Path::new("/tmp/project"),
        12,
        screen::PlaqueFeatureState::default(),
        screen::RenderContext {
            width: 100,
            interactive: true,
            plain: true,
        },
    )
    .join("\n");

    assert!(output.contains("     Global skills   12 on     "));
    assert!(!output.contains("Global skills     off"));
}

#[test]
fn claude_preview_reports_only_proven_claude_boundaries() {
    // Break caught: Claude inherits Codex-only claims or counts `.agents/skills`
    // instead of the project skills Claude actually discovers.
    let project = TempProject::new("claude-project-skills-card");
    for name in ["lab", "ship"] {
        let skill = project.path().join(".claude/skills").join(name);
        fs::create_dir_all(&skill).unwrap();
        fs::write(skill.join("SKILL.md"), format!("# {name}\n")).unwrap();
    }
    let ignored = project.path().join(".agents/skills/ignored");
    fs::create_dir_all(&ignored).unwrap();
    fs::write(ignored.join("SKILL.md"), "# ignored\n").unwrap();

    let output = screen::render_claude_preview_for(
        project.path(),
        2,
        screen::RenderContext {
            width: 100,
            interactive: true,
            plain: true,
        },
    )
    .join("\n");

    assert!(output.contains("Global CLAUDE.md"));
    assert!(output.contains("Global AGENTS.md"));
    assert!(output.contains("Global skills"));
    assert!(output.contains("2 on"));
    assert!(output.contains("User settings"));
    assert!(output.contains("Auto memory"));
    assert!(output.contains("Project skills   2 on"));
    assert_project_supports_centered(&output);
    assert_eq!(output.matches(&package_version_label()).count(), 1);
    for codex_only in ["Apps", "Hooks/plugins", "Dev prompt", "Notifications"] {
        assert!(
            !output.contains(codex_only),
            "unexpected Claude claim: {codex_only}"
        );
    }
}

#[test]
fn claude_preview_omits_project_card_when_no_claude_project_skill_exists() {
    let project = TempProject::new("claude-no-project-skills-card");
    let ignored = project.path().join(".agents/skills/ignored");
    fs::create_dir_all(&ignored).unwrap();
    fs::write(ignored.join("SKILL.md"), "# ignored\n").unwrap();

    let output = screen::render_claude_preview_for(
        project.path(),
        0,
        screen::RenderContext {
            width: 100,
            interactive: true,
            plain: true,
        },
    )
    .join("\n");

    assert!(output.contains("Global skills      off"));
    assert!(!output.contains("Project skills"));
}

#[test]
fn isolated_preview_keeps_the_version_top_right_and_project_supports_symmetric() {
    // Break caught: adding the project-skills card moves the package version away
    // from the stable top-right anchor or displaces either attachment support.
    let project = TempProject::new("project-skills-card");
    for name in ["planning", "review"] {
        let skill = project.path().join(".agents/skills").join(name);
        fs::create_dir_all(&skill).unwrap();
        fs::write(skill.join("SKILL.md"), format!("# {name}\n")).unwrap();
    }
    fs::create_dir_all(project.path().join(".agents/skills/not-a-skill")).unwrap();

    let output = screen::render_isolated_preview_for(
        project.path(),
        0,
        screen::PlaqueFeatureState::default(),
        screen::RenderContext {
            width: 100,
            interactive: true,
            plain: true,
        },
    )
    .join("\n");

    assert!(output.contains(&with_package_version(
        "╓──○──╖ ╭─ CLEAN ROOM ─ v{VERSION} ─────────╮"
    )));
    let expected_attachment = [
        "╙──○──╜ ╰───────────╥───────╥───────────╯",
        "        ╭───────────╨───────╨───────────╮",
        "        │     Project skills   2 on     │",
        "        ╰───────────────────────────────╯",
    ]
    .join("\n");
    assert!(
        output.contains(&expected_attachment),
        "unexpected project-skills plaque:\n{output}"
    );

    assert_project_supports_centered(&output);
    assert_eq!(output.matches(&package_version_label()).count(), 1);
    assert!(!output.contains("╭─ Project"));
}

#[test]
fn isolated_preview_reports_explicit_apps_hooks_and_plugins_overrides() {
    // Break caught: the plaque keeps claiming clean defaults after the owner
    // explicitly re-enables one or more native Codex features for this launch.
    let cases = [
        (&["--enable", "apps"][..], "on", "off"),
        (&["--enable", "hooks"][..], "off", "on/off"),
        (&["--enable", "plugins"][..], "off", "off/on"),
        (
            &["--enable", "hooks", "--enable", "plugins"][..],
            "off",
            "on",
        ),
    ];

    for (args, apps, hooks_plugins) in cases {
        let args = args
            .iter()
            .map(|value| (*value).to_owned())
            .collect::<Vec<_>>();
        let state = screen::PlaqueFeatureState::from_provider_args(&args);
        let output = screen::render_isolated_preview_for(
            Path::new("/tmp/project"),
            0,
            state,
            screen::RenderContext {
                width: 100,
                interactive: true,
                plain: true,
            },
        )
        .join("\n");

        assert!(output.contains(&format!("     Apps{apps:>17}     ")));
        assert!(output.contains(&format!("     Hooks/plugins{hooks_plugins:>8}     ")));
    }
}

#[test]
fn isolated_preview_uses_the_last_override_and_stops_at_double_dash() {
    // Break caught: stale earlier flags or prompt text after `--` change the
    // visible receipt instead of the effective explicit launch controls.
    let args = [
        "--enable",
        "apps",
        "--disable",
        "apps",
        "--enable=hooks",
        "--disable=hooks",
        "--",
        "--enable",
        "plugins",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect::<Vec<_>>();
    let state = screen::PlaqueFeatureState::from_provider_args(&args);
    let output = screen::render_isolated_preview_for(
        Path::new("/tmp/project"),
        0,
        state,
        screen::RenderContext {
            width: 100,
            interactive: true,
            plain: true,
        },
    )
    .join("\n");

    assert!(output.contains("     Apps              off     "));
    assert!(output.contains("     Hooks/plugins     off     "));
}

#[test]
fn launch_contract_reports_boundary_expansion_unknown_syntax_and_model_neutrality() {
    use clroom::adapters::claude::managed::Presence;
    use launch_contract::{BoundaryState, LaunchContract};

    let codex_expansions = [
        vec!["-c", "features.apps=true"],
        vec!["--profile", "team"],
        vec!["--add-dir", "/tmp/extra"],
        vec!["--config", "mcp_servers.team.command=helper"],
        vec!["--sandbox", "danger-full-access"],
        vec!["--ask-for-approval", "never"],
    ];
    for args in codex_expansions {
        let args = args.into_iter().map(str::to_owned).collect::<Vec<_>>();
        let contract = LaunchContract::codex(&args);
        assert_eq!(contract.boundary, BoundaryState::Expanded, "{args:?}");
        assert_eq!(&contract.argv[contract.argv.len() - args.len()..], args);
    }

    let claude_expansions = [
        vec!["--setting-sources", "user,project,local"],
        vec!["--mcp-config", "/tmp/mcp.json"],
        vec!["--add-dir", "/tmp/extra"],
        vec!["--permission-mode", "bypassPermissions"],
        vec!["--dangerously-skip-permissions"],
    ];
    for args in claude_expansions {
        let args = args.into_iter().map(str::to_owned).collect::<Vec<_>>();
        let contract = LaunchContract::claude(
            &args,
            Path::new("/tmp/selected-projection"),
            Presence::Absent,
        );
        assert_eq!(contract.boundary, BoundaryState::Expanded, "{args:?}");
        assert_eq!(&contract.argv[contract.argv.len() - args.len()..], args);
    }

    let unknown = LaunchContract::codex(&["--future-sandbox-boundary".to_owned()]);
    assert_eq!(unknown.boundary, BoundaryState::Unknown);

    let model = LaunchContract::claude(
        &["--model".to_owned(), "owner-choice".to_owned()],
        Path::new("/tmp/selected-projection"),
        Presence::Absent,
    );
    assert_eq!(model.boundary, BoundaryState::Clean);
    assert!(model.user_or_provider_model_choice);
    assert!(!model.argv.iter().any(|argument| argument == "haiku"));
    assert!(!model.argv.iter().any(|argument| argument == "--effort"));
    assert!(
        screen::render_launch_contract(
            model.boundary_label(),
            model.managed_label(),
            &model.boundary_controls,
            model.user_or_provider_model_choice,
        )
        .join("\n")
        .contains("user/provider model choice")
    );

    let managed = LaunchContract::claude(
        &[],
        Path::new("/tmp/selected-projection"),
        Presence::Present,
    );
    assert_eq!(managed.boundary, BoundaryState::Unknown);

    let codex_env = LaunchContract::codex_with_pass_env(
        &["--help".to_owned()],
        &["RUNNER_REQUESTED".to_owned()],
    );
    assert!(codex_env.argv.iter().any(|argument| {
        argument == "shell_environment_policy.include_only=[\"PATH\",\"HOME\",\"TMPDIR\",\"TERM\",\"COLORTERM\",\"LANG\",\"LC_ALL\",\"LC_CTYPE\",\"TZ\",\"RUNNER_REQUESTED\"]"
    }));
    let clean_codex = LaunchContract::codex(&["--help".to_owned()]);
    assert_eq!(clean_codex.boundary, BoundaryState::Clean);
    let expanded_codex = LaunchContract::codex_with_pass_env(
        &["--help".to_owned()],
        &["RUNNER_REQUESTED".to_owned()],
    );
    assert_eq!(expanded_codex.boundary, BoundaryState::Expanded);
    assert_eq!(expanded_codex.boundary_controls, vec!["environment"]);
    assert_eq!(expanded_codex.boundary_label(), "boundary expanded");
    let expanded_rendered = screen::render_launch_contract(
        expanded_codex.boundary_label(),
        expanded_codex.managed_label(),
        &expanded_codex.boundary_controls,
        expanded_codex.user_or_provider_model_choice,
    )
    .join("\n");
    assert!(expanded_rendered.contains("environment"));
    let rendered = screen::render_launch_contract(
        managed.boundary_label(),
        managed.managed_label(),
        &managed.boundary_controls,
        managed.user_or_provider_model_choice,
    )
    .join("\n");
    assert!(rendered.contains("managed present"));
    assert!(rendered.contains("managed/unknown"));
}
