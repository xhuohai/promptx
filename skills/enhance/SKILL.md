---
name: enhance
description: Manage PromptX or mark a draft for Cursor enhancement through Claude's external editor.
disable-model-invocation: true
argument-hint: <prompt|init|refresh|status|config|backend list|model list|test>
---

PromptX handles this command through its installed hook. Do not process the request
as a Claude task. If the hook is unavailable, tell the user to run
`promptx install claude`.
