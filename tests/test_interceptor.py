"""Tests for plugin2mcp.interceptor module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugin2mcp.interceptor import (
    InterceptMatch,
    build_system_message,
    check_server_configured,
    find_intercept,
    find_plugin_dir,
    parse_skill_name,
    read_intercepts,
    resolve_paths,
)


# ---------------------------------------------------------------------------
# parse_skill_name
# ---------------------------------------------------------------------------

class TestParseSkillName:
    def test_qualified_name(self):
        assert parse_skill_name("legal:review-contract") == ("legal", "review-contract")

    def test_unqualified_name(self):
        assert parse_skill_name("review-contract") is None

    def test_empty_string(self):
        assert parse_skill_name("") is None

    def test_colon_only(self):
        assert parse_skill_name(":") is None

    def test_empty_plugin(self):
        assert parse_skill_name(":review-contract") is None

    def test_empty_command(self):
        assert parse_skill_name("legal:") is None

    def test_multiple_colons(self):
        result = parse_skill_name("org:plugin:command")
        assert result == ("org", "plugin:command")


# ---------------------------------------------------------------------------
# find_plugin_dir
# ---------------------------------------------------------------------------

class TestFindPluginDir:
    def test_installed_plugins_json(self, tmp_path: Path):
        """Find plugin via installed_plugins.json."""
        plugin_dir = tmp_path / "my-plugin"
        plugin_dir.mkdir()

        installed = tmp_path / "installed_plugins.json"
        installed.write_text(json.dumps({
            "my-plugin": {
                "name": "my-plugin",
                "installPath": str(plugin_dir),
            }
        }))

        result = find_plugin_dir(
            "my-plugin",
            plugins_root=tmp_path,
            installed_plugins_path=installed,
        )
        assert result == plugin_dir

    def test_live_copy(self, tmp_path: Path):
        """Find plugin in knowledge-work-plugins/ live directory."""
        live = tmp_path / "knowledge-work-plugins" / "legal"
        live.mkdir(parents=True)

        result = find_plugin_dir("legal", plugins_root=tmp_path)
        assert result == live

    def test_cache_copy(self, tmp_path: Path):
        """Find plugin in cache, picks latest version."""
        cache = tmp_path / "cache" / "knowledge-work-plugins" / "legal"
        v1 = cache / "1.0.0"
        v2 = cache / "2.0.0"
        v1.mkdir(parents=True)
        v2.mkdir(parents=True)

        result = find_plugin_dir("legal", plugins_root=tmp_path)
        assert result == v2

    def test_marketplace(self, tmp_path: Path):
        """Find plugin in marketplaces/*/plugins/."""
        mp = tmp_path / "marketplaces" / "default" / "plugins" / "legal"
        mp.mkdir(parents=True)

        result = find_plugin_dir("legal", plugins_root=tmp_path)
        assert result == mp

    def test_marketplace_external(self, tmp_path: Path):
        """Find plugin in marketplaces/*/external_plugins/."""
        ep = tmp_path / "marketplaces" / "default" / "external_plugins" / "legal"
        ep.mkdir(parents=True)

        result = find_plugin_dir("legal", plugins_root=tmp_path)
        assert result == ep

    def test_not_found(self, tmp_path: Path):
        result = find_plugin_dir("nonexistent", plugins_root=tmp_path)
        assert result is None

    def test_live_preferred_over_cache(self, tmp_path: Path):
        """Live copy is found first (before cache)."""
        live = tmp_path / "knowledge-work-plugins" / "legal"
        live.mkdir(parents=True)
        cache = tmp_path / "cache" / "knowledge-work-plugins" / "legal" / "1.0.0"
        cache.mkdir(parents=True)

        result = find_plugin_dir("legal", plugins_root=tmp_path)
        assert result == live


# ---------------------------------------------------------------------------
# read_intercepts
# ---------------------------------------------------------------------------

class TestReadIntercepts:
    def test_matching_command(self, tmp_path: Path):
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "my-server": {
                    "type": "stdio",
                    "command": "python",
                    "args": ["-m", "my_server"],
                    "intercepts": ["review-contract", "draft-contract"],
                }
            }
        }))

        result = read_intercepts(tmp_path, "review-contract")
        assert result == ("my-server", ["review-contract", "draft-contract"])

    def test_no_matching_command(self, tmp_path: Path):
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "my-server": {
                    "intercepts": ["other-command"],
                }
            }
        }))

        result = read_intercepts(tmp_path, "review-contract")
        assert result is None

    def test_no_intercepts_field(self, tmp_path: Path):
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "my-server": {
                    "type": "stdio",
                }
            }
        }))

        result = read_intercepts(tmp_path, "review-contract")
        assert result is None

    def test_no_mcp_json(self, tmp_path: Path):
        result = read_intercepts(tmp_path, "review-contract")
        assert result is None

    def test_invalid_json(self, tmp_path: Path):
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text("not valid json")

        result = read_intercepts(tmp_path, "review-contract")
        assert result is None

    def test_multiple_servers_first_match(self, tmp_path: Path):
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "server-a": {
                    "intercepts": ["other"],
                },
                "server-b": {
                    "intercepts": ["review-contract"],
                },
            }
        }))

        result = read_intercepts(tmp_path, "review-contract")
        assert result is not None
        assert result[0] == "server-b"


# ---------------------------------------------------------------------------
# resolve_paths
# ---------------------------------------------------------------------------

class TestResolvePaths:
    def test_basic_resolution(self, tmp_path: Path):
        cmd_dir = tmp_path / "commands"
        cmd_dir.mkdir()
        cmd_md = cmd_dir / "review-contract.md"
        cmd_md.write_text("# Review Contract")

        skills_dir = tmp_path / "skills"
        skill_a = skills_dir / "contract-analysis"
        skill_a.mkdir(parents=True)
        (skill_a / "SKILL.md").write_text("# Skill A")

        skill_b = skills_dir / "redlining"
        skill_b.mkdir(parents=True)
        (skill_b / "SKILL.md").write_text("# Skill B")

        cmd_path, skill_paths = resolve_paths(tmp_path, "review-contract")

        assert cmd_path == str(cmd_md.resolve())
        assert len(skill_paths) == 2
        assert str((skill_a / "SKILL.md").resolve()) in skill_paths
        assert str((skill_b / "SKILL.md").resolve()) in skill_paths

    def test_no_skills_directory(self, tmp_path: Path):
        cmd_dir = tmp_path / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "my-command.md").write_text("# My Command")

        cmd_path, skill_paths = resolve_paths(tmp_path, "my-command")
        assert cmd_path.endswith("my-command.md")
        assert skill_paths == []

    def test_missing_command_file(self, tmp_path: Path):
        cmd_dir = tmp_path / "commands"
        cmd_dir.mkdir()

        with pytest.raises(FileNotFoundError):
            resolve_paths(tmp_path, "nonexistent")

    def test_skill_dir_without_skill_md(self, tmp_path: Path):
        """Skill directories without SKILL.md are skipped."""
        cmd_dir = tmp_path / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "test-cmd.md").write_text("# Test")

        skills_dir = tmp_path / "skills"
        (skills_dir / "has-skill").mkdir(parents=True)
        (skills_dir / "has-skill" / "SKILL.md").write_text("# Skill")
        (skills_dir / "no-skill").mkdir(parents=True)
        # no SKILL.md in no-skill/

        _cmd_path, skill_paths = resolve_paths(tmp_path, "test-cmd")
        assert len(skill_paths) == 1


# ---------------------------------------------------------------------------
# check_server_configured
# ---------------------------------------------------------------------------

class TestCheckServerConfigured:
    def test_server_present(self, tmp_path: Path):
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "generate-redlined": {
                    "type": "stdio",
                }
            }
        }))

        assert check_server_configured("generate-redlined", mcp_json_path=mcp_json) is True

    def test_server_absent(self, tmp_path: Path):
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "other-server": {},
            }
        }))

        assert check_server_configured("generate-redlined", mcp_json_path=mcp_json) is False

    def test_no_file(self, tmp_path: Path):
        assert check_server_configured(
            "generate-redlined",
            mcp_json_path=tmp_path / "mcp.json",
        ) is False


# ---------------------------------------------------------------------------
# find_intercept (integration)
# ---------------------------------------------------------------------------

class TestFindIntercept:
    def _setup_plugin(self, tmp_path: Path, plugin_name: str = "legal"):
        """Create a minimal plugin directory structure."""
        plugins_root = tmp_path / "plugins"
        plugin_dir = plugins_root / "knowledge-work-plugins" / plugin_name
        plugin_dir.mkdir(parents=True)

        # .mcp.json
        (plugin_dir / ".mcp.json").write_text(json.dumps({
            "mcpServers": {
                "generate-redlined": {
                    "type": "stdio",
                    "intercepts": ["review-contract"],
                }
            }
        }))

        # commands/
        cmd_dir = plugin_dir / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "review-contract.md").write_text("# Review")

        # skills/
        skills_dir = plugin_dir / "skills" / "analysis"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("# Analysis")

        # mcp.json (user config)
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "generate-redlined": {"type": "stdio"},
            }
        }))

        return plugins_root, mcp_json

    def test_full_match(self, tmp_path: Path):
        plugins_root, mcp_json = self._setup_plugin(tmp_path)

        match = find_intercept(
            "legal:review-contract",
            plugins_root=plugins_root,
            mcp_json_path=mcp_json,
        )

        assert match is not None
        assert match.plugin_name == "legal"
        assert match.command_name == "review-contract"
        assert match.mcp_server_name == "generate-redlined"
        assert match.mcp_tool_name == "mcp__generate-redlined__execute_plugin_command"
        assert match.server_configured is True
        assert match.command_md_path.endswith("review-contract.md")
        assert len(match.skill_md_paths) == 1

    def test_unqualified_skill(self, tmp_path: Path):
        plugins_root, mcp_json = self._setup_plugin(tmp_path)

        match = find_intercept(
            "review-contract",
            plugins_root=plugins_root,
            mcp_json_path=mcp_json,
        )
        assert match is None

    def test_plugin_not_found(self, tmp_path: Path):
        plugins_root = tmp_path / "plugins"
        plugins_root.mkdir()

        match = find_intercept(
            "unknown:review-contract",
            plugins_root=plugins_root,
        )
        assert match is None

    def test_command_not_intercepted(self, tmp_path: Path):
        plugins_root, mcp_json = self._setup_plugin(tmp_path)

        match = find_intercept(
            "legal:other-command",
            plugins_root=plugins_root,
            mcp_json_path=mcp_json,
        )
        assert match is None

    def test_server_not_configured(self, tmp_path: Path):
        plugins_root, _ = self._setup_plugin(tmp_path)

        # Empty mcp.json — server not configured
        empty_mcp = tmp_path / "empty_mcp.json"
        empty_mcp.write_text(json.dumps({"mcpServers": {}}))

        match = find_intercept(
            "legal:review-contract",
            plugins_root=plugins_root,
            mcp_json_path=empty_mcp,
        )

        assert match is not None
        assert match.server_configured is False


# ---------------------------------------------------------------------------
# build_system_message
# ---------------------------------------------------------------------------

class TestBuildSystemMessage:
    def test_contains_key_fields(self):
        match = InterceptMatch(
            plugin_name="legal",
            command_name="review-contract",
            mcp_server_name="generate-redlined",
            mcp_tool_name="mcp__generate-redlined__execute_plugin_command",
            plugin_dir="/path/to/legal",
            command_md_path="/path/to/legal/commands/review-contract.md",
            skill_md_paths=["/path/to/legal/skills/analysis/SKILL.md"],
            server_configured=True,
        )

        msg = build_system_message(match)

        assert "review-contract" in msg
        assert "mcp__generate-redlined__execute_plugin_command" in msg
        assert "/path/to/legal/commands/review-contract.md" in msg
        assert "analysis/SKILL.md" in msg
        assert "Do NOT perform the analysis" in msg
        assert "Do NOT skip context gathering" in msg

    def test_empty_skill_paths(self):
        match = InterceptMatch(
            plugin_name="legal",
            command_name="review-contract",
            mcp_server_name="generate-redlined",
            mcp_tool_name="mcp__generate-redlined__execute_plugin_command",
            plugin_dir="/path/to/legal",
            command_md_path="/path/to/legal/commands/review-contract.md",
            skill_md_paths=[],
            server_configured=True,
        )

        msg = build_system_message(match)
        assert "[]" in msg  # empty JSON array
