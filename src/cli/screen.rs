use std::{
    fs,
    io::{self, IsTerminal},
    path::Path,
};

pub struct PrepareReady {
    pub provider: &'static str,
}

pub struct RenderContext {
    pub width: usize,
    pub interactive: bool,
    pub plain: bool,
}

#[cfg(test)]
pub fn render_launch_contract(
    boundary_label: &str,
    managed_label: Option<&str>,
    boundary_controls: &[&str],
    user_or_provider_model_choice: bool,
) -> Vec<String> {
    let mut lines = vec![format!("Boundary: {boundary_label}")];
    if let Some(state) = managed_label {
        lines.push(format!("Managed: managed {state}"));
    }
    if !boundary_controls.is_empty() {
        lines.push(format!(
            "Boundary controls: {}",
            boundary_controls.join(", ")
        ));
    }
    if user_or_provider_model_choice {
        lines.push("Model: user/provider model choice".to_owned());
    }
    lines
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct PlaqueFeatureState {
    apps: bool,
    hooks: bool,
    plugins: bool,
}

impl PlaqueFeatureState {
    pub fn from_provider_args(args: &[String]) -> Self {
        let mut state = Self::default();
        let mut args = args.iter();
        while let Some(argument) = args.next() {
            if argument == "--" {
                break;
            }
            if matches!(argument.as_str(), "--enable" | "--disable") {
                if let Some(feature) = args.next() {
                    state.set(feature, argument == "--enable");
                }
            } else if let Some(feature) = argument.strip_prefix("--enable=") {
                state.set(feature, true);
            } else if let Some(feature) = argument.strip_prefix("--disable=") {
                state.set(feature, false);
            }
        }
        state
    }

    fn set(&mut self, feature: &str, enabled: bool) {
        match feature {
            "apps" => self.apps = enabled,
            "hooks" => self.hooks = enabled,
            "plugins" => self.plugins = enabled,
            _ => {}
        }
    }

    fn apps_label(self) -> &'static str {
        if self.apps { "on" } else { "off" }
    }

    fn hooks_plugins_label(self) -> &'static str {
        match (self.hooks, self.plugins) {
            (false, false) => "off",
            (true, false) => "on/off",
            (false, true) => "off/on",
            (true, true) => "on",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UnqualifiedAction {
    LaunchCodex,
    Stop,
}

pub fn terminal_is_interactive() -> bool {
    std::io::stdin().is_terminal() && std::io::stdout().is_terminal()
}

pub fn read_unqualified_action() -> io::Result<UnqualifiedAction> {
    let mut input = String::new();
    let bytes_read = std::io::stdin().read_line(&mut input)?;
    if bytes_read == 0 {
        Ok(UnqualifiedAction::Stop)
    } else {
        Ok(parse_unqualified_action(&input))
    }
}

pub fn parse_unqualified_action(input: &str) -> UnqualifiedAction {
    match input.trim() {
        "" | "1" => UnqualifiedAction::LaunchCodex,
        _ => UnqualifiedAction::Stop,
    }
}

pub fn render_unqualified(ready: PrepareReady) -> Vec<String> {
    let width = std::env::var("COLUMNS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|width| *width >= 20)
        .unwrap_or(80);
    let interactive = terminal_is_interactive();
    let plain = !interactive
        || std::env::var_os("NO_COLOR").is_some()
        || std::env::var("TERM").is_ok_and(|term| term.eq_ignore_ascii_case("dumb"));
    render_unqualified_for(
        ready,
        RenderContext {
            width,
            interactive,
            plain,
        },
    )
}

pub fn render_unqualified_for(ready: PrepareReady, context: RenderContext) -> Vec<String> {
    let _provider = ready.provider;
    let styled = context.interactive && !context.plain;
    let tagline = if context.interactive {
        "Ready to launch Codex without unrelated global instructions or skills."
    } else {
        "Launch Codex without unrelated global instructions and skills."
    };
    let mut lines = vec![if styled {
        "\u{1b}[1;36mClean Room Launcher\u{1b}[0m".to_owned()
    } else {
        "Clean Room Launcher".to_owned()
    }];
    lines.extend(wrap(tagline, context.width).into_iter().map(|line| {
        if styled {
            format!("\u{1b}[2m{line}\u{1b}[0m")
        } else {
            line
        }
    }));
    lines.push(String::new());
    lines.extend(render_preflight_command(context.width, styled));
    lines.push(String::new());
    if !context.interactive {
        lines.extend([
            "Preview only · provider not launched".to_owned(),
            "Run clroom codex [CODEX_ARGS...]".to_owned(),
        ]);
    } else if context.plain {
        lines.extend([
            "1. Launch Codex".to_owned(),
            String::new(),
            "Enter to launch · q to quit".to_owned(),
        ]);
    } else {
        lines.extend([
            "\u{1b}[1m› Launch Codex\u{1b}[0m".to_owned(),
            String::new(),
            "\u{1b}[2mEnter to launch · q to quit\u{1b}[0m".to_owned(),
        ]);
    }
    lines
}

fn render_preflight_command(width: usize, styled: bool) -> Vec<String> {
    let base = "clroom codex";
    let selector = "--skill-set=any-my-skill,@any-my-skill-set";
    let approval = "--approve-for-me";
    let plain = format!("{base} {selector} {approval}");
    if plain.chars().count() <= width {
        return vec![if styled {
            format!("\u{1b}[1m{base} \u{1b}[1;36m{selector}\u{1b}[0m \u{1b}[1m{approval}\u{1b}[0m")
        } else {
            plain
        }];
    }
    let base_line = format!("{base} \\");
    let selector_line = format!("  {selector} \\");
    if selector_line.chars().count() <= width {
        return if styled {
            vec![
                format!("\u{1b}[1m{base_line}\u{1b}[0m"),
                format!("\u{1b}[1;36m{selector}\u{1b}[0m \u{1b}[1m\\\u{1b}[0m"),
                format!("  \u{1b}[1m{approval}\u{1b}[0m"),
            ]
        } else {
            vec![base_line, selector_line, format!("  {approval}")]
        };
    }
    let (direct_skill, named_set) = selector
        .split_once(',')
        .expect("the documented selector has one direct skill and one named set");
    if styled {
        vec![
            format!("\u{1b}[1m{base_line}\u{1b}[0m"),
            format!("  \u{1b}[1;36m{direct_skill},\\\u{1b}[0m"),
            format!("\u{1b}[1;36m{named_set}\u{1b}[0m \u{1b}[1m\\\u{1b}[0m"),
            format!("  \u{1b}[1m{approval}\u{1b}[0m"),
        ]
    } else {
        vec![
            base_line,
            format!("  {direct_skill},\\"),
            format!("{named_set} \\"),
            format!("  {approval}"),
        ]
    }
}

fn plaque_top_fill(title: &str, version: &str, panel_width: usize) -> String {
    let visible_prefix = format!("╭─ {title} ─ {version} ");
    "─".repeat(panel_width.saturating_sub(visible_prefix.chars().count() + 1))
}

fn render_plaque_top(title: &str, version: &str, panel_width: usize, styled: bool) -> String {
    let fill = plaque_top_fill(title, version, panel_width);
    if styled {
        format!(
            "\u{1b}[2m╭─ \u{1b}[0m\u{1b}[1;36m{title}\u{1b}[0m\u{1b}[2m ─ {version} {fill}╮\u{1b}[0m"
        )
    } else {
        format!("╭─ {title} ─ {version} {fill}╮")
    }
}

pub fn render_isolated_preview(
    project: &Path,
    selected_global_skills: usize,
    feature_state: PlaqueFeatureState,
) -> Vec<String> {
    let width = std::env::var("COLUMNS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|width| *width >= 20)
        .unwrap_or(80);
    let interactive = std::io::stderr().is_terminal();
    let plain = !interactive
        || std::env::var_os("NO_COLOR").is_some()
        || std::env::var("TERM").is_ok_and(|term| term.eq_ignore_ascii_case("dumb"));
    render_isolated_preview_for(
        project,
        selected_global_skills,
        feature_state,
        RenderContext {
            width,
            interactive,
            plain,
        },
    )
}

pub fn render_isolated_preview_for(
    project: &Path,
    selected_global_skills: usize,
    feature_state: PlaqueFeatureState,
    context: RenderContext,
) -> Vec<String> {
    let styled = context.interactive && !context.plain;
    let panel_width: usize = 33;
    let content_width = panel_width - 4;
    let title = "CLEAN ROOM";
    let version = concat!("v", env!("CARGO_PKG_VERSION"));
    // Visual model: a wall-mounted boundary status plaque. The seven-cell mounting
    // rail stays fixed at the left; one-cell standoff markers connect it to the
    // right plaque. Plaque height follows `rows` automatically. If row text grows,
    // change `panel_width` and the exact receipt test together—never hand-pad height.
    let mounting_rail_top = "╓──○──╖";
    let mounting_rail_bottom = "╙──○──╜";
    let mounting_rail_fill = "║░░░░░║";
    let standoff_marker = "⠒";
    let mut lines = vec![String::new(), String::new(), String::new()];
    let styled_mounting_rail_top = if styled {
        format!("\u{1b}[2m{mounting_rail_top}\u{1b}[0m")
    } else {
        mounting_rail_top.to_owned()
    };
    lines.push(format!(
        "{styled_mounting_rail_top} {}",
        render_plaque_top(title, version, panel_width, styled)
    ));
    let skill_state = if selected_global_skills == 0 {
        "off".to_owned()
    } else {
        format!("{selected_global_skills} on")
    };
    let apps_state = feature_state.apps_label();
    let hooks_plugins_state = feature_state.hooks_plugins_label();
    let rows = vec![
        (String::new(), String::new()),
        (
            "    Global AGENTS.md  off".to_owned(),
            "    \u{1b}[1mGlobal AGENTS.md\u{1b}[0m  off".to_owned(),
        ),
        (
            format!("    Global skills{skill_state:>8}"),
            format!("    \u{1b}[1mGlobal skills\u{1b}[0m{skill_state:>8}"),
        ),
        (
            format!("    Apps{apps_state:>17}"),
            format!("    \u{1b}[1mApps\u{1b}[0m{apps_state:>17}"),
        ),
        (
            format!("    Hooks/plugins{hooks_plugins_state:>8}"),
            format!("    \u{1b}[1mHooks/plugins\u{1b}[0m{hooks_plugins_state:>8}"),
        ),
        (
            "    Dev prompt        off".to_owned(),
            "    \u{1b}[1mDev prompt\u{1b}[0m        off".to_owned(),
        ),
        (
            "    Notifications     off".to_owned(),
            "    \u{1b}[1mNotifications\u{1b}[0m     off".to_owned(),
        ),
        (String::new(), String::new()),
    ];
    for (plain, decorated) in rows {
        let padding = " ".repeat(content_width.saturating_sub(plain.chars().count()));
        lines.push(if styled {
            format!(
                "\u{1b}[2m{mounting_rail_fill}{standoff_marker}│\u{1b}[0m {}{padding} \u{1b}[2m│\u{1b}[0m",
                decorated
            )
        } else {
            format!("{mounting_rail_fill}{standoff_marker}│ {plain}{padding} │")
        });
    }
    let project_skills = count_project_skills(project);
    // The version has one stable anchor: the main plaque's top-right edge.
    // Project-skill state may add a satellite below, but it must never move the
    // version or disturb the paired supports in the main plaque's bottom edge.
    let main_bottom_border = if project_skills > 0 {
        "───────────╥───────╥───────────".to_owned()
    } else {
        "─".repeat(panel_width - 2)
    };
    lines.push(if styled {
        format!("\u{1b}[2m{mounting_rail_bottom} ╰{main_bottom_border}╯\u{1b}[0m")
    } else {
        format!("{mounting_rail_bottom} ╰{main_bottom_border}╯")
    });
    if project_skills > 0 {
        let card_indent = " ".repeat(mounting_rail_top.chars().count() + 1);
        let project_skill_state = format!("{project_skills} on");
        let plain = format!("    Project skills{project_skill_state:>7}");
        let padding = " ".repeat(content_width.saturating_sub(plain.chars().count()));
        // An untitled project-skills satellite plaque attaches directly to the
        // main plaque through paired mixed-weight tee standoffs. Keep both
        // borders synchronized when panel geometry changes.
        lines.push(if styled {
            format!("{card_indent}\u{1b}[2m╭───────────╨───────╨───────────╮\u{1b}[0m")
        } else {
            format!("{card_indent}╭───────────╨───────╨───────────╮")
        });
        lines.push(if styled {
            format!(
                "{card_indent}\u{1b}[2m│\u{1b}[0m     \u{1b}[1mProject skills\u{1b}[0m{project_skill_state:>7}{padding} \u{1b}[2m│\u{1b}[0m"
            )
        } else {
            format!("{card_indent}│ {plain}{padding} │")
        });
        lines.push(if styled {
            format!("{card_indent}\u{1b}[2m╰───────────────────────────────╯\u{1b}[0m")
        } else {
            format!("{card_indent}╰───────────────────────────────╯")
        });
    }
    lines.push(String::new());
    lines
}

pub fn render_claude_preview(project: &Path, selected_global_skills: usize) -> Vec<String> {
    let width = std::env::var("COLUMNS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|width| *width >= 20)
        .unwrap_or(80);
    let interactive = std::io::stderr().is_terminal();
    let plain = !interactive
        || std::env::var_os("NO_COLOR").is_some()
        || std::env::var("TERM").is_ok_and(|term| term.eq_ignore_ascii_case("dumb"));
    render_claude_preview_for(
        project,
        selected_global_skills,
        RenderContext {
            width,
            interactive,
            plain,
        },
    )
}

pub fn render_claude_preview_for(
    project: &Path,
    selected_global_skills: usize,
    context: RenderContext,
) -> Vec<String> {
    let styled = context.interactive && !context.plain;
    let panel_width: usize = 33;
    let content_width = panel_width - 4;
    let title = "CLEAN ROOM";
    let version = concat!("v", env!("CARGO_PKG_VERSION"));
    let mounting_rail_top = "╓──○──╖";
    let mounting_rail_bottom = "╙──○──╜";
    let mounting_rail_fill = "║░░░░░║";
    let standoff_marker = "⠒";
    let mut lines = vec![String::new(), String::new(), String::new()];
    let styled_mounting_rail_top = if styled {
        format!("\u{1b}[2m{mounting_rail_top}\u{1b}[0m")
    } else {
        mounting_rail_top.to_owned()
    };
    lines.push(format!(
        "{styled_mounting_rail_top} {}",
        render_plaque_top(title, version, panel_width, styled)
    ));

    let skill_state = if selected_global_skills == 0 {
        "off".to_owned()
    } else {
        format!("{selected_global_skills} on")
    };
    let status_row = |label: &str, state: &str| {
        let plain = format!("    {label:<16}  {state:>4}");
        let decorated = format!("    \u{1b}[1m{label:<16}\u{1b}[0m  {state:>4}");
        (plain, decorated)
    };
    let rows = vec![
        (String::new(), String::new()),
        status_row("Global instructions", "off"),
        status_row("Global skills", &skill_state),
        status_row("User settings", "off"),
        status_row("Auto memory", "off"),
        (String::new(), String::new()),
    ];
    for (plain, decorated) in rows {
        let padding = " ".repeat(content_width.saturating_sub(plain.chars().count()));
        lines.push(if styled {
            format!(
                "\u{1b}[2m{mounting_rail_fill}{standoff_marker}│\u{1b}[0m {}{padding} \u{1b}[2m│\u{1b}[0m",
                decorated
            )
        } else {
            format!("{mounting_rail_fill}{standoff_marker}│ {plain}{padding} │")
        });
    }

    let project_skills = count_claude_project_skills(project);
    let main_bottom_border = if project_skills > 0 {
        "───────────╥───────╥───────────".to_owned()
    } else {
        "─".repeat(panel_width - 2)
    };
    lines.push(if styled {
        format!("\u{1b}[2m{mounting_rail_bottom} ╰{main_bottom_border}╯\u{1b}[0m")
    } else {
        format!("{mounting_rail_bottom} ╰{main_bottom_border}╯")
    });
    if project_skills > 0 {
        let card_indent = " ".repeat(mounting_rail_top.chars().count() + 1);
        let project_skill_state = format!("{project_skills} on");
        let plain = format!("    Project skills{project_skill_state:>7}");
        let padding = " ".repeat(content_width.saturating_sub(plain.chars().count()));
        lines.push(if styled {
            format!("{card_indent}\u{1b}[2m╭───────────╨───────╨───────────╮\u{1b}[0m")
        } else {
            format!("{card_indent}╭───────────╨───────╨───────────╮")
        });
        lines.push(if styled {
            format!(
                "{card_indent}\u{1b}[2m│\u{1b}[0m     \u{1b}[1mProject skills\u{1b}[0m{project_skill_state:>7}{padding} \u{1b}[2m│\u{1b}[0m"
            )
        } else {
            format!("{card_indent}│ {plain}{padding} │")
        });
        lines.push(if styled {
            format!("{card_indent}\u{1b}[2m╰───────────────────────────────╯\u{1b}[0m")
        } else {
            format!("{card_indent}╰───────────────────────────────╯")
        });
    }
    lines.push(String::new());
    lines
}

fn count_project_skills(project: &Path) -> usize {
    count_project_skills_in(project, ".agents/skills")
}

fn count_claude_project_skills(project: &Path) -> usize {
    count_project_skills_in(project, ".claude/skills")
}

fn count_project_skills_in(project: &Path, relative_root: &str) -> usize {
    let Ok(project) = fs::canonicalize(project) else {
        return 0;
    };
    let Ok(entries) = fs::read_dir(project.join(relative_root)) else {
        return 0;
    };
    entries
        .flatten()
        .filter(|entry| {
            let Ok(skill) = fs::canonicalize(entry.path()) else {
                return false;
            };
            skill.starts_with(&project)
                && fs::metadata(&skill).is_ok_and(|metadata| metadata.is_dir())
                && fs::metadata(skill.join("SKILL.md")).is_ok_and(|metadata| metadata.is_file())
        })
        .count()
}

fn wrap(text: &str, width: usize) -> Vec<String> {
    let mut lines = Vec::new();
    let mut line = String::new();
    for word in text.split_whitespace() {
        let next_len = line.chars().count() + usize::from(!line.is_empty()) + word.chars().count();
        if next_len > width && !line.is_empty() {
            lines.push(line);
            line = word.to_owned();
        } else {
            if !line.is_empty() {
                line.push(' ');
            }
            line.push_str(word);
        }
    }
    if !line.is_empty() {
        lines.push(line);
    }
    lines
}
