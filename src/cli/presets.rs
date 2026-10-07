use std::{
    collections::{BTreeMap, BTreeSet},
    env, fs,
    io::ErrorKind,
    path::{Path, PathBuf},
};

use serde::Deserialize;

use super::{resource_options::Provider, zero_auth};

const CONFIG_RELATIVE_PATH: &str = "clroom/presets.yaml";
const SCHEMA: &str = "clroom.presets.v1";
const MAX_FILE_BYTES: usize = 256 * 1024;
const MAX_PRESETS: usize = 1000;
const MAX_NAME_BYTES: usize = 64;
const MAX_LIST_ITEMS: usize = 128;
const MAX_PROVIDER_ARGS: usize = 256;
const MAX_ARG_BYTES: usize = 4096;
const MAX_SELECTED_PRESETS: usize = 128;
const MAX_RESOLVED_ITEMS: usize = 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Resolution {
    pub provider: Provider,
    pub args: Vec<String>,
    pub presets: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PresetFile {
    schema: String,
    presets: BTreeMap<String, Preset>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Preset {
    #[serde(rename = "default-provider")]
    default_provider: Option<String>,
    providers: BTreeMap<String, ProviderPreset>,
    #[serde(rename = "skill-set", default)]
    skill_set: Vec<String>,
    #[serde(rename = "with", default)]
    with: Vec<String>,
    #[serde(rename = "without", default)]
    without: Vec<String>,
    #[serde(rename = "pass-env", default)]
    pass_env: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProviderPreset {
    #[serde(default)]
    args: Vec<String>,
}

#[derive(Debug)]
struct Selection {
    requested: Option<Vec<String>>,
    remaining_args: Vec<String>,
}

pub fn apply(provider: Option<Provider>, args: &[String]) -> Result<Resolution, String> {
    let selection = extract_selection(args)?;
    if selection
        .requested
        .as_ref()
        .is_some_and(|terms| terms.len() == 1 && terms[0] == "none")
    {
        let provider = provider.ok_or_else(provider_required)?;
        return Ok(Resolution {
            provider,
            args: selection.remaining_args,
            presets: Vec::new(),
        });
    }

    let explicit_requested = selection.requested.is_some();
    let path = match config_path() {
        Ok(path) => path,
        Err(_) if !explicit_requested => {
            let provider = provider.ok_or_else(provider_required)?;
            return Ok(Resolution {
                provider,
                args: selection.remaining_args,
                presets: Vec::new(),
            });
        }
        Err(error) => return Err(error),
    };
    let config = load_optional(&path)?;

    let Some(config) = config else {
        if explicit_requested {
            return Err(format!(
                "CLROOM_PRESET_CONFIG_UNAVAILABLE: preset file is unavailable at {}; create it or use --preset=none",
                path.display()
            ));
        }
        let provider = provider.ok_or_else(provider_required)?;
        return Ok(Resolution {
            provider,
            args: selection.remaining_args,
            presets: Vec::new(),
        });
    };

    validate_config(&config, &path)?;
    let selected = select_names(&config, selection.requested.as_deref())?;
    if selected.is_empty() {
        let provider = provider.ok_or_else(provider_required)?;
        return Ok(Resolution {
            provider,
            args: selection.remaining_args,
            presets: Vec::new(),
        });
    }
    if selected.len() > MAX_SELECTED_PRESETS {
        return Err(resolution_too_large());
    }

    let permitted = permitted_providers(&config, &selected)?;
    let resolved_provider = match provider {
        Some(provider) => {
            if !permitted.contains(&provider.id()) {
                return Err(format!(
                    "CLROOM_PRESET_PROVIDER_UNAVAILABLE: selected presets do not permit {}; choose a compatible provider or use --preset=none",
                    provider.id()
                ));
            }
            provider
        }
        None => infer_provider(&config, &selected, &permitted)?,
    };

    let has_explicit_skill_set = has_explicit_skill_set(&selection.remaining_args);
    let explicit_resource_overrides = explicit_resource_overrides(&selection.remaining_args);
    let mut synthetic = Vec::new();
    let mut preset_skills = Vec::new();
    let mut preset_resources = BTreeMap::<String, bool>::new();
    let mut provider_args = Vec::new();

    for name in &selected {
        let preset = config
            .presets
            .get(name)
            .expect("validated selected preset must exist");
        preset_skills.extend(preset.skill_set.iter().cloned());
        apply_resource_layer(&mut preset_resources, &preset.with, true);
        apply_resource_layer(&mut preset_resources, &preset.without, false);
        synthetic.extend(
            preset
                .pass_env
                .iter()
                .map(|value| format!("--pass-env={value}")),
        );
        provider_args.extend(
            preset
                .providers
                .get(resolved_provider.id())
                .expect("provider intersection already validated")
                .args
                .iter()
                .cloned(),
        );
        if preset_skills.len() > MAX_RESOLVED_ITEMS
            || preset_resources.len() > MAX_RESOLVED_ITEMS
            || synthetic.len() > MAX_RESOLVED_ITEMS
            || provider_args.len() > MAX_RESOLVED_ITEMS
        {
            return Err(resolution_too_large());
        }
    }

    for value in explicit_resource_overrides {
        preset_resources.remove(&value);
    }
    synthetic.extend(preset_resources.into_iter().map(|(value, included)| {
        if included {
            format!("--with={value}")
        } else {
            format!("--without={value}")
        }
    }));

    if !preset_skills.is_empty() && !has_explicit_skill_set {
        synthetic.push(format!("--skill-set={}", preset_skills.join(",")));
    }
    synthetic.extend(provider_args);
    synthetic.extend(selection.remaining_args);

    Ok(Resolution {
        provider: resolved_provider,
        args: synthetic,
        presets: selected,
    })
}

pub fn config_path() -> Result<PathBuf, String> {
    let base = match env::var_os("XDG_CONFIG_HOME").filter(|value| !value.is_empty()) {
        Some(value) => {
            let path = PathBuf::from(value);
            if !path.is_absolute() {
                return Err(
                    "CLROOM_PRESET_CONFIG_PATH_INVALID: preset config root is unavailable"
                        .to_owned(),
                );
            }
            path
        }
        None => {
            let home = env::var_os("HOME").ok_or_else(|| {
                "CLROOM_PRESET_CONFIG_PATH_INVALID: HOME is unavailable and XDG_CONFIG_HOME is not set"
                    .to_owned()
            })?;
            PathBuf::from(home).join(".config")
        }
    };
    if !base.is_absolute() {
        return Err(
            "CLROOM_PRESET_CONFIG_PATH_INVALID: preset config root is unavailable".to_owned(),
        );
    }
    Ok(base.join(CONFIG_RELATIVE_PATH))
}

fn extract_selection(args: &[String]) -> Result<Selection, String> {
    let mut requested = None;
    let mut remaining_args = Vec::with_capacity(args.len());
    let mut launcher_options = true;
    for argument in args {
        if launcher_options && argument == "--" {
            launcher_options = false;
            remaining_args.push(argument.clone());
        } else if launcher_options && argument == "--preset" {
            return Err(
                "CLROOM_PRESET_SELECTOR_INVALID: use --preset=name[,name] or --preset=none"
                    .to_owned(),
            );
        } else if launcher_options && let Some(value) = argument.strip_prefix("--preset=") {
            if requested.is_some() || value.is_empty() {
                return Err(
                    "CLROOM_PRESET_SELECTOR_INVALID: use one --preset=name[,name] option"
                        .to_owned(),
                );
            }
            let terms = value.split(',').map(str::to_owned).collect::<Vec<_>>();
            if terms.iter().any(|term| term.is_empty()) {
                return Err(
                    "CLROOM_PRESET_SELECTOR_INVALID: preset names must be non-empty".to_owned(),
                );
            }
            requested = Some(terms);
        } else {
            remaining_args.push(argument.clone());
        }
    }
    Ok(Selection {
        requested,
        remaining_args,
    })
}

fn load_optional(path: &Path) -> Result<Option<PresetFile>, String> {
    let metadata = match fs::metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(config_unavailable(path)),
    };
    if !metadata.is_file() || metadata.len() > MAX_FILE_BYTES as u64 {
        return Err(config_invalid(path));
    }
    let bytes = fs::read(path).map_err(|_| config_unavailable(path))?;
    if bytes.len() > MAX_FILE_BYTES {
        return Err(config_invalid(path));
    }
    let config =
        serde_yaml::from_slice::<PresetFile>(&bytes).map_err(|_| config_invalid(path))?;
    Ok(Some(config))
}

fn validate_config(config: &PresetFile, path: &Path) -> Result<(), String> {
    if config.schema != SCHEMA || config.presets.len() > MAX_PRESETS {
        return Err(config_invalid(path));
    }
    for (name, preset) in &config.presets {
        if !valid_name(name) || name == "none" || preset.providers.is_empty() {
            return Err(config_invalid(path));
        }
        validate_list(&preset.skill_set, path)?;
        validate_list(&preset.with, path)?;
        validate_list(&preset.without, path)?;
        validate_list(&preset.pass_env, path)?;
        if preset.pass_env.iter().any(|name| !valid_pass_env_name(name)) {
            return Err(config_invalid(path));
        }

        let mut provider_ids = BTreeSet::new();
        for (provider, overlay) in &preset.providers {
            let Some(parsed) = Provider::parse(provider) else {
                return Err(config_invalid(path));
            };
            provider_ids.insert(parsed.id());
            if overlay.args.len() > MAX_PROVIDER_ARGS {
                return Err(config_invalid(path));
            }
            for argument in &overlay.args {
                validate_provider_arg(argument, path)?;
            }
        }
        if let Some(default_provider) = preset.default_provider.as_deref() {
            let Some(default_provider) = Provider::parse(default_provider) else {
                return Err(config_invalid(path));
            };
            if !provider_ids.contains(default_provider.id()) {
                return Err(config_invalid(path));
            }
        }
    }
    Ok(())
}

fn validate_list(values: &[String], path: &Path) -> Result<(), String> {
    if values.len() > MAX_LIST_ITEMS
        || values
            .iter()
            .any(|value| value.is_empty() || value.len() > MAX_ARG_BYTES)
    {
        return Err(config_invalid(path));
    }
    Ok(())
}

fn validate_provider_arg(argument: &str, path: &Path) -> Result<(), String> {
    if argument.len() > MAX_ARG_BYTES
        || argument.as_bytes().contains(&0)
        || argument == "--"
        || zero_auth::is_sensitive_argument(argument)
        || matches!(argument.as_str(), "auth" | "login" | "logout")
        || [
            "--preset",
            "--with",
            "--without",
            "--skill-set",
            "--pass-env",
        ]
        .iter()
        .any(|owned| argument == *owned || argument.starts_with(&format!("{owned}=")))
    {
        return Err(config_invalid(path));
    }
    Ok(())
}

fn select_names(config: &PresetFile, requested: Option<&[String]>) -> Result<Vec<String>, String> {
    let mut selected = Vec::new();
    let mut seen = BTreeSet::new();
    if config.presets.contains_key("default") {
        selected.push("default".to_owned());
        seen.insert("default".to_owned());
    }

    if let Some(requested) = requested {
        for term in requested {
            if term == "none" {
                selected.clear();
                seen.clear();
                continue;
            }
            if !valid_name(term) || !config.presets.contains_key(term) {
                return Err(format!(
                    "CLROOM_PRESET_UNKNOWN: unknown preset '{term}'; choose a configured preset or use --preset=none"
                ));
            }
            if !seen.insert(term.clone()) {
                return Err(format!(
                    "CLROOM_PRESET_SELECTOR_INVALID: preset '{term}' is selected more than once"
                ));
            }
            selected.push(term.clone());
        }
    }
    Ok(selected)
}

fn permitted_providers(
    config: &PresetFile,
    selected: &[String],
) -> Result<BTreeSet<&'static str>, String> {
    let mut permitted = ["codex", "claude"].into_iter().collect::<BTreeSet<_>>();
    for name in selected {
        let preset = config
            .presets
            .get(name)
            .expect("selected preset already validated");
        let current = preset
            .providers
            .keys()
            .filter_map(|provider| Provider::parse(provider).map(Provider::id))
            .collect::<BTreeSet<_>>();
        permitted = permitted
            .intersection(&current)
            .copied()
            .collect::<BTreeSet<_>>();
    }
    if permitted.is_empty() {
        return Err(
            "CLROOM_PRESET_PROVIDER_AMBIGUOUS: selected presets share no supported provider"
                .to_owned(),
        );
    }
    Ok(permitted)
}

fn infer_provider(
    config: &PresetFile,
    selected: &[String],
    permitted: &BTreeSet<&'static str>,
) -> Result<Provider, String> {
    let defaults = selected
        .iter()
        .filter_map(|name| {
            config
                .presets
                .get(name)
                .and_then(|preset| preset.default_provider.as_deref())
        })
        .collect::<BTreeSet<_>>();
    if defaults.len() > 1 {
        return Err(
            "CLROOM_PRESET_PROVIDER_AMBIGUOUS: selected presets declare conflicting default providers"
                .to_owned(),
        );
    }
    if let Some(value) = defaults.first() {
        let provider = Provider::parse(value).expect("validated default provider");
        if !permitted.contains(provider.id()) {
            return Err(
                "CLROOM_PRESET_PROVIDER_AMBIGUOUS: selected preset defaults are incompatible with their provider set"
                    .to_owned(),
            );
        }
        return Ok(provider);
    }
    if permitted.len() == 1 {
        return Ok(Provider::parse(permitted.first().expect("one provider"))
            .expect("validated provider"));
    }
    Err(provider_required())
}

fn apply_resource_layer(
    decisions: &mut BTreeMap<String, bool>,
    values: &[String],
    included: bool,
) {
    for value in values {
        for member in resource_selector_members(value) {
            decisions.insert(member, included);
        }
    }
}

fn resource_selector_members(value: &str) -> Vec<String> {
    let Some((kind, members)) = value.split_once(':') else {
        return vec![value.to_owned()];
    };
    if !matches!(kind, "plugin" | "mcp") || members.is_empty() {
        return vec![value.to_owned()];
    }
    let members = members.split(',').collect::<Vec<_>>();
    if members.iter().any(|member| member.is_empty()) {
        return vec![value.to_owned()];
    }
    members
        .into_iter()
        .map(|member| format!("{kind}:{member}"))
        .collect()
}

fn explicit_resource_overrides(args: &[String]) -> BTreeSet<String> {
    let mut values = BTreeSet::new();
    let mut launcher_options = true;
    for argument in args {
        if launcher_options && argument == "--" {
            launcher_options = false;
        } else if launcher_options {
            if let Some(value) = argument.strip_prefix("--with=") {
                values.extend(resource_selector_members(value));
            } else if let Some(value) = argument.strip_prefix("--without=") {
                values.extend(resource_selector_members(value));
            }
        }
    }
    values
}

fn has_explicit_skill_set(args: &[String]) -> bool {
    let mut launcher_options = true;
    for argument in args {
        if launcher_options && argument == "--" {
            launcher_options = false;
        } else if launcher_options
            && (argument == "--skill-set" || argument.starts_with("--skill-set="))
        {
            return true;
        }
    }
    false
}

fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= MAX_NAME_BYTES
        && name.chars().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.')
        })
}

