use std::process::Command;

fn run(args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_clroom"))
        .args(args)
        .env("HOME", "/tmp/clroom-help-home")
        .env("XDG_CONFIG_HOME", "/tmp/clroom-help-config")
        .output()
        .expect("clroom must run")
}

fn strip_ansi(value: &str) -> String {
    let mut output = String::new();
    let mut chars = value.chars().peekable();
    while let Some(character) = chars.next() {
        if character == '\u{1b}' && chars.peek() == Some(&'[') {
            chars.next();
            for code in chars.by_ref() {
                if code.is_ascii_alphabetic() {
                    break;
                }
            }
        } else {
            output.push(character);
        }
    }
    output
}

fn top_fixture() -> String {
    format!("{}\n", include_str!("../../fixtures/cli/help/top.txt"))
        .replace("{VERSION}", env!("CARGO_PKG_VERSION"))
}

#[test]
fn top_help_aliases_render_the_same_concise_index() {
    // Break caught: help aliases drift or expose a provider-option wall.
    let expected = top_fixture();
    for args in [&["help"][..], &["--help"], &["-h"]] {
        let output = run(args);
        assert_eq!(output.status.code(), Some(0));
        assert_eq!(String::from_utf8(output.stdout).unwrap(), expected);
        assert!(output.stderr.is_empty());
    }
}

#[test]
fn version_flags_report_the_packaged_clroom_version() {
    // Break caught: users cannot identify the installed launcher build, or a
    // version flag is accidentally forwarded to Codex instead of handled here.
    let expected = format!("clroom {}\n", env!("CARGO_PKG_VERSION"));
    for args in [&["--version"][..], &["-V"]] {
        let output = run(args);
        assert_eq!(output.status.code(), Some(0));
        assert_eq!(String::from_utf8(output.stdout).unwrap(), expected);
        assert!(output.stderr.is_empty());
    }
}

#[test]
fn top_help_shows_the_single_skill_set_option_and_resolved_file() {
    // Break caught: users need a second launcher flag or cannot find the one
    // file where reusable @sets are edited.
    let output = run(&["--help"]);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8(output.stdout).unwrap();
    assert!(stdout.contains("--skill-set=any-my-skill,@any-my-skill-set --approve-for-me"));
    assert!(stdout.contains("/tmp/clroom-help-config/clroom/skill-sets.yaml"));
    assert!(stdout.contains("/tmp/clroom-help-config/clroom/presets.yaml"));
    assert!(stdout.contains("clroom --preset=<name> [ARGS...]"));
    assert!(stdout.contains("clroom codex exec") || stdout.contains(
        "Open file and create skill groups and reuse them by name, such as\n  @any-my-skill-set."
    ));
    assert!(stdout.contains("clroom codex exec [CODEX_ARGS...]"));
    assert!(stdout.contains("clroom claude [CLAUDE_ARGS...]"));
    assert!(stdout.contains("clroom claude --with=plugin:<id>"));
    assert!(!stdout.contains("--skills="));
    assert!(output.stderr.is_empty());
}

#[test]
fn tty_help_uses_hierarchy_without_changing_redirected_output() {
    // Break caught: the title, launch command, and reusable sets collapse into
    // the same visual weight or redirected help leaks terminal escapes.
    let styled = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .arg("--help")
        .env("HOME", "/tmp/clroom-help-home")
        .env("XDG_CONFIG_HOME", "/tmp/clroom-help-config")
        .env_remove("NO_COLOR")
        .env("TERM", "xterm-256color")
        .env("CLICOLOR_FORCE", "1")
        .output()
        .expect("clroom must run");
    assert_eq!(styled.status.code(), Some(0));
    let styled = String::from_utf8(styled.stdout).unwrap();
    let expected_prefix = format!(
        "\n\n\u{1b}[1;36mClean Room Launcher\u{1b}[0m \u{1b}[2mv{}\u{1b}[0m\n",
        env!("CARGO_PKG_VERSION")
    );
    assert!(styled.starts_with(&expected_prefix));
    assert!(styled.contains(
        "\u{1b}[2mLaunch Codex or Claude Code without\u{1b}[0m\n\u{1b}[2munrelated global instructions and skills.\u{1b}[0m"
    ));
    assert!(styled.contains("\u{1b}[2mLaunch example:\u{1b}[0m\n\u{1b}[1mclroom codex "));
    assert!(styled.contains("\u{1b}[1mclroom codex "));
    assert!(styled.contains("\u{1b}[1;36m--skill-set=any-my-skill,@any-my-skill-set\u{1b}[0m"));
    assert!(styled.contains(
        "\u{1b}[2m  Open file and create skill groups and reuse them by name, such as\u{1b}[0m\n\u{1b}[2m  \u{1b}[0;36m@any-my-skill-set\u{1b}[0;2m.\u{1b}[0m"
    ));
    assert_eq!(strip_ansi(&styled), top_fixture());

    let plain = run(&["--help"]);
    assert!(!String::from_utf8(plain.stdout).unwrap().contains('\u{1b}'));

    for terminal_guard in [("NO_COLOR", "1"), ("TERM", "dumb")] {
        let guarded = Command::new(env!("CARGO_BIN_EXE_clroom"))
            .arg("--help")
            .env("HOME", "/tmp/clroom-help-home")
            .env("XDG_CONFIG_HOME", "/tmp/clroom-help-config")
            .env_remove("NO_COLOR")
            .env("TERM", "xterm-256color")
            .env("CLICOLOR_FORCE", "1")
            .env(terminal_guard.0, terminal_guard.1)
            .output()
            .expect("clroom must run");
        assert_eq!(guarded.status.code(), Some(0));
        assert!(
            !String::from_utf8(guarded.stdout)
                .unwrap()
                .contains('\u{1b}')
        );
    }
}

