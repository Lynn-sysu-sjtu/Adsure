#!/usr/bin/env python3
"""Install reusable PKULaw MCP configuration into a Codex project.

This script intentionally never accepts or writes a token. Codex reads the
token from PKULAW_MCP_TOKEN when it starts.
"""

import argparse
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Dict, List, Optional, Sequence, Tuple


TOKEN_ENV_VAR = "PKULAW_MCP_TOKEN"
SERVER_GROUPS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "law": (
        (
            "pkulaw-law-semantic",
            "https://apim-gateway.pkulaw.com/mcp-law-search-service",
        ),
        (
            "pkulaw-law-keyword",
            "https://apim-gateway.pkulaw.com/mcp-law",
        ),
    ),
    "case": (
        (
            "pkulaw-case-semantic",
            "https://apim-gateway.pkulaw.com/mcp-case-search-service",
        ),
        (
            "pkulaw-case-keyword",
            "https://apim-gateway.pkulaw.com/mcp-case",
        ),
    ),
}

SECTION_PATTERN = re.compile(
    r"""^\s*\[mcp_servers\.(?:"([^"]+)"|'([^']+)'|([A-Za-z0-9_-]+))\]"""
    r"\s*(?:#.*)?$",
    flags=re.MULTILINE,
)


def selected_servers(group: str) -> Tuple[Tuple[str, str], ...]:
    if group == "all":
        return SERVER_GROUPS["law"] + SERVER_GROUPS["case"]
    return SERVER_GROUPS[group]


def configured_server_names(config_text: str) -> set:
    return {
        next(group for group in match.groups() if group is not None)
        for match in SECTION_PATTERN.finditer(config_text)
    }


def section_body(config_text: str, server_name: str) -> str:
    match = re.search(
        rf"""^\s*\[mcp_servers\.(?:"{re.escape(server_name)}"|'"""
        rf"""{re.escape(server_name)}'|{re.escape(server_name)})\]"""
        rf"\s*(?:#.*)?$\n"
        rf"(?P<body>.*?)(?=^\s*\[|\Z)",
        config_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def render_server_block(servers: Sequence[Tuple[str, str]]) -> str:
    parts = [
        "# BEGIN PKULAW MCP - managed by tools/pkulaw_mcp/install.py",
        "# Credentials are read from PKULAW_MCP_TOKEN; never put a token here.",
    ]
    for name, url in servers:
        parts.extend(
            [
                "",
                f"[mcp_servers.{name}]",
                f'url = "{url}"',
                f'bearer_token_env_var = "{TOKEN_ENV_VAR}"',
                "enabled = true",
                "required = false",
                "startup_timeout_sec = 20",
                "tool_timeout_sec = 60",
            ]
        )
    parts.extend(["", "# END PKULAW MCP"])
    return "\n".join(parts)


def merged_config(config_text: str, servers: Sequence[Tuple[str, str]]) -> Tuple[str, List[str]]:
    existing = configured_server_names(config_text)
    missing = [(name, url) for name, url in servers if name not in existing]
    if not missing:
        return config_text, []

    block = render_server_block(missing)
    prefix = config_text.rstrip()
    merged = f"{prefix}\n\n{block}\n" if prefix else f"{block}\n"
    return merged, [name for name, _ in missing]


def write_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError(f"Refusing to replace symlink: {path}")

    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary_name = temporary.name
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def install(project: Path, group: str, dry_run: bool = False) -> List[str]:
    project = project.expanduser().resolve()
    if not project.exists() or not project.is_dir():
        raise RuntimeError(f"Project directory does not exist: {project}")

    config_path = project / ".codex" / "config.toml"
    if config_path.parent.is_symlink():
        raise RuntimeError(f"Refusing to write through symlink: {config_path.parent}")
    config_text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    merged, added = merged_config(config_text, selected_servers(group))

    if dry_run:
        print(merged, end="")
    elif added:
        write_atomically(config_path, merged)

    return added


def audit_config(project: Path, group: str) -> List[str]:
    config_path = project.expanduser().resolve() / ".codex" / "config.toml"
    if not config_path.exists():
        return [f"missing config: {config_path}"]

    config_text = config_path.read_text(encoding="utf-8")
    issues: List[str] = []
    for name, expected_url in selected_servers(group):
        body = section_body(config_text, name)
        if not body:
            issues.append(f"{name}: missing")
            continue
        if f'url = "{expected_url}"' not in body:
            issues.append(f"{name}: unexpected URL")
        if f'bearer_token_env_var = "{TOKEN_ENV_VAR}"' not in body:
            issues.append(f"{name}: environment-token authentication missing")
        if re.search(r"^\s*http_headers\s*=", body, flags=re.MULTILINE):
            issues.append(f"{name}: static http_headers found; review for hard-coded secrets")

    if not os.environ.get(TOKEN_ENV_VAR):
        issues.append(f"{TOKEN_ENV_VAR}: not set in this process")
    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely add PKULaw law and case MCP servers to a Codex project."
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="Target project directory (default: current directory).",
    )
    parser.add_argument(
        "--services",
        choices=("all", "law", "case"),
        default="all",
        help="Service group to configure (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the merged config without writing it.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check local configuration and token presence without network calls.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.check:
            issues = audit_config(args.project, args.services)
            if issues:
                for issue in issues:
                    print(f"[FAIL] {issue}")
                return 1
            print("[OK] PKULaw MCP configuration and token environment are ready.")
            return 0

        added = install(args.project, args.services, args.dry_run)
        if args.dry_run:
            return 0
        if added:
            print("Added MCP servers: " + ", ".join(added))
        else:
            print("No changes: requested PKULaw MCP servers already exist.")
        print(f"Token was not written. Set {TOKEN_ENV_VAR}, then restart Codex.")
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
