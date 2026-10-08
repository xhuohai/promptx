from __future__ import annotations

import argparse
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from promptx import activity
from promptx.cli import command_status
from promptx.config import CacheConfig, Config
from promptx.enhance.pipeline import enhance_prompt
from promptx.repo import discover


class ActivityTests(unittest.TestCase):
    def test_enhance_records_cursor_route_and_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = MagicMock()
            backend.enhance.return_value = "Enhanced request"
            config = Config(cache=CacheConfig(enabled=False))
            with (
                patch.dict(os.environ, {"XDG_CACHE_HOME": str(root / "cache")}),
                patch("promptx.enhance.pipeline.create_backend", return_value=backend),
            ):
                enhance_prompt("fix it", discover(root), config)
                last = activity.load()
        self.assertIsNotNone(last)
        self.assertEqual(last.route, "enhance")
        self.assertEqual(last.backend, "cursor")
        self.assertEqual(last.model, "auto")
        self.assertEqual(last.status, "ok")
        self.assertFalse(last.translation_fallback)

    def test_status_displays_last_actual_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"XDG_CACHE_HOME": str(root / "cache")}):
                activity.save(
                    route="translate", backend="openai-compatible", model="qwen",
                    workspace=root,
                )
                output = io.StringIO()
                backend = MagicMock()
                backend.available.return_value = True
                with (
                    patch("promptx.cli.discover", return_value=discover(root)),
                    patch("promptx.cli.load_config", return_value=Config(cache=CacheConfig(enabled=False))),
                    patch("promptx.cli.create_backend", return_value=backend),
                    contextlib.redirect_stdout(output),
                ):
                    command_status(argparse.Namespace(backend=None, model=None))
        self.assertIn("Last route: translate", output.getvalue())
        self.assertIn("Last backend: openai-compatible", output.getvalue())
        self.assertIn("Last status: ok", output.getvalue())

    def test_status_displays_last_translation_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"XDG_CACHE_HOME": str(root / "cache")}):
                activity.save(
                    route="translate", backend="openai-compatible", model="qwen",
                    workspace=root, status="failed", error="Translator HTTP 401",
                )
                output = io.StringIO()
                backend = MagicMock()
                backend.available.return_value = True
                with (
                    patch("promptx.cli.discover", return_value=discover(root)),
                    patch("promptx.cli.load_config", return_value=Config(cache=CacheConfig(enabled=False))),
                    patch("promptx.cli.create_backend", return_value=backend),
                    contextlib.redirect_stdout(output),
                ):
                    command_status(argparse.Namespace(backend=None, model=None))
        self.assertIn("Last status: failed", output.getvalue())
        self.assertIn("Last error: Translator HTTP 401", output.getvalue())
