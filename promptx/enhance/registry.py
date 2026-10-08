from __future__ import annotations

from dataclasses import dataclass

from ..config import Config
from ..errors import ConfigError
from .base import BackendCapabilities, EnhanceBackend
from .cursor import CursorBackend


@dataclass(frozen=True)
class BackendDescriptor:
    name: str
    capabilities: BackendCapabilities
    implemented: bool


BACKENDS = (
    BackendDescriptor(
        "cursor", BackendCapabilities(True, True, True, True), True
    ),
    BackendDescriptor("codex", BackendCapabilities(True, True, True, True), False),
    BackendDescriptor("gemini-cli", BackendCapabilities(True, True, True, True), False),
    BackendDescriptor("auggie", BackendCapabilities(True, True, True, True), False),
    BackendDescriptor("openai-api", BackendCapabilities(False, False, True, False), False),
)


def create_backend(config: Config) -> EnhanceBackend:
    if config.enhance.backend == "cursor":
        return CursorBackend(config.enhance.executable)
    known = {item.name for item in BACKENDS}
    if config.enhance.backend in known:
        raise ConfigError(
            f"Enhance backend '{config.enhance.backend}' is not implemented in v0.1"
        )
        raise ConfigError(f"Unknown enhance backend: {config.enhance.backend}")
