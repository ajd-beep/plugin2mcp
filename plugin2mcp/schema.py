"""Data structures for plugin command interception."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginInvocation:
    """Universal payload for intercepting plugin command execution.

    This dataclass captures everything needed to execute a plugin command
    via an MCP tool instead of directly in Claude's context.

    Attributes:
        command_name: Name of the command being invoked (e.g., "review-contract")
        command_md_path: Path to the command's markdown instruction file
        skill_md_paths: Paths to skill markdown files providing domain expertise
        config_paths: Paths to user configuration files (playbook, preferences)
        source_paths: Paths to files being analyzed/processed
        source_texts: Raw text content to analyze (alternative to source_paths)
        supplemental: Additional runtime context from the conversation
        api_key: Anthropic API key (uses ANTHROPIC_API_KEY env var if None)
        model: Model to use (defaults to claude-sonnet-4-20250514)
        max_tokens: Maximum tokens for response (defaults to 16384)
        output_path: Optional path for generated output file
        plugin_name: Optional plugin identifier for logging/routing
    """

    # Required
    command_name: str
    command_md_path: str

    # Instruction paths
    skill_md_paths: list[str] = field(default_factory=list)
    config_paths: list[str] = field(default_factory=list)

    # Source material
    source_paths: list[str] = field(default_factory=list)
    source_texts: list[str] = field(default_factory=list)

    # Runtime context
    supplemental: dict[str, Any] | None = None

    # LLM configuration
    api_key: str | None = None
    model: str | None = None
    max_tokens: int | None = None

    # Output configuration
    output_path: str | None = None

    # Optional metadata
    plugin_name: str | None = None


@dataclass
class PluginResult:
    """Result from plugin command execution.

    Attributes:
        markdown: Human-readable output following the command's output format
        structured_data: Parsed JSON data extracted from the response
        output_paths: Paths to any generated files (DOCX, PDF, etc.)
        metadata: Execution metadata (timing, token usage, model info)
        success: Whether execution completed successfully
        error_message: Error details if execution failed
    """

    # Primary outputs
    markdown: str = ""
    structured_data: dict[str, Any] | None = None

    # Generated files
    output_paths: list[str] = field(default_factory=list)

    # Execution metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    # Status
    success: bool = True
    error_message: str | None = None
