from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Activity:
    route: str
    backend: str
    model: str
    workspace: str
    status: str
    translation_fallback: bool
    created_at: str
    error: str = ""


def activity_path() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "promptx" / "last-run.json"


def save(
    *,
    route: str,
    backend: str,
    model: str,
    workspace: Path,
    status: str = "ok",
    translation_fallback: bool = False,
    error: str = "",
) -> Activity:
    entry = Activity(
        route=route,
        backend=backend,
        model=model,
        workspace=str(workspace.resolve()),
        status=status,
        translation_fallback=translation_fallback,
        created_at=datetime.now(timezone.utc).isoformat(),
        error=error,
    )
    try:
        path = activity_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(asdict(entry), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        # Diagnostics must never break prompt preprocessing.
        pass
    return entry


def load() -> Activity | None:
    try:
        payload = json.loads(activity_path().read_text(encoding="utf-8"))
        return Activity(**payload)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
