use std::io::IsTerminal;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Command {
    Guided,
    Provider,
    Generic,
    Info,
    Status,
    Starts,
    Scan,
    Init,
    Prepare,
    Check,
    Explain,
    Inspect,
    Doctor,
    Help,
}

pub struct CommandSpec {
    pub command: Command,
    pub canonical: &'static str,
    pub aliases: &'static [&'static str],
    pub description: &'static str,
    pub usage: &'static str,
    pub example: &'static str,
}

const COMMANDS: &[CommandSpec] = &[
    CommandSpec {
        command: Command::Help,
        canonical: "help",
        aliases: &["--help", "-h"],
        description: "Show concise help",
        usage: "help [COMMAND]",
        example: "help inspect",
    },
    CommandSpec {
        command: Command::Provider,
        canonical: "codex",
        aliases: &[],
        description: "Launch qualified interactive Codex or exec",
        usage: "codex [CODEX_ARGS...]",
        example: "codex --help",
    },
    CommandSpec {
        command: Command::Provider,
        canonical: "claude",
        aliases: &[],
        description: "Launch the installed Claude Code CLI with unchanged arguments",
        usage: "claude [CLAUDE_ARGS...]",
        example: "claude --help",
    },
    CommandSpec {
        command: Command::Info,
        canonical: "info",
        aliases: &[],
        description: "Inspect provider state without launching a model",
        usage: "info <codex|claude> [RESOURCE...]",
        example: "info codex",
    },
    CommandSpec {
        command: Command::Generic,
        canonical: "--",
        aliases: &[],
        description: "Refuse external execution under zero-auth",
        usage: "-- <executable> [ARGS...]",
        example: "-- executable --help",
    },
    CommandSpec {
        command: Command::Status,
        canonical: "status",
        aliases: &[],
        description: "Show current status",
        usage: "status",
        example: "status",
    },
    CommandSpec {
        command: Command::Starts,
        canonical: "starts",
        aliases: &["start"],
        description: "Show saved starts",
        usage: "starts",
        example: "starts",
    },
    CommandSpec {
        command: Command::Scan,
        canonical: "scan",
        aliases: &[],
        description: "Scan local inputs",
        usage: "scan",
        example: "scan",
    },
    CommandSpec {
        command: Command::Init,
        canonical: "init",
        aliases: &[],
        description: "Initialize local setup",
        usage: "init",
        example: "init",
    },
    CommandSpec {
        command: Command::Prepare,
        canonical: "prepare",
        aliases: &[],
        description: "Prepare local context",
        usage: "prepare",
        example: "prepare",
    },
    CommandSpec {
        command: Command::Check,
        canonical: "check",
        aliases: &[],
        description: "Check local context",
        usage: "check",
        example: "check",
    },
    CommandSpec {
        command: Command::Explain,
        canonical: "explain",
        aliases: &[],
        description: "Explain one skill decision",
        usage: "explain <skill>",
        example: "explain skill:rust",
    },
    CommandSpec {
        command: Command::Inspect,
        canonical: "inspect",
        aliases: &[],
        description: "Inspect the resolved Codex launch without starting a model",
        usage: "inspect codex [CODEX_ARGS...]",
        example: "inspect codex --with=plugin:<id> --with=mcp:<id>",
    },
    CommandSpec {
        command: Command::Doctor,
        canonical: "doctor",
        aliases: &[],
        description: "Check installation safely",
        usage: "doctor --root <path>",
        example: "doctor --root .",
    },
];

pub fn resolve(token: &str) -> Option<&'static CommandSpec> {
    COMMANDS
        .iter()
        .find(|spec| spec.canonical == token || spec.aliases.contains(&token))
}

