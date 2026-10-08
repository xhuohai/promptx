from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..config import Config
from ..repo import Repository
from .context import WorkspaceContext


@dataclass(frozen=True)
class BackendCapabilities:
    repo_aware: bool
    filesystem_search: bool
    model_selection: bool
    readonly_mode: bool


class EnhanceBackend(ABC):
    name: str
    capabilities: BackendCapabilities

    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def summarize(self, repo: Repository, config: Config) -> str:
        raise NotImplementedError