#[test]
fn narrow_help_wraps_the_launch_command_at_semantic_boundaries() {
    // Break caught: the primary command splits in the middle of an option or
    // overflows the terminal before users can copy it.
    let output = Command::new(env!("CARGO_BIN_EXE_clroom"))
        .arg("--help")
        .env("HOME", "/tmp/h")
        .env_remove("XDG_CONFIG_HOME")
        .env("COLUMNS", "40")
        .output()
        .expect("clroom must run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8(output.stdout).unwrap();
    assert!(stdout.contains("clroom codex exec") || stdout.contains(
        "clroom codex \\\n  --skill-set=any-my-skill,\\\n@any-my-skill-set \\\n  --approve-for-me"
    ));
    assert!(stdout.lines().all(|line| line.chars().count() <= 40));
}

#[test]
fn skill_set_help_topic_explains_selectors_and_the_editable_yaml_file() {
    // Break caught: top-level help points users toward command help, but the
    // skill-set concept has no actionable destination.
    for topic in ["skill-set", "skill-sets"] {
        let output = run(&["help", topic]);
        assert_eq!(output.status.code(), Some(0));
        let stdout = String::from_utf8(output.stdout).unwrap();
        assert!(
            stdout.contains(
                "clroom <codex|claude> --skill-set=<SKILL_OR_SET>[,...] [PROVIDER_ARGS...]"
            )
        );
        assert!(stdout.contains("/tmp/clroom-help-config/clroom/skill-sets.yaml"));
        assert!(stdout.contains("any-my-skill-set:"));
        assert!(stdout.contains("  - any-my-skill"));
        assert!(stdout.contains("  - any-namespace:any-other-skill"));
        assert!(stdout.contains(
            "clroom codex exec --skill-set=any-my-skill,@any-my-skill-set --approve-for-me"
        ));
        assert!(output.stderr.is_empty());
    }
}

#[test]
fn preset_help_topic_explains_schema_reset_and_provider_inference() {
    for topic in ["preset", "presets"] {
        let output = run(&["help", topic]);
        assert_eq!(output.status.code(), Some(0));
        let stdout = String::from_utf8(output.stdout).unwrap();
        assert!(stdout.contains("clroom <codex|claude> --preset=<NAME>[,...]"));
        assert!(stdout.contains("clroom --preset=<NAME>[,...]"));
        assert!(stdout.contains("/tmp/clroom-help-config/clroom/presets.yaml"));
        assert!(stdout.contains("schema: clroom.presets.v1"));
        assert!(stdout.contains("--preset=none"));
        assert!(stdout.contains("provider args are literal argv elements"));
        assert!(stdout.contains("secret values, scripts, interpolation"));
        assert!(output.stderr.is_empty());
    }
}

#[test]
fn command_help_aliases_render_the_same_inspect_card() {
    // Break caught: `help inspect` and command-suffix help use different contracts.
    let expected = include_str!("../../fixtures/cli/help/inspect.txt");
    for args in [
        &["help", "inspect"][..],
        &["inspect", "--help"],
        &["inspect", "-h"],
    ] {
        let output = run(args);
        assert_eq!(output.status.code(), Some(0));
        assert_eq!(String::from_utf8(output.stdout).unwrap(), expected);
        assert!(output.stderr.is_empty());
    }
}

#[test]
fn command_card_uses_its_own_usage_instead_of_a_skill_placeholder() {
    // Break caught: a generic card tells users to pass `<skill>` to `doctor`.
    let output = run(&["help", "doctor"]);
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(
        String::from_utf8(output.stdout).unwrap(),
        include_str!("../../fixtures/cli/help/doctor.txt")
    );
    assert!(output.stderr.is_empty());
}

#[test]
fn unknown_help_topic_is_stderr_only_and_actionable() {
    // Break caught: unknown help executes a command or loses the smallest safe action.
    let output = run(&["help", "not-a-command"]);
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    assert_eq!(
        String::from_utf8(output.stderr).unwrap(),
        "UNKNOWN_HELP_TOPIC: not-a-command; try \"clroom help\"\n"
    );
}
