from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from promptx import activity
from promptx.config import Config, TranslateAPIConfig, TranslateConfig
from promptx.errors import BackendError
from promptx.integrations.claude.editor import process_editor_file, translate_file
from promptx.translate.base import contains_cjk
from promptx.translate.openai_compat import (
    TRANSLATION_END,
    TRANSLATION_START,
    OpenAICompatibleTranslator,
)


class FakeResponse:
    def __init__(self, content="Use std::span; keep ABI unchanged."):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(
            {"choices": [{"message": {"content": self.content}}]}
        ).encode()


class TranslateTests(unittest.TestCase):
    def test_contains_cjk(self):
        self.assertTrue(contains_cjk("检查 BLOCKS[0][2]"))
        self.assertFalse(contains_cjk("Check BLOCKS[0][2]"))

    def test_openai_compatible_translation_preserves_request_payload(self):
        config = TranslateConfig(
            model="test-model",
            api=TranslateAPIConfig(
                base_url="https://example.test/v1", api_key_env="TEST_PROMPTX_KEY"
            ),
        )
        with patch.dict(os.environ, {"TEST_PROMPTX_KEY": "secret"}), patch(
            "urllib.request.urlopen", return_value=FakeResponse()
        ) as urlopen:
            result = OpenAICompatibleTranslator(config).translate(
                "把 foo() 改成 std::span，但是 ABI 不能变"
            )
        self.assertEqual(result, "Use std::span; keep ABI unchanged.")
        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(
            body["messages"][1]["content"], "把 foo() 改成 std::span，但是 ABI 不能变"
        )

    def test_mixed_input_retries_when_first_result_still_contains_chinese(self):
        config = TranslateConfig(
            model="test-model",
            api=TranslateAPIConfig(
                base_url="https://example.test/v1", api_key_env="TEST_PROMPTX_KEY"
            ),
        )
        first = FakeResponse(
            f"{TRANSLATION_START}Review routecheck，然后修复 B1-B4。{TRANSLATION_END}"
        )
        second = FakeResponse(
            f"{TRANSLATION_START}Review routecheck, then fix B1-B4.{TRANSLATION_END}"
        )
        with patch.dict(os.environ, {"TEST_PROMPTX_KEY": "secret"}), patch(
            "urllib.request.urlopen", side_effect=[first, second]
        ) as urlopen:
            result = OpenAICompatibleTranslator(config).translate(
                "Review routecheck，然后修复 B1-B4。"
            )
        self.assertEqual(result, "Review routecheck, then fix B1-B4.")
        self.assertEqual(urlopen.call_count, 2)

    def test_translation_strips_reasoning_outside_result_block(self):
        config = TranslateConfig(
            api=TranslateAPIConfig(
                base_url="https://example.test/v1", api_key_env="TEST_PROMPTX_KEY"
            )
        )
        response = FakeResponse(
            "<think>我需要翻译混合输入。</think>\n"
            f"{TRANSLATION_START}Fix B1-B4.{TRANSLATION_END}"
        )
        with patch.dict(os.environ, {"TEST_PROMPTX_KEY": "secret"}), patch(
            "urllib.request.urlopen", return_value=response
        ):
            result = OpenAICompatibleTranslator(config).translate("修复 B1-B4")
        self.assertEqual(result, "Fix B1-B4.")

    def test_translate_file_skips_english_without_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prompt.txt"
            path.write_text("Investigate worker_pool.\n", encoding="utf-8")
            self.assertFalse(translate_file(path))
            self.assertEqual(
                path.read_text(encoding="utf-8"), "Investigate worker_pool.\n"
            )

    def test_translate_file_does_not_write_chinese_backend_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prompt.txt"
            original = "检查 worker_pool\n"
            path.write_text(original, encoding="utf-8")
            with patch(
                "promptx.integrations.claude.editor.load_config",
                return_value=type(
                    "Config",
                    (),
                    {"translate": TranslateConfig(api=TranslateAPIConfig(base_url="x"))},
                )(),
            ), patch(
                "promptx.integrations.claude.editor.OpenAICompatibleTranslator.translate",
                return_value="仍然是中文",
            ):
                with self.assertRaisesRegex(Exception, "still contains Chinese"):
                    translate_file(path)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_translation_uses_workspace_config_and_records_failure_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".promptx.toml").write_text(
                '[translate]\nmodel = "workspace-model"\n'
                '[translate.openai-compatible]\nbase_url = "https://example.test/v1"\n',
                encoding="utf-8",
            )
            path = root / "prompt.txt"
            path.write_text("检查 routecheck\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {
                    "XDG_CACHE_HOME": str(root / "cache"),
                    "PROMPTX_CONFIG": str(root / "missing-global.toml"),
                }),
                patch("promptx.integrations.claude.editor.discover") as discover,
                patch(
                    "promptx.integrations.claude.editor.OpenAICompatibleTranslator.translate",
                    return_value="Inspect routecheck.",
                ) as translate,
            ):
                discover.return_value.root = root
                self.assertTrue(translate_file(path))
                last = activity.load()
            self.assertEqual(path.read_text(encoding="utf-8"), "Inspect routecheck.\n")
            translate.assert_called_once_with("检查 routecheck\n")
            self.assertEqual(last.model, "workspace-model")
            self.assertEqual(last.status, "ok")

    def test_translation_failure_records_reason_without_changing_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "prompt.txt"
            original = "检查 B1-B4\n"
            path.write_text(original, encoding="utf-8")
            config = Config(translate=TranslateConfig(api=TranslateAPIConfig(base_url="x")))
            with (
                patch.dict(os.environ, {"XDG_CACHE_HOME": str(root / "cache")}),
                patch("promptx.integrations.claude.editor.load_config", return_value=config),
                patch(
                    "promptx.integrations.claude.editor.OpenAICompatibleTranslator.translate",
                    side_effect=BackendError(
                        "Translator HTTP 401: a private server response"
                    ),
                ),
            ):
                with self.assertRaisesRegex(Exception, "Translator HTTP 401"):
                    translate_file(path)
                last = activity.load()
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(last.route, "translate")
            self.assertEqual(last.status, "failed")
            self.assertEqual(last.error, "Translator HTTP 401")

    def test_external_editor_enhances_prefixed_draft_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prompt.txt"
            path.write_text("/enhance hello\n", encoding="utf-8")
            repo = type("Repo", (), {"root": Path(directory)})()
            config = object()
            with (
                patch(
                    "promptx.integrations.claude.editor.discover",
                    return_value=repo,
                ),
                patch(
                    "promptx.integrations.claude.editor.load_config",
                    return_value=config,
                ),
                patch(
                    "promptx.integrations.claude.editor.enhance_prompt",
                    return_value="Inspect the workspace and improve the greeting.",
                ) as enhance,
            ):
                self.assertTrue(process_editor_file(path))
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "Inspect the workspace and improve the greeting.\n",
            )
            enhance.assert_called_once_with("hello", repo, config)

    def test_external_editor_chinese_translation_never_uses_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "prompt.txt"
            path.write_text("检查 worker_pool\n", encoding="utf-8")
            config = Config(
                translate=TranslateConfig(
                    api=TranslateAPIConfig(base_url="https://example.test/v1")
                )
            )
            with (
                patch.dict(os.environ, {"XDG_CACHE_HOME": str(root / "cache")}),
                patch(
                    "promptx.integrations.claude.editor.load_config",
                    return_value=config,
                ),
                patch(
                    "promptx.integrations.claude.editor.OpenAICompatibleTranslator.translate",
                    return_value="Inspect worker_pool.",
                ) as translate,
                patch(
                    "promptx.integrations.claude.editor.enhance_prompt",
                ) as enhance,
            ):
                self.assertTrue(process_editor_file(path))
            self.assertEqual(path.read_text(encoding="utf-8"), "Inspect worker_pool.\n")
            translate.assert_called_once_with("检查 worker_pool\n")
            enhance.assert_not_called()
