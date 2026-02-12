"""Cowork support: auto-register plugin tools with resolved instruction paths.

Cowork (Claude Desktop) doesn't support PostToolUse hooks, so it can't be told
to delegate to the MCP tool via a systemMessage. Instead, we register
Cowork-friendly tools with directive descriptions that tell Cowork to delegate
the entire analysis to the tool.

Usage from MCP servers::

    from plugin2mcp.cowork import register_plugin_tools

    register_plugin_tools(
        mcp_server=mcp,
        server_name="generate-redlined",
        plugin_name="legal",
        config_paths=["/path/to/legal.local.md"],
        descriptions={"review-contract": "Review a contract..."},
        get_output_requirements=get_output_requirements,
    )
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from .interceptor import find_plugin_dir, resolve_paths
from .executor import execute
from .schema import PluginInvocation

logger = logging.getLogger(__name__)


def list_intercepted_commands(plugin_dir: Path, server_name: str) -> list[str]:
    """List commands intercepted by a specific server in a plugin's .mcp.json.

    Args:
        plugin_dir: Path to the plugin directory containing .mcp.json
        server_name: The MCP server name to look up

    Returns:
        List of command names intercepted by this server, or empty list.
    """
    mcp_json_path = plugin_dir / ".mcp.json"
    if not mcp_json_path.is_file():
        return []

    try:
        data = json.loads(mcp_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        return []

    server_config = servers.get(server_name, {})
    if not isinstance(server_config, dict):
        return []

    intercepts = server_config.get("intercepts", [])
    if not isinstance(intercepts, list):
        return []

    return intercepts


def _make_handler(
    command_name: str,
    command_md_path: str,
    skill_md_paths: list[str],
    config_paths: list[str],
    get_output_requirements_fn: Callable[[str], str] | None = None,
    description: str | None = None,
) -> Callable:
    """Create a tool handler function for a single intercepted command.

    The returned handler has __name__ and __doc__ set for FastMCP registration.

    Args:
        command_name: The command name (e.g., "review-contract")
        command_md_path: Absolute path to the command markdown file
        skill_md_paths: Absolute paths to skill markdown files
        config_paths: Paths to config files (will be filtered to existing)
        get_output_requirements_fn: Callback to get output requirements string
        description: Tool description for FastMCP

    Returns:
        A handler function suitable for mcp_server.add_tool()
    """

    def handler(
        source_path: str,
        context: str = "{}",
        api_key: str | None = None,
        model: str | None = None,
        output_path: str | None = None,
    ) -> str:
        # Parse context JSON
        try:
            supplemental = json.loads(context)
        except (json.JSONDecodeError, TypeError) as e:
            return json.dumps({
                "success": False,
                "markdown": "",
                "output_paths": [],
                "structured_data": None,
                "metadata": {},
                "error_message": f"Invalid context JSON: {e}",
            })

        # Filter config_paths to only existing files
        valid_configs = [p for p in config_paths if Path(p).is_file()]

        # Build invocation
        invocation = PluginInvocation(
            command_name=command_name,
            command_md_path=command_md_path,
            skill_md_paths=list(skill_md_paths),
            config_paths=valid_configs,
            source_paths=[source_path],
            supplemental=supplemental if supplemental else None,
            api_key=api_key,
            model=model,
            output_path=output_path,
        )

        # Get output requirements
        if get_output_requirements_fn:
            output_requirements = get_output_requirements_fn(command_name)
        else:
            output_requirements = (
                "Produce your analysis following the Output Format "
                "in the Command Instructions."
            )

        # Execute
        result = execute(invocation, output_requirements)

        # Validate success
        success = result.success and not result.error_message

        # For review-contract, require output files
        if success and command_name == "review-contract" and not result.output_paths:
            success = False
            if not result.error_message:
                result.error_message = "No redlined document generated (internal error)"

        return json.dumps({
            "success": success,
            "markdown": result.markdown,
            "output_paths": result.output_paths,
            "structured_data": result.structured_data,
            "metadata": result.metadata,
            "error_message": result.error_message,
        }, indent=2)

    # Set function metadata for FastMCP
    tool_name = command_name.replace("-", "_")
    handler.__name__ = tool_name
    handler.__doc__ = description or f"Execute the {command_name} command."

    return handler


def register_plugin_tools(
    mcp_server: Any,
    server_name: str,
    plugin_name: str,
    config_paths: list[str] | None = None,
    descriptions: dict[str, str] | None = None,
    get_output_requirements: Callable[[str], str] | None = None,
    plugins_root: Path | None = None,
) -> list[str]:
    """Auto-discover and register Cowork-friendly tools for intercepted commands.

    Finds the plugin directory, reads .mcp.json for intercepted commands,
    resolves instruction file paths, and registers a tool for each command.

    Args:
        mcp_server: FastMCP server instance
        server_name: MCP server name (as in .mcp.json)
        plugin_name: Plugin name to find (e.g., "legal")
        config_paths: Paths to config files (playbook, etc.)
        descriptions: Map of command_name -> tool description
        get_output_requirements: Callback to get output requirements for a command
        plugins_root: Override for ~/.claude/plugins (for testing)

    Returns:
        List of registered tool names.
    """
    if config_paths is None:
        config_paths = []
    if descriptions is None:
        descriptions = {}

    registered: list[str] = []

    # Find plugin directory
    try:
        plugin_dir = find_plugin_dir(plugin_name, plugins_root=plugins_root)
    except Exception as e:
        logger.warning("Failed to find plugin '%s': %s", plugin_name, e)
        return registered

    if plugin_dir is None:
        logger.warning(
            "Plugin '%s' not found. Cowork tools will not be registered. "
            "This is normal if the plugin is not installed.",
            plugin_name,
        )
        return registered

    # List intercepted commands for this server
    commands = list_intercepted_commands(plugin_dir, server_name)
    if not commands:
        logger.warning(
            "No intercepted commands found for server '%s' in plugin '%s'",
            server_name,
            plugin_name,
        )
        return registered

    # Register a tool for each command
    for command_name in commands:
        try:
            command_md_path, skill_md_paths = resolve_paths(plugin_dir, command_name)
        except FileNotFoundError as e:
            logger.warning(
                "Skipping command '%s': %s", command_name, e,
            )
            continue

        description = descriptions.get(command_name)
        tool_name = command_name.replace("-", "_")

        handler = _make_handler(
            command_name=command_name,
            command_md_path=command_md_path,
            skill_md_paths=skill_md_paths,
            config_paths=config_paths,
            get_output_requirements_fn=get_output_requirements,
            description=description,
        )

        try:
            mcp_server.add_tool(handler, name=tool_name, description=description)
            registered.append(tool_name)
            logger.info("Registered Cowork tool: %s", tool_name)
        except Exception as e:
            logger.warning("Failed to register tool '%s': %s", tool_name, e)

    return registered