fn valid_pass_env_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 128
        && name.bytes().enumerate().all(|(index, byte)| {
            (byte.is_ascii_uppercase() || byte == b'_') || (index > 0 && byte.is_ascii_digit())
        })
}

fn resolution_too_large() -> String {
    "CLROOM_PRESET_RESOLUTION_TOO_LARGE: selected preset composition exceeds the bounded launch budget; select fewer presets or reduce preset contents"
        .to_owned()
}

fn provider_required() -> String {
    "CLROOM_PRESET_PROVIDER_REQUIRED: selected presets do not identify one provider; use clroom <codex|claude> --preset=... or add an unambiguous default-provider"
        .to_owned()
}

fn config_unavailable(path: &Path) -> String {
    format!(
        "CLROOM_PRESET_CONFIG_UNAVAILABLE: preset file is unavailable at {}; continue locally",
        path.display()
    )
}

fn config_invalid(path: &Path) -> String {
    format!(
        "CLROOM_PRESET_CONFIG_INVALID: preset file is invalid at {}; continue locally",
        path.display()
    )
}

#[cfg(test)]
mod tests {
    use std::{collections::{BTreeMap, BTreeSet}, path::Path};

    use super::{
        apply_resource_layer, explicit_resource_overrides, extract_selection,
        has_explicit_skill_set, infer_provider, permitted_providers, resource_selector_members,
        select_names, valid_name, valid_pass_env_name, validate_config, PresetFile, Provider,
    };

