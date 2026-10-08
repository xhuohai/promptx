from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from promptx.integrations.claude.install import (
    claude_diagnostics,
    install_claude,
    uninstall_claude,
)


def executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)


class ClaudeInstallTests(unittest.TestCase):
    def test_install_merges_and_uninstall_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            claude = tmp_path / "claude"
            claude.mkdir()
            settings = {"theme": "dark", "env": {"EDITOR": "nvim"}}
            keybindings = {
                "bindings": [
                    {
                        "context": "Chat",
                        "bindings": {"ctrl+e": "chat:externalEditor"},
                    }
                ]
            }
            (claude / "settings.json").write_text(
                json.dumps(settings), encoding="utf-8"
            )
            (claude / "keybindings.json").write_text(
                json.dumps(keybindings), encoding="utf-8"
            )
            promptx = tmp_path / "promptx"
            editor = tmp_path / "promptx-claude-editor"
            executable(promptx)
            executable(editor)
            env = {
                "PROMPTX_CLAUDE_HOME": str(claude),
                "PROMPTX_COMMAND": str(promptx),
                "PROMPTX_CLAUDE_EDITOR": str(editor),
            }
            with patch.dict(os.environ, env):
                install_claude()
                installed_settings = json.loads(
                    (claude / "settings.json").read_text()
                )
                installed_keys = json.loads(
                    (claude / "keybindings.json").read_text()
                )
                self.assertEqual(installed_settings["theme"], "dark")
                self.assertEqual(
                    installed_settings["env"]["PROMPTX_REAL_EDITOR"], "nvim"
                )
                self.assertEqual(installed_settings["env"]["EDITOR"], str(editor))
                expansion_hooks = installed_settings["hooks"][
                    "UserPromptExpansion"
                ]
                promptx_hook = next(
                    item for item in expansion_hooks if item.get("matcher") == "enhance"
                )
                self.assertEqual(promptx_hook["hooks"][0]["type"], "command")
                self.assertEqual(
                    promptx_hook["hooks"][0]["command"], f"{promptx} claude-hook"
                )
                submit_hooks = installed_settings["hooks"]["UserPromptSubmit"]
                guard = next(
                    item for item in submit_hooks
                    if any(
                        hook.get("command") == f"{promptx} claude-submit-guard"
                        for hook in item.get("hooks", [])
                    )
                )
                self.assertEqual(guard["hooks"][0]["timeout"], 5)
                chat = next(
                    item
                    for item in installed_keys["bindings"]
                    if item["context"] == "Chat"
                )
                self.assertEqual(
                    chat["bindings"]["ctrl+e"], "chat:externalEditor"
                )
                self.assertNotIn("ctrl+t", chat["bindings"])
                global_bindings = next(
                    item
                    for item in installed_keys["bindings"]
                    if item["context"] == "Global"
                )
                self.assertEqual(
                    global_bindings["bindings"]["ctrl+t"],
                    "chat:externalEditor",
                )
                skill = (
                    claude / "skills" / "enhance" / "SKILL.md"
                ).read_text()
                self.assertIn("PromptX handles this command", skill)
                self.assertNotIn("$ARGUMENTS", skill)
                diagnostics = claude_diagnostics()
                self.assertIn(
                    "Ctrl+T global external editor binding: yes", diagnostics
                )
                install_claude()
                reinstalled = json.loads((claude / "settings.json").read_text())
                self.assertEqual(len(reinstalled["hooks"]["UserPromptSubmit"]), 1)
                uninstall_claude()
            self.assertEqual(
                json.loads((claude / "settings.json").read_text()), settings
            )
            self.assertEqual(
                json.loads((claude / "keybindings.json").read_text()), keybindings
            )
            self.assertFalse((claude / "skills" / "enhance" / "SKILL.md").exists())

    def test_diagnostics_warn_when_telemetry_disables_customization(self):
        with tempfile.TemporaryDirectory() as directory:
            claude = Path(directory) / "claude"
            claude.mkdir()
            (claude / "settings.json").write_text(
                json.dumps({"env": {"DISABLE_TELEMETRY": "1"}}),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"PROMPTX_CLAUDE_HOME": str(claude)},
                clear=False,
            ):
                diagnostics = claude_diagnostics()
            self.assertTrue(any(line.startswith("Warning:") for line in diagnostics))

    def test_install_migrates_legacy_split_ctrl_t_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            claude = tmp_path / "claude"
            claude.mkdir()
            legacy = {
                "bindings": [
                    {"context": "Global", "bindings": {"ctrl+t": None}},
                    {
                        "context": "Chat",
                        "bindings": {"ctrl+t": "chat:externalEditor"},
                    },
                ]
            }
            (claude / "keybindings.json").write_text(
                json.dumps(legacy), encoding="utf-8"
            )
            promptx = tmp_path / "promptx"
            editor = tmp_path / "promptx-claude-editor"
            executable(promptx)
            executable(editor)
            with patch.dict(
                os.environ,
                {
                    "PROMPTX_CLAUDE_HOME": str(claude),
                    "PROMPTX_COMMAND": str(promptx),
                    "PROMPTX_CLAUDE_EDITOR": str(editor),
                },
            ):
                install_claude()
            installed = json.loads((claude / "keybindings.json").read_text())
            global_values = next(
                item["bindings"]
                for item in installed["bindings"]
                if item["context"] == "Global"
            )
            chat_values = next(
                item["bindings"]
                for item in installed["bindings"]
                if item["context"] == "Chat"
            )
            self.assertEqual(global_values["ctrl+t"], "chat:externalEditor")
            self.assertNotIn("ctrl+t", chat_values)
