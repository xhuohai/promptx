from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shlex
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable

from . import __version__
from . import activity, cache
from .config import Config, get_value, load_config, render, set_value
from .enhance.pipeline import enhance_prompt
from .enhance.registry import BACKENDS, create_backend
from .errors import PromptXError
from .integrations.claude.editor import translate_file
from .integrations.claude.install import (
    claude_diagnostics,
    install_claude,
    uninstall_claude,
)
from .repo import Repository, discover
from .translate.base import contains_cjk
from .translate.openai_compat import OpenAICompatibleTranslator


def _read_text(parts: list[str], force_stdin: bool) -> str:
    if force_stdin or not parts:
        if sys.stdin.isatty():
            raise PromptXError("Provide text as an argument or pipe it on stdin")
        value = sys.stdin.read()
    else:
        value = " ".join(parts)
    if not value.strip():
        raise PromptXError("Prompt is empty")
    return value


def _optional_repo() -> Repository | None:
    try:
        return discover()
    except PromptXError:
        return None


def _config_for_repo(repo: Repository | None) -> Config:
    return load_config(repo.root if repo else None)


def _apply_enhance_overrides(config: Config, args: argparse.Namespace) -> Config:
    values = config.enhance
    if getattr(args, "backend", None):
        values = replace(values, backend=args.backend)
    if getattr(args, "model", None):
        values = replace(values, model=args.model)
    return replace(config, enhance=values)


def command_translate(args: argparse.Namespace) -> int:
    text = _read_text(args.text, args.stdin)
    if not contains_cjk(text):
        activity.save(route="passthrough", backend="local", model="-", workspace=Path.cwd())
        print(text, end="" if text.endswith("\n") else "\n")
        return 0
    config = load_config()
    translate_config = config.translate
    if args.model:
        translate_config = replace(translate_config, model=args.model)
    if args.base_url:
        translate_config = replace(
            translate_config,
            api=replace(translate_config.api, base_url=args.base_url),
        )
    if translate_config.backend != "openai-compatible":
        raise PromptXError(
            f"Unsupported translate backend: {translate_config.backend}"
        )
    activity.save(
        route="translate",
        backend=translate_config.backend,
        model=translate_config.model,
        workspace=Path.cwd(),
        status="started",
    )
    try:
        result = OpenAICompatibleTranslator(translate_config).translate(text)
        if contains_cjk(result):
            raise PromptXError("Translator output still contains Chinese")
    except Exception:
        activity.save(
            route="translate",
            backend=translate_config.backend,
            model=translate_config.model,
            workspace=Path.cwd(),
            status="failed",
        )
        raise
    activity.save(
        route="translate",
        backend=translate_config.backend,
        model=translate_config.model,
        workspace=Path.cwd(),
        status="ok",
    )
    print(result)
    return 0


def command_translate_file(args: argparse.Namespace) -> int:
    translate_file(args.file)
    return 0


def _summary_for(repo: Repository, config: Config) -> cache.CacheState:
    if not config.cache.enabled:
        return cache.CacheState("disabled", None, None)
    return cache.load(repo)


def _run_enhancement(prompt: str, args: argparse.Namespace) -> int:
    repo = discover()
    config = _apply_enhance_overrides(_config_for_repo(repo), args)
    result = enhance_prompt(prompt, repo, config)
    print(result)
    return 0


def command_init(args: argparse.Namespace) -> int:
    repo = discover()
    config = _apply_enhance_overrides(_config_for_repo(repo), args)
    if not config.cache.enabled:
        raise PromptXError("Cache is disabled; set cache.enabled to true first")
    state = cache.load(repo)
    if state.status != "missing" and not getattr(args, "force", False):
        print(f"Summary already exists and is {state.status}; use refresh to rebuild it")
        return 0
    backend = create_backend(config)
    summary = backend.summarize(repo, config)
    cache.save(
        repo,
        summary,
        backend=config.enhance.backend,
        model=config.enhance.model,
    )
    print(f"Initialized summary for {repo.root}")
    return 0


def command_refresh(args: argparse.Namespace) -> int:
    setattr(args, "force", True)
    return command_init(args)


