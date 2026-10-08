from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..config import Config
from ..errors import BackendError
from ..repo import Repository
from .base import BackendCapabilities, EnhanceBackend
from .context import WorkspaceContext
from .prompts import RESULT_END, RESULT_START, build_enhance_prompt, build_summary_prompt


def extract_enhance_result(result: str) -> str:
    start = result.rfind(RESULT_START)
    if start < 0:
        raise BackendError(
            "Cursor did not return the enhanced prompt inside PromptX result delimiters"
        )
    start += len(RESULT_START)
    end = result.find(RESULT_END, start)
    if end < 0:
        raise BackendError("Cursor returned an incomplete PromptX result block")
    prompt = result[start:end].strip()
    if not prompt:
        raise BackendError("Cursor returned an empty PromptX result block")
    return prompt


class CursorBackend(EnhanceBackend):
    name = "cursor"
    capabilities = BackendCapabilities(
        repo_aware=True,
        filesystem_search=True,
        model_selection=True,
        readonly_mode=True,
    )

    def __init__(self, executable: str = "auto"):
        self.executable_setting = executable

    def executable(self) -> str | None:
        if self.executable_setting != "auto":
            return shutil.which(self.executable_setting)
        return shutil.which("agent") or shutil.which("cursor-agent")

    def available(self) -> bool:
        return self.executable() is not None

    def _run(self, instruction: str, repo: Path, config: Config) -> str:
        executable = self.executable()
        if executable is None:
            expected = (
                self.executable_setting
                if self.executable_setting != "auto"
                else "agent or cursor-agent"
            )
            raise BackendError(f"Cursor CLI is not available ({expected})")

        command = [
            executable,
            "-p",
            "--trust",
            "--mode=ask",
            "--sandbox",
            "enabled",
            "--output-format",
            "json",
            "--model",
            config.enhance.model,
        ]
        command.append(instruction)

        try:
            process = subprocess.run(
                command,
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=config.enhance.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BackendError(
                f"Cursor CLI timed out after {config.enhance.timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise BackendError(f"Cannot start Cursor CLI: {exc}") from exc

        if process.returncode != 0:
            detail = process.stderr.strip() or process.stdout.strip()
            raise BackendError(
                f"Cursor CLI failed with exit code {process.returncode}: {detail[:2000]}"
            )
        try:
            payload = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise BackendError(
                "Cursor CLI did not return JSON; check its version and authentication"
            ) from exc
        if payload.get("is_error"):
            raise BackendError(str(payload.get("result") or "Cursor CLI reported an error"))
        result = payload.get("result")
        if not isinstance(result, str) or not result.strip():
            raise BackendError("Cursor CLI returned no final response")
        return result.strip()

    def enhance(
        self,
        prompt: str,
        repo: Repository,
        summary: str | None,
        config: Config,
        *,
        summary_stale: bool = False,
        context: WorkspaceContext | None = None,
    ) -> str:
        result = self._run(
            build_enhance_prompt(
                prompt,
                summary,
                summary_stale=summary_stale,
                is_git=repo.is_git,
                context=context,
            ),
            repo.root,
            config,
        )
        return extract_enhance_result(result)

    def summarize(self, repo: Repository, config: Config) -> str:
        return self._run(
            build_summary_prompt(is_git=repo.is_git), repo.root, config
        )
