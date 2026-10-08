from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import PromptXError


@dataclass(frozen=True)
class Repository:
    root: Path
    remote: str
    head: str
    is_git: bool = True

    @property
    def identifier(self) -> str:
        if self.is_git:
            source_text = f"{self.remote}\0{self.root.resolve()}"
        else:
            source_text = f"plain-workspace\0{self.root.resolve()}"
        source = source_text.encode("utf-8")
        return hashlib.sha256(source).hexdigest()[:20]


def _git(cwd: Path, *args: str, required: bool = True) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        if required:
            detail = process.stderr.strip() or "git command failed"
            raise PromptXError(detail)
        return ""
    return process.stdout.strip()


def discover(start: Path | None = None, *, require_git: bool = False) -> Repository:
    cwd = (start or Path.cwd()).resolve()
    root_text = _git(cwd, "rev-parse", "--show-toplevel", required=False)
    if not root_text:
        if require_git:
            raise PromptXError(
                f"Not inside a Git repository: {cwd}. "
                "Run this command from a directory inside the repository."
            )
        return Repository(
            root=cwd,
            remote="",
            head="non-git",
            is_git=False,
        )
    root = Path(root_text).resolve()
    remote = _git(root, "config", "--get", "remote.origin.url", required=False)
    head = _git(root, "rev-parse", "HEAD", required=False) or "unborn"
    return Repository(root=root, remote=remote, head=head, is_git=True)
