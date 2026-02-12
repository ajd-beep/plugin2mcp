# plugin2mcp

A generic library for intercepting Claude Code/Cowork plugin commands and routing them through MCP tools with LLM call control.

## What This Does

When a user invokes a plugin command (e.g., `/my-command`), the plugin system normally:
1. Loads command instructions + skill files into Claude's context
2. Claude executes the workflow directly
3. Claude produces output

With `plugin2mcp`, you can intercept this flow:
1. Claude gathers inputs and identifies file paths
2. Claude calls your MCP tool via `plugin2mcp`
3. **Your MCP tool makes the LLM call** (with your API key, model choice, etc.)
4. Your MCP tool post-processes the response (validation, file generation, etc.)
5. Results return to Claude for presentation

## Why Use This

- **API Key Control**: Use your own Anthropic API key instead of consuming from Claude Code/Cowork plan
- **LLM Customization**: Control model selection, temperature, max tokens, retry logic
- **Response Post-Processing**: Validate outputs, generate files (DOCX, PDF), compute derived fields
- **Structured Output Enforcement**: Guarantee parseable JSON alongside markdown
- **Caching/Logging**: Track API usage, cache repeated analyses, maintain audit trails

## Automatic Command Interception (PostToolUse Hook)

plugin2mcp includes a PostToolUse hook that automatically intercepts qualified plugin commands and routes them to bound MCP servers.

### How It Works

1. User types `/my-plugin:my-command document.docx`
2. Claude's Skill tool fires and returns the command markdown
3. The PostToolUse hook fires and checks if the command has an MCP interception binding
4. If matched, a `systemMessage` tells Claude to gather context then delegate to the MCP tool
5. Claude follows the command's context-gathering workflow (accepting files, asking questions, etc.)
6. Instead of executing inline, Claude calls the bound MCP tool (e.g., `execute_plugin_command`)
7. The MCP tool assembles the prompt, calls the Claude API, post-processes, and returns results

### Setup

```bash
# Install plugin2mcp
pip install -e .

# Install the hook and configure intercepts
plugin2mcp-install install --plugin <plugin-name> --server <mcp-server> --commands <command1,command2>

# Check status
plugin2mcp-install status

# Remove intercepts for a specific server (hook removed if no bindings remain)
plugin2mcp-install uninstall --plugin <plugin-name> --server <mcp-server>

# Remove hook unconditionally
plugin2mcp-install uninstall
```

The installer:
- Adds a PostToolUse hook to `~/.claude/settings.json`
- Adds an `"intercepts"` entry to the plugin's `.mcp.json` (creates the server entry if needed)

### Intercept Configuration

Intercepts are defined in the plugin's `.mcp.json` via the `intercepts` field:

```json
{
  "mcpServers": {
    "my-mcp-server": {
      "intercepts": ["my-command"]
    }
  }
}
```

The server entry only needs the `intercepts` field — connection details (type, command, args) are configured separately via `claude mcp add`.

The `intercepts` field is a custom extension — Claude Code silently ignores unknown fields.

### Programmatic API

```python
from plugin2mcp import find_intercept, build_system_message

# Check if a skill has an interception binding
match = find_intercept("my-plugin:my-command")
if match:
    print(match.mcp_server_name)   # "my-mcp-server"
    print(match.mcp_tool_name)     # "mcp__my-mcp-server__execute_plugin_command"
    print(match.server_configured) # True if server is in ~/.claude/mcp.json

    # Build the systemMessage for Claude
    message = build_system_message(match)
```

### Cowork Tool Registration

Cowork doesn't support PostToolUse hooks. Use `register_plugin_tools()` to auto-register
Cowork-friendly tools that resolve instruction file paths at startup:

```python
from plugin2mcp import register_plugin_tools

register_plugin_tools(
    mcp_server=mcp,                          # FastMCP instance
    server_name="my-mcp-server",             # as in .mcp.json
    plugin_name="my-plugin",                 # plugin to find
    config_paths=["/path/to/config.md"],     # playbook, preferences
    descriptions={"my-command": "..."},      # tool descriptions
    get_output_requirements=my_fn,           # optional callback
)
```

