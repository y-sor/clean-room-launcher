use std::os::unix::fs::PermissionsExt;

#[test]
fn consolidated_gate_exists_and_is_executable_contract_surface() {
    let path = std::path::Path::new("scripts/gates/p02/verify.sh");
    if !path.exists() {
        let inventory = std::fs::read_to_string("qualification/public-release-inventory-v1.json")
            .expect("public release inventory exists when internal gates are excluded");
        assert!(inventory.contains("\"scripts/gates\""));
        return;
    }
    let metadata = std::fs::metadata(path).expect("P02 gate exists");
    assert!(
        metadata.permissions().mode() & 0o111 != 0,
        "P02 gate executable"
    );
}

#[test]
fn accepted_main_stage_primes_the_full_locked_graph_before_packaging() {
    let stage = std::fs::read_to_string("scripts/release/stage-release.sh").unwrap();
    let release = std::fs::read_to_string(".github/workflows/release.yml").unwrap();

    let fetch = stage
        .find("cargo fetch --locked")
        .expect("pre-tag stage must prime the locked dependency graph");
    let metadata = stage
        .find("cargo metadata")
        .expect("pre-tag stage must generate target-filtered metadata");
    let target = stage
        .find("--filter-platform aarch64-apple-darwin")
        .expect("pre-tag stage must bind the shipping platform");
    let package = stage
        .find("packaging/build-artifacts.sh")
        .expect("pre-tag stage must build the canonical shipping archive");

    assert!(fetch < metadata && metadata < target && target < package);
    assert!(!stage.contains("cargo fetch --locked --target"));
    for forbidden in ["cargo fetch", "cargo build", "packaging/build-artifacts.sh"] {
        assert!(
            !release.contains(forbidden),
            "post-tag Release workflow must not rebuild shipping bytes: {forbidden}"
        );
    }
}

