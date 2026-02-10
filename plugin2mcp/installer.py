"""CLI installer for plugin2mcp PostToolUse hook and intercept bindings.

Commands:
    plugin2mcp-install install --plugin legal --server generate-redlined --commands review-contract
    plugin2mcp-install uninstall --plugin legal --server generate-redlined
    plugin2mcp-install uninstall          # removes hook only (no intercept cleanup)
    plugin2mcp-install status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HOOK_ENTRY = {
    "matcher": "Skill",
    "hooks": [
        {
            "type": "command",
            "command": "python -m plugin2mcp.hook",
            "timeout": 10,
        }
    ],
}


def get_settings_path() -> Path:
    """Return path to ~/.claude/settings.json."""
    return Path.home() / ".claude" / "settings.json"


def load_json(path: Path) -> dict:
    """Load JSON from a file, returning empty dict if not found."""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_json(path: Path, data: dict) -> None:
    """Save JSON to a file, creating parent directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def install_hook(settings_path: Path | None = None) -> bool:
    """Add PostToolUse hook to settings.json. Idempotent.

    Returns True if the hook was added or already present.
    """
    if settings_path is None:
        settings_path = get_settings_path()

    settings = load_json(settings_path)

    hooks = settings.setdefault("hooks", {})
    post_tool_use = hooks.setdefault("PostToolUse", [])

    # Check if our hook is already installed
    for entry in post_tool_use:
        if entry.get("matcher") == "Skill":
            for h in entry.get("hooks", []):
                if "plugin2mcp.hook" in h.get("command", ""):
                    return True  # already installed

    post_tool_use.append(HOOK_ENTRY)
    save_json(settings_path, settings)
    return True


def uninstall_hook(settings_path: Path | None = None) -> bool:
    """Remove PostToolUse hook from settings.json.

    Returns True if the hook was removed or wasn't present.
    """
    if settings_path is None:
        settings_path = get_settings_path()

    settings = load_json(settings_path)

    hooks = settings.get("hooks", {})
    post_tool_use = hooks.get("PostToolUse", [])

    # Filter out our hook entries
    filtered = []
    removed = False
    for entry in post_tool_use:
        if entry.get("matcher") == "Skill":
            inner_hooks = entry.get("hooks", [])
            inner_filtered = [
                h for h in inner_hooks
                if "plugin2mcp.hook" not in h.get("command", "")
            ]
            if len(inner_filtered) < len(inner_hooks):
                removed = True
            if inner_filtered:
                entry["hooks"] = inner_filtered
                filtered.append(entry)
            # else: drop the entire entry if no hooks remain
        else:
            filtered.append(entry)

    if removed:
        if filtered:
            hooks["PostToolUse"] = filtered
        else:
            hooks.pop("PostToolUse", None)
        if not hooks:
            settings.pop("hooks", None)
        save_json(settings_path, settings)

    return True


def add_intercepts(
    plugin_dir: Path,
    server_name: str,
    commands: list[str],
) -> bool:
    """Add intercepts to a plugin's .mcp.json for the given server.

    Creates the server entry if it doesn't already exist (intercept-only
    entries don't need connection details — the MCP server is registered
    separately via ``claude mcp add``).

    Args:
        plugin_dir: Path to the plugin directory containing .mcp.json
        server_name: MCP server name in the mcpServers dict
        commands: Command names to add to the intercepts list

    Returns:
        True if successful, False if .mcp.json doesn't exist and can't be created.
    """
    mcp_json_path = plugin_dir / ".mcp.json"
    data = load_json(mcp_json_path)

    servers = data.setdefault("mcpServers", {})
    server_config = servers.setdefault(server_name, {})
    existing = server_config.get("intercepts", [])
    if not isinstance(existing, list):
        existing = []

    # Merge without duplicates, preserving order
    for cmd in commands:
        if cmd not in existing:
            existing.append(cmd)

    server_config["intercepts"] = existing
    save_json(mcp_json_path, data)
    return True


def remove_intercepts(
    plugin_dir: Path,
    server_name: str,
) -> bool:
    """Remove a server's intercept entry from a plugin's .mcp.json.

    If the server entry contains only ``intercepts`` (no connection config),
    the entire entry is removed.  If it has other keys, only ``intercepts``
    is deleted.

    Args:
        plugin_dir: Path to the plugin directory containing .mcp.json
        server_name: MCP server name to remove

    Returns:
        True if the entry was found and removed, False otherwise.
    """
    mcp_json_path = plugin_dir / ".mcp.json"
    data = load_json(mcp_json_path)

    servers = data.get("mcpServers", {})
    if server_name not in servers:
        return False

    server_config = servers[server_name]
    has_only_intercepts = set(server_config.keys()) <= {"intercepts"}

    if has_only_intercepts:
        del servers[server_name]
    else:
        server_config.pop("intercepts", None)

    save_json(mcp_json_path, data)
    return True


