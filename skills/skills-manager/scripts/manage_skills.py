#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


OPENCODE_CANDIDATES = (
    "~/.config/opencode/skills",
    "~/.opencode/skills",
    "~/.local/share/opencode/skills",
)
DEFAULT_CONFIG_CANDIDATES = (
    "./skills-manager.toml",
    "~/.config/skills-manager/config.toml",
)


@dataclass
class AuthConfig:
    username: str | None = None
    password: str | None = None


def expand(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def load_config(config_path: str | None) -> tuple[dict, Path | None]:
    candidates = []
    env_config = os.environ.get("SKILLS_MANAGER_CONFIG")
    if config_path:
        candidates.append(config_path)
    elif env_config:
        candidates.append(env_config)
    else:
        candidates.extend(DEFAULT_CONFIG_CANDIDATES)

    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.exists():
            with path.open("rb") as fh:
                data = tomllib.load(fh)
            if not isinstance(data, dict):
                raise ValueError(f"Config root must be a TOML table: {path}")
            return data, path.resolve()
    return {}, None


def config_get(config: dict, *keys: str) -> str | None:
    current = config
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    if current is None:
        return None
    if isinstance(current, (str, int, float, bool)):
        return str(current)
    raise ValueError(f"Config value at {'.'.join(keys)} must be scalar")


def apply_config_defaults(args: argparse.Namespace, config: dict) -> None:
    command = getattr(args, "command", None)
    if command is None:
        return

    if hasattr(args, "repo") and not getattr(args, "repo", None):
        args.repo = config_get(config, "git", "repo")
    if hasattr(args, "repo_subdir") and getattr(args, "repo_subdir", None) == "skills":
        args.repo_subdir = config_get(config, "git", "repo_subdir") or args.repo_subdir
    if hasattr(args, "ref") and not getattr(args, "ref", None):
        args.ref = config_get(config, "git", "ref")
    if hasattr(args, "codex_dir") and not getattr(args, "codex_dir", None):
        args.codex_dir = config_get(config, "paths", "codex_dir")
    if hasattr(args, "opencode_dir") and not getattr(args, "opencode_dir", None):
        args.opencode_dir = config_get(config, "paths", "opencode_dir")
    if hasattr(args, "app") and not getattr(args, "app", None):
        args.app = config_get(config, "defaults", "app")
    if hasattr(args, "username") and not getattr(args, "username", None):
        args.username = config_get(config, "auth", "username")
    if hasattr(args, "password") and not getattr(args, "password", None):
        args.password = config_get(config, "auth", "password")
    if hasattr(args, "token") and not getattr(args, "token", None):
        args.token = config_get(config, "auth", "token")


def detect_opencode_dir() -> Path:
    override = os.environ.get("OPENCODE_SKILLS_DIR")
    if override:
        return expand(override)
    for candidate in OPENCODE_CANDIDATES:
        path = expand(candidate)
        if path.exists():
            return path
    return expand(OPENCODE_CANDIDATES[0])


def resolve_app_dir(app: str, explicit_dir: str | None = None) -> Path:
    if explicit_dir:
        return expand(explicit_dir)
    if app == "codex":
        return expand(os.environ.get("CODEX_SKILLS_DIR", "~/.codex/skills"))
    if app == "opencode":
        return detect_opencode_dir()
    raise ValueError(f"Unsupported app: {app}")


def discover_skill_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path for path in root.iterdir() if path.is_dir() and (path / "SKILL.md").exists()
    )


def ensure_skill_dir(path: Path) -> None:
    skill_md = path / "SKILL.md"
    if not path.is_dir() or not skill_md.exists():
        raise ValueError(f"Not a skill directory: {path}")


def copy_skill(source: Path, destination_root: Path, force: bool) -> Path:
    ensure_skill_dir(source)
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / source.name
    if destination.exists():
        if not force:
            raise FileExistsError(
                f"Destination already exists: {destination}. Re-run with --force to overwrite."
            )
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination


def remove_skill(destination_root: Path, skill_name: str, missing_ok: bool) -> Path | None:
    target = destination_root / skill_name
    if not target.exists():
        if missing_ok:
            return None
        raise FileNotFoundError(f"Skill not found: {target}")
    ensure_skill_dir(target)
    shutil.rmtree(target)
    return target


def auth_from_args(args: argparse.Namespace) -> AuthConfig:
    token = getattr(args, "token", None) or os.environ.get("GHE_TOKEN")
    username = getattr(args, "username", None) or os.environ.get("GHE_USERNAME") or os.environ.get(
        "GIT_USERNAME"
    )
    password = getattr(args, "password", None) or os.environ.get("GHE_PASSWORD") or os.environ.get(
        "GIT_PASSWORD"
    )
    if token:
        return AuthConfig(username=username or "x-access-token", password=token)
    if username and password:
        return AuthConfig(username=username, password=password)
    return AuthConfig()


