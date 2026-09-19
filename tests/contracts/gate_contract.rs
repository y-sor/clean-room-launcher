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
    assert!(!source.contains("npm install"));
    assert!(provisioner.contains("@openai/codex@0.154.0"));
    assert!(provisioner.contains("@openai/codex@0.154.0-darwin-arm64"));
    assert!(provisioner.contains("@anthropic-ai/claude-code@2.1.272"));
    assert!(provisioner.contains("HP/vJCH/t2hB9Kg6hotN9UglClJ6/z584fal5lEP14C9gNAgAQS4/kTQC7l5V+BA3TqwDPwINSjul28cX8AYXg=="));
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
fn tag_push_revalidates_mutable_remote_state_at_action_time() {
    let source = std::fs::read_to_string("scripts/release/push-release-tag.sh").unwrap();

    assert!(source.contains("REMOTE_TAG_QUERY_$phase"));
    assert!(source.contains("REMOTE_TAG_PRESENT_$phase"));

    let action_time = source
        .find("# Mutable remote release state is refreshed immediately before the irreversible push.")
        .expect("tag helper must have an explicit action-time refresh boundary");
    let provider_evidence = source
        .find("evidence_claude_version=$(python3 - \"$evidence\"")
        .expect("action-time provider evidence must be loaded");
    let provider_version = source
        .find("CLAUDE_PROVIDER_DRIFT_ACTION_TIME")
        .expect("provider version must be revalidated");
    let provider_bytes = source
        .find("CLAUDE_PROVIDER_BYTES_DRIFT_ACTION_TIME")
        .expect("provider bytes must be revalidated");
    let push = source
        .find("git push origin \"refs/tags/$tag\"")
        .expect("tag helper must push the protected tag");
    let reconciliation = source
        .find("TAG_PUSH_BLOCKED:REMOTE_TARGET_NOT_RECONCILED")
        .expect("tag push must reconcile the remote result");

    assert_eq!(
        source.matches("git push origin \"refs/tags/$tag\"").count(),
        1,
        "tag helper must perform exactly one irreversible tag push"
    );
    assert_eq!(
        source.matches("TAG_PUSH_BLOCKED:REMOTE_TARGET_NOT_RECONCILED").count(),
        1,
        "tag push reconciliation must exist only after the actual push"
    );
    assert!(
        action_time < provider_evidence
            && provider_evidence < provider_version
            && provider_version < provider_bytes
            && provider_bytes < push
            && push < reconciliation,
        "all action-time provider checks must finish before the single push; reconciliation must follow it"
    );

    let guard = &source[action_time..push];
    for required in [
        "git fetch --quiet origin main",
        "MAIN_DRIFT_ACTION_TIME",
        "LOCAL_HEAD_DRIFT_ACTION_TIME",
        "ensure_remote_tag_absent ACTION_TIME",
        "verify_tag_ruleset",
        "check-release-contract.py --report",
        "RELEASE_CONTRACT_ACTION_TIME",
        "CLAUDE_PROVIDER_DRIFT_ACTION_TIME",
        "CLAUDE_PROVIDER_BYTES_DRIFT_ACTION_TIME",
    ] {
        assert!(guard.contains(required), "missing action-time tag guard: {required}");
    }
}

#[test]
fn draft_release_smoke_requires_repository_release_immutability() {
    let source = std::fs::read_to_string("scripts/release/local-plugin-activation-smoke.sh").unwrap();

    assert!(source.contains("repos/y-sor/clean-room-launcher/immutable-releases"));
    assert!(source.contains("IMMUTABLE_RELEASE_POLICY_UNVERIFIED"));
    assert!(source.contains("IMMUTABLE_RELEASE_POLICY_DISABLED"));
    assert!(source.contains("\"claude_provider_sha256\":claude_provider_sha"));

    let draft_branch = source
        .find("if [[ \"$phase\" == \"pretag\" ]]; then")
        .expect("release smoke must branch between pretag and draft behavior");
    let policy = source
        .find("immutable-releases --jq .enabled")
        .expect("draft smoke must verify release immutability");
    let release_download = source
        .find("gh release download \"$tag\" --dir \"$assets\"")
        .expect("draft smoke must download the exact Draft assets");
    assert!(
        draft_branch < policy && policy < release_download,
        "immutability must be proven in the Draft pre-publish path before accepting release assets"
    );
}

#[test]
fn draft_plugin_release_smoke_binds_cyclonedx_predicate() {
    let source = std::fs::read_to_string("scripts/release/local-plugin-activation-smoke.sh").unwrap();
    assert!(
        source.contains("--bundle \"$sbom\"     --predicate-type https://cyclonedx.org/bom"),
        "draft release smoke must verify the SBOM bundle as CycloneDX instead of the default SLSA provenance predicate"
    );
}

use std::os::unix::fs::PermissionsExt;
