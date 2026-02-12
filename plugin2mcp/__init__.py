"""plugin2mcp - Generic plugin command interception for MCP tools."""

from .schema import PluginInvocation, PluginResult
from .executor import execute
from .registry import register_postprocessor, get_postprocessor, list_postprocessors
from .interceptor import InterceptMatch, find_intercept, build_system_message
from .cowork import register_plugin_tools

__all__ = [
    "PluginInvocation",
    "PluginResult",
    "execute",
    "register_postprocessor",
    "get_postprocessor",
    "list_postprocessors",
    "InterceptMatch",
    "find_intercept",
    "build_system_message",
    "register_plugin_tools",
]

__version__ = "0.1.0"
