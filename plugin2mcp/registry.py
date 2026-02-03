"""Registry for command-specific post-processors."""

from __future__ import annotations

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .schema import PluginInvocation, PluginResult

# Type alias for post-processor functions
PostProcessor = Callable[["PluginResult", "PluginInvocation"], "PluginResult"]

# Registry mapping command names to post-processors
_REGISTRY: dict[str, PostProcessor] = {}


def register_postprocessor(command_name: str):
    """Decorator to register a post-processor for a command.

    Usage:
        @register_postprocessor("review-contract")
        def my_postprocessor(result: PluginResult, invocation: PluginInvocation) -> PluginResult:
            # Custom post-processing logic
            return result

    Args:
        command_name: The command this post-processor handles

    Returns:
        Decorator function
    """

    def decorator(func: PostProcessor) -> PostProcessor:
        _REGISTRY[command_name] = func
        return func

    return decorator


def get_postprocessor(command_name: str) -> PostProcessor | None:
    """Look up the post-processor for a command.

    Args:
        command_name: The command to look up

    Returns:
        The registered post-processor, or None if not registered
    """
    return _REGISTRY.get(command_name)


def list_postprocessors() -> list[str]:
    """List all registered command names.

    Returns:
        List of command names with registered post-processors
    """
    return list(_REGISTRY.keys())


def clear_registry() -> None:
    """Clear all registered post-processors. Primarily for testing."""
    _REGISTRY.clear()
