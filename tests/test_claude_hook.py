from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from promptx.cli import main


class ClaudeHookTests(unittest.TestCase):
    def run_hook(self, payload: dict[str, object]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("sys.stdin", io.StringIO(json.dumps(payload))),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            result = main(["claude-hook"])
        return result, stdout.getvalue(), stderr.getvalue()

    def run_submit_guard(self, prompt: str) -> tuple[int, str, str]:
        payload = {"hook_event_name": "UserPromptSubmit", "prompt": prompt}
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("sys.stdin", io.StringIO(json.dumps(payload, ensure_ascii=False))),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            result = main(["claude-submit-guard"])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_submit_guard_blocks_chinese_without_echoing_it_to_claude(self):
        code, stdout, stderr = self.run_submit_guard("Review B1-B4，然后修复问题")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("Press Ctrl+T", stderr)
        self.assertNotIn("修复问题", stderr)

    def test_submit_guard_allows_english(self):
        code, stdout, stderr = self.run_submit_guard("Review B1-B4 and fix the issue")
        self.assertEqual((code, stdout, stderr), (0, "", ""))

    def test_regular_enhance_prompt_is_blocked_before_claude(self):
        result, stdout, stderr = self.run_hook(
            {
                "hook_event_name": "UserPromptExpansion",
                "command_name": "enhance",
                "command_args": "fix the scheduler deadlock",
                "cwd": os.getcwd(),
            }
        )
        response = json.loads(stdout)
        self.assertEqual(result, 0)
        self.assertEqual(response["decision"], "block")
        self.assertIn("press Ctrl+T", response["reason"])
        self.assertEqual(stderr, "")

    def test_config_is_returned_as_a_block_reason_without_model_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            with patch.dict(os.environ, {"PROMPTX_CONFIG": str(config_path)}):
                result, stdout, stderr = self.run_hook(
                    {
                        "hook_event_name": "UserPromptExpansion",
                        "command_name": "enhance",
                        "command_args": "config",
                        "cwd": directory,
                    }
                )
        response = json.loads(stdout)
        self.assertEqual(result, 0)
        self.assertEqual(response["decision"], "block")
        self.assertIn('[enhance]', response["reason"])
        self.assertIn('backend = "cursor"', response["reason"])
        self.assertEqual(stderr, "")

    def test_init_supports_plain_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = unittest.mock.Mock()
            backend.summarize.return_value = "Plain workspace summary"
            with (
                patch("promptx.cli.create_backend", return_value=backend),
                patch.dict(
                    os.environ,
                    {"XDG_CACHE_HOME": str(Path(directory) / "cache")},
                ),
            ):
                result, stdout, stderr = self.run_hook(
                    {
                        "hook_event_name": "UserPromptExpansion",
                        "command_name": "enhance",
                        "command_args": "init",
                        "cwd": directory,
                    }
                )
        response = json.loads(stdout)
        self.assertEqual(result, 0)
        self.assertEqual(response["decision"], "block")
        self.assertIn("Initialized summary", response["reason"])
        backend.summarize.assert_called_once()
        self.assertFalse(backend.summarize.call_args.args[0].is_git)
        self.assertEqual(stderr, "")
