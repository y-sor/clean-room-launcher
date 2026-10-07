---
layout: page
title: Reusable CLROOM skill sets for Codex and Claude Code
description: Create, edit, use, and combine reusable Clean Room Launcher (CLROOM) skill sets for Codex and Claude Code launches.
permalink: /skill-sets/
nav_title: Skill sets
---
CLROOM skill sets are user-created groups of global skill references. They let you reuse a selection without rewriting your normal provider setup.

## Create a skill set

Run:

```sh
clroom --help
```

It shows the exact skill-set file path for your setup. The normal path is:

```text
~/.config/clroom/skill-sets.yaml
```

Create or edit that YAML file and define reusable groups:

```yaml
review:
  - my-review-skill
  - my-security-review

bugfix:
  - superpowers:systematic-debugging
  - my-regression-check

brainstorming:
  - my-design-skill
  - superpowers:brainstorming
```

The `my-*` names are placeholders for global skills you installed or created. The `superpowers:*` examples assume those skills are already installed in a global skill location CLROOM can discover. CLROOM groups skill references; it does not install skills.

For the built-in skill-set example, run:

```sh
clroom help skill-set
```

## Use a skill set

Reference a saved group with `@set-name`:

```sh
clroom codex --skill-set=@review

clroom codex --skill-set=@bugfix

clroom claude --skill-set=@brainstorming
```

The same user-created set mechanism is available through both CLROOM launchers. Codex and Claude Code remain different provider environments.

## Combine skills and skill sets

Use more than one saved set in the same launch:

```sh
clroom codex --skill-set=@review,@bugfix
```

Or combine a direct global skill with a saved set:

```sh
clroom codex --skill-set=my-skill,@review
```

Skill references are comma-separated. Repeated and overlapping references are deduplicated, and the selection applies only to this launch.

<a id="symlinked-global-skills"></a>
## Symlinked global skills

A common setup keeps reusable Agent Skills in one version-controlled directory and exposes individual skill directories to provider discovery locations with symlinks.

CLROOM qualifies symlinked personal-global skills as both a discovery and filesystem-security case:

- an unselected supported symlinked skill and its canonical target stay outside the clean launch;
- a selected supported symlinked skill resolves to the intended skill and is counted once;
- duplicate names follow the documented source precedence and the losing target stays unreadable;
- links that would expose protected provider, configuration, or credential paths are refused;
- provider-owned/system-managed skill locations are not automatically user-selectable.

Exact support differs by provider and source location. See [Claude Code](claude-code.md) and [Codex](codex.md).

## Edit a skill set

Open the same YAML file, add or remove skill references under the set name, and keep using the same `@set-name`.

CLROOM reads the file when an `@set` is used. It does not create or rewrite the file for you.

## Selection rules

- A bare `name` selects the logical global skill with that name, or every skill in a namespace with that name.
- `namespace:skill` selects one specific skill from a namespace.
- `@set-name` selects a user-created saved group from the YAML file.
- Direct skills and saved sets can be combined in one comma-separated `--skill-set` value.
- Multiple saved sets can be combined in one launch.
- Repeated and overlapping skill references are deduplicated.
- Saved sets cannot contain other `@sets`.
- Invalid or unknown selections stop before the provider starts.
- The YAML file is read only when an `@set` is used.
- CLROOM never creates or rewrites the YAML file.
- Selections apply only to the current launch.
- Project-local skills remain available automatically.