    fn config(input: &str) -> PresetFile {
        serde_yaml::from_str(input).unwrap()
    }

    fn valid_fixture() -> PresetFile {
        config(
            r#"schema: clroom.presets.v1
presets:
  default:
    default-provider: codex
    providers:
      codex: {}
      claude: {}
    skill-set: [review]
    pass-env: [REVIEW_TOKEN]
  job:
    providers:
      codex:
        args: [--model, gpt-5]
      claude:
        args: [--model, sonnet]
    with: [plugin:review-tools@team]
"#,
        )
    }

    #[test]
    fn selector_is_launcher_owned_only_before_provider_terminator() {
        let args = ["--preset=job", "--", "--preset=literal"]
            .map(str::to_owned)
            .to_vec();
        let selection = extract_selection(&args).unwrap();
        assert_eq!(selection.requested.unwrap(), vec!["job"]);
        assert_eq!(selection.remaining_args, ["--", "--preset=literal"]);
    }

    #[test]
    fn explicit_resource_controls_override_preset_layer_by_exact_selector() {
        let values = explicit_resource_overrides(&[
            "--with=plugin:review@team".to_owned(),
            "--without=mcp:debug".to_owned(),
            "--".to_owned(),
            "--with=plugin:literal".to_owned(),
        ]);
        assert_eq!(
            values,
            BTreeSet::from([
                "mcp:debug".to_owned(),
                "plugin:review@team".to_owned(),
            ])
        );
    }