def make_askpass_script(temp_dir: Path, auth: AuthConfig) -> Path | None:
    if not auth.username or not auth.password:
        return None
    script_path = temp_dir / "git_askpass.py"
    script_path.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        "prompt = (sys.argv[1] if len(sys.argv) > 1 else '').lower()\n"
        "if 'username' in prompt:\n"
        "    sys.stdout.write(os.environ.get('SKILLS_GIT_USERNAME', ''))\n"
        "elif 'password' in prompt:\n"
        "    sys.stdout.write(os.environ.get('SKILLS_GIT_PASSWORD', ''))\n"
        "else:\n"
        "    sys.stdout.write(os.environ.get('SKILLS_GIT_PASSWORD', ''))\n"
    )
    current_mode = script_path.stat().st_mode
    script_path.chmod(current_mode | stat.S_IXUSR)
    return script_path


def run(cmd: list[str], env: dict[str, str] | None = None, cwd: Path | None = None) -> None:
    subprocess.run(cmd, check=True, env=env, cwd=cwd)


def clone_sparse(
    repo: str,
    ref: str | None,
    sparse_paths: Iterable[str],
    auth: AuthConfig,
) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="skills-manager-"))
    repo_dir = temp_dir / "repo"
    env = os.environ.copy()
    askpass_script = make_askpass_script(temp_dir, auth)
    if askpass_script:
        env["GIT_ASKPASS"] = str(askpass_script)
        env["SKILLS_GIT_USERNAME"] = auth.username or ""
        env["SKILLS_GIT_PASSWORD"] = auth.password or ""
        env["GIT_TERMINAL_PROMPT"] = "0"

    clone_cmd = ["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout"]
    if ref:
        clone_cmd.extend(["--branch", ref])
    clone_cmd.extend([repo, str(repo_dir)])
    run(clone_cmd, env=env)
    run(["git", "-C", str(repo_dir), "sparse-checkout", "init", "--cone"], env=env)
    run(["git", "-C", str(repo_dir), "sparse-checkout", "set", *list(sparse_paths)], env=env)
    run(["git", "-C", str(repo_dir), "checkout"], env=env)
    return repo_dir


def list_repo_skills(repo_dir: Path, repo_subdir: str) -> list[Path]:
    base = repo_dir / repo_subdir
    return discover_skill_dirs(base)


def install_repo_skills(
    repo: str,
    ref: str | None,
    repo_subdir: str,
    app_dir: Path,
    skill_names: list[str] | None,
    force: bool,
    auth: AuthConfig,
) -> list[Path]:
    sparse_paths = [repo_subdir]
    if skill_names:
        sparse_paths = [f"{repo_subdir}/{name}" for name in skill_names]
    repo_dir = clone_sparse(repo, ref, sparse_paths, auth)
    try:
        base = repo_dir / repo_subdir
        if skill_names:
            sources = [base / name for name in skill_names]
        else:
            sources = discover_skill_dirs(base)
        if not sources:
            raise FileNotFoundError(f"No skill directories found under {repo_subdir} in {repo}")
        copied = []
        for source in sources:
            ensure_skill_dir(source)
            copied.append(copy_skill(source, app_dir, force=force))
        return copied
    finally:
        shutil.rmtree(repo_dir.parent, ignore_errors=True)


def print_json(data: object) -> None:
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def require_args(args: argparse.Namespace, fields: list[str]) -> None:
    missing = []
    for field in fields:
        value = getattr(args, field, None)
        if value is None or value == "":
            missing.append(f"--{field.replace('_', '-')}")
    if missing:
        raise ValueError(f"Missing required arguments after config resolution: {', '.join(missing)}")


def cmd_show_config(args: argparse.Namespace) -> int:
    config = args.loaded_config
    payload = {
        "config_path": str(args.loaded_config_path) if args.loaded_config_path else None,
        "config": config,
    }
    if args.json:
        print_json(payload)
    else:
        print(f"Config path: {payload['config_path'] or '(none loaded)'}")
        if config:
            print_json(config)
        else:
            print("(empty config)")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    apps = ["codex", "opencode"] if args.app == "all" else [args.app]
    payload = []
    for app in apps:
        root = resolve_app_dir(app, explicit_dir=getattr(args, f"{app}_dir", None))
        payload.append(
            {
                "app": app,
                "root": str(root),
                "exists": root.exists(),
                "skills": [path.name for path in discover_skill_dirs(root)],
            }
        )
    if args.json:
        print_json(payload)
    else:
        for item in payload:
            print(f"[{item['app']}] {item['root']}")
            if not item["exists"]:
                print("  (directory missing)")
                continue
            if not item["skills"]:
                print("  (no skills found)")
                continue
            for skill in item["skills"]:
                print(f"  - {skill}")
    return 0


