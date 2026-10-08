from __future__ import annotations

import argparse
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from promptx.cli import _run_enhancement
from promptx.config import CacheConfig, Config, TranslateAPIConfig, TranslateConfig


@contextlib.contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def configured_translation() -> Config:
    return Config(
        translate=TranslateConfig(
            api=TranslateAPIConfig(
                base_url="https://example.test/v1",
                api_key_env="PROMPTX_API_KEY",
            )
        ),
        cache=CacheConfig(enabled=False),
    )


class EnhancePipelineTests(unittest.TestCase):
    def test_empty_plain_workspace_still_uses_cursor(self):
        args = argparse.Namespace(backend=None, model=None)
        backend = MagicMock()
        backend.enhance.return_value = (
            "I am testing the enhance skill to see what happens."
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout = io.StringIO()
            with (
                working_directory(root),
                patch("promptx.cli.load_config", return_value=configured_translation()),
                patch("promptx.enhance.pipeline.create_backend", return_value=backend),
                patch(
                    "promptx.enhance.pipeline.OpenAICompatibleTranslator.translate",
                ) as translate,
                contextlib.redirect_stdout(stdout),
            ):
                result = _run_enhancement(
                    "我在执行 enhance skill 的测试，看看会发生什么", args
                )

        self.assertEqual(result, 0)
        self.assertEqual(
            stdout.getvalue(),
            "I am testing the enhance skill to see what happens.\n",
        )
        backend.enhance.assert_called_once()
        self.assertFalse(backend.enhance.call_args.args[1].is_git)
        translate.assert_not_called()

    def test_cursor_chinese_output_uses_translation_fallback(self):
        args = argparse.Namespace(backend=None, model=None)
        backend = MagicMock()
        backend.enhance.return_value = "Please inspect scheduler，然后修复死锁。"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scheduler.py").write_text("pass\n", encoding="utf-8")
            stdout = io.StringIO()
            with (
                working_directory(root),
                patch("promptx.cli.load_config", return_value=configured_translation()),
                patch("promptx.enhance.pipeline.create_backend", return_value=backend),
                patch(
                    "promptx.enhance.pipeline.OpenAICompatibleTranslator.translate",
                    return_value="Inspect scheduler.py and fix the deadlock.",
                ) as translate,
                contextlib.redirect_stdout(stdout),
            ):
                result = _run_enhancement("修复死锁", args)

        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), "Inspect scheduler.py and fix the deadlock.\n")
        translate.assert_called_once_with("Please inspect scheduler，然后修复死锁。")

    def test_chinese_is_not_printed_when_fallback_still_contains_it(self):
        args = argparse.Namespace(backend=None, model=None)
        backend = MagicMock()
        backend.enhance.return_value = "仍然是中文"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text("pass\n", encoding="utf-8")
            stdout = io.StringIO()
            with (
                working_directory(root),
                patch("promptx.cli.load_config", return_value=configured_translation()),
                patch("promptx.enhance.pipeline.create_backend", return_value=backend),
                patch(
                    "promptx.enhance.pipeline.OpenAICompatibleTranslator.translate",
                    return_value="还是中文",
                ),
                contextlib.redirect_stdout(stdout),
            ):
                with self.assertRaisesRegex(
                    Exception, "translator outputs still contain Chinese"
                ):
                    _run_enhancement("修复问题", args)

        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