    #[test]
    fn grouped_resource_selectors_are_normalized_to_exact_members() {
        assert_eq!(
            resource_selector_members("plugin:review@team,test@team"),
            vec!["plugin:review@team", "plugin:test@team"]
        );
        assert_eq!(
            resource_selector_members("mcp:review,debug"),
            vec!["mcp:review", "mcp:debug"]
        );
    }

    #[test]
    fn later_resource_layer_overrides_one_member_of_an_earlier_group() {
        let mut decisions = BTreeMap::new();
        apply_resource_layer(
            &mut decisions,
            &["plugin:review@team,test@team".to_owned()],
            false,
        );
        apply_resource_layer(
            &mut decisions,
            &["plugin:review@team".to_owned()],
            true,
        );
        assert_eq!(decisions.get("plugin:review@team"), Some(&true));
        assert_eq!(decisions.get("plugin:test@team"), Some(&false));
    }

    #[test]
    fn explicit_grouped_resource_control_overrides_each_preset_member() {
        let values = explicit_resource_overrides(&[
            "--with=plugin:review@team,test@team".to_owned(),
            "--without=mcp:debug,trace".to_owned(),
        ]);
        assert_eq!(
            values,
            BTreeSet::from([
                "mcp:debug".to_owned(),
                "mcp:trace".to_owned(),
                "plugin:review@team".to_owned(),
                "plugin:test@team".to_owned(),
            ])
        );
    }

