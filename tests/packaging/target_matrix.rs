//! Focused, dependency-free contract tests for the CLROOM release target matrix.

use std::{collections::BTreeMap, fs, path::Path, process::Command};

const RECEIPT_PATH: &str = "reports/gates/clroom-packaging/task-1.json";
const TOPOLOGY_EVIDENCE_ID: &str = "EVD-CLROOM_PACKAGING-T1-R4-GIT-TOPOLOGY-DURABILITY-GREEN";

fn read(path: &str) -> String {
    fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join(path))
        .expect("packaging fixture exists")
}

fn list_value(source: &str, key: &str) -> Vec<String> {
    source
        .lines()
        .find_map(|line| line.strip_prefix(&format!("{key} = ")))
        .map(|value| {
            value
                .trim()
                .trim_start_matches('[')
                .trim_end_matches(']')
                .split(',')
                .filter_map(|item| {
                    let item = item.trim().trim_matches('"');
                    (!item.is_empty()).then(|| item.to_owned())
                })
                .collect()
        })
        .unwrap_or_default()
}

fn target_blocks(source: &str) -> Vec<BTreeMap<String, String>> {
    source.split("[[targets]]").skip(1).map(|block| {
        block.lines().filter_map(|line| {
            let (key, value) = line.split_once('=')?;
            Some((key.trim().to_owned(), value.trim().trim_matches('"').to_owned()))
        }).collect()
    }).collect()
}

fn matrix_is_honest(source: &str) -> bool {
    let advertised = list_value(source, "advertised_targets");
    let qualified = list_value(source, "qualified_targets");
    if advertised != qualified { return false; }
    let targets = target_blocks(source);
    advertised.iter().all(|name| targets.iter().any(|target| {
        target.get("name") == Some(name)
            && target.get("qualification_status") == Some(&"INTEGRITY_VERIFIED".to_owned())
            && target.get("runner").is_some_and(|runner| runner != "unsupported" && runner != "missing-runner")
            && target.get("artifact_name").is_some_and(|artifact| !artifact.is_empty())
    }))
}

fn workflow_is_bound_to_qualified(source: &str) -> bool {
    source.contains("packaging/targets.toml")
        && source.contains("qualified_targets")
        && source.contains("qualification_status")
        && source.contains("rust_target")
        && source.contains("runs-on: ${{ matrix.runner }}")
        && source.contains("matrix:")
        && source.contains("name: alpha-macos-aarch64")
        && source.contains("runner: macos-15")
        && source.contains("rust_target: aarch64-apple-darwin")
        && source.contains("cargo test")
        && !source.contains("test -z \"$qualified\"")
        && !source.contains("for target in $qualified")
        && !source.contains("continue-on-error")
        && !source.contains("if: always()")
        && !source.contains("cargo fmt --all")
}

fn receipt_string_value(source: &str, key: &str) -> Option<String> {
    source.lines().find_map(|line| {
        let value = line.trim().strip_prefix(&format!("\"{key}\":"))?;
        Some(
            value
                .trim()
                .trim_end_matches(',')
                .trim_matches('"')
                .to_owned(),
        )
    })
}

