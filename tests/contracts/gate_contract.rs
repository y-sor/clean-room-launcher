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
fn tag_release_primes_the_full_locked_graph_before_offline_notice_packaging() {
    let source = std::fs::read_to_string(".github/workflows/release.yml").unwrap();
    let fetch = source
        .find("cargo fetch --locked")
        .expect("release workflow must prime the full locked dependency graph");
    let offline_probe = source
        .find("cargo metadata --locked --offline --format-version 1 >/dev/null")
        .expect("release workflow must prove the full graph is available offline");
    let target_metadata = source
        .find("--filter-platform aarch64-apple-darwin")
        .expect("release workflow must keep the target-filtered SBOM metadata");
    let package = source
        .find("./packaging/build-artifacts.sh target/release-artifacts")
        .expect("release workflow must invoke the canonical artifact builder");

    assert!(
        fetch < offline_probe && offline_probe < target_metadata && target_metadata < package,
        "full-graph prefetch and offline proof must precede NOTICE packaging"
    );
    assert!(
        !source.contains("cargo fetch --locked --target"),
        "target-scoped fetch cannot satisfy the full locked NOTICE census"
    );
}

#[test]
fn tag_release_qualifies_the_exact_archive_before_upload() {
    let source = std::fs::read_to_string(".github/workflows/release.yml").unwrap();
    let provisioner =
        std::fs::read_to_string("scripts/release/provision-provider-canaries.sh").unwrap();
    let package = source
        .find("./packaging/build-artifacts.sh target/release-artifacts")
        .expect("release workflow must build the canonical archive");
    let provision = source
        .find("name: Provision pinned real provider canaries")
        .expect("release workflow must provision pinned real providers");
    let qualify = source
        .find("name: Qualify exact release archive with real providers")
        .expect("release workflow must qualify the exact release archive");
    let upload = source
        .find("name: Upload verified release bundle")
        .expect("release workflow must upload the verified release bundle");

    assert!(
        package < provision && provision < qualify && qualify < upload,
        "exact-byte provider qualification must happen after packaging and before upload"
    );
    let release_version_guard = format!(
        "test \"$CLROOM_RELEASE_VERSION\" = \"{}\"",
        env!("CARGO_PKG_VERSION")
    );
    assert!(
        source.contains(&release_version_guard),
        "provider qualification pins must fail closed unless explicitly reviewed for the packaged release version"
    );
    assert!(source.contains(
        "./scripts/release/provision-provider-canaries.sh \"$RUNNER_TEMP/clroom-providers\" \"$GITHUB_ENV\""
    ));
    let provider_pins =
        std::fs::read_to_string("scripts/release/provider-pins.sh").unwrap();
    assert!(!source.contains("npm install"));
    assert!(provisioner.contains("source \"$root/scripts/release/provider-pins.sh\""));
    assert!(provisioner.contains("bash \"$root/scripts/release/check-provider-pins.sh\""));
    for required in [
        "CODEX_VERSION=0.156.0",
        "CLAUDE_VERSION=2.1.280",
        "CODEX_SHA512=",
        "CODEX_PLATFORM_SHA512=",
        "CLAUDE_SHA512=",
        "CLAUDE_PLATFORM_SHA512=",
    ] {
        assert!(
            provider_pins.contains(required),
            "release provider pins must contain {required}"
        );
    }
    for required in [
        "\"@openai/codex@$CODEX_VERSION\"",
        "\"@openai/codex@$CODEX_VERSION-darwin-arm64\"",
        "\"@anthropic-ai/claude-code@$CLAUDE_VERSION\"",
        "\"@anthropic-ai/claude-code-darwin-arm64@$CLAUDE_VERSION\"",
        "\"$CODEX_SHA512\"",
        "\"$CODEX_PLATFORM_SHA512\"",
        "\"$CLAUDE_SHA512\"",
        "\"$CLAUDE_PLATFORM_SHA512\"",
    ] {
        assert!(
            provisioner.contains(required),
            "provider canary provisioning must consume canonical pin {required}"
        );
    }
    assert!(!provisioner.contains("npm install"));
    assert!(
        source.contains("tar -xzf \"$artifact\" -C \"$extract_dir\""),
        "provider qualification must extract the exact packaged archive"
    );
    assert!(source.contains("codex_candidate=\"$archive_root/bin/clroom-codex\""));
    assert!(source.contains("claude_candidate=\"$archive_root/bin/clroom-claude\""));
    assert!(
        !source.contains("codex_candidate=\"target/aarch64-apple-darwin/release/clroom-codex\"")
            && !source.contains(
                "claude_candidate=\"target/aarch64-apple-darwin/release/clroom-claude\""
            ),
        "release qualification must not fall back to sibling build outputs"
    );
    assert_eq!(
        source.matches("scripts/release/qualify-real-provider.sh").count(),
        2,
        "both qualified providers must execute against the archive-extracted binaries"
    );
    assert_eq!(
        source.matches("scripts/release/verify-qualification.py").count(),
        2,
        "both qualification records must be rebound to the exact release archive"
    );
    assert!(
        source.contains(
            "\"$GITHUB_SHA\" \"$CLROOM_RELEASE_VERSION\" codex \"$CLROOM_PROVIDER_CODEX_VERSION\""
        ),
        "Codex archive evidence verification must consume the canonical pinned provider version"
    );
    assert!(
        source.contains(
            "\"$GITHUB_SHA\" \"$CLROOM_RELEASE_VERSION\" claude \"$CLROOM_PROVIDER_CLAUDE_VERSION\""
        ),
        "Claude archive evidence verification must consume the canonical pinned provider version"
    );
    let verifier =
        std::fs::read_to_string("scripts/release/verify-qualification.py").unwrap();
    assert!(
        verifier.contains("record[\"provider_version\"] != expected_provider_version"),
        "qualification verifier must compare evidence to its explicit pinned provider version"
    );
    assert!(
        !verifier.contains("\"0.154.0\"") && !verifier.contains("\"2.1.272\""),
        "qualification verifier must not keep a second stale copy of provider pins"
    );
    assert!(
        verifier.contains(r#"r"[0-9]+\.[0-9]+\.[0-9]+""#),
        "qualification verifier must accept ordinary three-part semantic versions"
    );
    assert!(
        !verifier.contains(r#"r"[0-9]+\\.[0-9]+\\.[0-9]+""#),
        "qualification verifier must not double-escape semantic-version separators"
    );
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
fn codex_rehearsal_smoke_closes_state_after_runtime_probe() {
    let smoke =
        std::fs::read_to_string("scripts/release/local-codex-plugin-activation-smoke.sh").unwrap();
    let stage =
        std::fs::read_to_string("scripts/release/verify-release-stage.py").unwrap();

    let runtime = smoke
        .find("codex-mcp-fixture.py\" probe-provider")
        .expect("Codex rehearsal smoke must exercise the selected plugin through the real provider");
    let post_interactive = smoke
        .find("POST_RUNTIME_CLEAN_MCP_LIST")
        .expect("Codex rehearsal smoke must launch clean again after real-provider runtime discovery");
    let evidence = smoke
        .find("clroom.codex-plugin-release-smoke.v4")
        .expect("Codex rehearsal evidence must use the MCP-runtime-aware schema");
    assert!(
        runtime < post_interactive && post_interactive < evidence,
        "post-runtime clean closure must happen before accepted evidence is written"
    );
    for required in [
        "\"provider_mcp_initialize_observed\": provider_mcp_initialize == \"true\"",
        "\"provider_mcp_tools_list_observed\": provider_mcp_tools_list == \"true\"",
        "\"fixture_mcp_tool_call_passed\": fixture_mcp_tool_call == \"true\"",
        "\"provider_state_lifecycle_closed\": True",
        "\"real_provider_runtime_confirmed\": runtime_confirmed == \"true\"",
        "\"expected_mcp_runtime_healthy_confirmed\": runtime_mcp_healthy == \"true\"",
        "\"model_prompt_sent\": False",
        "\"post_runtime_clean_confirmed\": post_runtime_clean == \"true\"",
    ] {
        assert!(smoke.contains(required), "missing Codex runtime evidence field");
    }
    assert!(smoke.contains("exact-release-artifact-v1"));
    assert!(smoke.contains(r#""$phase" == "stage""#));
    for required in [
        "\"phase\": \"stage\"",
        "\"evidence_binding\": \"exact-release-artifact-v1\"",
        "\"provider_state_lifecycle_closed\": True",
        "\"ambient_config_and_plugin_tree_unchanged\": True",
        "\"plugin_source_unchanged\": True",
        "\"post_runtime_clean_confirmed\": True",
    ] {
        assert!(stage.contains(required), "stage verifier must retain runtime invariant");
    }
}

#[test]
fn ci_stops_full_test_reruns_after_protected_tag() {
    let ci = std::fs::read_to_string(".github/workflows/ci.yml").unwrap();
    let release = std::fs::read_to_string(".github/workflows/release.yml").unwrap();
    assert!(ci.contains("branches:\n      - main"));
    assert!(!ci.contains("tags:\n      - \"v*\""));
    assert!(ci.contains("pull_request:"));
    assert!(ci.contains("cancel-in-progress: true"));
    assert!(release.contains("tags:\n      - \"v*\""));
}

#[test]
fn draft_release_verdict_reconciles_exact_staged_bytes_without_runtime_reruns() {
    let verifier = std::fs::read_to_string("scripts/release/verify-draft-release.sh").unwrap();

    assert!(verifier.contains("resolve-release-stage.sh"));
    assert!(verifier.contains("verify-release-stage.py"));
    assert!(verifier.contains("STAGED_BYTE_DRIFT"));
    assert!(verifier.contains(r#"run.get("head_branch") == tag"#));
    assert!(verifier.contains(r#"run.get("head_sha") == expected"#));
    assert!(verifier.contains(r#"run.get("event") == "push""#));
    assert!(verifier.contains(r#"if "Release" not in names"#));
    assert!(verifier.contains(r#"run.get("status") != "completed" or run.get("conclusion") != "success""#));
    assert!(verifier.contains("DRAFT_RELEASE_VERIFY_PASS"));
    assert!(!verifier.contains("check-provider-pins.sh"));
    assert!(!verifier.contains("local-codex-plugin-activation-smoke"));
    assert!(!verifier.contains("local-plugin-activation-smoke"));
    assert!(!verifier.contains("resolve-codex-draft-evidence.sh"));
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
    assert!(contract.contains(r#""tag_remote_refresh_order": "after_staged_release_closure_before_push""#));
    assert!(checker.contains("validate_changelog_tag_date"));
    assert!(checker.contains("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_LATER_TAG"));
    assert!(checker.contains("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_FUTURE_DECLARATION"));
    assert!(checker.contains("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_DUPLICATE"));
    assert!(checker.contains("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_MALFORMED_HEADING"));
    assert!(checker.contains("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_INVALID_DATE"));
    assert!(checker.contains("RELEASE_CONTRACT_SELF_TEST_FAIL_CHANGELOG_BEFORE_BASELINE"));
    assert!(checker.contains("RELEASE_CONTRACT_BLOCKED:CANDIDATE_NOT_ADVANCED"));
    assert!(helper.contains(r#"check-release-contract.py --tag-date "$tag_date""#));
    assert!(!workflow.contains("check-release-contract.py --tag-date"));
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
fn tag_push_requires_staged_closure_then_refreshes_only_action_time_state() {
    let source = std::fs::read_to_string("scripts/release/push-release-tag.sh").unwrap();

    let stage = source
        .find("resolve-release-stage.sh")
        .expect("accepted-main staged bytes must be resolved before tag");
    let claude_stage = source
        .find("STAGE_CLAUDE_EVIDENCE_MISSING")
        .expect("exact staged Claude TTY evidence must be required before tag");
    let initial_policy = source
        .find("verify_immutable_release_policy INITIAL")
        .expect("repository release policy must be observable before irreversible tag");
    let final_remote = source
        .find("# Final mutable action-time guard.")
        .expect("tag helper must have a final mutable action-time guard");
    let push = source
        .find("git push origin \"refs/tags/$tag\"")
        .expect("tag helper must push the protected tag");
    let reconciliation = source
        .find("TAG_PUSH_OUTCOME_UNKNOWN:REMOTE_TARGET_NOT_RECONCILED")
        .expect("tag push must reconcile the remote result");

    assert!(stage < claude_stage && initial_policy < final_remote && claude_stage < final_remote);
    assert!(final_remote < push && push < reconciliation);
    assert_eq!(source.matches("git push origin \"refs/tags/$tag\"").count(), 1);
    assert!(!source.contains("check-provider-pins.sh"));
    assert!(!source.contains("CLAUDE_PROVIDER_DRIFT_ACTION_TIME"));
    assert!(!source.contains("CODEX_PROVIDER_DRIFT_ACTION_TIME"));

    let guard = &source[final_remote..push];
    for required in [
        "git fetch --quiet origin main",
        "MAIN_DRIFT_ACTION_TIME",
        "LOCAL_HEAD_DRIFT_ACTION_TIME",
        "ensure_remote_tag_absent ACTION_TIME",
        "ensure_remote_release_absent ACTION_TIME",
        "verify_tag_ruleset",
        "verify_immutable_release_policy ACTION_TIME",
        "check-release-contract.py --tag-date \"$tag_date\" --report",
    ] {
        assert!(guard.contains(required), "missing action-time tag guard");
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
fn release_runtime_rehearsal_is_premerge_then_exact_staged_bytes_before_tag() {
    let claude =
        std::fs::read_to_string("scripts/release/local-plugin-activation-smoke.sh").unwrap();
    let codex =
        std::fs::read_to_string("scripts/release/local-codex-plugin-activation-smoke.sh").unwrap();
    let tag = std::fs::read_to_string("scripts/release/push-release-tag.sh").unwrap();
    let stage = std::fs::read_to_string("scripts/release/verify-release-stage.py").unwrap();
    let contract =
        std::fs::read_to_string("schemas/release/release-contract-v1.json").unwrap();

    for smoke in [&claude, &codex] {
        assert!(smoke.contains(r#""$phase" == "rehearse""#));
        assert!(smoke.contains(r#""$phase" == "stage""#));
        assert!(smoke.contains("HEAD_NOT_EXPECTED_CANDIDATE"));
        assert!(smoke.contains("HEAD_NOT_EXPECTED_ACCEPTED_MAIN"));
        assert!(smoke.contains("content-addressed-runtime-v1"));
        assert!(smoke.contains("exact-release-artifact-v1"));
    }
    assert!(tag.contains("rehearse-v${version}-${evidence_key}.json"));
    assert!(tag.contains("codex-rehearse-v${version}-${evidence_key}.json"));
    assert!(tag.contains("stage-v${version}-${expected:0:12}.json"));
    assert!(tag.contains("resolve-release-stage.sh"));
    assert!(stage.contains("clroom.release-stage.v1"));
    assert!(contract.contains(r#""post_merge_runtime_role": "accepted_main_exact_shipping_stage_before_tag""#));
    assert!(contract.contains(r#""post_tag_release_role": "promotion_attestation_and_reconciliation_only""#));
}

#[test]
fn codex_release_evidence_uses_actions_for_pr_and_exact_staged_bytes() {
    let candidate =
        std::fs::read_to_string(".github/workflows/release-candidate.yml").unwrap();
    let release = std::fs::read_to_string(".github/workflows/release.yml").unwrap();
    let tag = std::fs::read_to_string("scripts/release/push-release-tag.sh").unwrap();
    let stage_resolver =
        std::fs::read_to_string("scripts/release/resolve-release-stage.sh").unwrap();
    let contract =
        std::fs::read_to_string("schemas/release/release-contract-v1.json").unwrap();

    assert!(candidate.contains("Rehearse Codex runtime on exact PR candidate"));
    assert!(candidate.contains("local-codex-plugin-activation-smoke.sh rehearse"));
    assert!(candidate.contains("Stage exact accepted-main release bytes"));
    assert!(candidate.contains("local-codex-plugin-activation-smoke.sh stage"));
    assert!(candidate.contains("Upload accepted-main release stage"));
    assert!(candidate.contains("Rehearse staged attestation mechanism"));
    assert!(tag.contains("resolve-release-stage.sh"));
    assert!(release.contains("resolve-release-stage.sh"));
    assert!(!release.contains("local-codex-plugin-activation-smoke"));
    assert!(!release.contains("provision-provider-canaries"));
    assert!(stage_resolver.contains("Release candidate readiness"));
    assert!(stage_resolver.contains("SUCCESSFUL_ACCEPTED_MAIN_RUN_NOT_FOUND"));
    assert!(contract.contains(r#""codex_pretag_stage_transport": "accepted_main_github_actions_exact_artifact""#));
    assert!(contract.contains(r#""ambient_local_codex_release_input": "forbidden""#));
}

#[test]
fn repository_release_immutability_is_checked_with_owner_auth_not_actions_runtime() {
    let claude =
        std::fs::read_to_string("scripts/release/local-plugin-activation-smoke.sh").unwrap();
    let codex =
        std::fs::read_to_string("scripts/release/local-codex-plugin-activation-smoke.sh").unwrap();
    let tag = std::fs::read_to_string("scripts/release/push-release-tag.sh").unwrap();
    let verifier = std::fs::read_to_string("scripts/release/verify-draft-release.sh").unwrap();
    let release = std::fs::read_to_string(".github/workflows/release.yml").unwrap();

    assert!(!claude.contains("immutable-releases"));
    assert!(!codex.contains("immutable-releases"));
    assert!(!release.contains("immutable-releases"));
    assert!(tag.contains("repos/y-sor/clean-room-launcher/immutable-releases"));
    assert!(verifier.contains("repos/$repository/immutable-releases"));
}

#[test]
fn tag_bound_promotion_binds_cyclonedx_predicate() {
    let source = std::fs::read_to_string(".github/workflows/release.yml").unwrap();
    assert!(source.contains("--bundle \"$sbom\""));
    assert!(source.contains("--predicate-type https://cyclonedx.org/bom"));
    assert!(source.contains("--source-ref \"$GITHUB_REF\""));
    assert!(source.contains("--source-digest \"$GITHUB_SHA\""));
}

#[test]
fn canonical_readiness_owns_the_draft_release_verifier() {
    let readiness = std::fs::read_to_string("scripts/release/readiness.sh").unwrap();

    assert!(readiness.contains("DRAFT_RELEASE_VERIFY_EXECUTABLE"));
    assert!(readiness.matches("scripts/release/verify-draft-release.sh").count() >= 3);
}

#[test]
fn codex_lifecycle_evidence_names_only_the_ambient_state_it_fingerprints() {
    let smoke =
        std::fs::read_to_string("scripts/release/local-codex-plugin-activation-smoke.sh").unwrap();
    let stage =
        std::fs::read_to_string("scripts/release/verify-release-stage.py").unwrap();

    assert!(smoke.contains("\"ambient_config_and_plugin_tree_unchanged\": True"));
    assert!(!smoke.contains("persistent_provider_state_unchanged"));
    assert!(stage.contains("\"ambient_config_and_plugin_tree_unchanged\": True"));
    assert!(stage.contains("\"plugin_source_unchanged\": True"));
}