pub fn respond(args: &[String], invoked_as: &str) -> Result<Option<String>, String> {
    let Some(first) = args.first() else {
        return Ok(None);
    };
    if matches!(first.as_str(), "help" | "--help" | "-h") {
        return match args.get(1) {
            None => Ok(Some(top(invoked_as))),
            Some(subject) => card(invoked_as, subject)
                .map(Some)
                .ok_or_else(|| unknown_topic(subject, invoked_as)),
        };
    }
    if args.len() == 2
        && matches!(args[1].as_str(), "--help" | "-h")
        && let Some(spec) = resolve(first)
        && !matches!(spec.command, Command::Provider | Command::Generic)
    {
        return Ok(Some(render_card(invoked_as, spec)));
    }
    Ok(None)
}

pub fn top(invoked_as: &str) -> String {
    let home = std::env::var_os("HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from("$HOME"));
    let skill_sets_path = super::skill_sets::config_path(&home)
        .unwrap_or_else(|_| std::path::PathBuf::from("$HOME/.config/clroom/skill-sets.yaml"));
    let presets_path = super::presets::config_path()
        .unwrap_or_else(|_| std::path::PathBuf::from("$HOME/.config/clroom/presets.yaml"));
    let width = std::env::var("COLUMNS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|width| *width >= 20)
        .unwrap_or(80);
    let force_color =
        std::env::var_os("CLICOLOR_FORCE").is_some_and(|value| value.to_string_lossy() != "0");
    let styled = (std::io::stdout().is_terminal() || force_color)
        && std::env::var_os("NO_COLOR").is_none()
        && !std::env::var("TERM").is_ok_and(|term| term.eq_ignore_ascii_case("dumb"));
    render_top(
        invoked_as,
        &display_skill_sets_path(&skill_sets_path, &home),
        &display_skill_sets_path(&presets_path, &home),
        width,
        styled,
    )
    .join("\n")
}

fn render_top(
    invoked_as: &str,
    skill_sets_path: &str,
    presets_path: &str,
    width: usize,
    styled: bool,
) -> Vec<String> {
    let mut lines = vec![String::new(), String::new()];
    let version = format!("v{}", env!("CARGO_PKG_VERSION"));
    lines.push(if styled {
        format!("\u{1b}[1;36mClean Room Launcher\u{1b}[0m \u{1b}[2m{version}\u{1b}[0m")
    } else {
        format!("Clean Room Launcher {version}")
    });
    for tagline_line in [
        "Launch Codex or Claude Code without",
        "unrelated global instructions and skills.",
    ] {
        lines.extend(styled_wrapped(tagline_line, width, 0, styled, Style::Dim));
    }
    lines.push(String::new());
    lines.extend(styled_wrapped(
        "Launch example:",
        width,
        0,
        styled,
        Style::Dim,
    ));
    lines.extend(primary_command(invoked_as, width, styled));
    lines.push(String::new());
    lines.push(section("Usage", styled));
    lines.extend(usage(
        &format!("{invoked_as} codex [CODEX_ARGS...]"),
        "Qualified interactive Codex",
        width,
        styled,
    ));
    lines.extend(usage(
        &format!("{invoked_as} codex exec [CODEX_ARGS...]"),
        "Qualified non-interactive Codex exec",
        width,
        styled,
    ));
    lines.extend(usage(
        &format!("{invoked_as} claude [CLAUDE_ARGS...]"),
        "Launch Claude Code",
        width,
        styled,
    ));
    lines.extend(usage(
        &format!("{invoked_as} claude --with=plugin:<id>"),
        "Admit one qualified Claude plugin",
        width,
        styled,
    ));
    lines.extend(usage(
        &format!("{invoked_as} --preset=<name> [ARGS...]"),
        "Infer provider from a reusable launch preset",
        width,
        styled,
    ));
    lines.extend(usage(
        &format!("{invoked_as} info codex"),
        "Inspect provider state",
        width,
        styled,
    ));
    lines.extend(styled_wrapped(
        "Launcher options: --preset=name[,name] reuses bounded launch intent; repeat --pass-env=NAME to admit exact existing environment names. Drop-in commands: clroom-codex and clroom-claude.",
        width,
        2,
        styled,
        Style::Dim,
    ));
    lines.extend(usage(
        &format!("{invoked_as} doctor --root ."),
        "Check installation",
        width,
        styled,
    ));
    lines.push(String::new());
    lines.push(section("Skill sets", styled));
    lines.extend(styled_wrapped(
        skill_sets_path,
        width,
        2,
        styled,
        Style::Plain,
    ));
    lines.extend(styled_wrapped(
        "Open file and create skill groups and reuse them by name, such as @any-my-skill-set.",
        width,
        2,
        styled,
        Style::SkillSetNote,
    ));
    lines.push(String::new());
    lines.push(section("Presets", styled));
    lines.extend(styled_wrapped(
        presets_path,
        width,
        2,
        styled,
        Style::Plain,
    ));
    lines.extend(styled_wrapped(
        "Save provider-bounded launch intent once; use --preset=none to bypass user presets.",
        width,
        2,
        styled,
        Style::Dim,
    ));
    lines.push(String::new());
    lines.push(section("More", styled));
    lines.push(format!("  {invoked_as} help <command>"));
    lines.push(String::new());
    lines
}

#[derive(Clone, Copy)]
enum Style {
    Plain,
    Dim,
    SkillSetNote,
}

fn styled_wrapped(
    text: &str,
    width: usize,
    indent: usize,
    styled: bool,
    style: Style,
) -> Vec<String> {
    wrap_words(text, width.saturating_sub(indent).max(1))
        .into_iter()
        .map(|line| {
            let plain = format!("{}{line}", " ".repeat(indent));
            if !styled {
                return plain;
            }
            match style {
                Style::Plain => plain,
                Style::Dim => format!("\u{1b}[2m{plain}\u{1b}[0m"),
                Style::SkillSetNote => format!(
                    "\u{1b}[2m{}\u{1b}[0m",
                    plain.replace(
                        "@any-my-skill-set",
                        "\u{1b}[0;36m@any-my-skill-set\u{1b}[0;2m",
                    )
                ),
            }
        })
        .collect()
}

fn primary_command(invoked_as: &str, width: usize, styled: bool) -> Vec<String> {
    let base = format!("{invoked_as} codex");
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

fn usage(command: &str, description: &str, width: usize, styled: bool) -> Vec<String> {
    let command_column = 27usize.max(command.chars().count() + 1);
    let command_padding = " ".repeat(command_column - command.chars().count());
    let plain = format!("  {command}{command_padding}{description}");
    if plain.chars().count() <= width {
        return vec![if styled {
            format!("  \u{1b}[1m{command}\u{1b}[0m{command_padding}{description}")
        } else {
            plain
        }];
    }
    let mut lines = vec![if styled {
        format!("  \u{1b}[1m{command}\u{1b}[0m")
    } else {
        format!("  {command}")
    }];
    lines.extend(styled_wrapped(
        description,
        width,
        4,
        styled,
        Style::Plain,
    ));
    lines
}

fn section(name: &str, styled: bool) -> String {
    if styled {
        format!("\u{1b}[1m{name}\u{1b}[0m")
    } else {
        name.to_owned()
    }
}

fn display_skill_sets_path(path: &std::path::Path, home: &std::path::Path) -> String {
    path.strip_prefix(home).map_or_else(
        |_| path.display().to_string(),
        |relative| format!("~/{}", relative.display()),
    )
}

fn wrap_words(text: &str, width: usize) -> Vec<String> {
    let mut lines = Vec::new();
    let mut line = String::new();
    for word in text.split_whitespace() {
        let mut chunks = word
            .chars()
            .collect::<Vec<_>>()
            .chunks(width.max(1))
            .map(|chunk| chunk.iter().collect::<String>())
            .collect::<Vec<_>>();
        for chunk in chunks.drain(..) {
            let next = line.chars().count() + usize::from(!line.is_empty()) + chunk.chars().count();
            if next > width && !line.is_empty() {
                lines.push(line);
                line = String::new();
            }
            if !line.is_empty() {
                line.push(' ');
            }
            line.push_str(&chunk);
            if line.chars().count() == width {
                lines.push(line);
                line = String::new();
            }
        }
    }
    if !line.is_empty() {
        lines.push(line);
    }
    lines
}

pub fn card(invoked_as: &str, token: &str) -> Option<String> {
    if matches!(token, "skill-set" | "skill-sets") {
        return Some(render_skill_set_card(invoked_as));
    }
    if matches!(token, "preset" | "presets") {
        return Some(render_preset_card(invoked_as));
    }
    resolve(token).map(|spec| render_card(invoked_as, spec))
}

fn render_skill_set_card(invoked_as: &str) -> String {
    let home = std::env::var_os("HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from("$HOME"));
    let skill_sets_path = super::skill_sets::config_path(&home)
        .unwrap_or_else(|_| std::path::PathBuf::from("$HOME/.config/clroom/skill-sets.yaml"));
    let skill_sets_path = display_skill_sets_path(&skill_sets_path, &home);
    format!(
        "Clean Room Launcher — skill-set\n\nChoose global skills for one clean launch.\nProject-local skills stay available automatically.\n\nUsage:\n  {invoked_as} <codex|claude> --skill-set=<SKILL_OR_SET>[,...] [PROVIDER_ARGS...]\n\nSelectors:\n  any-my-skill                   one global skill\n  any-namespace                 every skill in one namespace\n  any-namespace:any-other-skill one namespaced skill\n  @any-my-skill-set             one reusable group\n\nSkill sets:\n  {skill_sets_path}\n\n  any-my-skill-set:\n    - any-my-skill\n    - any-namespace:any-other-skill\n\nExample:\n  {invoked_as} codex exec --skill-set=any-my-skill,@any-my-skill-set --approve-for-me\n"
    )
}

fn render_preset_card(invoked_as: &str) -> String {
    let home = std::env::var_os("HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from("$HOME"));
    let presets_path = super::presets::config_path()
        .unwrap_or_else(|_| std::path::PathBuf::from("$HOME/.config/clroom/presets.yaml"));
    let presets_path = display_skill_sets_path(&presets_path, &home);
    format!(
        "Clean Room Launcher — preset\n\nReuse one bounded CLROOM launch intent without creating a second provider settings system.\n\nUsage:\n  {invoked_as} <codex|claude> --preset=<NAME>[,...] [PROVIDER_ARGS...]\n  {invoked_as} --preset=<NAME>[,...] [PROVIDER_ARGS...]\n\nReset:\n  {invoked_as} codex --preset=none\n\nPreset file:\n  {presets_path}\n\nSchema:\n  schema: clroom.presets.v1\n  presets:\n    review:\n      default-provider: codex\n      providers:\n        codex: {{}}\n        claude: {{}}\n      skill-set:\n        - @review\n      pass-env:\n        - REVIEW_TOKEN\n\nRules:\n  - default is an ordinary implicit preset when present\n  - none resets preset layers\n  - explicit provider wins; otherwise inference must be unambiguous\n  - provider args are literal argv elements, not shell strings\n  - secret values, scripts, interpolation, and new provider capabilities are not preset features\n"
    )
}

fn render_card(invoked_as: &str, spec: &CommandSpec) -> String {
    let description = if spec.command == Command::Inspect {
        spec.description.to_owned()
    } else {
        format!("{} without changing state", spec.description)
    };
    format!(
        "Clean Room Launcher — {}\n\n{description}.\n\nUsage: {invoked_as} {}\n\nExample:\n  {invoked_as} {}\n\nFor more: {invoked_as} help",
        spec.canonical, spec.usage, spec.example
    )
}

fn unknown_topic(topic: &str, invoked_as: &str) -> String {
    format!("UNKNOWN_HELP_TOPIC: {topic}; try \"{invoked_as} help\"")
}
