from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from ...errors import PromptXError


MANIFEST_NAME = ".promptx-install.json"


def claude_home() -> Path:
    override = os.environ.get("PROMPTX_CLAUDE_HOME")
    return Path(override).expanduser() if override else Path.home() / ".claude"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromptXError(f"Cannot read JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PromptXError(f"Expected a JSON object in {path}")
    return value


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".promptx.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _find_executable(name: str, override_env: str) -> str:
    override = os.environ.get(override_env)
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return str(path.resolve())
        raise PromptXError(f"{override_env} does not point to a file: {path}")
    located = shutil.which(name)
    if located:
        return str(Path(located).resolve())
    invoked = Path(sys.argv[0]).expanduser()
    if name == "promptx" and invoked.name == "promptx" and invoked.is_file():
        return str(invoked.resolve())
    if name == "promptx-claude-editor" and invoked.name == "promptx":
        sibling = invoked.with_name("promptx-claude-editor")
        if sibling.is_file():
            return str(sibling.resolve())
    raise PromptXError(
        f"Cannot find {name} on PATH. Install PromptX first, then rerun this command."
    )


def _binding_block(document: dict[str, Any], context: str) -> dict[str, Any]:
    bindings = document.setdefault("bindings", [])
    if not isinstance(bindings, list):
        raise PromptXError("Claude keybindings.json field 'bindings' must be an array")
    for block in bindings:
        if isinstance(block, dict) and block.get("context") == context:
            values = block.setdefault("bindings", {})
            if not isinstance(values, dict):
                raise PromptXError(
                    f"Claude keybindings for context {context} must be an object"
                )
            return values
    block = {"context": context, "bindings": {}}
    bindings.append(block)
    return block["bindings"]


def _set_binding(
    document: dict[str, Any], context: str, keystroke: str, action: str | None
) -> None:
    bindings = document.setdefault("bindings", [])
    if not isinstance(bindings, list):
        raise PromptXError("Claude keybindings.json field 'bindings' must be an array")
    matched = False
    for block in bindings:
        if isinstance(block, dict) and block.get("context") == context:
            values = block.setdefault("bindings", {})
            if not isinstance(values, dict):
                raise PromptXError(
                    f"Claude keybindings for context {context} must be an object"
                )
            values[keystroke] = action
            matched = True
    if not matched:
        _binding_block(document, context)[keystroke] = action


def _remove_binding(
    document: dict[str, Any],
    context: str,
    keystroke: str,
    *,
    expected_action: str | None = None,
) -> None:
    bindings = document.get("bindings", [])
    if not isinstance(bindings, list):
        raise PromptXError("Claude keybindings.json field 'bindings' must be an array")
    for block in bindings:
        if not isinstance(block, dict) or block.get("context") != context:
            continue
        values = block.get("bindings", {})
        if not isinstance(values, dict):
            raise PromptXError(
                f"Claude keybindings for context {context} must be an object"
            )
        if keystroke not in values:
            continue
        if expected_action is None or values.get(keystroke) == expected_action:
            del values[keystroke]


def _render_skill(promptx_command: str) -> str:
    template = (
        resources.files("promptx.integrations.claude")
        .joinpath("skill_template.md")
        .read_text(encoding="utf-8")
    )
    quoted = shlex.quote(promptx_command)
    return template.replace("__PROMPTX_COMMAND__", quoted)


def _add_prompt_expansion_hook(
    settings: dict[str, Any], promptx_command: str
) -> None:
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise PromptXError("Claude settings.json field 'hooks' must be an object")
    expansions = hooks.setdefault("UserPromptExpansion", [])
    if not isinstance(expansions, list):
        raise PromptXError(
            "Claude settings.json hook 'UserPromptExpansion' must be an array"
        )
    entry = {
        "matcher": "enhance",
        "hooks": [
            {
                "type": "command",
                "command": f"{shlex.quote(promptx_command)} claude-hook",
                "timeout": 300,
            }
        ],
    }
    if entry not in expansions:
        expansions.append(entry)


def _add_submit_guard_hook(settings: dict[str, Any], promptx_command: str) -> None:
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise PromptXError("Claude settings.json field 'hooks' must be an object")
    submissions = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(submissions, list):
        raise PromptXError(
            "Claude settings.json hook 'UserPromptSubmit' must be an array"
        )
    entry = {
        "hooks": [
            {
                "type": "command",
                "command": f"{shlex.quote(promptx_command)} claude-submit-guard",
                "timeout": 5,
            }
        ],
    }
    if entry not in submissions:
        submissions.append(entry)


def _truthy_environment_value(value: Any) -> bool:
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def claude_diagnostics() -> list[str]:
    root = claude_home()
    settings_path = root / "settings.json"
    keybindings_path = root / "keybindings.json"
    settings = _read_json(settings_path)
    keybindings = _read_json(keybindings_path)
    env = settings.get("env", {})
    if not isinstance(env, dict):
        env = {}

    global_bound = False
    legacy_global_unbound = False
    legacy_chat_bound = False
    bindings = keybindings.get("bindings", [])
    if isinstance(bindings, list):
        for block in bindings:
            if not isinstance(block, dict):
                continue
            values = block.get("bindings", {})
            if not isinstance(values, dict):
                continue
            if (
                block.get("context") == "Global"
                and values.get("ctrl+t") == "chat:externalEditor"
            ):
                global_bound = True
            if block.get("context") == "Global" and values.get("ctrl+t", 1) is None:
                legacy_global_unbound = True
            if (
                block.get("context") == "Chat"
                and values.get("ctrl+t") == "chat:externalEditor"
            ):
                legacy_chat_bound = True

    disabled_by_telemetry = _truthy_environment_value(
        env.get("DISABLE_TELEMETRY")
    ) or _truthy_environment_value(os.environ.get("DISABLE_TELEMETRY"))
    lines = [
        f"Claude home: {root}",
        f"Ctrl+T global external editor binding: {_yes_no(global_bound)}",
        f"DISABLE_TELEMETRY enabled: {_yes_no(disabled_by_telemetry)}",
    ]
    if disabled_by_telemetry:
        lines.append(
            "Warning: affected Claude Code versions may ignore custom keybindings "
            "when DISABLE_TELEMETRY is enabled; the built-in Ctrl+G binding still works."
        )
    elif global_bound:
        lines.append(
            "Static keybinding configuration is valid. If Ctrl+T is still ignored, "
            "run 'claude --debug' and inspect lines containing '[keybindings]'."
        )
    elif legacy_global_unbound and legacy_chat_bound:
        lines.append(
            "Warning: legacy split Ctrl+T bindings are installed; rerun "
            "'promptx install claude' to replace the Global action directly."
        )
    else:
        lines.append(
            "Warning: PromptX Ctrl+T bindings are incomplete; rerun "
            "'promptx install claude'."
        )
    return lines


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def install_claude(*, force: bool = False, dry_run: bool = False) -> list[str]:
    root = claude_home()
    settings_path = root / "settings.json"
    keybindings_path = root / "keybindings.json"
    skill_path = root / "skills" / "enhance" / "SKILL.md"
    manifest_path = root / MANIFEST_NAME

    editor_command = _find_executable(
        "promptx-claude-editor", "PROMPTX_CLAUDE_EDITOR"
    )
    promptx_command = _find_executable("promptx", "PROMPTX_COMMAND")
    skill_content = _render_skill(promptx_command)

    if skill_path.exists() and skill_path.read_text(encoding="utf-8") != skill_content:
        if not force:
            raise PromptXError(
                f"A different Claude skill already exists at {skill_path}; use --force to replace it"
            )

    settings = _read_json(settings_path)
    keybindings = _read_json(keybindings_path)
    if manifest_path.exists():
        previous = _read_json(manifest_path).get("previous", {})
        if not isinstance(previous, dict):
            raise PromptXError(f"Invalid PromptX installation record: {manifest_path}")
    else:
        previous = {
            "settings_existed": settings_path.exists(),
            "settings": settings,
            "keybindings_existed": keybindings_path.exists(),
            "keybindings": keybindings,
            "skill_existed": skill_path.exists(),
            "skill": skill_path.read_text(encoding="utf-8") if skill_path.exists() else None,
        }

    new_settings = json.loads(json.dumps(settings))
    env = new_settings.setdefault("env", {})
    if not isinstance(env, dict):
        raise PromptXError("Claude settings.json field 'env' must be an object")
    real_editor = (
        env.get("PROMPTX_REAL_EDITOR")
        or env.get("VISUAL")
        or env.get("EDITOR")
        or os.environ.get("VISUAL")
        or os.environ.get("EDITOR")
    )
    if real_editor:
        env["PROMPTX_REAL_EDITOR"] = real_editor
    env["VISUAL"] = editor_command
    env["EDITOR"] = editor_command
    _add_prompt_expansion_hook(new_settings, promptx_command)
    _add_submit_guard_hook(new_settings, promptx_command)

    new_keybindings = json.loads(json.dumps(keybindings))
    new_keybindings.setdefault(
        "$schema", "https://www.schemastore.org/claude-code-keybindings.json"
    )
    new_keybindings.setdefault("$docs", "https://code.claude.com/docs/en/keybindings")
    _set_binding(
        new_keybindings, "Global", "ctrl+t", "chat:externalEditor"
    )
    _remove_binding(
        new_keybindings,
        "Chat",
        "ctrl+t",
        expected_action="chat:externalEditor",
    )

    changed = [str(settings_path), str(keybindings_path), str(skill_path)]
    if dry_run:
        return changed
    root.mkdir(parents=True, exist_ok=True)
    _write_json(
        manifest_path,
        {
            "previous": previous,
            "installed": {
                "settings": new_settings,
                "keybindings": new_keybindings,
                "skill": skill_content,
            },
        },
    )
    _write_json(settings_path, new_settings)
    _write_json(keybindings_path, new_keybindings)
    _atomic_write(skill_path, skill_content)
    return changed


def uninstall_claude() -> list[str]:
    root = claude_home()
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        raise PromptXError("No PromptX Claude installation record was found")
    manifest = _read_json(manifest_path)
    previous = manifest.get("previous", {})
    installed = manifest.get("installed", {})
    if not isinstance(previous, dict) or not isinstance(installed, dict):
        raise PromptXError(f"Invalid PromptX installation record: {manifest_path}")
    settings_path = root / "settings.json"
    keybindings_path = root / "keybindings.json"
    skill_path = root / "skills" / "enhance" / "SKILL.md"

    current_settings = _read_json(settings_path)
    current_keybindings = _read_json(keybindings_path)
    current_skill = skill_path.read_text(encoding="utf-8") if skill_path.exists() else None
    if (
        current_settings != installed.get("settings")
        or current_keybindings != installed.get("keybindings")
        or current_skill != installed.get("skill")
    ):
        raise PromptXError(
            "Claude configuration changed after PromptX was installed; refusing to overwrite newer changes"
        )

    if previous.get("settings_existed"):
        _write_json(settings_path, previous.get("settings", {}))
    elif settings_path.exists():
        settings_path.unlink()
    if previous.get("keybindings_existed"):
        _write_json(keybindings_path, previous.get("keybindings", {}))
    elif keybindings_path.exists():
        keybindings_path.unlink()
    if previous.get("skill_existed"):
        _atomic_write(skill_path, str(previous.get("skill") or ""))
    elif skill_path.exists():
        skill_path.unlink()
        try:
            skill_path.parent.rmdir()
        except OSError:
            pass
    manifest_path.unlink()
    return [str(settings_path), str(keybindings_path), str(skill_path)]
