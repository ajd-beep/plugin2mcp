"""Core interception logic for routing plugin commands to MCP servers.

All business logic, no I/O beyond file reads. Fully testable with tmp_path fixtures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class InterceptMatch:
    """Result of a successful interception match.

    Contains all information needed to build a systemMessage that tells
    Claude to delegate analysis to the MCP tool.
    """

    plugin_name: str  # e.g. "legal"
    command_name: str  # e.g. "review-contract"
    mcp_server_name: str  # e.g. "generate-redlined"
    mcp_tool_name: str  # e.g. "mcp__generate-redlined__execute_plugin_command"
    plugin_dir: str  # absolute path to plugin directory
    command_md_path: str  # absolute path to commands/review-contract.md
    skill_md_paths: list[str] = field(default_factory=list)  # absolute paths to skills/*/SKILL.md
    server_configured: bool = False


def parse_skill_name(skill_name: str) -> tuple[str, str] | None:
    """Split a qualified skill name into (plugin_name, command_name).

    Args:
        skill_name: e.g. "legal:review-contract"

    Returns:
        Tuple of (plugin_name, command_name) or None if not qualified.
    """
    if ":" not in skill_name:
        return None
    parts = skill_name.split(":", 1)
    if not parts[0] or not parts[1]:
        return None
    return (parts[0], parts[1])


def find_plugin_dir(
    plugin_name: str,
    plugins_root: Path | None = None,
    installed_plugins_path: Path | None = None,
) -> Path | None:
    """Search for a plugin directory by name.

    Search order:
    1. installed_plugins.json for installPath
    2. ~/.claude/plugins/knowledge-work-plugins/{name}/ (live copy)
    3. ~/.claude/plugins/cache/knowledge-work-plugins/{name}/*/ (cached)
    4. ~/.claude/plugins/marketplaces/*/plugins/{name}/ and external_plugins/{name}/

    Args:
        plugin_name: Plugin name to find (e.g. "legal")
        plugins_root: Override for ~/.claude/plugins (for testing)
        installed_plugins_path: Override for installed_plugins.json path (for testing)

    Returns:
        Path to plugin directory or None.
    """
    if plugins_root is None:
        plugins_root = Path.home() / ".claude" / "plugins"

    # 1. Check installed_plugins.json
    if installed_plugins_path is None:
        installed_plugins_path = plugins_root / "installed_plugins.json"
    if installed_plugins_path.is_file():
        try:
            data = json.loads(installed_plugins_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for _key, entry in data.items():
                    if isinstance(entry, dict):
                        name = entry.get("name", "")
                        install_path = entry.get("installPath", "")
                        if name == plugin_name and install_path:
                            p = Path(install_path)
                            if p.is_dir():
                                return p
        except (json.JSONDecodeError, OSError):
            pass

    # 2. Live copy: knowledge-work-plugins/{name}/
    live = plugins_root / "knowledge-work-plugins" / plugin_name
    if live.is_dir():
        return live

    # 3. Cache: cache/knowledge-work-plugins/{name}/*/
    cache_parent = plugins_root / "cache" / "knowledge-work-plugins" / plugin_name
    if cache_parent.is_dir():
        # Pick the latest version directory
        versions = sorted(
            [d for d in cache_parent.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )
        if versions:
            return versions[0]

    # 4. Marketplaces: marketplaces/*/plugins/{name}/ and external_plugins/{name}/
    marketplaces = plugins_root / "marketplaces"
    if marketplaces.is_dir():
        for marketplace in marketplaces.iterdir():
            if not marketplace.is_dir():
                continue
            candidate = marketplace / "plugins" / plugin_name
            if candidate.is_dir():
                return candidate
            candidate = marketplace / "external_plugins" / plugin_name
            if candidate.is_dir():
                return candidate

    return None


def read_intercepts(
    plugin_dir: Path, command_name: str
) -> tuple[str, list[str]] | None:
    """Read .mcp.json and find a server that intercepts the given command.

    Args:
        plugin_dir: Path to the plugin directory
        command_name: Command name to look for in intercepts lists

    Returns:
        Tuple of (server_name, intercepts_list) or None if no match.
    """
    mcp_json_path = plugin_dir / ".mcp.json"
    if not mcp_json_path.is_file():
        return None

    try:
        data = json.loads(mcp_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        return None

    for server_name, server_config in servers.items():
        if not isinstance(server_config, dict):
            continue
        intercepts = server_config.get("intercepts", [])
        if isinstance(intercepts, list) and command_name in intercepts:
            return (server_name, intercepts)

    return None


def resolve_paths(
    plugin_dir: Path, command_name: str
) -> tuple[str, list[str]]:
    """Resolve command markdown path and skill markdown paths from plugin directory.

    Expected structure:
        plugin_dir/
            commands/
                {command_name}.md
            skills/
                */
                    SKILL.md

    Args:
        plugin_dir: Path to the plugin directory
        command_name: Command name (e.g. "review-contract")

    Returns:
        Tuple of (command_md_path, skill_md_paths) with absolute path strings.

    Raises:
        FileNotFoundError: If command markdown file doesn't exist.
    """
    command_md = plugin_dir / "commands" / f"{command_name}.md"
    if not command_md.is_file():
        raise FileNotFoundError(
            f"Command file not found: {command_md}"
        )
    command_md_path = str(command_md.resolve())

    skill_md_paths: list[str] = []
    skills_dir = plugin_dir / "skills"
    if skills_dir.is_dir():
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if skill_md.is_file():
                skill_md_paths.append(str(skill_md.resolve()))

    return (command_md_path, skill_md_paths)


def check_server_configured(
    server_name: str,
    mcp_json_path: Path | None = None,
) -> bool:
    """Check if an MCP server is configured in the user's Claude MCP config.

    Args:
        server_name: Server name to look for (e.g. "generate-redlined")
        mcp_json_path: Override for ~/.claude/mcp.json (for testing)

    Returns:
        True if the server is configured.
    """
    if mcp_json_path is None:
        mcp_json_path = Path.home() / ".claude" / "mcp.json"

    if not mcp_json_path.is_file():
        return False

    try:
        data = json.loads(mcp_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        return False

    return server_name in servers


def find_intercept(
    skill_name: str,
    plugins_root: Path | None = None,
    installed_plugins_path: Path | None = None,
    mcp_json_path: Path | None = None,
) -> InterceptMatch | None:
    """Main entry point: find an interception match for a skill name.

    Combines parse_skill_name, find_plugin_dir, read_intercepts,
    resolve_paths, and check_server_configured.

    Args:
        skill_name: Qualified skill name (e.g. "legal:review-contract")
        plugins_root: Override for ~/.claude/plugins
        installed_plugins_path: Override for installed_plugins.json path
        mcp_json_path: Override for ~/.claude/mcp.json

    Returns:
        InterceptMatch if all lookups succeed, None otherwise.
    """
    parsed = parse_skill_name(skill_name)
    if parsed is None:
        return None

    plugin_name, command_name = parsed

    plugin_dir = find_plugin_dir(
        plugin_name,
        plugins_root=plugins_root,
        installed_plugins_path=installed_plugins_path,
    )
    if plugin_dir is None:
        return None

    intercept_result = read_intercepts(plugin_dir, command_name)
    if intercept_result is None:
        return None

    server_name, _intercepts = intercept_result

    try:
        command_md_path, skill_md_paths = resolve_paths(plugin_dir, command_name)
    except FileNotFoundError:
        return None

    server_configured = check_server_configured(
        server_name, mcp_json_path=mcp_json_path
    )

    mcp_tool_name = f"mcp__{server_name}__execute_plugin_command"

    return InterceptMatch(
        plugin_name=plugin_name,
        command_name=command_name,
        mcp_server_name=server_name,
        mcp_tool_name=mcp_tool_name,
        plugin_dir=str(plugin_dir.resolve()),
        command_md_path=command_md_path,
        skill_md_paths=skill_md_paths,
        server_configured=server_configured,
    )


def build_system_message(match: InterceptMatch) -> str:
    """Generate the systemMessage that tells Claude to delegate to the MCP tool.

    Args:
        match: A successful InterceptMatch.

    Returns:
        The systemMessage string.
    """
    skill_md_paths_json = json.dumps(match.skill_md_paths)

    return f"""IMPORTANT: Command Interception Active for /{match.command_name}

This command has an MCP interception binding. Follow this protocol:

## What You Do:
Follow the command's context-gathering workflow yourself — accept input, gather user
context, load configuration/playbook files. Do this conversationally across as many
turns as needed.

## What You Delegate:
When context gathering is complete and you are ready to begin analysis/execution,
call the MCP tool instead of performing the work yourself:

  Tool: {match.mcp_tool_name}
  Parameters:
    command_name: "{match.command_name}"
    command_md_path: "{match.command_md_path}"
    skill_md_paths: '{skill_md_paths_json}'
    source_paths: <JSON array of source file paths from the user>
    config_paths: <JSON array of playbook/config files you found>
    supplemental: <JSON object with all context gathered from the user>

## Rules:
1. Do NOT perform the analysis/execution yourself — the MCP tool handles it
2. Do NOT skip context gathering — the MCP tool needs the full context
3. After receiving the MCP tool result, present the markdown to the user and
   mention any files in output_paths
4. If the tool returns an API key error, ask the user for their Anthropic API key"""
