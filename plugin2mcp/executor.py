"""Executes LLM calls and parses responses."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import anthropic

from .prompt_builder import build_prompt
from .registry import get_postprocessor
from .schema import PluginInvocation, PluginResult

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 16384


def _resolve_api_key(api_key: str | None) -> tuple[str | None, str | None]:
    """Resolve and validate an API key for direct Anthropic API calls.

    Mirrors the Anthropic SDK's resolution logic (explicit arg -> env var)
    but adds detection of known-incompatible token formats before the SDK
    sees them.

    Args:
        api_key: Explicitly provided key, or None to check env var.

    Returns:
        (resolved_key, error_message): If error_message is non-None, the
        caller should abort with that message.
    """
    import os

    resolved = api_key.strip() if api_key and api_key.strip() else None

    if resolved is None:
        env_val = os.environ.get("ANTHROPIC_API_KEY", "")
        if env_val.strip():
            resolved = env_val.strip()

    if not resolved:
        return None, (
            "No Anthropic API key found. plugin2mcp requires a direct API key "
            "for LLM calls. Set ANTHROPIC_API_KEY or pass api_key explicitly."
        )

    # Detect Claude Code/Cowork OAuth tokens — these are session tokens
    # that don't work with anthropic.Anthropic(api_key=...).
    if resolved.startswith("sk-ant-oat"):
        return None, (
            "The resolved API key appears to be a Claude Code/Cowork OAuth "
            "session token (sk-ant-oat...), not a direct Anthropic API key. "
            "plugin2mcp requires a standard API key (sk-ant-api...). "
            "Provide one via the api_key parameter or set ANTHROPIC_API_KEY."
        )

    return resolved, None


def execute(
    invocation: PluginInvocation,
    output_requirements: str,
    system_prompt: str | None = None,
    prompt_template: str | None = None,
) -> PluginResult:
    """Execute a plugin command via LLM call.

    This is the main entry point for plugin2mcp. It:
    1. Builds the prompt from the invocation
    2. Makes the LLM call (using provided or env API key)
    3. Parses the response into markdown and structured data
    4. Runs any registered post-processor
    5. Returns the result

    Args:
        invocation: The plugin invocation with all paths and context
        output_requirements: Instructions for structured output format to append to prompt
        system_prompt: Optional system prompt (uses default if None)
        prompt_template: Optional custom prompt template

    Returns:
        PluginResult with markdown, structured data, and metadata
    """
    start_time = time.time()

    # Build the prompt
    try:
        user_prompt = build_prompt(invocation, output_requirements, prompt_template)
    except Exception as e:
        logger.exception("Failed to build prompt")
        return PluginResult(
            success=False,
            error_message=f"Prompt building failed: {e}",
            metadata={"elapsed_seconds": time.time() - start_time},
        )

    # Configure LLM call
    model = invocation.model or DEFAULT_MODEL
    max_tokens = invocation.max_tokens or DEFAULT_MAX_TOKENS

    # Resolve and validate API key before expensive SDK call
    resolved_key, key_error = _resolve_api_key(invocation.api_key)
    if key_error:
        return PluginResult(
            success=False,
            error_message=key_error,
            metadata={"elapsed_seconds": time.time() - start_time},
        )

    # Make LLM call
    try:
        client = anthropic.Anthropic(api_key=resolved_key)

        messages = [{"role": "user", "content": user_prompt}]

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        logger.info(
            "Making LLM call for command '%s' with model '%s'",
            invocation.command_name,
            model,
        )
        response = client.messages.create(**kwargs)
        response_text = response.content[0].text

    except anthropic.AuthenticationError as e:
        return PluginResult(
            success=False,
            error_message=f"Authentication failed: {e}. Check your API key.",
            metadata={"elapsed_seconds": time.time() - start_time},
        )
    except anthropic.APIError as e:
        logger.exception("LLM API error")
        return PluginResult(
            success=False,
            error_message=f"LLM API error: {e}",
            metadata={"elapsed_seconds": time.time() - start_time},
        )
    except TypeError as e:
        if "Could not resolve authentication" in str(e):
            return PluginResult(
                success=False,
                error_message=(
                    f"Anthropic SDK could not resolve authentication: {e}. "
                    "Provide a valid API key via api_key parameter or "
                    "ANTHROPIC_API_KEY environment variable."
                ),
                metadata={"elapsed_seconds": time.time() - start_time},
            )
        raise  # Re-raise if it's an unrelated TypeError

    # Parse response into markdown and structured data
    markdown, structured_data = _parse_response(response_text)

    # Build initial result
    result = PluginResult(
        markdown=markdown,
        structured_data=structured_data,
        metadata={
            "model": model,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "elapsed_seconds": time.time() - start_time,
            "command_name": invocation.command_name,
        },
    )

    # Run post-processor if registered
    postprocessor = get_postprocessor(invocation.command_name)
    if postprocessor:
        logger.info(
            "Running post-processor for command '%s'", invocation.command_name
        )
        try:
            result = postprocessor(result, invocation)
        except Exception as e:
            logger.exception(
                "Post-processor failed for %s", invocation.command_name
            )
            # Keep the LLM result but note the post-processing error
            result.error_message = f"Post-processing error: {e}"
            # Don't set success=False since LLM call succeeded

    # Update elapsed time to include post-processing
    result.metadata["elapsed_seconds"] = time.time() - start_time

    return result


def _parse_response(response_text: str) -> tuple[str, dict[str, Any] | None]:
    """Parse LLM response into markdown and structured JSON.

    Expects response to contain markdown followed by a JSON block.
    The JSON block may be:
    - In a ```json code fence
    - After a marker like "## Structured Data" or "## JSON Output"

    Args:
        response_text: Raw LLM response text

    Returns:
        Tuple of (markdown_text, structured_data_dict_or_none)
    """
    # Strategy 1: Find JSON block in code fence
    json_match = re.search(r"```json\s*\n(.*?)\n```", response_text, re.DOTALL)

    if json_match:
        json_str = json_match.group(1)
        # Markdown is everything before the JSON block
        markdown = response_text[: json_match.start()].strip()
        try:
            structured_data = json.loads(json_str)
            logger.debug("Parsed JSON from code fence")
            return markdown, structured_data
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse JSON block: %s", e)
            # Fall through to try other strategies

    # Strategy 2: Find JSON after known markers
    markers = [
        "## Structured Data",
        "## JSON Output",
        "## Structured JSON",
        "## JSON",
        "---\n\n{",  # Common separator before JSON
    ]

    for marker in markers:
        if marker in response_text:
            parts = response_text.split(marker, 1)
            markdown = parts[0].strip()
            json_part = parts[1].strip()

            # Try to extract JSON object from the remaining text
            # Look for the outermost { } pair
            brace_start = json_part.find("{")
            if brace_start >= 0:
                # Find matching closing brace
                depth = 0
                for i, char in enumerate(json_part[brace_start:], brace_start):
                    if char == "{":
                        depth += 1
                    elif char == "}":
                        depth -= 1
                        if depth == 0:
                            json_str = json_part[brace_start : i + 1]
                            try:
                                structured_data = json.loads(json_str)
                                logger.debug("Parsed JSON after marker '%s'", marker)
                                return markdown, structured_data
                            except json.JSONDecodeError:
                                pass
                            break

    # Strategy 3: Try to find any JSON object at the end of the response
    # (Some LLMs just append JSON without markers)
    last_brace = response_text.rfind("}")
    if last_brace > 0:
        # Walk backwards to find the matching opening brace
        depth = 0
        for i in range(last_brace, -1, -1):
            if response_text[i] == "}":
                depth += 1
            elif response_text[i] == "{":
                depth -= 1
                if depth == 0:
                    json_str = response_text[i : last_brace + 1]
                    try:
                        structured_data = json.loads(json_str)
                        markdown = response_text[:i].strip()
                        logger.debug("Parsed JSON from end of response")
                        return markdown, structured_data
                    except json.JSONDecodeError:
                        pass
                    break

    # No structured data found; entire response is markdown
    logger.debug("No structured JSON found in response")
    return response_text, None