#[test]
fn accepted_main_stage_qualifies_exact_archive_before_tag() {
    let stage = std::fs::read_to_string("scripts/release/stage-release.sh").unwrap();
    let candidate =
        std::fs::read_to_string(".github/workflows/release-candidate.yml").unwrap();
    let release = std::fs::read_to_string(".github/workflows/release.yml").unwrap();
    let provisioner =
        std::fs::read_to_string("scripts/release/provision-provider-canaries.sh").unwrap();
    let verifier =
        std::fs::read_to_string("scripts/release/verify-qualification.py").unwrap();

    for required in [
        "packaging/build-artifacts.sh",
        "tar -xzf \"$artifact\"",
        "codex_candidate=\"$archive_root/bin/clroom-codex\"",
        "claude_candidate=\"$archive_root/bin/clroom-claude\"",
        "scripts/release/qualify-real-provider.sh",
        "scripts/release/verify-qualification.py",
        "local-codex-plugin-activation-smoke.sh stage",
        "--artifact \"$artifact\"",
        "pretag-manifest.json",
        "\"executable_sha256\"",
        "PRETAG_STAGE_PASS",
    ] {
        assert!(stage.contains(required), "missing pre-tag exact-byte gate: {required}");
    }
    assert_eq!(stage.matches("scripts/release/qualify-real-provider.sh").count(), 2);
    assert_eq!(stage.matches("scripts/release/verify-qualification.py").count(), 2);
    assert!(candidate.contains("Rehearse/stage exact release bytes"));
    let stage_step = candidate
        .split("Build and qualify exact future shipping bytes")
        .nth(1)
        .expect("exact-byte stage step must exist");
    assert!(
        stage_step.contains(r#"GITHUB_TOKEN: ${{ github.token }}"#),
        "exact-byte stage must authenticate release-contract GitHub API reads"
    );
    assert!(candidate.contains("pretag-stage-v${{ needs.release-readiness.outputs.version }}-${{ github.event.pull_request.head.sha || github.sha }}"));
    assert!(candidate.contains(
        "./scripts/release/provision-provider-canaries.sh \"$RUNNER_TEMP/clroom-providers\" \"$GITHUB_ENV\""
    ));
    assert!(!release.contains("provision-provider-canaries.sh"));
    assert!(!release.contains("qualify-real-provider.sh"));
    assert!(!release.contains("local-codex-plugin-activation-smoke.sh"));
    assert!(!release.contains("local-plugin-activation-smoke.sh"));
    assert!(!provisioner.contains("npm install"));
    assert!(verifier.contains("record[\"provider_version\"] != expected_provider_version"));
    let stage_verifier =
        std::fs::read_to_string("scripts/release/verify-pretag-stage.py").unwrap();
    assert!(stage_verifier.contains("CODEX_RUNTIME:provider_bytes"));
    assert!(stage_verifier.contains("EXECUTABLE_SHA256"));
}

#[test]
fn codex_runtime_fixture_seeds_only_owned_synthetic_project_trust() {
    let fixture = std::fs::read_to_string("scripts/release/codex-mcp-fixture.py").unwrap();
    assert!(fixture.contains("def seed_synthetic_project_trust("));
    assert!(fixture.contains(r#"init_argv.extend(["mcp", "list", "--json"])"#));
    assert!(fixture.contains(r#".clroom-clean-state-v2"#));
    assert!(fixture.contains(r#".clroom-state-v2"#));
    assert!(fixture.contains(r#"trust_level = "trusted""#));
    assert!(fixture.contains("CLROOM Codex shadow ownership marker missing"));
    assert!(fixture.contains("CLROOM Codex shadow ownership marker invalid"));
    assert!(fixture.contains("if not initialized:"));
    assert!(fixture.contains("stderr=subprocess.PIPE"));
    assert!(fixture.contains("existing CLROOM-owned shadow trust seed failed"));
    assert!(fixture.contains("missing shadow marker did not require bootstrap"));
    assert!(
        !fixture.contains("doyoutrustthecontentsofthisdirectory"),
        "release harness must not scrape or answer the interactive trust UI"
    );
}

#[test]
fn codex_release_harness_uses_one_private_synthetic_auth_fixture() {
    let fixture = std::fs::read_to_string("scripts/release/codex-mcp-fixture.py").unwrap();
    let smoke =
        std::fs::read_to_string("scripts/release/local-codex-plugin-activation-smoke.sh").unwrap();
    let qualifier = std::fs::read_to_string("scripts/release/qualify-real-provider.sh").unwrap();

    for required in [
        r#"SYNTHETIC_AUTH = {"#,
        r#""OPENAI_API_KEY": "clroom-provider-qualification""#,
        r#""tokens": None"#,
        r#""last_refresh": None"#,
        "ensure_synthetic_auth(codex_home)",
        "os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600",
        "synthetic Codex auth fixture conflicts with existing state",
    ] {
        assert!(fixture.contains(required), "shared Codex auth fixture must contain {required}");
    }

    let smoke_install = smoke
        .find(r#"codex-mcp-fixture.py" install"#)
        .expect("pre-merge rehearsal must install the shared Codex fixture");
    let smoke_launch = smoke
        .find(r#""$clroom" --output json info codex"#)
        .expect("pre-merge rehearsal must exercise the exact candidate");
    assert!(smoke_install < smoke_launch, "synthetic auth fixture must exist before the first candidate launch");

    let qualifier_install = qualifier
        .find(r#"codex-mcp-fixture.py" install"#)
        .expect("CI qualifier must install the same shared Codex fixture");
    let qualifier_probe = qualifier
        .find(r#"codex-mcp-fixture.py" probe-provider"#)
        .expect("CI qualifier must exercise the real provider");
    assert!(qualifier_install < qualifier_probe, "CI qualification must seed the shared fixture before provider startup");
    assert!(
        !qualifier.contains(r#"{"OPENAI_API_KEY":"clroom-provider-qualification","tokens":null,"last_refresh":null}"#),
        "the qualifier must not carry a second synthetic-auth payload copy"
    );
}

#[test]
fn codex_real_provider_qualification_requires_repeat_startup_on_one_home() {
    let qualifier = std::fs::read_to_string("scripts/release/qualify-real-provider.sh").unwrap();
    let verifier = std::fs::read_to_string("scripts/release/verify-qualification.py").unwrap();
    let fixture = std::fs::read_to_string("scripts/release/codex-mcp-fixture.py").unwrap();

    assert!(qualifier.contains("real-provider-repeat-interactive-mcp-discovery-no-model"));
    assert!(qualifier.contains("for lifecycle_run in 1 2; do"));
    assert!(qualifier.contains("codex-mcp-fixture.py\" probe-provider"));
    assert!(fixture.contains(r#""TERM": "xterm-256color""#));
    assert!(qualifier.contains("observed_count=$((observed_count + 1))"));
    assert!(qualifier.contains("clroom.real-provider-qualification.v2"));
    assert!(fixture.contains(r#""OPENAI_API_KEY": "clroom-provider-qualification""#));
    assert!(qualifier.contains("repeat_provider_executed"));
    assert!(verifier.contains(r#"record["lifecycle_runs"] != 2"#));
    assert!(verifier.contains(r#"record["repeat_provider_executed"] is not True"#));
}

#[test]
fn codex_runtime_probe_matches_provider_by_file_identity_not_path_string() {
    let fixture =
        std::fs::read_to_string("scripts/release/codex-mcp-fixture.py").unwrap();
    assert!(fixture.contains("def same_executable_identity("));
    assert!(fixture.contains("def process_argv("));
    assert!(fixture.contains("KERN_PROCARGS2"));
    assert!(fixture.contains("def process_uses_provider("));
    assert!(fixture.contains("same_executable_identity(path, provider)"));
    assert!(fixture.contains("same_executable_identity(argument, provider)"));
    assert!(fixture.contains("provider file identity rejected an equivalent path"));
    assert!(fixture.contains("provider file identity accepted unrelated executable"));
    assert!(fixture.contains(
        "provider argv identity missed an interpreter-backed launcher"
    ));
    assert!(fixture.contains(
        "provider argv identity accepted unrelated executable"
    ));
    assert!(
        !fixture.contains("process_path(pid) == provider"),
        "macOS executable proof must not depend on pathname-string equality"
    );
}

#[test]
fn codex_runtime_probe_preserves_lexical_auth_home_identity() {
    let fixture =
        std::fs::read_to_string("scripts/release/codex-mcp-fixture.py").unwrap();
    assert!(fixture.contains("home_path = pathlib.Path(home)"));
    assert!(fixture.contains(r#""HOME": str(home_path)"#));
    assert!(fixture.contains(r#""CODEX_HOME": str(home_path / ".codex")"#));
    assert!(
        !fixture.contains(r#""CODEX_HOME": str((pathlib.Path(home) / ".codex").resolve())"#),
        "runtime fixture must not rewrite macOS /var paths to /private/var after shadow auth references exist"
    );
}

#[test]
fn codex_runtime_probe_uses_protocol_success_not_process_table_as_acceptance() {
    let fixture =
        std::fs::read_to_string("scripts/release/codex-mcp-fixture.py").unwrap();
    assert!(fixture.contains("methods_seen = methods_seen or observed_methods(log)"));
    assert!(fixture.contains(
        r#"CODEX_MCP_PROVIDER_PROBE_PASS provider_process_observer="#
    ));
    assert!(
        !fixture.contains(r#"raise RuntimeError("real Codex provider was not observed")"#),
        "process-table observation is diagnostic only; MCP protocol success is the runtime boundary"
    );
    assert!(fixture.contains("Codex did not reach MCP initialize + tools/list"));
}

#[test]
fn codex_runtime_probe_preserves_fixture_root_blocker() {
    let smoke =
        std::fs::read_to_string("scripts/release/local-codex-plugin-activation-smoke.sh").unwrap();
    assert!(smoke.contains(r#"sed -n 's/^CODEX_MCP_FIXTURE_BLOCKED://p'"#));
    assert!(smoke.contains(r#"2>"$tmp/selected-runtime.err""#));
    assert!(smoke.contains(
        r#"fail_from_stderr "SELECTED_MCP_RUNTIME" "$tmp/selected-runtime.err""#
    ));
    assert!(
        !smoke.contains(r#"|| fail "SELECTED_MCP_RUNTIME""#),
        "runtime fixture failures must preserve the nested canonical reason"
    );
}

#[test]
fn provider_canary_negative_fixture_defers_runtime_argv_expansion() {
    let contract =
        std::fs::read_to_string("scripts/release/check-provider-canary-contract.sh").unwrap();
    assert!(
        contract.contains(r#"if [[ \${1:-} == --version ]]; then"#),
        "fake-provider fixture must preserve positional expansion for fake-provider runtime"
    );
    assert!(
        contract.contains(r#"EARLY_EXIT_STATUS:$status"#),
        "negative fixture failure must expose the unexpected qualifier exit status"
    );
    assert!(
        !contract.contains("python3 -m py_compile"),
        "release contract self-test must not write Python bytecode into the public source tree"
    );
    assert!(
        contract.contains("ast.parse("),
        "Python verifier syntax must be checked without creating __pycache__"
    );
}

#[test]
fn codex_rehearsal_and_stage_close_state_before_tag() {
    let smoke =
        std::fs::read_to_string("scripts/release/local-codex-plugin-activation-smoke.sh").unwrap();
    let stage = std::fs::read_to_string("scripts/release/stage-release.sh").unwrap();
    let verifier = std::fs::read_to_string("scripts/release/verify-pretag-stage.py").unwrap();

    let runtime = smoke
        .find("codex-mcp-fixture.py\" probe-provider")
        .expect("Codex smoke must exercise selected plugin through the real provider");
    let post_runtime = smoke
        .find("POST_RUNTIME_CLEAN_MCP_LIST")
        .expect("Codex smoke must launch clean after the runtime probe");
    let evidence = smoke
        .find("clroom.codex-plugin-release-smoke.v4")
        .expect("Codex evidence schema must remain runtime-aware");
    assert!(runtime < post_runtime && post_runtime < evidence);

    assert!(stage.contains("local-codex-plugin-activation-smoke.sh stage"));
    assert!(stage.contains("codex-stage.json"));
    for required in [
        "\"phase\": \"stage\"",
        "\"real_provider_runtime_confirmed\": True",
        "\"expected_mcp_runtime_healthy_confirmed\": True",
        "\"provider_mcp_initialize_observed\": True",
        "\"provider_mcp_tools_list_observed\": True",
        "\"fixture_mcp_tool_call_passed\": True",
        "\"provider_state_lifecycle_closed\": True",
        "\"post_runtime_clean_confirmed\": True",
        "\"model_prompt_sent\": False",
    ] {
        assert!(verifier.contains(required), "staged runtime verifier missing {required}");
    }
}

#[test]
fn ci_dedupes_branch_pushes_and_does_not_reopen_full_tests_after_tag() {
    let workflow = std::fs::read_to_string(".github/workflows/ci.yml").unwrap();
    assert!(workflow.contains("branches:\n      - main"));
    assert!(workflow.contains("pull_request:"));
    assert!(workflow.contains("cancel-in-progress: true"));
    let trigger = workflow
        .split("concurrency:")
        .next()
        .expect("CI trigger block");
    assert!(!trigger.contains("tags:"), "full CI must not first run after protected tag");
    assert!(!trigger.contains("- \"v*\""));
}

#[test]
fn draft_release_verdict_reconciles_pretag_bytes_and_promotion_only() {
    let verifier = std::fs::read_to_string("scripts/release/verify-draft-release.sh").unwrap();

    for required in [
        "resolve-pretag-stage.sh",
        "verify-pretag-stage.py",
        "verify-claude-stage-evidence.py",
        "run.get(\"name\") == \"Release\"",
        "run.get(\"event\") == \"push\"",
        "DRAFT_BYTE_RECONCILIATION",
        "DRAFT_RELEASE_VERIFY_PASS",
        "immutable-releases",
        "gh attestation verify",
    ] {
        assert!(verifier.contains(required), "pre-publish verifier missing {required}");
    }
    for forbidden in [
        "check-provider-pins.sh",
        "resolve-codex-draft-evidence.sh",
        "local-codex-plugin-activation-smoke.sh",
        "local-plugin-activation-smoke.sh",
        "cargo build",
        "cargo test",
    ] {
        assert!(!verifier.contains(forbidden), "pre-publish must not reopen {forbidden}");
    }
}

#[test]
fn local_tag_helper_parses_annotated_tagger_timestamp_with_digit_regex() {
    let source = std::fs::read_to_string("scripts/release/push-release-tag.sh").unwrap();
    assert!(
        source.contains(r#"match = re.search(r" (\d+) ([+-])(\d{2})(\d{2})$", line)"#),
        "tag helper must parse the real annotated-tagger timestamp format"
    );
    assert!(
        !source.contains(r#"match = re.search(r" (\\d+) ([+-])(\\d{2})(\\d{2})$", line)"#),
        "double-escaped digit classes would match literal backslashes and break the tag gate"
    );
}


#[test]
fn tag_date_binding_is_monotonic_not_exact_day_equality() {
    let checker = std::fs::read_to_string("scripts/release/check-release-contract.py").unwrap();
    let helper = std::fs::read_to_string("scripts/release/push-release-tag.sh").unwrap();
    let workflow = std::fs::read_to_string(".github/workflows/release.yml").unwrap();
    let contract = std::fs::read_to_string("schemas/release/release-contract-v1.json").unwrap();

    assert!(contract.contains(r#""changelog_action_time_relation": "declared_on_or_before_tag""#));
    assert!(contract.contains(r#""candidate_version_relation": "strictly_after_published_baseline""#));
    assert!(contract.contains(r#""changelog_date_floor": "published_baseline_date""#));
    assert!(contract.contains(r#""tag_remote_refresh_order": "after_pretag_stage_before_push""#));
    assert!(checker.contains("validate_changelog_tag_date"));
    assert!(checker.contains("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_LATER_TAG"));
    assert!(checker.contains("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_FUTURE_DECLARATION"));
    assert!(checker.contains("RELEASE_CONTRACT_BLOCKED:CANDIDATE_NOT_ADVANCED"));
    assert!(helper.contains(r#"check-release-contract.py --tag-date "$tag_date""#));
    assert!(!workflow.contains("check-release-contract.py"));
    assert!(!workflow.contains("git ls-remote --symref origin HEAD"));
    assert!(!helper.contains("grep -Fxq \"## [$version] - $tag_date\" CHANGELOG.md"));
}

#[test]
fn release_candidate_models_post_publish_and_active_candidate_lifecycle() {
    let workflow = std::fs::read_to_string(".github/workflows/release-candidate.yml").unwrap();
    let readiness = std::fs::read_to_string("scripts/release/readiness.sh").unwrap();

    assert!(workflow.contains("name: Resolve published release lifecycle"));
    assert!(workflow.contains("scripts/release/resolve-release-lifecycle.py"));
    assert!(workflow.contains("PROVIDER_CANARY_SKIPPED lifecycle=POST_PUBLISH"));
    assert!(
        !workflow.contains("CLROOM_RELEASE_VERSION: 0.4.0"),
        "release-candidate CI must derive the candidate version from Cargo.toml instead of pinning a published version"
    );
    assert!(readiness.contains("RELEASE_LIFECYCLE_SELF_TEST"));
    assert!(readiness.contains("RELEASE_LIFECYCLE_RESOLUTION"));
    assert!(readiness.contains("RELEASE_LIFECYCLE_MISMATCH"));
    assert!(readiness.contains("RELEASE_CONTRACT_SKIPPED lifecycle=POST_PUBLISH"));
    assert!(readiness.contains("if [[ \"$lifecycle\" == \"ACTIVE_CANDIDATE\" ]]; then"));

    let post_publish_exit = readiness
        .find("RELEASE_READINESS_PASS lifecycle=POST_PUBLISH")
        .expect("post-publish readiness must terminate before candidate artifact work");
    let candidate_build = readiness
        .find("./packaging/build-artifacts.sh")
        .expect("active candidates must still build and verify a release artifact");
    assert!(
        post_publish_exit < candidate_build,
        "published-version PRs must not fabricate another candidate artifact for the already-published version"
    );
}

#[test]
fn release_lifecycle_resolver_and_local_audit_are_fail_closed() {
    let resolver = std::fs::read_to_string("scripts/release/resolve-release-lifecycle.py").unwrap();
    let audit = std::fs::read_to_string("scripts/release/local-release-audit.sh").unwrap();

    assert!(resolver.contains("POST_PUBLISH"));
    assert!(resolver.contains("ACTIVE_CANDIDATE"));
    assert!(resolver.contains("CANDIDATE_NOT_ADVANCED"));
    assert!(resolver.contains("RELEASE_LIFECYCLE_SELF_TEST_PASS"));

    assert!(audit.contains("scripts/release/resolve-release-lifecycle.py"));
    assert!(audit.contains("PUBLISHED_BASELINE_NOT_STABLE_IMMUTABLE"));
    assert!(audit.contains("RELEASE_CONTRACT_SKIPPED lifecycle=POST_PUBLISH"));
    let post_publish_pass = audit
        .find("LOCAL_RELEASE_AUDIT_PASS lifecycle=POST_PUBLISH")
        .expect("post-publish local audit must terminate before candidate artifact work");
    let candidate_build = audit
        .find("./packaging/build-artifacts.sh")
        .expect("active candidate local audit must still verify a built artifact");
    assert!(post_publish_pass < candidate_build);
}

#[test]
fn tag_push_requires_complete_stage_then_refreshes_only_mutable_state() {
    let source = std::fs::read_to_string("scripts/release/push-release-tag.sh").unwrap();

    let stage = source
        .find("resolve-pretag-stage.sh")
        .expect("tag helper must resolve the accepted pre-tag stage");
    let claude = source
        .find("verify-claude-stage-evidence.py")
        .expect("tag helper must require exact-stage Claude evidence");
    let final_remote = source
        .find("# Final mutable action-time guard.")
        .expect("tag helper must have a final mutable-state guard");
    let push = source
        .find("git push origin \"refs/tags/$tag\"")
        .expect("tag helper must perform a protected tag push");
    let reconcile = source
        .find("TAG_PUSH_OUTCOME_UNKNOWN:REMOTE_TARGET_NOT_RECONCILED")
        .expect("tag helper must reconcile push outcome");

    assert!(stage < claude && claude < final_remote && final_remote < push && push < reconcile);
    assert_eq!(source.matches("git push origin \"refs/tags/$tag\"").count(), 1);

    for forbidden in [
        "check-provider-pins.sh",
        "resolve-codex-rehearsal-evidence.sh",
        "local-codex-plugin-activation-smoke.sh",
        "local-plugin-activation-smoke.sh",
        "CODEX_PROVIDER_DRIFT_ACTION_TIME",
        "CLAUDE_PROVIDER_DRIFT_ACTION_TIME",
    ] {
        assert!(!source.contains(forbidden), "tag gate must not reopen pre-tag blocker {forbidden}");
    }

    let guard = &source[final_remote..push];
    for required in [
        "git fetch --quiet origin main",
        "MAIN_DRIFT_ACTION_TIME",
        "LOCAL_HEAD_DRIFT_ACTION_TIME",
        "ensure_remote_tag_absent ACTION_TIME",
        "ensure_release_absent ACTION_TIME",
        "verify_required_main_workflows ACTION_TIME",
        "verify_tag_ruleset",
        "verify_immutable_policy ACTION_TIME",
        "check-release-contract.py --tag-date \"$tag_date\" --report",
        "PRETAG_STAGE_BINDING_ACTION_TIME=PASS",
    ] {
        assert!(guard.contains(required), "missing action-time guard: {required}");
    }
    for forbidden in [
        "check-provider-pins.sh",
        "provision-provider-canaries.sh",
        "cargo ",
        "npm ",
        "local-codex-plugin-activation-smoke.sh",
        "local-plugin-activation-smoke.sh",
        "resolve-pretag-stage.sh",
        "verify-pretag-stage.py",
    ] {
        assert!(!guard.contains(forbidden), "final guard must not reopen {forbidden}");
    }
}

#[test]
fn release_review_boundary_is_content_addressed_and_squash_stable() {
    let checker =
        std::fs::read_to_string("scripts/release/check-release-contract.py").unwrap();
    let contract =
        std::fs::read_to_string("docs/release/RELEASE_CONTRACT.md").unwrap();

    for required in [
        "clroom.release-review.v2",
        "LEGACY_REVIEW_ANCESTRY_FIELD",
        "reviewed_content_digest",
        "REVIEW_CONTENT_DRIFT",
        "REVIEW_BINDING=content-addressed",
    ] {
        assert!(
            checker.contains(required),
            "release checker must fail closed on content-addressed review drift: {required}"
        );
    }
    assert!(
        !checker.contains("merge-base\", \"--is-ancestor"),
        "active v2 review acceptance must not retain commit-ancestry enforcement"
    );
    assert!(
        contract.contains("content-addressed, not commit-ancestry-addressed")
            && contract.contains("candidate-tree ==")
            && contract.contains("accepted-tree verification"),
        "release contract must document squash-stable content-addressed acceptance"
    );
}

#[test]
fn claude_release_smoke_rejects_unqualified_plugin_before_model_probe() {
    let source =
        std::fs::read_to_string("scripts/release/local-plugin-activation-smoke.sh").unwrap();

    let preflight = source
        .find("PLUGIN_INFO_PREFLIGHT")
        .expect("Claude release smoke must have a qualification preflight");
    let model_probe = source
        .find("Reply exactly UNUSED.")
        .expect("Claude release smoke automated provider probe must remain explicit");

    assert!(
        preflight < model_probe,
        "plugin qualification must fail closed before any automated model prompt"
    );
    assert!(
        source.contains("PLUGIN_INFO_PREFLIGHT_BLOCKED")
            && source.contains("\"conflicts\"")
            && source.contains("\"kinds\""),
        "preflight failure must preserve sanitized qualification diagnostics"
    );
}

#[test]
fn release_contract_enforces_public_doc_version_coherence() {
    let checker =
        std::fs::read_to_string("scripts/release/check-release-contract.py").unwrap();
    let schema =
        std::fs::read_to_string("schemas/release/release-contract-v1.json").unwrap();
    let docs =
        std::fs::read_to_string("docs/release/RELEASE_CONTRACT.md").unwrap();

    for required in [
        "validate_public_doc_versions",
        "provider_versions_from_pins",
        "PUBLIC_DOC_VERSION_DRIFT",
        "RELEASE_CONTRACT_BLOCKED:PUBLIC_DOC_VERSION_DRIFT",
        "PUBLIC_DOC_VERSION_ALLOWLIST_REASON",
        "docs/providers.md",
    ] {
        assert!(
            checker.contains(required),
            "release checker must retain public-doc version gate: {required}"
        );
    }
    for required in [
        "public_doc_version_inventory",
        "provider_version_source",
        "allowed_noncurrent_provider_versions",
        "allowed_other_versions",
        "historical_exclusions",
        "stale_or_unclassified_version",
    ] {
        assert!(
            schema.contains(required),
            "release schema must retain public-doc version policy: {required}"
        );
    }
    assert!(docs.contains("## Public documentation version coherence"));
    assert!(docs.contains("The release harness never edits documentation after provider tests."));
}

#[test]
fn post_tag_contract_is_allowlisted_not_only_blacklisted() {
    let guard =
        std::fs::read_to_string("scripts/release/check-post-tag-contract.sh").unwrap();
    assert!(guard.contains("POST_TAG_SCRIPT_NOT_ALLOWED"));
    assert!(guard.contains("POST_TAG_HELPER_BLOCKER"));
    assert!(guard.contains("scripts/release/resolve-pretag-stage.sh"));
    assert!(guard.contains("scripts/release/verify-pretag-stage.py"));
    assert!(guard.contains("scripts/release/provider-pins.sh"));
}

#[test]
fn release_runtime_rehearsal_moves_left_and_exact_shipping_bytes_close_before_tag() {
    let claude =
        std::fs::read_to_string("scripts/release/local-plugin-activation-smoke.sh").unwrap();
    let codex =
        std::fs::read_to_string("scripts/release/local-codex-plugin-activation-smoke.sh").unwrap();
    let stage = std::fs::read_to_string("scripts/release/stage-release.sh").unwrap();
    let tag = std::fs::read_to_string("scripts/release/push-release-tag.sh").unwrap();
    let draft = std::fs::read_to_string("scripts/release/verify-draft-release.sh").unwrap();
    let contract =
        std::fs::read_to_string("schemas/release/release-contract-v1.json").unwrap();

    for smoke in [&claude, &codex] {
        assert!(smoke.contains(r#""$phase" == "rehearse" || "$phase" == "stage""#));
        assert!(smoke.contains("HEAD_NOT_EXPECTED_CANDIDATE"));
        assert!(smoke.contains("source_tree"));
        assert!(smoke.contains("reviewed_content_digest"));
        assert!(smoke.contains("content-addressed-runtime-v1"));
        assert!(!smoke.contains(r#""$phase" == "draft""#));
    }
    assert!(stage.contains("local-codex-plugin-activation-smoke.sh stage"));
    assert!(stage.contains("pretag-manifest.json"));
    assert!(tag.contains("resolve-pretag-stage.sh"));
    assert!(tag.contains("verify-claude-stage-evidence.py"));
    assert!(draft.contains("resolve-pretag-stage.sh"));
    assert!(draft.contains("verify-claude-stage-evidence.py"));
    assert!(contract.contains(r#""pretag_blocker_closure": "required""#));
    assert!(contract.contains(r#""post_merge_runtime_role": "accepted_main_exact_shipping_byte_closure_before_tag""#));
    assert!(contract.contains(r#""post_tag_provider_latest_recheck": "forbidden""#));
    assert!(contract.contains(r#""post_tag_role": "tag_bound_attestation_exact_byte_promotion_and_reconciliation_only""#));
}

#[test]
fn codex_release_evidence_uses_actions_before_tag_not_owner_or_draft_runtime() {
    let candidate =
        std::fs::read_to_string(".github/workflows/release-candidate.yml").unwrap();
    let release = std::fs::read_to_string(".github/workflows/release.yml").unwrap();
    let stage = std::fs::read_to_string("scripts/release/stage-release.sh").unwrap();
    let resolver = std::fs::read_to_string("scripts/release/resolve-pretag-stage.sh").unwrap();
    let contract =
        std::fs::read_to_string("schemas/release/release-contract-v1.json").unwrap();
    let release_docs =
        std::fs::read_to_string("docs/release/RELEASE_CONTRACT.md").unwrap();

    assert!(candidate.contains("Rehearse Codex runtime on exact PR candidate"));
    assert!(candidate.contains("local-codex-plugin-activation-smoke.sh rehearse"));
    assert!(candidate.contains("Upload Codex pre-merge rehearsal evidence"));
    assert!(candidate.contains("Rehearse/stage exact release bytes"));
    assert!(stage.contains("local-codex-plugin-activation-smoke.sh stage"));
    assert!(resolver.contains(r#""event": "push""#));
    assert!(resolver.contains(r#""head_branch": "main""#));
    assert!(resolver.contains("SUCCESSFUL_MAIN_STAGE_RUN_NOT_FOUND"));

    assert!(!release.contains("local-codex-plugin-activation-smoke.sh"));
    assert!(!release.contains("verify-codex-draft:"));
    assert!(!release.contains("codex-draft-"));
    assert!(!release.contains("provision-provider-canaries.sh"));

    assert!(contract.contains(
        r#""codex_premerge_rehearsal_transport": "github_actions_macos_content_addressed_artifact""#
    ));
    assert!(contract.contains(
        r#""codex_pretag_stage_transport": "github_actions_macos_accepted_main_exact_archive""#
    ));
    assert!(contract.contains(r#""ambient_local_codex_release_input": "forbidden""#));
    assert!(release_docs.contains("Codex pre-merge and exact-stage evidence"));
}

#[test]
fn immutable_release_policy_is_owner_authenticated_before_tag_and_publish() {
    let claude =
        std::fs::read_to_string("scripts/release/local-plugin-activation-smoke.sh").unwrap();
    let codex =
        std::fs::read_to_string("scripts/release/local-codex-plugin-activation-smoke.sh").unwrap();
    let tag = std::fs::read_to_string("scripts/release/push-release-tag.sh").unwrap();
    let draft = std::fs::read_to_string("scripts/release/verify-draft-release.sh").unwrap();
    let release = std::fs::read_to_string(".github/workflows/release.yml").unwrap();

    assert!(!claude.contains("immutable-releases"));
    assert!(!codex.contains("immutable-releases"));
    assert!(!release.contains("immutable-releases"));
    assert!(tag.contains("repos/y-sor/clean-room-launcher/immutable-releases"));
    assert!(tag.contains("IMMUTABLE_RELEASE_POLICY_UNVERIFIED_$phase"));
    assert!(tag.contains("IMMUTABLE_RELEASE_POLICY_DISABLED_$phase"));
    assert!(draft.contains("repos/$repository/immutable-releases"));
    assert!(draft.contains("IMMUTABLE_RELEASE_POLICY_UNVERIFIED"));
    assert!(draft.contains("IMMUTABLE_RELEASE_POLICY_DISABLED"));
    assert!(draft.contains("TAG_RULESET_PREPUBLISH_PASS"));
    assert!(draft.contains("TAG_RULESET_WEAKENED"));
}

#[test]
fn tag_bound_promotion_binds_cyclonedx_predicate_without_runtime_rerun() {
    let release = std::fs::read_to_string(".github/workflows/release.yml").unwrap();
    let draft = std::fs::read_to_string("scripts/release/verify-draft-release.sh").unwrap();

    for source in [&release, &draft] {
        assert!(source.contains("--predicate-type https://cyclonedx.org/bom"));
        assert!(source.contains("--source-ref"));
    }
    for forbidden in [
        "local-codex-plugin-activation-smoke.sh",
        "local-plugin-activation-smoke.sh",
        "check-provider-pins.sh",
    ] {
        assert!(!release.contains(forbidden));
        assert!(!draft.contains(forbidden));
    }
}

#[test]
fn canonical_readiness_owns_the_draft_release_verifier() {
    let readiness = std::fs::read_to_string("scripts/release/readiness.sh").unwrap();

    assert!(readiness.contains("DRAFT_RELEASE_VERIFY_EXECUTABLE"));
    assert!(readiness.matches("scripts/release/verify-draft-release.sh").count() >= 3);
}

#[test]
fn codex_lifecycle_evidence_is_consumed_by_pretag_stage_not_posttag_runtime() {
    let smoke =
        std::fs::read_to_string("scripts/release/local-codex-plugin-activation-smoke.sh").unwrap();
    let stage = std::fs::read_to_string("scripts/release/stage-release.sh").unwrap();
    let verifier = std::fs::read_to_string("scripts/release/verify-pretag-stage.py").unwrap();
    let release = std::fs::read_to_string(".github/workflows/release.yml").unwrap();

    assert!(smoke.contains("\"ambient_config_and_plugin_tree_unchanged\": True"));
    assert!(!smoke.contains("persistent_provider_state_unchanged"));
    assert!(stage.contains("codex-stage.json"));
    assert!(verifier.contains("\"provider_state_lifecycle_closed\": True"));
    assert!(verifier.contains("\"post_runtime_clean_confirmed\": True"));
    assert!(!release.contains("local-codex-plugin-activation-smoke.sh"));
}

