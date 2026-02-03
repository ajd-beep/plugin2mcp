"""plugin2mcp - Generic plugin command interception for MCP tools."""

from .schema import PluginInvocation, PluginResult
from .executor import execute
from .registry import register_postprocessor, get_postprocessor, list_postprocessors

__all__ = [
    "PluginInvocation",
    "PluginResult",
    "execute",
    "register_postprocessor",
    "get_postprocessor",
    "list_postprocessors",
]

__version__ = "0.1.0"