def _available_label(value: bool) -> str:
    return "yes" if value else "no"


def command_status(args: argparse.Namespace) -> int:
    repo = discover()
    config = _apply_enhance_overrides(_config_for_repo(repo), args)
    state = _summary_for(repo, config)
    backend = create_backend(config)
    metadata = state.metadata
    last = activity.load()
    lines = [
        f"Workspace: {repo.root}",
        f"Git repository: {_available_label(repo.is_git)}",
        f"Backend: {config.enhance.backend}",
        f"Model: {config.enhance.model}",
        f"Cursor CLI: {'available' if backend.available() else 'missing'}",
        f"Summary: {state.status}",
        f"Summary HEAD: {metadata.head if metadata and repo.is_git else '-'}",
        f"Current HEAD: {repo.head if repo.is_git else '-'}",
        f"Translator: {config.translate.backend} / {config.translate.model}",
        f"Last route: {last.route if last else '-'}",
        f"Last backend: {last.backend if last else '-'}",
        f"Last model: {last.model if last else '-'}",
        f"Last status: {last.status if last else '-'}",
        f"Last error: {last.error if last and last.error else '-'}",
        f"Last workspace: {last.workspace if last else '-'}",
        f"Last translation fallback: {_available_label(last.translation_fallback) if last else '-'}",
        f"Last run at: {last.created_at if last else '-'}",
    ]
    print("\n".join(lines))
    return 0


def command_backend_list(args: argparse.Namespace) -> int:
    config = load_config()
    rows = ["Backend\tRepo-aware\tModel select\tRead-only\tAvailable"]
    for item in BACKENDS:
        available = False
        if item.name == "cursor" and item.implemented:
            try:
                probe_config = replace(
                    config, enhance=replace(config.enhance, backend="cursor")
                )
                available = create_backend(probe_config).available()
            except PromptXError:
                available = False
        rows.append(
            "\t".join(
                [
                    item.name,
                    _available_label(item.capabilities.repo_aware),
                    _available_label(item.capabilities.model_selection),
                    _available_label(item.capabilities.readonly_mode),
                    _available_label(available),
                ]
            )
        )
    print("\n".join(rows))
    return 0


def command_model_list(args: argparse.Namespace) -> int:
    config = load_config()
    print(f"Configured enhance model: {config.enhance.model}")
    print("Cursor exposes its current model catalog through the interactive agent /model command.")
    return 0


def command_config(args: argparse.Namespace) -> int:
    repo = _optional_repo()
    if args.config_action is None:
        print(render(_config_for_repo(repo)), end="")
        return 0
    target_repo = None
    if getattr(args, "repo", False):
        if repo is None:
            raise PromptXError("--repo requires a Git repository")
        target_repo = repo.root
    if args.config_action == "get":
        config = load_config(target_repo) if target_repo else load_config()
        print(get_value(config, args.key))
        return 0
    path = set_value(args.key, args.value, repo=target_repo)
    print(f"Updated {args.key} in {path}")
    return 0


def command_test(args: argparse.Namespace) -> int:
    repo = _optional_repo()
    config = _apply_enhance_overrides(_config_for_repo(repo), args)
    failures = 0

    if config.translate.backend != "openai-compatible":
        print(f"Translator: unsupported ({config.translate.backend})")
        failures += 1
    elif not config.translate.api.base_url:
        print("Translator: not configured (missing base_url)")
        failures += 1
    elif not os.environ.get(config.translate.api.api_key_env):
        print(f"Translator: missing {config.translate.api.api_key_env}")
        failures += 1
    else:
        try:
            translated = OpenAICompatibleTranslator(config.translate).translate("测试")
            print(f"Translator: ok ({translated[:80]})")
        except PromptXError as exc:
            print(f"Translator: failed ({exc})")
            failures += 1

    if repo is None:
        print("Workspace: missing")
        failures += 1
    else:
        kind = "Git repository" if repo.is_git else "plain directory"
        print(f"Workspace: ok ({repo.root}; {kind})")

    try:
        backend = create_backend(config)
        if not backend.available():
            print("Enhance backend: missing")
            failures += 1
        elif repo is None:
            print("Enhance backend: skipped (no repository)")
        else:
            result = backend.enhance(
                "Return the words 'PromptX backend OK' only.",
                repo,
                None,
                config,
            )
            print(f"Enhance backend: ok ({result[:120]})")
    except PromptXError as exc:
        print(f"Enhance backend: failed ({exc})")
        failures += 1
    return 1 if failures else 0


