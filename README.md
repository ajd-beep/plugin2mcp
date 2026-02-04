# plugin2mcp

A generic library for intercepting Claude Code/Cowork plugin commands and routing them through MCP tools with LLM call control.

## What This Does

When a user invokes a plugin command (e.g., `/review-contract`), the plugin system normally:
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

## Installation

```bash
pip install plugin2mcp
```

Or install from source:

```bash
git clone https://github.com/yourorg/plugin2mcp.git
cd plugin2mcp
pip install -e .
```

## Quick Start

### 1. Define a Post-Processor (Optional)

```python
from plugin2mcp import register_postprocessor, PluginResult, PluginInvocation

@register_postprocessor("review-contract")
def review_contract_postprocess(
    result: PluginResult,
    invocation: PluginInvocation,
) -> PluginResult:
    """Custom post-processing for review-contract command."""

    # Validate structured data
    if result.structured_data:
        # Your validation logic here
        pass

    # Generate output files
    if invocation.source_paths:
        output_path = generate_docx(result.structured_data, invocation.source_paths[0])
        result.output_paths.append(output_path)

    return result
```

### 2. Use in Your MCP Tool

```python
from plugin2mcp import PluginInvocation, execute

# In your MCP tool handler:
invocation = PluginInvocation(
    command_name="review-contract",
    command_md_path="/path/to/commands/review-contract.md",
    skill_md_paths=["/path/to/skills/contract-review/SKILL.md"],
    config_paths=["/path/to/legal.local.md"],
    source_paths=["/path/to/contract.docx"],
    supplemental={
        "side": "customer",
        "deadline": "end of week",
        "focus_areas": ["liability", "data protection"],
    },
    api_key="sk-ant-...",  # Optional, uses ANTHROPIC_API_KEY env var if not set
)

# Define what structured output you need
output_requirements = """
After your markdown analysis, include a JSON block with:
```json
{
  "clauses": [...],
  "risk_level": "high|medium|low"
}
```
"""

result = execute(invocation, output_requirements)

# result.markdown - Human-readable output
# result.structured_data - Parsed JSON
# result.output_paths - Generated files
# result.metadata - Timing, token usage, model info
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
    command_name: str           # e.g., "review-contract"
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

## Fragile Areas

If you're modifying plugin files, be aware these elements are often parsed by MCP tools:

| Element | Example | Impact if Changed |
|---------|---------|-------------------|
| Severity indicators | GREEN, YELLOW, RED | Post-processors may expect specific values |
| Priority tiers | Must-have, Should-have, Nice-to-have | Schema validation may fail |
| Output format markers | `## Key Findings`, `### Clause` | JSON extraction may fail |

**Safe to modify:**
- Playbook positions and thresholds
- Clause analysis guidance
- Examples and explanations
- Workflow steps (as long as output format preserved)

## Examples

See the `/examples` directory:
- `legal_contract_review/` - Contract review with DOCX generation
- `code_review/` - Code review with GitHub integration
- `document_summary/` - Generic document summarization

## License

MIT