def cmd_install_local(args: argparse.Namespace) -> int:
    require_args(args, ["app", "source"])
    app_dir = resolve_app_dir(args.app, explicit_dir=getattr(args, f"{args.app}_dir", None))
    installed = copy_skill(expand(args.source), app_dir, force=args.force)
    print(f"Installed {installed.name} to {installed}")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    require_args(args, ["app", "name"])
    app_dir = resolve_app_dir(args.app, explicit_dir=getattr(args, f"{args.app}_dir", None))
    removed = remove_skill(app_dir, args.name, missing_ok=args.missing_ok)
    if removed is None:
        print(f"Skill already absent: {args.name}")
    else:
        print(f"Removed {removed.name} from {removed.parent}")
    return 0


def cmd_catalog_git(args: argparse.Namespace) -> int:
    require_args(args, ["repo"])
    repo_dir = clone_sparse(args.repo, args.ref, [args.repo_subdir], auth_from_args(args))
    try:
        skills = list_repo_skills(repo_dir, args.repo_subdir)
        payload = {
            "repo": args.repo,
            "ref": args.ref,
            "repo_subdir": args.repo_subdir,
            "skills": [path.name for path in skills],
        }
        if args.json:
            print_json(payload)
        else:
            print(f"Repo: {args.repo}")
            print(f"Subdir: {args.repo_subdir}")
            if args.ref:
                print(f"Ref: {args.ref}")
            if payload["skills"]:
                for skill in payload["skills"]:
                    print(f"  - {skill}")
            else:
                print("  (no skills found)")
        return 0
    finally:
        shutil.rmtree(repo_dir.parent, ignore_errors=True)


def cmd_install_git(args: argparse.Namespace) -> int:
    require_args(args, ["app", "repo"])
    app_dir = resolve_app_dir(args.app, explicit_dir=getattr(args, f"{args.app}_dir", None))
    copied = install_repo_skills(
        repo=args.repo,
        ref=args.ref,
        repo_subdir=args.repo_subdir,
        app_dir=app_dir,
        skill_names=args.skill,
        force=args.force,
        auth=auth_from_args(args),
    )
    print(f"Installed {len(copied)} skill(s) to {app_dir}")
    for path in copied:
        print(f"  - {path.name}")
    return 0


def cmd_sync_git(args: argparse.Namespace) -> int:
    args.skill = None
    return cmd_install_git(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Codex and OpenCode skills.")
    parser.add_argument("--config", help="Path to a TOML config file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_config = subparsers.add_parser("show-config", help="Display loaded config")
    show_config.add_argument("--json", action="store_true")
    show_config.set_defaults(func=cmd_show_config)

    list_parser = subparsers.add_parser("list", help="List installed skills")
    list_parser.add_argument("--app", choices=["codex", "opencode", "all"], default="all")
    list_parser.add_argument("--codex-dir")
    list_parser.add_argument("--opencode-dir")
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(func=cmd_list)

    install_local = subparsers.add_parser("install-local", help="Install a local skill directory")
    install_local.add_argument("--app", choices=["codex", "opencode"])
    install_local.add_argument("--source", required=True)
    install_local.add_argument("--codex-dir")
    install_local.add_argument("--opencode-dir")
    install_local.add_argument("--force", action="store_true")
    install_local.set_defaults(func=cmd_install_local)

    uninstall = subparsers.add_parser("uninstall", help="Remove an installed skill")
    uninstall.add_argument("--app", choices=["codex", "opencode"])
    uninstall.add_argument("--name", required=True)
    uninstall.add_argument("--codex-dir")
    uninstall.add_argument("--opencode-dir")
    uninstall.add_argument("--missing-ok", action="store_true")
    uninstall.set_defaults(func=cmd_uninstall)

    for command in ("catalog-git", "install-git", "sync-git"):
        git_parser = subparsers.add_parser(command, help=f"{command} against a git repo")
        if command != "catalog-git":
            git_parser.add_argument("--app", choices=["codex", "opencode"])
            git_parser.add_argument("--codex-dir")
            git_parser.add_argument("--opencode-dir")
            git_parser.add_argument("--force", action="store_true")
        git_parser.add_argument("--repo")
        git_parser.add_argument("--repo-subdir", default="skills")
        git_parser.add_argument("--ref")
        git_parser.add_argument("--username")
        git_parser.add_argument("--password")
        git_parser.add_argument("--token")
        git_parser.add_argument("--json", action="store_true")
        if command == "install-git":
            git_parser.add_argument("--skill", action="append")
        if command == "catalog-git":
            git_parser.set_defaults(func=cmd_catalog_git)
        elif command == "install-git":
            git_parser.set_defaults(func=cmd_install_git)
        else:
            git_parser.set_defaults(func=cmd_sync_git)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        loaded_config, loaded_config_path = load_config(getattr(args, "config", None))
        args.loaded_config = loaded_config
        args.loaded_config_path = loaded_config_path
        apply_config_defaults(args, loaded_config)
        return args.func(args)
    except subprocess.CalledProcessError as exc:
        print(f"Command failed: {' '.join(exc.cmd)}", file=sys.stderr)
        return exc.returncode or 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
