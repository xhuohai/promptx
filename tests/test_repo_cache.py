from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from promptx import cache
from promptx.repo import discover


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class RepoCacheTests(unittest.TestCase):
    def test_plain_directory_is_a_supported_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = discover(Path(directory))
            self.assertEqual(workspace.root, Path(directory).resolve())
            self.assertFalse(workspace.is_git)
            self.assertEqual(workspace.head, "non-git")

    def test_plain_workspace_cache_remains_fresh_until_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            workspace_path = tmp_path / "workspace"
            workspace_path.mkdir()
            with patch.dict(
                os.environ, {"XDG_CACHE_HOME": str(tmp_path / "cache")}
            ):
                workspace = discover(workspace_path)
                cache.save(workspace, "summary", backend="cursor", model="auto")
                (workspace_path / "new.txt").write_text("new", encoding="utf-8")
                self.assertEqual(cache.load(discover(workspace_path)).status, "fresh")

    def test_cache_becomes_stale_after_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            repo_path = tmp_path / "repo"
            repo_path.mkdir()
            git(repo_path, "init")
            git(repo_path, "config", "user.email", "test@example.com")
            git(repo_path, "config", "user.name", "Test")
            (repo_path / "a.txt").write_text("one", encoding="utf-8")
            git(repo_path, "add", "a.txt")
            git(repo_path, "commit", "-m", "one")
            with patch.dict(
                os.environ, {"XDG_CACHE_HOME": str(tmp_path / "cache")}
            ):
                repo = discover(repo_path)
                cache.save(repo, "summary", backend="cursor", model="auto")
                self.assertEqual(cache.load(repo).status, "fresh")
                (repo_path / "a.txt").write_text("two", encoding="utf-8")
                git(repo_path, "commit", "-am", "two")
                updated = discover(repo_path)
                self.assertEqual(cache.load(updated).status, "stale")
