"""Assembles LLM prompts from plugin file paths."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from .schema import PluginInvocation

logger = logging.getLogger(__name__)


# Default prompt template
PROMPT_TEMPLATE = '''A user has invoked the "{command_name}" command.

## Command Instructions

{command_md_content}

## Expert Skills

{skills_md_content}

## Configuration

{config_content}

## Source Material

{source_content}

## Additional Context

{supplemental_content}

## Output Requirements

{output_requirements}
'''


# Registry for source file readers by extension
_SOURCE_READERS: dict[str, Callable[[Path], str]] = {}


def register_source_reader(extension: str):
    """Decorator to register a source file reader for a file extension.

    Usage:
        @register_source_reader(".docx")
        def read_docx(path: Path) -> str:
            # Extract text from docx
            return text

    Args:
        extension: File extension including dot (e.g., ".docx", ".pdf")
    """

    def decorator(func: Callable[[Path], str]) -> Callable[[Path], str]:
        _SOURCE_READERS[extension.lower()] = func
        return func

    return decorator


def build_prompt(
    invocation: PluginInvocation,
    output_requirements: str,
    template: str | None = None,
) -> str:
    """Build the complete LLM prompt from a PluginInvocation.

    Reads all referenced files and assembles them into the prompt template.

    Args:
        invocation: The plugin invocation with file paths
        output_requirements: Instructions for structured output format
        template: Optional custom prompt template (uses default if None)

    Returns:
        Assembled prompt string
    """
    template = template or PROMPT_TEMPLATE

    # Read command markdown
    command_md_content = _read_file(invocation.command_md_path)

    # Read and concatenate skill markdowns
    skills_parts = []
    for i, path in enumerate(invocation.skill_md_paths, 1):
        content = _read_file(path)
        name = Path(path).stem
        skills_parts.append(f"### Skill {i}: {name}\n\n{content}")
    skills_md_content = (
        "\n\n---\n\n".join(skills_parts) if skills_parts else "No skills specified."
    )

    # Read and concatenate config files
    config_parts = []
    for path in invocation.config_paths:
        content = _read_file(path)
        name = Path(path).name
        config_parts.append(f"### {name}\n\n{content}")
    config_content = (
        "\n\n---\n\n".join(config_parts)
        if config_parts
        else "No configuration provided."
    )

    # Read source files
    source_parts = []
    for path in invocation.source_paths:
        content = _read_source_file(path)
        name = Path(path).name
        source_parts.append(f"### {name}\n\n{content}")
    source_content = (
        "\n\n---\n\n".join(source_parts)
        if source_parts
        else "No source material provided."
    )

    # Format supplemental context
    if invocation.supplemental:
        supplemental_content = json.dumps(invocation.supplemental, indent=2)
    else:
        supplemental_content = "No additional context provided."

    return template.format(
        command_name=invocation.command_name,
        command_md_content=command_md_content,
        skills_md_content=skills_md_content,
        config_content=config_content,
        source_content=source_content,
        supplemental_content=supplemental_content,
        output_requirements=output_requirements,
    )


def _read_file(path: str) -> str:
    """Read a text file, return content or error message.

    Args:
        path: Path to the file

    Returns:
        File content or error message
    """
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("File not found: %s", path)
        return f"[File not found: {path}]"
    except Exception as e:
        logger.warning("Error reading %s: %s", path, e)
        return f"[Error reading {path}: {e}]"


def _read_source_file(path: str) -> str:
    """Read a source file, using registered readers for known extensions.

    Args:
        path: Path to the source file

    Returns:
        Extracted text content
    """
    path_obj = Path(path)
    suffix = path_obj.suffix.lower()

    # Check for registered reader
    if suffix in _SOURCE_READERS:
        try:
            return _SOURCE_READERS[suffix](path_obj)
        except Exception as e:
            logger.warning("Source reader failed for %s: %s", path, e)
            return f"[Error reading {path}: {e}]"

    # Default: try reading as text
    return _read_file(path)


# Built-in reader for plain text files
@register_source_reader(".txt")
@register_source_reader(".md")
@register_source_reader(".text")
@register_source_reader(".markdown")
def _read_text_file(path: Path) -> str:
    """Read plain text files."""
    return path.read_text(encoding="utf-8")


# Note: .docx and .pdf readers should be registered by consuming packages
# that have the appropriate dependencies installed.
#
# Example (in your MCP tool):
#
#     from plugin2mcp.prompt_builder import register_source_reader
#
#     @register_source_reader(".docx")
#     def read_docx(path: Path) -> str:
#         from docx import Document
#         doc = Document(path)
#         return "\n".join(p.text for p in doc.paragraphs)