def get_status(
    settings_path: Path | None = None,
    plugins_root: Path | None = None,
) -> dict:
    """Get current hook and intercept status.

    Returns:
        Dict with hook_installed, bindings list.
    """
    if settings_path is None:
        settings_path = get_settings_path()
    if plugins_root is None:
        plugins_root = Path.home() / ".claude" / "plugins"

    # Check hook installation
    settings = load_json(settings_path)
    hook_installed = False
    post_tool_use = settings.get("hooks", {}).get("PostToolUse", [])
    for entry in post_tool_use:
        if entry.get("matcher") == "Skill":
            for h in entry.get("hooks", []):
                if "plugin2mcp.hook" in h.get("command", ""):
                    hook_installed = True

    # Scan for intercept bindings
    bindings: list[dict[str, str | list[str]]] = []
    kwp = plugins_root / "knowledge-work-plugins"
    if kwp.is_dir():
        for plugin_dir in sorted(kwp.iterdir()):
            if not plugin_dir.is_dir():
                continue
            mcp_json_path = plugin_dir / ".mcp.json"
            if not mcp_json_path.is_file():
                continue
            data = load_json(mcp_json_path)
            for srv_name, srv_config in data.get("mcpServers", {}).items():
                if not isinstance(srv_config, dict):
                    continue
                intercepts = srv_config.get("intercepts", [])
                if intercepts:
                    bindings.append({
                        "plugin": plugin_dir.name,
                        "server": srv_name,
                        "intercepts": intercepts,
                    })

    return {
        "hook_installed": hook_installed,
        "bindings": bindings,
    }


def _find_all_plugin_dirs(plugin_name: str, plugins_root: Path) -> list[Path]:
    """Find all copies of a plugin directory (live + cached)."""
    dirs: list[Path] = []

    # Live copy
    live = plugins_root / "knowledge-work-plugins" / plugin_name
    if live.is_dir():
        dirs.append(live)

    # Cache copies
    cache_parent = plugins_root / "cache" / "knowledge-work-plugins" / plugin_name
    if cache_parent.is_dir():
        for version_dir in cache_parent.iterdir():
            if version_dir.is_dir():
                dirs.append(version_dir)

    return dirs


def cmd_install(args: argparse.Namespace) -> int:
    """Handle the 'install' subcommand."""
    plugins_root = Path.home() / ".claude" / "plugins"

    # 1. Install the hook
    install_hook()
    print("PostToolUse hook installed in settings.json")

    # 2. Add intercepts to all copies of the plugin's .mcp.json
    if args.plugin and args.server and args.commands:
        commands = [c.strip() for c in args.commands.split(",")]
        plugin_dirs = _find_all_plugin_dirs(args.plugin, plugins_root)

        if not plugin_dirs:
            print(f"Warning: Plugin '{args.plugin}' not found in {plugins_root}")
            return 1

        for pd in plugin_dirs:
            success = add_intercepts(pd, args.server, commands)
            if success:
                print(f"Added intercepts {commands} to {pd / '.mcp.json'}")
            else:
                print(f"Warning: Server '{args.server}' not found in {pd / '.mcp.json'}")

    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    """Handle the 'uninstall' subcommand.

    With --plugin and --server: removes intercept bindings, then removes
    the hook only if no bindings remain across any plugin.
    Without args: removes the hook unconditionally.
    """
    plugins_root = Path.home() / ".claude" / "plugins"

    if getattr(args, "plugin", None) and getattr(args, "server", None):
        plugin_dirs = _find_all_plugin_dirs(args.plugin, plugins_root)
        for pd in plugin_dirs:
            if remove_intercepts(pd, args.server):
                print(f"Removed '{args.server}' intercepts from {pd / '.mcp.json'}")
            else:
                print(f"No '{args.server}' entry in {pd / '.mcp.json'}")

        # Remove hook only if no intercept bindings remain anywhere
        status = get_status(plugins_root=plugins_root)
        if not status["bindings"]:
            uninstall_hook()
            print("No intercept bindings remain — PostToolUse hook removed")
        else:
            print("Other intercept bindings still active — hook preserved")
    else:
        uninstall_hook()
        print("PostToolUse hook removed from settings.json")

    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    """Handle the 'status' subcommand."""
    status = get_status()

    print(f"Hook installed: {status['hook_installed']}")
    if status["bindings"]:
        print("Intercept bindings:")
        for b in status["bindings"]:
            print(f"  {b['plugin']} -> {b['server']}: {b['intercepts']}")
    else:
        print("No intercept bindings found")

    return 0


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="plugin2mcp-install",
        description="Install and manage plugin2mcp PostToolUse hooks",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # install
    install_parser = subparsers.add_parser(
        "install", help="Install hook and configure intercepts"
    )
    install_parser.add_argument(
        "--plugin", help="Plugin name (e.g., legal)"
    )
    install_parser.add_argument(
        "--server", help="MCP server name (e.g., generate-redlined)"
    )
    install_parser.add_argument(
        "--commands",
        help="Comma-separated command names to intercept (e.g., review-contract)",
    )

    # uninstall
    uninstall_parser = subparsers.add_parser(
        "uninstall", help="Remove intercept bindings and/or PostToolUse hook"
    )
    uninstall_parser.add_argument(
        "--plugin", help="Plugin name to remove intercepts from (e.g., legal)"
    )
    uninstall_parser.add_argument(
        "--server", help="MCP server name to remove (e.g., generate-redlined)"
    )

    # status
    subparsers.add_parser("status", help="Show current hook and binding status")

    args = parser.parse_args()

    handlers = {
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "status": cmd_status,
    }

    sys.exit(handlers[args.command](args))


if __name__ == "__main__":
    main()
