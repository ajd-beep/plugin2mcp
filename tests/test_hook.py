"""Tests for plugin2mcp.hook module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from plugin2mcp.hook import main
from plugin2mcp.interceptor import InterceptMatch


class TestHookMain:
    """Tests for the PostToolUse hook main() function."""

    def test_non_skill_tool_exits(self):
        """Non-Skill tool calls should exit silently."""
        hook_input = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        })

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = hook_input
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_unqualified_skill_exits(self):
        """Skill calls without ':' should exit silently."""
        hook_input = json.dumps({
            "tool_name": "Skill",
            "tool_input": {"skill": "commit"},
        })

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = hook_input
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_empty_skill_exits(self):
        """Empty skill name should exit silently."""
        hook_input = json.dumps({
            "tool_name": "Skill",
            "tool_input": {"skill": ""},
        })

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = hook_input
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_no_match_exits(self):
        """Qualified skill with no interception match should exit silently."""
        hook_input = json.dumps({
            "tool_name": "Skill",
            "tool_input": {"skill": "unknown:command"},
        })

        with patch("sys.stdin") as mock_stdin, \
             patch("plugin2mcp.hook.find_intercept", return_value=None):
            mock_stdin.read.return_value = hook_input
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_match_outputs_system_message(self, capsys):
        """Matching skill should output JSON with systemMessage."""
        hook_input = json.dumps({
            "tool_name": "Skill",
            "tool_input": {"skill": "legal:review-contract"},
        })

        mock_match = InterceptMatch(
            plugin_name="legal",
            command_name="review-contract",
            mcp_server_name="generate-redlined",
            mcp_tool_name="mcp__generate-redlined__execute_plugin_command",
            plugin_dir="/path/to/legal",
            command_md_path="/path/to/commands/review-contract.md",
            skill_md_paths=["/path/to/skills/analysis/SKILL.md"],
            server_configured=True,
        )

        with patch("sys.stdin") as mock_stdin, \
             patch("plugin2mcp.hook.find_intercept", return_value=mock_match):
            mock_stdin.read.return_value = hook_input
            main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "systemMessage" in output
        assert "review-contract" in output["systemMessage"]
        assert "mcp__generate-redlined__execute_plugin_command" in output["systemMessage"]

    def test_invalid_json_exits(self):
        """Invalid JSON input should exit silently."""
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "not json"
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_missing_tool_input_exits(self):
        """Missing tool_input should exit silently."""
        hook_input = json.dumps({
            "tool_name": "Skill",
        })

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = hook_input
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
