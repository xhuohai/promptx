from __future__ import annotations

from .. import activity, cache
from ..config import Config
from ..errors import PromptXError
from ..repo import Repository
from ..translate.base import contains_cjk
from ..translate.openai_compat import OpenAICompatibleTranslator
from .registry import create_backend
from .context import collect_context


def _translate_result(text: str, config: Config) -> str:
    if config.translate.backend != "openai-compatible":
        raise PromptXError(
            "Enhance backend output contains Chinese, but the configured translator "
            f"is unsupported ({config.translate.backend}); nothing was sent to Claude"
        )
    try:
        result = OpenAICompatibleTranslator(config.translate).translate(text)
    except PromptXError as exc:
        raise PromptXError(
            "Enhance backend output contains Chinese and the translation fallback "
            f"failed: {exc}; nothing was sent to Claude"
        ) from exc
    if contains_cjk(result):
        raise PromptXError(
            "Enhance backend and translator outputs still contain Chinese; "
            "nothing was sent to Claude"
        )
    return result


def enhance_prompt(prompt: str, repo: Repository, config: Config) -> str:
    state = (
        cache.load(repo)
        if config.cache.enabled
        else cache.CacheState("disabled", None, None)
    )
    activity.save(
        route="enhance",
        backend=config.enhance.backend,
        model=config.enhance.model,
        workspace=repo.root,
        status="started",
    )
    used_fallback = False
    try:
        backend = create_backend(config)
        context = collect_context(prompt, repo)
        result = backend.enhance(
            prompt,
            repo,
            state.summary,
            config,
            summary_stale=state.status == "stale",
            context=context,
        )
        if contains_cjk(result):
            result = _translate_result(result, config)
            used_fallback = True
    except Exception:
        activity.save(
            route="enhance",
            backend=config.enhance.backend,
            model=config.enhance.model,
            workspace=repo.root,
            status="failed",
            translation_fallback=used_fallback,
        )
        raise
    activity.save(
        route="enhance",
        backend=config.enhance.backend,
        model=config.enhance.model,
        workspace=repo.root,
        status="ok",
        translation_fallback=used_fallback,
    )
    return result