def command_install(args: argparse.Namespace) -> int:
    if args.integration != "claude":
        raise PromptXError(f"Unknown integration: {args.integration}")
    paths = install_claude(force=args.force, dry_run=args.dry_run)
    prefix = "Would update" if args.dry_run else "Updated"
    print(prefix + ":\n" + "\n".join(f"- {path}" for path in paths))
    if not args.dry_run:
        for item in claude_diagnostics():
            if item.startswith("Warning:"):
                print(item)
    return 0


def command_uninstall(args: argparse.Namespace) -> int:
    if args.integration != "claude":
        raise PromptXError(f"Unknown integration: {args.integration}")
    paths = uninstall_claude()
    print("Restored:\n" + "\n".join(f"- {path}" for path in paths))
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    if args.component != "claude":
        raise PromptXError(f"Unknown diagnostic component: {args.component}")
    print("\n".join(claude_diagnostics()))
    return 0


def _dispatch_enhance_control(text: str, args: argparse.Namespace) -> int | None:
    stripped = text.strip()
    try:
        words = shlex.split(stripped)
    except ValueError:
        return None
    if words == ["init"]:
        return command_init(args)
    if words == ["refresh"]:
        return command_refresh(args)
    if words == ["status"]:
        return command_status(args)
    if words == ["test"]:
        return command_test(args)
    if words == ["backend", "list"]:
        return command_backend_list(args)
    if words == ["model", "list"]:
        return command_model_list(args)
    if words == ["config"]:
        args.config_action = None
        return command_config(args)
    if len(words) == 3 and words[0] == "config" and words[1] in {"backend", "model"}:
        args.config_action = "set"
        args.key = f"enhance.{words[1]}"
        args.value = words[2]
        args.repo = False
        return command_config(args)
    return None


