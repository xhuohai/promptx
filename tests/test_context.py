from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from promptx.enhance.context import collect_context
from promptx.repo import discover


class ContextTests(unittest.TestCase):
    def test_collects_stack_task_tree_and_ranked_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(
                json.dumps({"dependencies": {"react": "latest"}}), encoding="utf-8"
            )
            source = root / "src"
            source.mkdir()
            (source / "scheduler.ts").write_text(
                "export function acquireLock() {}\n", encoding="utf-8"
            )
            (source / "unrelated.ts").write_text("export const x = 1\n", encoding="utf-8")

            context = collect_context("Fix the scheduler deadlock", discover(root))

        self.assertEqual(context.task_type, "debug")
        self.assertIn("JavaScript/TypeScript", context.stack)
        self.assertIn("React", context.stack)
        self.assertIn("package.json", context.markers)
        self.assertIn("src/scheduler.ts", context.tree)
        self.assertEqual(context.candidates[0].path, "src/scheduler.ts")
        self.assertEqual(context.git_branch, "")
        self.assertEqual(context.git_status, ())
        self.assertEqual(context.git_diff, ())

    def test_ignores_generated_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "node_modules" / "scheduler"
            generated.mkdir(parents=True)
            (generated / "index.js").write_text("deadlock", encoding="utf-8")
            context = collect_context("fix scheduler deadlock", discover(root))
        self.assertFalse(any("node_modules" in item for item in context.tree))

    def test_git_context_is_read_only_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "worker.py").write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "worker.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
            (root / "worker.py").write_text("value = 2\n", encoding="utf-8")
            context = collect_context("debug worker", discover(root))
        self.assertTrue(context.git_branch)
        self.assertTrue(any("worker.py" in line for line in context.git_status))
        self.assertTrue(any("worker.py" in line for line in context.git_diff))
