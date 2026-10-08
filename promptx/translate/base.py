from __future__ import annotations

import re
from abc import ABC, abstractmethod


_CJK_RE = re.compile(
    "["
    "\\u3400-\\u4dbf"
    "\\u4e00-\\u9fff"
    "\\uf900-\\ufaff"
    "\\U00020000-\\U0002ffff"
    "]"
)


def contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def cjk_count(text: str) -> int:
    return len(_CJK_RE.findall(text))


class Translator(ABC):
    @abstractmethod
    def translate(self, text: str) -> str:
        raise NotImplementedError
