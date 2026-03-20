---
name: skills-manager
description: Manage installed skills for Codex and OpenCode, including listing existing skills, installing local skill folders, uninstalling skills, inspecting skill roots, and syncing skills from a GitHub Enterprise repository or a specific skills subdirectory. Use when Codex needs to view available skills across apps, copy a skill into an app's skills directory, remove a skill, or pull one or more skills from a private GitHub Enterprise repo with automatic username/password or token-backed git authentication.
---

# Skills Manager

Use this skill to manage skill folders for Codex and OpenCode from one place. Prefer the bundled script for deterministic operations instead of reimplementing copy, delete, or git sparse-checkout logic each time.

## Workflow

1. Resolve the target app and its skills directory.
2. Inspect the current installed skills before modifying anything.
3. Choose one operation: install from local path, uninstall, list remote repo catalog, inspect one remote `SKILL.md`, or sync from GitHub Enterprise.
4. Run the bundled `./skillsctl` inside this skill folder, or run `scripts/manage_skills.py` directly.
5. Re-list the target directory after changes when confirmation matters.

## Target Paths

Use the script defaults unless the user gives a concrete path.

- `codex`: default `~/.codex/skills`, override with `CODEX_SKILLS_DIR`
- `opencode`: first existing path from `~/.config/opencode/skills`, `~/.opencode/skills`, `~/.local/share/opencode/skills`; if none exist, use `~/.config/opencode/skills`; override with `OPENCODE_SKILLS_DIR`

Run:

```bash
./skillsctl list --app all
```

If the skill is installed under another root, run the `skillsctl` file that lives inside the installed skill directory.

## Config File

Prefer a TOML config file when the same GitHub Enterprise repo is used repeatedly.

Load order:

1. `--config /path/to/config.toml`
2. `SKILLS_MANAGER_CONFIG`
3. `./skills-manager.toml`
4. `~/.config/skills-manager/config.toml`

Inspect the active config with:

```bash
./skillsctl show-config
```

A portable example config is bundled at `skills-manager.toml.example` inside this skill folder.

## Local Install And Removal

Install a local skill directory into an app:

```bash
./skillsctl install-local \
  --app codex \
  --source /absolute/path/to/skill-folder
```

Force overwrite an existing installed skill:

```bash
./skillsctl install-local \
  --app opencode \
  --source /absolute/path/to/skill-folder \
  --force
```

Remove an installed skill:

```bash
./skillsctl uninstall \
  --app codex \
  --name my-skill
```

## GitHub Enterprise Repo Catalog

Use `catalog-git` to inspect which skills are available under a repo subdirectory before installing them:

```bash
./skillsctl catalog-git \
  --repo https://github.example.com/org/skills.git \
  --repo-subdir skills \
  --ref main
```

Use `--details` to show descriptions from each remote `SKILL.md` frontmatter:

```bash
./skillsctl catalog-git --details
```

Use `show-skill-git` to fetch one remote `SKILL.md` without cloning:

```bash
./skillsctl show-skill-git \
  --repo https://github.example.com/org/skills.git \
  --repo-subdir skills \
  --ref main \
  --skill release-helper
```

`catalog-git` and `show-skill-git` use remote archive reads instead of clone. They fetch only the target directory or `SKILL.md`.

## GitHub Enterprise Install And Sync

Install specific repo skills into an app:

```bash
./skillsctl install-git \
  --app codex \
  --repo https://github.example.com/org/skills.git \
  --repo-subdir skills \
  --skill release-helper \
  --skill jira-triage
```

Sync the whole repo skills directory into an app:

```bash
./skillsctl sync-git \
  --app opencode \
  --repo https://github.example.com/org/skills.git \
  --repo-subdir skills \
  --ref main \
  --force
```

`sync-git` is the right choice when the user wants the repo's skills directory pulled into the target app. `install-git` is the right choice when only named skills should be copied.

## Authentication

For GitHub Enterprise, prefer environment variables so git authentication is automatic and non-interactive. Read [references/github-enterprise.md](references/github-enterprise.md) when auth details or examples are needed. A bundled config example is available at `skills-manager.toml.example`.

Supported inputs, in precedence order:

1. CLI flags `--token`, `--username`, `--password`
2. `GHE_TOKEN`
3. `GHE_USERNAME` with `GHE_PASSWORD`
4. `GIT_USERNAME` with `GIT_PASSWORD`

If a token is supplied, the script feeds it through `GIT_ASKPASS` and uses `x-access-token` as the username unless an explicit username is also provided.

## Safety Rules

- Inspect first with `list` or `catalog-git` before destructive changes.
- Use `--force` only when overwriting an installed skill is intended.
- Do not guess a remote repo subdirectory; list or inspect it first.
- Treat missing OpenCode paths as configuration, not as fatal corruption.
- Prefer explicit absolute source paths for local installs.

## Bundled Resources

- `scripts/manage_skills.py`: CLI for listing, installing, uninstalling, cataloging, and syncing skills
- `skillsctl`: wrapper that invokes `scripts/manage_skills.py` from inside the skill folder
- `skills-manager.toml.example`: portable config example for repeated repo operations
- `references/github-enterprise.md`: auth inputs, environment variables, and command examples
