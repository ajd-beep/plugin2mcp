# plugin2mcp - Development Guide

## What This Is

A generic library for intercepting Claude Code/Cowork plugin commands and routing them through MCP tools with LLM call control. This allows MCP tools to:

1. Use their own API keys instead of consuming from Claude Code/Cowork plan
2. Control LLM parameters (model, temperature, max_tokens)
3. Post-process responses (validation, file generation, derived fields)
4. Guarantee structured output alongside markdown

## Module Structure

```
plugin2mcp/
├── __init__.py          # Public API exports
├── schema.py            # PluginInvocation, PluginResult dataclasses
├── prompt_builder.py    # Assembles LLM prompt from file paths
├── executor.py          # Makes LLM call, parses response, runs post-processor
└── registry.py          # Post-processor registration
```

## Key Concepts

### PluginInvocation

Captures everything needed to execute a plugin command:
- `command_name`: Which command (e.g., "review-contract")
- `command_md_path`: Path to command instructions
- `skill_md_paths`: Paths to skill files (domain expertise)
- `config_paths`: Paths to user config (playbook, preferences)
- `source_paths`: Paths to files being analyzed
- `supplemental`: Runtime context from conversation
- LLM config: `api_key`, `model`, `max_tokens`

### PluginResult

What comes back:
- `markdown`: Human-readable output
- `structured_data`: Parsed JSON from response
- `output_paths`: Generated files (DOCX, PDF, etc.)
- `metadata`: Timing, token usage, model info
- `success`, `error_message`: Status

### Post-Processors

Register command-specific handlers that run after LLM response:

```python
@register_postprocessor("review-contract")
def my_handler(result: PluginResult, invocation: PluginInvocation) -> PluginResult:
    # Validate, generate files, compute fields
    return result
```

### Source Readers

Register handlers for different file types:

```python
@register_source_reader(".docx")
def read_docx(path: Path) -> str:
    # Extract text from docx
    return text
```

## How to Use as a Library

```python
# In your MCP tool
from plugin2mcp import PluginInvocation, execute, register_postprocessor

# 1. Register your post-processor (if any)
@register_postprocessor("your-command")
def your_postprocessor(result, invocation):
    # Custom logic
    return result

# 2. Build invocation from MCP tool inputs
invocation = PluginInvocation(
    command_name="your-command",
    command_md_path="/path/to/command.md",
    skill_md_paths=["/path/to/skill.md"],
    source_paths=["/path/to/source.txt"],
    api_key="sk-ant-...",  # or None to use env var
)

# 3. Execute
result = execute(invocation, output_requirements="Your JSON schema instructions")

# 4. Return result to Claude
return {
    "markdown": result.markdown,
    "output_paths": result.output_paths,
}
```

## Testing

```bash
cd plugin2mcp
pip install -e ".[dev]"
pytest
```

## API Key Configuration

When an MCP server using plugin2mcp is spawned by Claude Code/Cowork, the parent
process injects its own environment variables (including `ANTHROPIC_API_KEY`). These
may contain empty values or OAuth session tokens that are incompatible with direct
Anthropic API calls.

plugin2mcp's executor validates API keys before passing them to the SDK and rejects
known-incompatible formats (e.g., `sk-ant-oat*` OAuth tokens) with clear error
messages.

To set a persistent API key for your MCP server, use the `env` block in your
`mcp.json` configuration:

```json
{
  "mcpServers": {
    "your-server": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "your_package.cli", "--mcp"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-api-your-key-here"
      }
    }
  }
}
```

This overrides whatever the parent process injects and is the cleanest way to provide
a dedicated API key for the MCP tool.

## Dependencies

- `anthropic`: Claude API client
- `pydantic`: Data validation (used by consumers, not core)

Optional:
- `python-docx`: For .docx source reading
- `pypdf`: For .pdf source reading
