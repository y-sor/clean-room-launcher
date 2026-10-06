---
layout: page
title: Threat model
description: CLROOM threat model covering clean-launch isolation, malicious or injected context, skills and symlinks, provider drift, private-data leakage, release evidence, and residual risks.
permalink: /threat-model.html
---

## Scope and protected assets

This model covers local launch preparation, provider process birth, generated
context, release artifacts and evidence. Protected assets are provider
authentication state, user and project files, Git state, source skills,
generated runtime state, artifact identity and release receipts.

## Trust model, trust boundaries, and attacker-controlled inputs

Trust relationships exist between the parent environment and the isolated runtime,
between source skills and generated context, between Clean Room Launcher and a provider
CLI, and between a built artifact and its release evidence. Attacker-controlled
inputs include project files, skill metadata, command arguments, environment
variables, archive members, paths and symlinks, provider output and edited
receipts.

## Threats

- HOME contamination can expose parent configuration, unrelated skills or
  private files to a supposedly clean launch.
- A symlinked personal-global skill can leak its canonical target even when the
  discovery entry itself is under a known root; both providers must deny
  unselected targets and refuse protected overlaps.
- Path and symlink escape can redirect placement, reads, writes or cleanup
  outside Clean Room Launcher-owned runtime roots.
- Malicious context can use admitted files or skill metadata to influence a
  provider outside the intended task scope.
- Prompt injection can arrive through project files, documentation, source
  comments, issue/PR text, fetched web content, MCP/tool output, or another
  provider-visible data channel. A cleaner personal-global launch boundary does
  not make those inputs trusted and is not a prompt-injection defense.
- Adapter or provider drift can make evidence from one executable, version,
  operating system or architecture appear valid for another tuple.
- Private-data leakage can place secrets, absolute user paths, prompts or
  transcripts in source exports, artifacts, logs, SBOMs or receipts.
- Digest or receipt forgery can detach a successful observation from the bytes,
  process, state baseline or cleanup result that produced it.
- Unsafe archive entries or process construction can escape extraction roots or
  introduce shell interpretation.
- Incomplete cleanup can leave generated context or launcher-owned state that
  affects a later provider start.

## What CLROOM does not secure

CLROOM's clean/selective launch controls are about the supported launch inputs it
owns. They do **not** authenticate repository text, sanitize arbitrary web/tool
content, detect prompt injection, make MCP output trustworthy, or replace the
provider's sandbox, permission system, network policy, credential scope, or
human review.

Removing an unrelated personal-global instruction can make a reproduction easier
to reason about. It does not prove that the remaining repository/project/tool
context is benign.

## Mitigations

- Resolve executable, version, OS, architecture, source commit and artifact
  digests before provider birth; unsupported or stale tuples remain
  `NOT_QUALIFIED`.
- Build an allowlisted environment, refuse collisions before placement, reject
  symlinks and path traversal, and clean only digest-bound launcher-owned state.
- Track symlink entry and canonical paths separately, admit only selected
  supported links, and keep losing or unselected targets denied.
- Preserve provider-native skill loading and record only bounded observations;
  never retain raw provider output, prompts, credentials or transcripts.
- Require normalized archives, locked dependencies, checksums, SBOM and
  provenance bound to one artifact digest, plus deterministic receipt subjects.
- Scan public source inputs separately from immutable internal gate evidence and
  keep planted negative fixtures outside promotion evidence.

## Residual risks

- The current release artifacts are unsigned and unnotarized, and no independent
  security audit has been completed.
- The repository contains CODEOWNERS, but this document does not claim that
  repository-side enforcement is enabled. Private security-reporting
  availability must not be inferred from the public repository.
- Provider behavior may change after the exact observed version; evidence never
  transfers automatically to a new tuple.
