# GitHub Enterprise

Use the bundled script for repo-backed skill operations. It supports shallow sparse checkout so only the requested skills directory, or selected skill folders, are pulled locally.

## Supported Credentials

Precedence order:

1. CLI flags `--token`, `--username`, `--password`
2. `GHE_TOKEN`
3. `GHE_USERNAME` with `GHE_PASSWORD`
4. `GIT_USERNAME` with `GIT_PASSWORD`

Behavior:

- When a token is present, the script uses `x-access-token` as the default username.
- Credentials are injected through a temporary `GIT_ASKPASS` helper.
- The helper is non-interactive, so username and password input is automatic.

## Examples

List skills published by a private GitHub Enterprise repo:

```bash
export GHE_USERNAME='alice'
export GHE_PASSWORD='secret'
python skills/skills-manager/scripts/manage_skills.py catalog-git \
  --repo https://github.example.com/platform/skills.git \
  --repo-subdir skills \
  --ref main
```

Install one remote skill into Codex:

```bash
export GHE_TOKEN='ghp_xxx'
python skills/skills-manager/scripts/manage_skills.py install-git \
  --app codex \
  --repo https://github.example.com/platform/skills.git \
  --repo-subdir skills \
  --skill release-helper
```

Sync the full repo skills directory into OpenCode:

```bash
python skills/skills-manager/scripts/manage_skills.py sync-git \
  --app opencode \
  --repo https://github.example.com/platform/skills.git \
  --repo-subdir skills \
  --ref main \
  --force
```

## Notes

- `--repo-subdir` should point to the directory that contains skill folders, not to a single `SKILL.md` file.
- A valid skill folder must contain `SKILL.md`.
- `--ref` is intended for a branch or tag name in shallow clone mode.
