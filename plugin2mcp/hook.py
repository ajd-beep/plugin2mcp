"""PostToolUse hook entry point for plugin command interception.

Thin stdin/stdout wrapper invoked as: python -m plugin2mcp.hook

Reads hook input from stdin, checks if it's a qualified Skill invocation,
and outputs a systemMessage if an interception match is found.

Performance: non-intercepted commands exit in <50ms.
"""

from __future__ import annotations

import json
import sys

from .interceptor import build_system_message, find_intercept


def main() -> None:
    """Entry point for the PostToolUse hook."""
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    # Fast exit: only intercept Skill tool calls
    if hook_input.get("tool_name") != "Skill":
        sys.exit(0)

    skill_name = hook_input.get("tool_input", {}).get("skill", "")
    if not skill_name or ":" not in skill_name:
        sys.exit(0)

    match = find_intercept(skill_name)
    if match is None:
        sys.exit(0)

    msg = build_system_message(match)
    print(json.dumps({"systemMessage": msg}))


if __name__ == "__main__":
    main()