    #[test]
    fn explicit_skill_set_detection_stops_at_provider_terminator() {
        assert!(has_explicit_skill_set(&[
            "--skill-set=review".to_owned(),
            "--".to_owned(),
        ]));
        assert!(!has_explicit_skill_set(&[
            "--".to_owned(),
            "--skill-set=literal".to_owned(),
        ]));
    }

    #[test]
    fn preset_names_are_bounded_and_portable() {
        assert!(valid_name("job.review-1"));
        assert!(!valid_name(""));
        assert!(!valid_name("bad/name"));
        assert!(!valid_name(&"x".repeat(65)));
    }

    #[test]
    fn environment_names_use_the_same_closed_identifier_shape_as_cli_admission() {
        assert!(valid_pass_env_name("REVIEW_TOKEN"));
        assert!(valid_pass_env_name("_PRIVATE_2"));
        for invalid in ["", "lowercase", "HAS-DASH", "9STARTS_WITH_DIGIT"] {
            assert!(!valid_pass_env_name(invalid), "{invalid}");
        }
    }

    #[test]
    fn strict_schema_accepts_bounded_launch_intent() {
        let value = valid_fixture();
        validate_config(&value, Path::new("/tmp/presets.yaml")).unwrap();
    }

    #[test]
    fn strict_schema_rejects_unknown_fields_and_unknown_providers() {
        let unknown_field = serde_yaml::from_str::<PresetFile>(
            r#"schema: clroom.presets.v1
presets:
  job:
    providers:
      codex: {}
    shell: "echo unsafe"
"#,
        );
        assert!(unknown_field.is_err());

        let unknown_provider = config(
            r#"schema: clroom.presets.v1
presets:
  job:
    providers:
      future-agent: {}
"#,
        );
        assert!(validate_config(&unknown_provider, Path::new("/tmp/presets.yaml")).is_err());
    }

