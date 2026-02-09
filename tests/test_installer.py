"""Tests for plugin2mcp.installer module."""

from __future__ import annotations

import json
from pathlib import Path

from plugin2mcp.installer import (
    add_intercepts,
    get_status,
    install_hook,
    load_json,
    save_json,
    uninstall_hook,
)


class TestInstallHook:
    def test_install_creates_hook(self, tmp_path: Path):
        settings_path = tmp_path / "settings.json"

        install_hook(settings_path=settings_path)

        data = json.loads(settings_path.read_text())
        post_tool_use = data["hooks"]["PostToolUse"]
        assert len(post_tool_use) == 1
        assert post_tool_use[0]["matcher"] == "Skill"
        assert "plugin2mcp.hook" in post_tool_use[0]["hooks"][0]["command"]

    def test_install_idempotent(self, tmp_path: Path):
        settings_path = tmp_path / "settings.json"

        install_hook(settings_path=settings_path)
        install_hook(settings_path=settings_path)

        data = json.loads(settings_path.read_text())
        post_tool_use = data["hooks"]["PostToolUse"]
        assert len(post_tool_use) == 1  # not duplicated

    def test_install_preserves_existing_settings(self, tmp_path: Path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "autoUpdatesChannel": "stable",
            "enabledPlugins": ["legal"],
        }))

        install_hook(settings_path=settings_path)

        data = json.loads(settings_path.read_text())
        assert data["autoUpdatesChannel"] == "stable"
        assert data["enabledPlugins"] == ["legal"]
        assert "hooks" in data

    def test_install_preserves_existing_hooks(self, tmp_path: Path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": []}],
            }
        }))

        install_hook(settings_path=settings_path)

        data = json.loads(settings_path.read_text())
        assert "PreToolUse" in data["hooks"]
        assert "PostToolUse" in data["hooks"]


class TestUninstallHook:
    def test_uninstall_removes_hook(self, tmp_path: Path):
        settings_path = tmp_path / "settings.json"

        # Install first
        install_hook(settings_path=settings_path)
        # Then uninstall
        uninstall_hook(settings_path=settings_path)

        data = json.loads(settings_path.read_text())
        # hooks key should be cleaned up
        assert "hooks" not in data or "PostToolUse" not in data.get("hooks", {})

    def test_uninstall_when_not_installed(self, tmp_path: Path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({}))

        result = uninstall_hook(settings_path=settings_path)
        assert result is True

    def test_uninstall_preserves_other_hooks(self, tmp_path: Path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Skill",
                        "hooks": [
                            {"type": "command", "command": "python -m plugin2mcp.hook"},
                        ],
                    },
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {"type": "command", "command": "echo hello"},
                        ],
                    },
                ],
            }
        }))

        uninstall_hook(settings_path=settings_path)

        data = json.loads(settings_path.read_text())
        post_tool_use = data["hooks"]["PostToolUse"]
        assert len(post_tool_use) == 1
        assert post_tool_use[0]["matcher"] == "Bash"


class TestAddIntercepts:
    def test_add_intercepts(self, tmp_path: Path):
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "my-server": {
                    "type": "stdio",
                    "command": "python",
                }
            }
        }))

        result = add_intercepts(tmp_path, "my-server", ["review-contract"])
        assert result is True

        data = json.loads(mcp_json.read_text())
        assert data["mcpServers"]["my-server"]["intercepts"] == ["review-contract"]

    def test_add_intercepts_no_duplicates(self, tmp_path: Path):
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "my-server": {
                    "intercepts": ["review-contract"],
                }
            }
        }))

        add_intercepts(tmp_path, "my-server", ["review-contract", "draft-contract"])

        data = json.loads(mcp_json.read_text())
        intercepts = data["mcpServers"]["my-server"]["intercepts"]
        assert intercepts == ["review-contract", "draft-contract"]

    def test_add_intercepts_server_not_found(self, tmp_path: Path):
        mcp_json = tmp_path / ".mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "other-server": {},
            }
        }))

        result = add_intercepts(tmp_path, "my-server", ["review-contract"])
        assert result is False

    def test_add_intercepts_no_file(self, tmp_path: Path):
        result = add_intercepts(tmp_path, "my-server", ["review-contract"])
        assert result is False


class TestGetStatus:
    def test_status_with_hook_and_bindings(self, tmp_path: Path):
        # Settings with hook
        settings_path = tmp_path / "settings.json"
        install_hook(settings_path=settings_path)

        # Plugin with intercepts
        plugins_root = tmp_path / "plugins"
        plugin_dir = plugins_root / "knowledge-work-plugins" / "legal"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / ".mcp.json").write_text(json.dumps({
            "mcpServers": {
                "generate-redlined": {
                    "intercepts": ["review-contract"],
                }
            }
        }))

        status = get_status(
            settings_path=settings_path,
            plugins_root=plugins_root,
        )

        assert status["hook_installed"] is True
        assert len(status["bindings"]) == 1
        assert status["bindings"][0]["plugin"] == "legal"
        assert status["bindings"][0]["server"] == "generate-redlined"
        assert status["bindings"][0]["intercepts"] == ["review-contract"]

    def test_status_empty(self, tmp_path: Path):
        status = get_status(
            settings_path=tmp_path / "settings.json",
            plugins_root=tmp_path / "plugins",
        )

        assert status["hook_installed"] is False
        assert status["bindings"] == []


class TestLoadSaveJson:
    def test_load_missing_file(self, tmp_path: Path):
        assert load_json(tmp_path / "missing.json") == {}

    def test_load_invalid_json(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        assert load_json(bad) == {}

    def test_save_creates_parents(self, tmp_path: Path):
        path = tmp_path / "a" / "b" / "c.json"
        save_json(path, {"key": "value"})

        assert path.is_file()
        assert json.loads(path.read_text()) == {"key": "value"}
