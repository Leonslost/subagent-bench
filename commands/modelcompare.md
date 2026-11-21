---
description: Benchmark and compare models/thinking variants for OpenCode subagents (@fixer, @designer, @explorer, @oracle)
---

Load the `subagent-bench` skill first (`skill` tool with `id: "subagent-bench"`), then plan and run a controlled subagent model comparison for:

`$ARGUMENTS`

If `$ARGUMENTS` does not specify the target subagent (`fixer`, `designer`, `explorer`, `oracle`), candidate models/variants (e.g., `google/gemini-4-neon#medium vs google/gemini-4-hydrogen#high`), or scope (full suite vs quick subset), resolve candidate model IDs with `tools.opencode.models` and ask one concise clarifying question before scaffolding workspaces or launching benchmark runs.