This discovers the plugin directory, reads `.mcp.json` for intercepted commands,
resolves instruction file paths, and registers a tool per command (e.g., `my_command`).
If the plugin isn't installed, it logs a warning and registers nothing.

## Installation

```bash
pip install plugin2mcp
```

Or install from source:

```bash
git clone https://github.com/ajd-beep/plugin2mcp.git
cd plugin2mcp
pip install -e .
```

## Quick Start

### 1. Define a Post-Processor (Optional)

```python
from plugin2mcp import register_postprocessor, PluginResult, PluginInvocation

@register_postprocessor("my-command")
def my_command_postprocess(
    result: PluginResult,
    invocation: PluginInvocation,
) -> PluginResult:
    """Custom post-processing for my-command."""

    # Validate structured data
    if result.structured_data:
        # Your validation logic here
        pass

    # Generate output files
    if invocation.source_paths:
        output_path = generate_output(result.structured_data, invocation.source_paths[0])
        result.output_paths.append(output_path)

    return result
```

### 2. Use in Your MCP Tool

```python
from plugin2mcp import PluginInvocation, execute

# In your MCP tool handler:
invocation = PluginInvocation(
    command_name="my-command",
    command_md_path="/path/to/commands/my-command.md",
    skill_md_paths=["/path/to/skills/my-skill/SKILL.md"],
    config_paths=["/path/to/config.local.md"],
    source_paths=["/path/to/input-document.docx"],
    supplemental={
        "context_key": "context_value",
        "options": ["option1", "option2"],
    },
    api_key="sk-ant-...",  # Optional, uses ANTHROPIC_API_KEY env var if not set
)

# Define what structured output you need
output_requirements = """
#After your markdown analysis, include a JSON block with:
json
{
  "items": [...],
  "summary": "..."
}
result = execute(invocation, output_requirements)

```

### 3. Expose as MCP Tool

```python
import json
from mcp import Tool
from plugin2mcp import PluginInvocation, execute

@mcp.tool()
async def execute_plugin_command(
    command_name: str,
    command_md_path: str,
    skill_md_paths: str,  # JSON array
    source_paths: str,    # JSON array
    config_paths: str = "[]",
    supplemental: str = "{}",
    api_key: str | None = None,
    output_path: str | None = None,
) -> str:
    """Execute a plugin command with LLM call control."""

    invocation = PluginInvocation(
        command_name=command_name,
        command_md_path=command_md_path,
        skill_md_paths=json.loads(skill_md_paths),
        config_paths=json.loads(config_paths),
        source_paths=json.loads(source_paths),
        supplemental=json.loads(supplemental),
        api_key=api_key,
        output_path=output_path,
    )

    result = execute(invocation, output_requirements="...")

    return json.dumps({
        "success": result.success,
        "markdown": result.markdown,
        "output_paths": result.output_paths,
        "metadata": result.metadata,
    })
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Claude Code / Cowork                          │
│                                                                  │
│  User invokes /command                                          │
│      ↓                                                          │
│  Claude (with plugin context):                                  │
│      - Gathers user inputs                                      │
│      - Identifies file paths                                    │
│      - Calls MCP tool with PluginInvocation                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Your MCP Tool                                │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    plugin2mcp                              │  │
│  │                                                            │  │
│  │  1. Read files (command-md, skills, config, source)       │  │
│  │  2. Build LLM prompt                                       │  │
│  │  3. Make LLM call (your API key)                          │  │
│  │  4. Parse response → markdown + JSON                       │  │
│  │  5. Run registered post-processor                          │  │
│  │  6. Return PluginResult                                    │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │           Your Post-Processor (optional)                   │  │
│  │                                                            │  │
│  │  - Validate structured data                                │  │
│  │  - Generate output files (DOCX, PDF, etc.)                │  │
│  │  - Compute derived fields                                  │  │
│  │  - Custom business logic                                   │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Claude Code / Cowork                          │
│                                                                  │
│  Claude receives result:                                        │
│      - Displays markdown to user                                │
│      - Provides links to generated files                        │
└─────────────────────────────────────────────────────────────────┘
```

