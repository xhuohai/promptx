from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from promptx.config import Config, EnhanceConfig
from promptx.enhance.cursor import CursorBackend, extract_enhance_result
from promptx.enhance.prompts import RESULT_END, RESULT_START, build_enhance_prompt
from promptx.repo import Repository


class CursorTests(unittest.TestCase):
    def test_prompt_marks_stale_and_preserves_identifiers(self):
        prompt = build_enhance_prompt(
            "不要改 BLOCKS[0][2] 和 ABI", "Old summary", summary_stale=True
        )
        self.assertIn("BLOCKS[0][2]", prompt)
        self.assertIn("ABI", prompt)
        self.assertIn("may predate recent repository changes", prompt)
        self.assertIn("entirely in English", prompt)
        self.assertIn("no Chinese/CJK characters", prompt)
        self.assertIn("written in the user's own", prompt)
        self.assertIn("`hello` must remain `hello`", prompt)
        self.assertIn("Do not write meta-instructions", prompt)
        self.assertIn("`Respond to the user`", prompt)
        self.assertIn("one balanced", prompt)
        self.assertIn("DETERMINISTIC CONTEXT SNAPSHOT", prompt)
        self.assertIn("verify any file, symbol", prompt)
        self.assertIn(RESULT_START, prompt)
        self.assertIn(RESULT_END, prompt)

    def test_extracts_only_delimited_prompt_after_cursor_narration(self):
        result = extract_enhance_result(
            "I'll inspect the relevant files first.\n\n"
            f"{RESULT_START}\nReview B1-B4 and fix the route checks.\n{RESULT_END}"
        )
        self.assertEqual(result, "Review B1-B4 and fix the route checks.")

    def test_rejects_cursor_output_without_result_delimiters(self):
        with self.assertRaisesRegex(Exception, "result delimiters"):
            extract_enhance_result(
                "I'll inspect the files first.\n\nReview B1-B4."
            )

    def test_plain_workspace_prompt_skips_git_assumptions(self):
        prompt = build_enhance_prompt(
            "explain this directory", None, summary_stale=False, is_git=False
        )
        self.assertIn("inspect this workspace", prompt)
        self.assertIn("do not assume Git metadata", prompt)
        self.assertNotIn("inspect git status", prompt)

    def test_cursor_backend_uses_readonly_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            log = tmp_path / "args.json"
            executable = tmp_path / "agent"
            executable.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$@\" > {str(log)!r}\n"
                "printf '%s\\n' '{\"type\":\"result\",\"is_error\":false,\"result\":\"<PROMPTX_RESULT>Enhanced prompt</PROMPTX_RESULT>\"}'\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            repo = Repository(tmp_path, "", "head")
            config = Config(enhance=EnhanceConfig(executable=str(executable)))
            result = CursorBackend(str(executable)).enhance(
                "fix it", repo, None, config
            )
            self.assertEqual(result, "Enhanced prompt")
            args = log.read_text(encoding="utf-8").splitlines()
            self.assertIn("--trust", args)
            self.assertIn("--mode=ask", args)
            self.assertEqual(args[args.index("--sandbox") + 1], "enabled")
            self.assertEqual(args[args.index("--output-format") + 1], "json")
            self.assertEqual(args[args.index("--model") + 1], "auto")
