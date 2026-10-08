from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError


@dataclass(frozen=True)
class EnhanceConfig:
    backend: str = "cursor"
    model: str = "auto"
    executable: str = "auto"
    timeout_seconds: int = 180


@dataclass(frozen=True)
class TranslateAPIConfig:
    base_url: str = ""
    api_key_env: str = "PROMPTX_API_KEY"


@dataclass(frozen=True)
class TranslateConfig:
    backend: str = "openai-compatible"
    model: str = "qwen3-8b"
    timeout_seconds: int = 60
    api: TranslateAPIConfig = field(default_factory=TranslateAPIConfig)


@dataclass(frozen=True)
class CacheConfig:
    enabled: bool = True


@dataclass(frozen=True)
class Config:
    enhance: EnhanceConfig = field(default_factory=EnhanceConfig)
    translate: TranslateConfig = field(default_factory=TranslateConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)


def config_home() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "promptx"


def global_config_path() -> Path:
    override = os.environ.get("PROMPTX_CONFIG")
    return Path(override).expanduser() if override else config_home() / "config.toml"


def repo_config_path(repo: Path) -> Path:
    return repo / ".promptx.toml"


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Cannot read config {path}: {exc}") from exc


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _integer(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{key} must be a positive integer")
    return value


def _string(value: Any, key: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string")
    return value


def _boolean(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be true or false")
    return value


def _from_dict(raw: dict[str, Any]) -> Config:
    enhance = raw.get("enhance", {})
    translate = raw.get("translate", {})
    api = translate.get("openai-compatible", {})
    cache = raw.get("cache", {})
    for section_name, section in (
        ("enhance", enhance),
        ("translate", translate),
        ("translate.openai-compatible", api),
        ("cache", cache),
    ):
        if not isinstance(section, dict):
            raise ConfigError(f"[{section_name}] must be a TOML table")

    return Config(
        enhance=EnhanceConfig(
            backend=_string(enhance.get("backend", "cursor"), "enhance.backend"),
            model=_string(enhance.get("model", "auto"), "enhance.model"),
            executable=_string(enhance.get("executable", "auto"), "enhance.executable"),
            timeout_seconds=_integer(
                enhance.get("timeout_seconds", 180), "enhance.timeout_seconds"
            ),
        ),
        translate=TranslateConfig(
            backend=_string(
                translate.get("backend", "openai-compatible"), "translate.backend"
            ),
            model=_string(translate.get("model", "qwen3-8b"), "translate.model"),
            timeout_seconds=_integer(
                translate.get("timeout_seconds", 60), "translate.timeout_seconds"
            ),
            api=TranslateAPIConfig(
                base_url=_string(api.get("base_url", ""), "translate.openai-compatible.base_url"),
                api_key_env=_string(
                    api.get("api_key_env", "PROMPTX_API_KEY"),
                    "translate.openai-compatible.api_key_env",
                ),
            ),
        ),
        cache=CacheConfig(enabled=_boolean(cache.get("enabled", True), "cache.enabled")),
    )


def load_config(repo: Path | None = None) -> Config:
    raw = _load_toml(global_config_path())
    if repo is not None:
        raw = _deep_merge(raw, _load_toml(repo_config_path(repo)))
    return _from_dict(raw)


def as_dict(config: Config) -> dict[str, Any]:
    return {
        "enhance": {
            "backend": config.enhance.backend,
            "model": config.enhance.model,
            "executable": config.enhance.executable,
            "timeout_seconds": config.enhance.timeout_seconds,
        },
        "translate": {
            "backend": config.translate.backend,
            "model": config.translate.model,
            "timeout_seconds": config.translate.timeout_seconds,
            "openai-compatible": {
                "base_url": config.translate.api.base_url,
                "api_key_env": config.translate.api.api_key_env,
            },
        },
        "cache": {"enabled": config.cache.enabled},
    }


VALID_KEYS = {
    "enhance.backend",
    "enhance.model",
    "enhance.executable",
    "enhance.timeout_seconds",
    "translate.backend",
    "translate.model",
    "translate.timeout_seconds",
    "translate.openai-compatible.base_url",
    "translate.openai-compatible.api_key_env",
    "cache.enabled",
}


def get_value(config: Config, dotted_key: str) -> Any:
    if dotted_key not in VALID_KEYS:
        raise ConfigError(f"Unknown config key: {dotted_key}")
    value: Any = as_dict(config)
    for part in dotted_key.split("."):
        value = value[part]
    return value


def _parse_value(key: str, value: str) -> Any:
    if key.endswith("timeout_seconds"):
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ConfigError(f"{key} must be a positive integer") from exc
        return _integer(parsed, key)
    if key == "cache.enabled":
        lowered = value.lower()
        if lowered not in {"true", "false"}:
            raise ConfigError("cache.enabled must be true or false")
        return lowered == "true"
    return value


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _serialize(raw: dict[str, Any]) -> str:
    lines: list[str] = []
    for section in ("enhance", "translate"):
        values = raw.get(section, {})
        if values:
            lines.append(f"[{section}]")
            for key, value in values.items():
                if not isinstance(value, dict):
                    lines.append(f"{key} = {_format_toml(value)}")
            lines.append("")
    translate_api = raw.get("translate", {}).get("openai-compatible", {})
    if translate_api:
        lines.append("[translate.openai-compatible]")
        for key, value in translate_api.items():
            lines.append(f"{key} = {_format_toml(value)}")
        lines.append("")
    cache = raw.get("cache", {})
    if cache:
        lines.append("[cache]")
        for key, value in cache.items():
            lines.append(f"{key} = {_format_toml(value)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _format_toml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _toml_quote(value)
    raise ConfigError(f"Unsupported config value: {value!r}")


def set_value(dotted_key: str, value: str, *, repo: Path | None = None) -> Path:
    if dotted_key not in VALID_KEYS:
        raise ConfigError(f"Unknown config key: {dotted_key}")
    path = repo_config_path(repo) if repo is not None else global_config_path()
    raw = _load_toml(path)
    target = raw
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        child = target.setdefault(part, {})
        if not isinstance(child, dict):
            raise ConfigError(f"Cannot set {dotted_key}: {part} is not a table")
        target = child
    target[parts[-1]] = _parse_value(dotted_key, value)
    _from_dict(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_serialize(raw), encoding="utf-8")
    return path


def render(config: Config) -> str:
    return _serialize(as_dict(config))
