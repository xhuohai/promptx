from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from promptx.config import get_value, load_config, set_value


class ConfigTests(unittest.TestCase):
    def test_global_and_repo_config_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            global_path = tmp_path / "global.toml"
            with patch.dict(os.environ, {"PROMPTX_CONFIG": str(global_path)}):
                set_value("enhance.model", "global-model")
                set_value("translate.model", "translator-model")
                repo = tmp_path / "repo"
                repo.mkdir()
                set_value("enhance.model", "repo-model", repo=repo)
                config = load_config(repo)
            self.assertEqual(config.enhance.model, "repo-model")
            self.assertEqual(config.translate.model, "translator-model")
            self.assertEqual(get_value(config, "enhance.model"), "repo-model")

    def test_config_serializes_nested_openai_table(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            with patch.dict(os.environ, {"PROMPTX_CONFIG": str(path)}):
                set_value("translate.openai-compatible.base_url", "https://host/v1")
                self.assertEqual(
                    load_config().translate.api.base_url, "https://host/v1"
                )
            self.assertIn(
                "[translate.openai-compatible]", path.read_text(encoding="utf-8")
            )
