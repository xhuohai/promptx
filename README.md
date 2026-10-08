# PromptX

PromptX translates or workspace-enhances a prompt before Claude Code receives it.

- Press `Ctrl+T` in Claude Code to translate the current input to English and put it back into the input box without submitting it. The built-in `Ctrl+G` shortcut opens the same translation editor and remains available as a fallback.
- Type `/enhance <request>` and press `Ctrl+T` to let Cursor inspect the current workspace and replace the draft with a context-aware English request. Review it, then press Enter to send it to Claude.
- PromptX blocks submissions containing Chinese characters before Claude receives the text. Translate with `Ctrl+T`, review the English draft, then submit it.

The normal translation path uses an OpenAI-compatible API. The enhancement path uses Cursor CLI in Ask mode with its sandbox enabled. PromptX does not use the active Claude model for either preprocessing step. The two paths share Claude Code's single external-editor shortcut, but PromptX selects the backend from the input: only a draft beginning with `/enhance ` uses Cursor.

## Requirements

- Python 3.11 or newer
- Claude Code with custom keybindings support
- Cursor CLI (`agent` or `cursor-agent`) for `/enhance`
- An OpenAI-compatible endpoint for `Ctrl+T` translation

## Install

```bash
python3 -m pip install .
promptx config set translate.openai-compatible.base_url https://example.com/v1
promptx config set translate.model qwen3-8b
export PROMPTX_API_KEY=...
promptx install claude
```

The installer updates these user-scoped Claude Code files while preserving unrelated fields:

- `~/.claude/settings.json`
- `~/.claude/keybindings.json`
- `~/.claude/skills/enhance/SKILL.md`

It registers a `UserPromptSubmit` guard for Chinese text. Install the updated integration after upgrading PromptX to activate the guard:

```bash
promptx install claude
```

It stores the previous values so they can be restored with:

```bash
promptx uninstall claude
python3 -m pip uninstall promptx-cli
```

Run the commands in that order. Uninstalling the Python package first leaves Claude Code pointing to missing PromptX commands and does not restore the previous editor or keybindings.

`EDITOR` and `VISUAL` are changed only inside Claude Code's own environment, not in the shell. The previous editor is recorded as `PROMPTX_REAL_EDITOR`.

Claude Code has one external-editor action. After installation, both `Ctrl+T` and the built-in `Ctrl+G` external-editor shortcut invoke PromptX translation. `Ctrl+T` normally toggles Claude's to-do list, so PromptX replaces that action directly in the `Global` context. Binding it in `Chat` after unbinding `Global` is unreliable because the global context takes precedence. If `Ctrl+T` is not picked up by the installed Claude Code version or terminal, use `Ctrl+G`; uninstalling restores the previous editor configuration and keybindings.

## Configure translation

Default config path: `~/.config/promptx/config.toml`.

```toml
[translate]
backend = "openai-compatible"
model = "qwen3-8b"
timeout_seconds = 60

[translate.openai-compatible]
base_url = "https://example.com/v1"
api_key_env = "PROMPTX_API_KEY"
```

Commands:

```bash
promptx translate "帮我看看这里为什么有死锁"
echo '把 foo() 攁成 std::span，但是 ABI 不能变' | promptx translate
promptx translate-file /tmp/prompt.txt
```

Pure English input is returned unchanged without contacting the API.

## Configure enhancement

```toml
[enhance]
backend = "cursor"
model = "auto"
executable = "auto"
timeout_seconds = 180

[cache]
enabled = true
```

PromptX checks `.promptx.toml` in the current workspace after the global config. Command-line `--backend` and `--model` values take final precedence.
The configured model is always passed to Cursor CLI explicitly. With `model = "auto"`, PromptX invokes Cursor with `--model auto` instead of inheriting a previously selected CLI model.

```bash
promptx init
promptx enhance "修一下 scheduler 的死锁，注意不能改变外部接口"
promptx status
promptx refresh
promptx backend list
promptx model list
promptx test
```