def command_claude_hook(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        raise PromptXError(f"Invalid Claude hook input: {exc}") from exc
    if not isinstance(payload, dict):
        raise PromptXError("Claude hook input must be a JSON object")
    if (
        payload.get("hook_event_name") != "UserPromptExpansion"
        or payload.get("command_name") != "enhance"
    ):
        return 0

    command_args = payload.get("command_args", "")
    if not isinstance(command_args, str):
        raise PromptXError("Claude hook command_args must be a string")

    hook_args = argparse.Namespace(backend=None, model=None)
    stdout = io.StringIO()
    stderr = io.StringIO()
    previous_cwd = Path.cwd()
    requested_cwd = payload.get("cwd")
    handled: int | None = None
    try:
        if requested_cwd:
            cwd = Path(str(requested_cwd)).expanduser()
            if not cwd.is_dir():
                raise PromptXError(f"Claude working directory does not exist: {cwd}")
            os.chdir(cwd)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            handled = _dispatch_enhance_control(command_args, hook_args)
    except PromptXError as exc:
        handled = 2
        stderr.write(f"promptx: {exc}\n")
    finally:
        os.chdir(previous_cwd)

    if handled is None:
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": (
                        "PromptX did not send this request to Claude. Keep "
                        "'/enhance <prompt>' in the input box and press Ctrl+T "
                        "to replace it with Cursor's enhanced English prompt."
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 0

    output = (stdout.getvalue() + stderr.getvalue()).strip()
    if not output:
        output = "PromptX command completed."
    print(json.dumps({"decision": "block", "reason": output}, ensure_ascii=False))
    return 0


def command_claude_submit_guard(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        raise PromptXError(f"Invalid Claude submit hook input: {exc}") from exc
    if not isinstance(payload, dict):
        raise PromptXError("Claude submit hook input must be a JSON object")
    if payload.get("hook_event_name") != "UserPromptSubmit":
        return 0
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        raise PromptXError("Claude submit hook prompt must be a string")
    if contains_cjk(prompt):
        print(
            "PromptX blocked Chinese text before Claude received it. "
            "Press Ctrl+T to translate the draft, then review and submit it.",
            file=sys.stderr,
        )
        return 2
    return 0


def command_enhance(args: argparse.Namespace) -> int:
    text = _read_text(args.text, args.stdin)
    handled = _dispatch_enhance_control(text, args)
    if handled is not None:
        return handled
    return _run_enhancement(text, args)


def _add_enhance_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend")
    parser.add_argument("--model")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="promptx")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    translate = subparsers.add_parser("translate", help="Translate a prompt to English")
    translate.add_argument("text", nargs="*")
    translate.add_argument("--stdin", action="store_true")
    translate.add_argument("--model")
    translate.add_argument("--base-url")
    translate.set_defaults(handler=command_translate)

    translate_file_parser = subparsers.add_parser(
        "translate-file", help="Translate a file in place when it contains Chinese"
    )
    translate_file_parser.add_argument("file", type=Path)
    translate_file_parser.set_defaults(handler=command_translate_file)

    editor = subparsers.add_parser("claude-editor", help=argparse.SUPPRESS)
    editor.add_argument("file", type=Path)
    editor.set_defaults(handler=command_translate_file)

    claude_hook = subparsers.add_parser("claude-hook", help=argparse.SUPPRESS)
    claude_hook.set_defaults(handler=command_claude_hook)

    submit_guard = subparsers.add_parser("claude-submit-guard", help=argparse.SUPPRESS)
    submit_guard.set_defaults(handler=command_claude_submit_guard)

    enhance = subparsers.add_parser("enhance", help="Enhance a prompt with workspace context")
    enhance.add_argument("text", nargs="*")
    enhance.add_argument("--stdin", action="store_true")
    _add_enhance_options(enhance)
    enhance.set_defaults(handler=command_enhance)

    init = subparsers.add_parser("init", help="Create a workspace summary")
    init.add_argument("--force", action="store_true")
    _add_enhance_options(init)
    init.set_defaults(handler=command_init)

    refresh = subparsers.add_parser("refresh", help="Refresh a workspace summary")
    _add_enhance_options(refresh)
    refresh.set_defaults(handler=command_refresh)

    status = subparsers.add_parser("status", help="Show PromptX workspace status")
    _add_enhance_options(status)
    status.set_defaults(handler=command_status)

    config = subparsers.add_parser("config", help="Read or update configuration")
    config_sub = config.add_subparsers(dest="config_action")
    config_get = config_sub.add_parser("get")
    config_get.add_argument("key")
    config_get.add_argument("--repo", action="store_true")
    config_set = config_sub.add_parser("set")
    config_set.add_argument("key")
    config_set.add_argument("value")
    config_set.add_argument("--repo", action="store_true")
    config.set_defaults(handler=command_config)

    backend = subparsers.add_parser("backend", help="Inspect enhance backends")
    backend_sub = backend.add_subparsers(dest="backend_action", required=True)
    backend_list = backend_sub.add_parser("list")
    backend_list.set_defaults(handler=command_backend_list)

    model = subparsers.add_parser("model", help="Inspect enhance models")
    model_sub = model.add_subparsers(dest="model_action", required=True)
    model_list = model_sub.add_parser("list")
    model_list.set_defaults(handler=command_model_list)

    test = subparsers.add_parser("test", help="Test configured services")
    _add_enhance_options(test)
    test.set_defaults(handler=command_test)

    install = subparsers.add_parser("install", help="Install an integration")
    install.add_argument("integration", choices=["claude"])
    install.add_argument("--force", action="store_true")
    install.add_argument("--dry-run", action="store_true")
    install.set_defaults(handler=command_install)

    uninstall = subparsers.add_parser("uninstall", help="Uninstall an integration")
    uninstall.add_argument("integration", choices=["claude"])
    uninstall.set_defaults(handler=command_uninstall)

    doctor = subparsers.add_parser("doctor", help="Diagnose an integration")
    doctor.add_argument("component", choices=["claude"])
    doctor.set_defaults(handler=command_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args) or 0)
    except PromptXError as exc:
        print(f"promptx: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("promptx: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
