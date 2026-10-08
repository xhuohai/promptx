from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .repo import Repository


@dataclass(frozen=True)
class CacheEntry:
    repo_root: str
    remote: str
    head: str
    backend: str
    model: str
    created_at: str


@dataclass(frozen=True)
class CacheState:
    status: str
    summary: str | None
    metadata: CacheEntry | None


def cache_home() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "promptx" / "repos"


def entry_dir(repo: Repository) -> Path:
    return cache_home() / repo.identifier


def load(repo: Repository) -> CacheState:
    directory = entry_dir(repo)
    summary_path = directory / "summary.md"
    metadata_path = directory / "metadata.json"
    if not summary_path.exists() or not metadata_path.exists():
        return CacheState("missing", None, None)
    try:
        summary = summary_path.read_text(encoding="utf-8")
        metadata = CacheEntry(**json.loads(metadata_path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return CacheState("missing", None, None)
    status = "fresh" if metadata.head == repo.head else "stale"
    return CacheState(status, summary, metadata)


def save(repo: Repository, summary: str, *, backend: str, model: str) -> CacheEntry:
    directory = entry_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    metadata = CacheEntry(
        repo_root=str(repo.root),
        remote=repo.remote,
        head=repo.head,
        backend=backend,
        model=model,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    summary_tmp = directory / "summary.md.tmp"
    metadata_tmp = directory / "metadata.json.tmp"
    summary_tmp.write_text(summary.rstrip() + "\n", encoding="utf-8")
    metadata_tmp.write_text(
        json.dumps(asdict(metadata), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary_tmp.replace(directory / "summary.md")
    metadata_tmp.replace(directory / "metadata.json")
    return metadata
