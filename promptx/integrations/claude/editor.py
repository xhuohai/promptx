from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ... import activity
from ...config import load_config
from ...enhance.pipeline import enhance_prompt
from ...errors import BackendError, ConfigError, PromptXError
from ...repo import discover
from ...translate.base import contains_cjk
from ...translate.openai_compat import OpenAICompatibleTranslator


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptXError(f"Cannot read editor file {path}: {exc}") from exc


def _write_file(path: Path, original: str, result: str) -> None:
    if original.endswith("\n"):
        result += "\n"
    try:
        path.write_text(result, encoding="utf-8")
    except OSError as exc:
        raise PromptXError(f"Cannot update editor file {path}: {exc}") from exc


def _translation_error(exc: Exception) -> str:
    if isinstance(exc, ConfigError):
        if "is not set" in str(exc):
            return str(exc)
        if "base_url is not configured" in str(exc):
            return str(exc)
        return "Translator configuration error"
    if isinstance(exc, BackendError):
        message = str(exc)
        if message.startswith("Translator HTTP "):
            return message.split(":", 1)[0]
        if "timed out" in message.lower():
            return "Translator request timed out"
        return "Translator request or response failed"
    if isinstance(exc, PromptXError):
        if "still contains Chinese" in str(exc):
            return "Translation still contains Chinese after two attempts"
        if "Unsupported translate backend" in str(exc):
            return str(exc)
        return "Cannot update editor file"
    return f"Unexpected translator error ({type(exc).__name__})"


def translate_file(path: Path) -> bool:
    original = _read_file(path)
    if not contains_cjk(original):
        activity.save(
            route="passthrough",
            backend="local",
            model="-",
            workspace=Path.cwd(),
        )
        return False

    workspace = Path.cwd()
    backend, model = "openai-compatible", "-"
    activity.save(
        route="translate",
        backend=backend,
        model=model,
        workspace=workspace,
        status="started",
    )
    try:
        config = load_config(discover().root)
        backend, model = config.translate.backend, config.translate.model
        if backend != "openai-compatible":
            raise PromptXError(f"Unsupported translate backend: {backend}")
        translated = OpenAICompatibleTranslator(config.translate).translate(original)
        if contains_cjk(translated):
            raise PromptXError(
                "Translator output still contains Chinese; the editor file was left unchanged"
            )
        _write_file(path, original, translated)
    except Exception as exc:
        activity.save(
            route="translate",
            backend=backend,
            model=model,
            workspace=workspace,
            status="failed",
            error=_translation_error(exc),
        )
        raise
    activity.save(
        route="translate",
        backend=backend,
        model=model,
        workspace=workspace,
        status="ok",
    )
    return True


def process_editor_file(path: Path) -> bool:
    original = _read_file(path)
    stripped = original.strip()
    if stripped == "/enhance":
        raise PromptXError("Use /enhance <prompt>; the prompt is empty")
    if stripped.startswith("/enhance "):
        prompt = stripped[len("/enhance ") :].strip()
        if not prompt:
            raise PromptXError("Use /enhance <prompt>; the prompt is empty")
        repo = discover()
        config = load_config(repo.root)
        result = enhance_prompt(prompt, repo, config)
        _write_file(path, original, result)
        return True
    return translate_file(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="promptx-claude-editor")
    parser.add_argument("file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        process_editor_file(args.file)
    except PromptXError as exc:
        print(f"promptx: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
