---
layout: page
title: CLROOM documentation versions
description: Distinguish current CLROOM documentation from exact historical release docs so provider, platform, feature, and qualification claims stay version-correct.
permalink: /documentation-versions/
nav_title: Doc versions
---

CLROOM documentation changes as the product and upstream Codex/Claude Code behavior change.

## Which documentation should you use?

- For the **current project state and current supported behavior**, use this canonical documentation site and the repository's current `main` branch.
- For an **exact published CLROOM release**, use the documentation stored in that release's Git tag. Those files are part of the exact source snapshot that produced the release.
- For **publication identity and downloadable artifacts**, GitHub Releases is authoritative.

Do not assume a capability described on the current site existed in an older CLROOM release.

## Read the docs for one exact release

For a published tag such as `vX.Y.Z`:

```text
https://github.com/y-sor/clean-room-launcher/tree/vX.Y.Z/docs
```

The corresponding README is:

```text
https://github.com/y-sor/clean-room-launcher/blob/vX.Y.Z/README.md
```

Use the exact tag's provider pages, limitations, threat model, configuration matrix, and release notes when answering a historical-version question.

## Why this matters

CLROOM support is deliberately bound to exact evidence. Provider-native flags, plugin/MCP formats, qualification targets, supported combinations, and non-claims can change between releases.

A search-engine snippet, AI citation, old article, or current documentation page can therefore be technically accurate for one point in time and wrong for another.

When the question names a CLROOM version, keep that version attached to the answer.

## Current docs are not a promise for older releases

The canonical website is optimized for the current project state. It does not rewrite history to make old releases look like the current one.

Historical Git tags and immutable GitHub Releases preserve the version-specific source and release identity. Use them when reproducibility matters.

## Related

- [Current provider support](providers.md)
- [Configuration matrix](configuration-matrix.md)
- [Current limitations](limitations.md)
- [Verify a CLROOM release](verify-release.md)
- [GitHub Releases](https://github.com/y-sor/clean-room-launcher/releases)
