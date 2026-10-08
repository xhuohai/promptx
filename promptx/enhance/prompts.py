from __future__ import annotations

from .context import WorkspaceContext


RESULT_START = "<PROMPTX_RESULT>"
RESULT_END = "</PROMPTX_RESULT>"


def build_enhance_prompt(
    user_prompt: str,
    summary: str | None,
    *,
    summary_stale: bool,
    is_git: bool = True,
    context: WorkspaceContext | None = None,
) -> str:
    summary_text = summary.strip() if summary else "No cached project summary is available."
    workspace_kind = "repository" if is_git else "workspace"
    git_instruction = (
        "- inspect git status and diff when relevant."
        if is_git
        else "- do not assume Git metadata or history is available."
    )
    stale_note = (
        f"\nThis cached summary may predate recent {workspace_kind} changes. "
        f"Verify task-specific facts against the current {workspace_kind}."
        if summary_stale and summary
        else ""
    )
    context_text = context.render() if context else "No deterministic context snapshot is available."
    return f"""You are preparing a task for another coding agent.

Your job is NOT to implement the task.

First inspect this {workspace_kind} only as much as needed to understand the user's request.

You may:
- search the {workspace_kind};
- inspect relevant files and symbols;
- read CLAUDE.md, AGENTS.md and project documentation;
{git_instruction}

Do not modify files. Do not create files. Do not run commands that change workspace state.

Use the deterministic snapshot below to focus your inspection. Candidate files are
hints only: verify any file, symbol, command, architecture, or constraint before
including it. Search beyond the candidates when necessary.

Rewrite the user's request into one balanced, precise technical English prompt,
written in the user's own voice and ready to paste directly into another coding
assistant. The final response
must be entirely in English and contain no Chinese/CJK characters, even when the user
writes in Chinese.

Rules:
1. Preserve the user's intent.
2. Do not invent requirements.
3. Preserve symbols, paths, commands, numeric constraints, negations and errors.
4. Add workspace-specific context only when verified from the current workspace.
5. Do not prescribe an implementation unless the user requested one.
6. Keep simple tasks concise.
7. If the input is already short, clear English and needs no workspace context, return
   it unchanged. For example, `hello` must remain `hello`.
8. Do not describe or classify the request. Do not write meta-instructions such as
   `Respond to the user`, `The user wants`, or `No coding task was requested`.
9. Do not include progress reports, inspection narration, a preamble, or language labels.
10. When workspace context is relevant, include verified file paths, symbols,
    constraints, and an appropriate verification step. Do not pad the result with
    generic advice or an inventory of unrelated files.
11. Prefer a compact paragraph or short task-focused bullets. Do not output multiple
    variants.
12. Return the result inside the exact transport delimiters below. Put nothing outside
    them. The delimiters are not part of the enhanced prompt:
    {RESULT_START}
    final enhanced prompt
    {RESULT_END}

DETERMINISTIC CONTEXT SNAPSHOT:
{context_text}

PROJECT SUMMARY:
{summary_text}{stale_note}

USER REQUEST:
{user_prompt}
"""


def build_summary_prompt(*, is_git: bool = True) -> str:
    workspace_kind = "repository" if is_git else "workspace"
    git_note = (
        "Use Git metadata when it helps verify the summary."
        if is_git
        else "This directory is not a Git repository. Do not assume Git metadata or history exists."
    )
    return f"""Inspect this {workspace_kind} and produce a concise project summary for another coding agent.

Do not modify files. Do not create files. Do not solve any open task.

{git_note}

Cover only facts verified from the {workspace_kind}:
- architecture and major directories;
- primary languages and toolchain;
- build and test commands;
- key components and their responsibilities;
- important constraints;
- relevant CLAUDE.md, AGENTS.md, and repository documentation.

Prefer paths and concrete names. Mark uncertain details as unknown.
Output only the Markdown summary."""
