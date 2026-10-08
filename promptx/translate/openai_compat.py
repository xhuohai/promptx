from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from ..config import TranslateConfig
from ..errors import BackendError, ConfigError
from .base import Translator, contains_cjk


TRANSLATION_START = "<PROMPTX_TRANSLATION>"
TRANSLATION_END = "</PROMPTX_TRANSLATION>"

SYSTEM_PROMPT = f"""Translate every Chinese natural-language part of the user's prompt into natural technical English, including prompts that already contain English.

Preserve exactly:
- code
- symbols
- paths
- commands
- flags
- model names
- numbers
- error messages
- quoted text when appropriate

Do not add requirements.
Do not remove constraints.
Do not explain anything.
Do not leave Chinese prose untranslated merely because it is mixed with English.
Return exactly this format, with no reasoning or text outside the tags:
{TRANSLATION_START}
translated prompt
{TRANSLATION_END}"""

REPAIR_PROMPT = f"""The previous translation still contains Chinese. Translate every remaining Chinese natural-language part into English while preserving existing English, code, symbols, paths, commands, flags, model names, numbers, negations, and constraints.

Do not explain anything. Return exactly this format:
{TRANSLATION_START}
fully translated prompt
{TRANSLATION_END}"""


def _endpoint(base_url: str) -> str:
    value = base_url.rstrip("/")
    if not value:
        raise ConfigError(
            "translate.openai-compatible.base_url is not configured"
        )
    if value.endswith("/chat/completions"):
        return value
    if value.endswith("/v1"):
        return value + "/chat/completions"
    return value + "/v1/chat/completions"


class OpenAICompatibleTranslator(Translator):
    def __init__(self, config: TranslateConfig):
        self.config = config

    def _request(self, text: str, system_prompt: str) -> str:
        api_key = os.environ.get(self.config.api.api_key_env, "")
        if not api_key:
            raise ConfigError(
                f"Environment variable {self.config.api.api_key_env} is not set"
            )
        payload = {
            "model": self.config.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        }
        request = urllib.request.Request(
            _endpoint(self.config.api.base_url),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.config.timeout_seconds
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise BackendError(f"Translator HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise BackendError(f"Translator request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise BackendError("Translator returned invalid JSON") from exc

        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise BackendError("Translator response has no message content") from exc
        if not isinstance(content, str) or not content.strip():
            raise BackendError("Translator returned an empty response")
        return content.strip()

    @staticmethod
    def _extract(content: str) -> str:
        # Some reasoning models put hidden work in content despite the instruction.
        cleaned = re.sub(
            r"<think\b[^>]*>.*?</think>", "", content,
            flags=re.IGNORECASE | re.DOTALL,
        ).strip()
        start = cleaned.rfind(TRANSLATION_START)
        if start >= 0:
            start += len(TRANSLATION_START)
            end = cleaned.find(TRANSLATION_END, start)
            if end >= 0:
                extracted = cleaned[start:end].strip()
                if extracted:
                    return extracted
        return cleaned

    def translate(self, text: str) -> str:
        current = text
        for attempt in range(2):
            system_prompt = SYSTEM_PROMPT if attempt == 0 else REPAIR_PROMPT
            current = self._extract(self._request(current, system_prompt))
            if not contains_cjk(current):
                return current
        return current