## API Reference

### PluginInvocation

```python
@dataclass
class PluginInvocation:
    # Required
    command_name: str           # e.g., "my-command"
    command_md_path: str        # Path to command markdown

    # Optional instruction paths
    skill_md_paths: list[str]   # Paths to skill files
    config_paths: list[str]     # Paths to config files (playbook, etc.)

    # Source material
    source_paths: list[str]     # Files to analyze

    # Runtime context
    supplemental: dict | None   # Additional context from conversation

    # LLM configuration
    api_key: str | None         # Uses ANTHROPIC_API_KEY env var if None
    model: str | None           # Defaults to claude-sonnet-4-20250514
    max_tokens: int | None      # Defaults to 16384

    # Output
    output_path: str | None     # Optional output file path
```

### PluginResult

```python
@dataclass
class PluginResult:
    markdown: str                    # Human-readable output
    structured_data: dict | None     # Parsed JSON from response
    output_paths: list[str]          # Generated file paths
    metadata: dict                   # Timing, tokens, model info
    success: bool                    # Whether execution succeeded
    error_message: str | None        # Error details if failed
```

### execute()

```python
def execute(
    invocation: PluginInvocation,
    output_requirements: str,
    system_prompt: str | None = None,
) -> PluginResult:
    """
    Execute a plugin command.

    Args:
        invocation: The command invocation details
        output_requirements: Instructions for structured output format
        system_prompt: Optional system prompt override

    Returns:
        PluginResult with markdown, structured data, and generated files
    """
```

### InterceptMatch

```python
@dataclass
class InterceptMatch:
    plugin_name: str        # e.g., "my-plugin"
    command_name: str       # e.g., "my-command"
    mcp_server_name: str    # e.g., "my-mcp-server"
    mcp_tool_name: str      # e.g., "mcp__my-mcp-server__execute_plugin_command"
    plugin_dir: str         # Absolute path to plugin directory
    command_md_path: str    # Absolute path to commands/my-command.md
    skill_md_paths: list[str]  # Absolute paths to skills/*/SKILL.md
    server_configured: bool # True if server is in ~/.claude/mcp.json
```

### find_intercept()

```python
def find_intercept(
    skill_name: str,
    plugins_root: Path | None = None,
    installed_plugins_path: Path | None = None,
    mcp_json_path: Path | None = None,
) -> InterceptMatch | None:
    """
    Find an interception match for a qualified skill name.

    Args:
        skill_name: e.g., "my-plugin:my-command"
        plugins_root: Override for ~/.claude/plugins
        installed_plugins_path: Override for installed_plugins.json
        mcp_json_path: Override for ~/.claude/mcp.json

    Returns:
        InterceptMatch if all lookups succeed, None otherwise.
    """
```

### build_system_message()

```python
def build_system_message(match: InterceptMatch) -> str:
    """
    Generate the systemMessage that tells Claude to delegate to the MCP tool.

    Returns a string suitable for the PostToolUse hook's systemMessage field.
    """
```

### @register_postprocessor()

```python
@register_postprocessor("command-name")
def my_postprocessor(
    result: PluginResult,
    invocation: PluginInvocation,
) -> PluginResult:
    """
    Post-process results for a specific command.

    Called automatically after LLM response is parsed.
    Modify result in place or return new result.
    """
```

## The LLM Prompt

`plugin2mcp` assembles the LLM prompt from the provided files:

```
A user has invoked the "{command_name}" command.

## Command Instructions
[contents of command_md_path]

## Expert Skills
[contents of each skill_md_path]

## Configuration
[contents of each config_path]

## Source Material
[contents of each source_path]

## Additional Context
[supplemental dict as JSON]

## Output Requirements
[your output_requirements string]
```

## License

MIT
