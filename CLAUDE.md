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
├── registry.py          # Post-processor registration
├── interceptor.py       # Core interception logic (InterceptMatch, find_intercept, build_system_message)
├── cowork.py            # Cowork support: auto-register tools with resolved instruction paths
├── hook.py              # PostToolUse hook entry point (stdin/stdout, invoked as python -m plugin2mcp.hook)
├── installer.py         # CLI installer (plugin2mcp-install) for hook + intercept bindings
└── __main__.py          # Allows python -m plugin2mcp to invoke the hook
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

### Cowork Tool Registration

Cowork doesn't support PostToolUse hooks, so it can't be told to delegate via a
systemMessage. `register_plugin_tools()` auto-discovers intercepted commands, resolves
instruction file paths, and registers Cowork-friendly tools with directive descriptions:

```python
from plugin2mcp.cowork import register_plugin_tools

register_plugin_tools(
    mcp_server=mcp,
    server_name="my-mcp-server",
    plugin_name="my-plugin",
    config_paths=["/path/to/config.local.md"],
    descriptions={"my-command": "Execute my-command..."},
    get_output_requirements=get_output_requirements,
)
```

This registers tools like `my_command(source_path, context, api_key, ...)` that
internally build a `PluginInvocation` with pre-resolved paths and call `execute()`.
Graceful: logs warnings if the plugin isn't installed, never crashes the server.

### Command Interception (PostToolUse Hook)

The interception layer routes qualified plugin commands to bound MCP servers. It works
via Claude Code's PostToolUse hook system:

1. User types `/legal:review-contract contract.docx`
2. Claude's Skill tool fires, PostToolUse hook runs (`python -m plugin2mcp.hook`)
3. Hook parses skill name, finds plugin directory, reads `.mcp.json` for `intercepts`
4. If matched, outputs a `systemMessage` telling Claude to gather context then delegate
5. Claude follows the command workflow but calls the MCP tool instead of analyzing inline

**Key types:**
- `InterceptMatch`: Dataclass with all match info (plugin_name, command_name, mcp_server_name, mcp_tool_name, paths, server_configured)
- `find_intercept(skill_name)`: Main entry point — returns InterceptMatch or None
- `build_system_message(match)`: Generates the systemMessage for Claude

**Plugin directory search order** (`find_plugin_dir`):
1. `installed_plugins.json` for `installPath`
2. `~/.claude/plugins/knowledge-work-plugins/{name}/` (live copy)
3. `~/.claude/plugins/cache/knowledge-work-plugins/{name}/*/` (cached)
4. `~/.claude/plugins/marketplaces/*/plugins/{name}/` and `external_plugins/{name}/`

**Intercept configuration** lives in the plugin's `.mcp.json`:
```json
{
  "mcpServers": {
    "server-name": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "my_server"],
      "intercepts": ["review-contract"]
    }
  }
}
```

**CLI installer** (`plugin2mcp-install`):
- `install --plugin legal --server generate-redlined --commands review-contract`
- `uninstall` — removes the PostToolUse hook
- `status` — shows current hook and binding status

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