For prompt enhancement in Claude Code, type the request but press `Ctrl+T` instead of Enter:

```text
/enhance <prompt>
```

Cursor's result replaces the current input. It is not submitted automatically. The management forms below are regular commands; run them with Enter:

```text
/enhance init
/enhance refresh
/enhance status
/enhance config
/enhance config backend cursor
/enhance config model auto
/enhance backend list
/enhance model list
/enhance test
```

PromptX installs a `UserPromptExpansion` hook for these commands. It runs management forms directly and displays their output without sending them to Claude. If `/enhance <prompt>` is submitted with Enter, the hook blocks it and tells you to use `Ctrl+T`; Claude never receives the draft or the enhanced result automatically.

The `UserPromptSubmit` guard also blocks ordinary Chinese prompts, including drafts left unchanged after a translation error or missing API key. It tells you to use `Ctrl+T`; it does not translate or submit on Enter.

All management commands work in Git and non-Git workspaces.

Before Cursor runs, PromptX performs a bounded, read-only local scan inspired by the useful parts of Chiron-style context engines: it detects the task type, language/framework markers, a shallow workspace tree, likely relevant files, and (for Git repositories only) branch/status/diff summaries. Cursor receives these as search hints, verifies relevant files and symbols against the current workspace, and returns one Balanced prompt rather than a generic third-person answer or several variants. Generated/vendor directories and large files are excluded from the scan.

Cached workspace summaries live under `~/.cache/promptx/repos/<workspace-id>/`. In a Git repository, a different HEAD marks a summary stale but does not rebuild it. Cursor is told to verify task-specific facts against the current workspace.

PromptX also works in directories that are not Git repositories. Cursor uses the current directory as the workspace, skips Git-specific inspection, and can still build or refresh a cached summary. A non-Git cache remains fresh until it is manually refreshed because there is no Git HEAD to compare.

Cursor is explicitly instructed to return English only. If its result still contains Chinese, PromptX passes that result through the configured translator once and validates it again. A result containing Chinese is never sent to Claude.
Cursor is also instructed to return the enhanced request in the user's voice, not a third-person description or an instruction such as `Respond to the user`. Short, clear English input such as `hello` is preserved unchanged.

Cursor enhancement uses explicit result delimiters. PromptX extracts only the text inside the final result block, so Cursor progress narration such as `I'll inspect...` is not inserted into Claude's input box. If Cursor omits or truncates the result block, PromptX leaves the draft unchanged and reports an error instead of inserting ambiguous output.

The translator handles mixed Chinese/English prompts as one request. If the first response still contains Chinese, PromptX sends the partial translation through one focused repair pass before applying the existing no-Chinese gate. Reasoning text in `<think>...</think>` and text outside the translation result block are discarded.

`promptx status` (or `/enhance status`) shows the last preprocessing route, backend, model, status, workspace, and whether Cursor output needed the translation fallback. This makes it explicit whether the shared shortcut took `translate / openai-compatible`, `enhance / cursor`, or the local English passthrough path.

If `Ctrl+T` returns to the input box with no change, run `promptx status` from the same workspace. `Last route: passthrough` means the editor draft contained no detected Chinese. `Last route: translate` with `Last status: failed` shows a categorized `Last error` such as a missing API key, HTTP status, timeout, or untranslated Chinese. The original draft stays in the input box on failure. Translation uses the workspace's `.promptx.toml` overrides as enhancement does.

To inspect the installed Claude keybindings and common reasons why custom bindings are ignored:

```bash
promptx doctor claude
```

Cursor's documented Ask mode is read-only, and PromptX also passes `--sandbox enabled` plus explicit no-write instructions. Headless calls pass `--trust` to acknowledge the selected workspace without granting force/yolo permissions. Cursor CLI is still an external program; review its own configuration before using it with sensitive repositories.

## Development

```bash
python3 -m pip install -e '.[dev]'
pytest
```