    #[test]
    fn preset_provider_args_cannot_smuggle_secrets_or_clroom_controls() {
        for argument in [
            "--api-key=secret",
            "token=secret",
            "auth",
            "login",
            "logout",
            "--preset=other",
            "--with=mcp:other",
            "--without=plugin:other",
            "--skill-set=other",
            "--pass-env=SECRET",
            "--",
        ] {
            let value = config(&format!(
                "schema: clroom.presets.v1\npresets:\n  job:\n    providers:\n      codex:\n        args:\n          - {argument:?}\n"
            ));
            assert!(
                validate_config(&value, Path::new("/tmp/presets.yaml")).is_err(),
                "{argument}"
            );
        }
    }

    #[test]
    fn none_resets_implicit_and_earlier_presets() {
        let value = valid_fixture();
        assert_eq!(
            select_names(
                &value,
                Some(&["job".to_owned(), "none".to_owned(), "job".to_owned()])
            )
            .unwrap(),
            vec!["job"]
        );
    }

    #[test]
    fn provider_resolution_uses_intersection_not_union() {
        let value = config(
            r#"schema: clroom.presets.v1
presets:
  default:
    providers:
      codex: {}
      claude: {}
  codex-only:
    providers:
      codex: {}
"#,
        );
        validate_config(&value, Path::new("/tmp/presets.yaml")).unwrap();
        let selected =
            select_names(&value, Some(&["codex-only".to_owned()])).unwrap();
        let permitted = permitted_providers(&value, &selected).unwrap();
        assert_eq!(permitted, BTreeSet::from(["codex"]));
        assert_eq!(
            infer_provider(&value, &selected, &permitted).unwrap(),
            Provider::Codex
        );
    }

    #[test]
    fn conflicting_default_providers_fail_closed() {
        let value = config(
            r#"schema: clroom.presets.v1
presets:
  default:
    default-provider: codex
    providers:
      codex: {}
      claude: {}
  review:
    default-provider: claude
    providers:
      codex: {}
      claude: {}
"#,
        );
        validate_config(&value, Path::new("/tmp/presets.yaml")).unwrap();
        let selected = select_names(&value, Some(&["review".to_owned()])).unwrap();
        let permitted = permitted_providers(&value, &selected).unwrap();
        assert!(infer_provider(&value, &selected, &permitted).is_err());
    }
}