fn git(root: &Path, args: &[&str]) -> Result<String, String> {
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .map_err(|error| format!("could not run git {args:?}: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "git {args:?} exited {:?}: {}",
            output.status.code(),
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn receipt_topology_is_durable(root: &Path, receipt: &str) -> Result<(), String> {
    let implementation = receipt_string_value(receipt, "correction_implementation_head")
        .ok_or("receipt has no correction_implementation_head")?;
    if implementation.len() != 40 || !implementation.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("correction_implementation_head is not a full Git object ID".to_owned());
    }
    let declared_parent = receipt_string_value(receipt, "receipt_commit_parent")
        .ok_or("receipt has no receipt_commit_parent")?;

    let implementation_commit = format!("{implementation}^{{commit}}");
    git(root, &["cat-file", "-e", &implementation_commit])?;
    let implementation_paths = git(
        root,
        &[
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            &implementation,
        ],
    )?;
    if implementation_paths.lines().collect::<Vec<_>>() != ["tests/packaging/target_matrix.rs"] {
        return Err(format!(
            "correction implementation commit changed unexpected paths: {implementation_paths}"
        ));
    }

    git(
        root,
        &["merge-base", "--is-ancestor", &implementation, "HEAD"],
    )?;
    let ancestry_range = format!("{implementation}..HEAD");
    let receipt_commits = git(
        root,
        &[
            "rev-list",
            "--reverse",
            "--ancestry-path",
            &ancestry_range,
            "--",
            RECEIPT_PATH,
        ],
    )?;
    let receipt_commit = receipt_commits
        .lines()
        .next()
        .ok_or("no receipt commit descends from the correction implementation")?;
    let commit_and_parents = git(root, &["rev-list", "--parents", "-n", "1", receipt_commit])?;
    let words = commit_and_parents.split_whitespace().collect::<Vec<_>>();
    if words.len() != 2 {
        return Err(format!(
            "receipt commit is not a single-parent commit: {commit_and_parents}"
        ));
    }
    let actual_parent = words[1];
    if actual_parent != implementation || declared_parent != actual_parent {
        return Err(format!(
            "receipt parent mismatch: implementation={implementation}, declared={declared_parent}, actual={actual_parent}"
        ));
    }

    let receipt_paths = git(
        root,
        &[
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            receipt_commit,
        ],
    )?;
    if receipt_paths.lines().collect::<Vec<_>>() != [RECEIPT_PATH] {
        return Err(format!(
            "receipt commit changed non-receipt paths: {receipt_paths}"
        ));
    }
    git(
        root,
        &["merge-base", "--is-ancestor", receipt_commit, "HEAD"],
    )?;
    Ok(())
}

#[test]
fn matrix_advertised_targets_exactly_equal_qualified_lanes() {
    let matrix = read("packaging/targets.toml");
    assert!(matrix_is_honest(&matrix));
    assert_eq!(
        list_value(&matrix, "advertised_targets"),
        ["alpha-macos-aarch64"]
    );
    for target in target_blocks(&matrix) {
        for field in ["name", "rust_target", "runner", "qualification_status", "artifact_name", "required_checks", "signing_policy"] {
            assert!(target.contains_key(field), "target is missing {}", field);
        }
        assert!(target["required_checks"].contains("fmt"));
        assert!(target["required_checks"].contains("test"));
        assert!(!target["required_checks"].contains("skip"));
    }
}

#[test]
fn matrix_mutations_refuse_false_claims_and_mismatched_lists() {
    let matrix = read("packaging/targets.toml");
    let advertised_false = matrix.replacen(
        "qualification_status = \"INTEGRITY_VERIFIED\"",
        "qualification_status = \"NOT_QUALIFIED\"",
        1,
    );
    assert!(!matrix_is_honest(&advertised_false), "a NOT_QUALIFIED advertised target must fail");
    let lists_mismatch = matrix.replace(
        "qualified_targets = [\"alpha-macos-aarch64\"]",
        "qualified_targets = []",
    );
    assert!(!matrix_is_honest(&lists_mismatch), "advertised/qualified mismatch must fail");
}

#[test]
fn fixtures_distinguish_supported_unsupported_and_missing_runner() {
    let matrix = read("packaging/targets.toml");
    assert!(matrix.contains("fixture_supported"));
    assert!(matrix.contains("fixture_unsupported"));
    assert!(matrix.contains("fixture_missing_runner"));
    assert!(matrix.contains("NOT_QUALIFIED"));
    assert!(matrix.contains("unsupported targets are excluded"));
}

#[test]
fn workflow_is_structurally_bound_to_qualified_entries() {
    let workflow = read(".github/workflows/ci.yml");
    assert!(workflow_is_bound_to_qualified(&workflow));
    let retired_runner = workflow.replace("runner: macos-15", "runner: macos-14");
    assert!(!workflow_is_bound_to_qualified(&retired_runner));
    let advertised_binding = workflow.replace("qualified_targets", "advertised_targets");
    assert!(!workflow_is_bound_to_qualified(&advertised_binding));
    let hardcoded_runner = workflow.replace("runs-on: ${{ matrix.runner }}", "runs-on: ubuntu-latest");
    assert!(!workflow_is_bound_to_qualified(&hardcoded_runner));
    let global_fmt = format!("{workflow}\n      - run: cargo fmt --all -- --check\n");
    assert!(!workflow_is_bound_to_qualified(&global_fmt));
}

#[test]
fn supported_arm64_runner_is_consistent_across_ci_and_release() {
    let targets = read("packaging/targets.toml");
    let ci = read(".github/workflows/ci.yml");
    let release = read(".github/workflows/release-candidate.yml");
    assert!(targets.contains("runner = \\"macos-15\\""));
    assert!(ci.contains("runner: macos-15"));
    assert_eq!(release.matches("runs-on: macos-15").count(), 2);
    for source in [&targets, &ci, &release] {
        assert!(!source.contains("macos-14"), "retired runner must not be used");
    }
}

#[test]
fn receipt_is_durable_internally_or_absent_from_public_history() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    if !root.join(RECEIPT_PATH).is_file() {
        let inventory = read("qualification/public-release-inventory-v1.json");
        assert!(inventory.contains("IMMUTABLE_INTERNAL_EVIDENCE_EXCLUDED_FROM_PUBLIC_SOURCE"));
        assert!(inventory.contains("\"reports/gates\""));
        let public_history = git(root, &["log", "--format=%H", "HEAD", "--", RECEIPT_PATH])
            .expect("public history can be inspected");
        assert!(
            public_history.is_empty(),
            "internal receipt must be absent from public history"
        );
        return;
    }
    let receipt = read(RECEIPT_PATH);
    for field in [
        "\"input_head\": \"ea551a35b058b19e402071cfc07d34862ec9216b\"",
        "\"accepted_initial_head\": \"5249fd4c86760563b1f4306b74ee5e35fa949b4b\"",
        "\"correction_implementation_head\":",
        "\"receipt_seal_role\": \"receipt-only-child\"",
    ] {
        assert!(receipt.contains(field), "receipt binding field missing: {}", field);
    }
    assert!(!receipt.contains("\"result_head\": \"55b5dda9d3f432349c308ad9cfe69785571c1b72\""));

    receipt_topology_is_durable(root, &receipt)
        .unwrap_or_else(|error| panic!("receipt Git topology is not durable: {}", error));
    assert_eq!(
        receipt.matches(TOPOLOGY_EVIDENCE_ID).count(),
        2,
        "topology evidence ID must occur once in acceptance and once as an evidence entry"
    );

    let declared_parent = receipt_string_value(&receipt, "receipt_commit_parent").unwrap();
    let incorrect_parent = receipt.replace(
        &format!("\"receipt_commit_parent\": \"{declared_parent}\""),
        "\"receipt_commit_parent\": \"0000000000000000000000000000000000000000\"",
    );
    assert!(
        receipt_topology_is_durable(root, &incorrect_parent).is_err(),
        "a receipt with an incorrect Git parent must fail"
    );
}
