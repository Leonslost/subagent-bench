# `@explorer` & `@oracle` Benchmark Suite Reference

Lightweight, zero-edit evaluation protocols for read-only discovery (`@explorer`) and deep architectural/debugging advisory (`@oracle`) subagent lanes. Unlike `@designer`, both lanes are read-only and have no shared Playwright browser state — candidate configs can be dispatched in parallel waves.

---

## `@explorer` Suite (Fast Recon, Multi-Hop Tracing & External Docs)

`@explorer` is a high-volume, 10–25 hop search loop where **per-hop TTFT, recall accuracy, citation precision (exact `path:line`), and zero hallucinated symbols** matter far more than deep multi-minute reasoning.

### Recommended 4-Task Matrix
Run against either the user's current real repository (preferred — tests real codebase familiarity) or the scaffolded Fixer templates under `/tmp/opencode/fixer-bench/templates/`:

1. **`e1-symbol-trace` (Cross-File Call Graph)**: Trace a concrete request/event path end-to-end across 4+ files and list every caller, error transform, and side effect with exact `path:line` citations.
2. **`e2-needle-bug` (Silent Failure Discovery)**: Point `@explorer` at a multi-file repo with 2–3 planted subtle bugs (e.g., `c3-bugfix-py` template!) and ask it to locate all root causes with exact file/line evidence without editing files.
3. **`e3-api-docs` (External Docs Lookup)**: Ask a version-sensitive library/framework question requiring `context7` or `gh_grep` (e.g., a recently changed API signature or migration gotcha) and check for accurate current-version citations vs stale training-data guesses.
4. **`e4-impact-audit` (Refactor Blast Radius)**: Ask for every file, test, and export impacted by a proposed interface change, measuring both recall (missed sites) and precision (false positives).

### Grading Rubric (`0–10` per task)
- **Recall (0–4):** Fraction of ground-truth files/symbols/bugs found.
- **Citation Accuracy (0–3):** Exact `path:line` verified against disk (`0` hallucinated paths/line numbers).
- **Signal-to-Noise (0–3):** Concise, scannable output without dumping raw file walls into orchestrator context.
- **Telemetry (`telemetry.py`):** Pay close attention to `wall_s`, `turns`, `wall_s / turns` (per-hop latency!), `tool_calls`, `tool_errors`, and `cost`.

---

## `@oracle` Suite (Architecture, Root-Cause & High-Risk Trade-Offs)

`@oracle` is a rare, high-stakes one-shot escalation lane (so `high`/`xhigh` thinking is actually justified here!). Blind human/rubric comparison works best.

### Recommended 3-Task Matrix
1. **`o1-concurrency-root-cause`**: Supply a subtle race/deadlock/MVCC anomaly trace + relevant source files (e.g., an anomalous snapshot-isolation compaction trace from `c5-mvcc-kv-ts` or goroutine leak from `c4-concurrent-go`) and ask for exact interleaving proof + minimal fix + invariant verification plan.
2. **`o2-architecture-tradeoff`**: Present a concrete system design decision with 3 real constraints (latency budget, backward compatibility, operational complexity) and ask for a concrete recommendation, failure modes, and migration plan.
3. **`o3-code-simplification`**: Hand `@oracle` an over-engineered multi-file patch (~300–500 LOC) and ask what to delete, collapse, or keep without changing behavior.

### Blind Grading Protocol
- Strip model identifiers from each `@oracle` response and save them as `Response A`, `Response B`, ... (independently shuffled per task).
- Score blind on:
  1. **Correctness & Edge-Case Catch (0–4):** Did it find the actual mechanism/flaw rather than hand-waving?
  2. **Actionability & Restraint (0–3):** Concrete, minimal plan vs generic boilerplate or over-abstraction.
  3. **Honest Trade-Offs & Risk Calibration (0–3):** Calls out what could still go wrong.
- Compare blind scores against `wall_s`, `tokens_reasoning`, and `cost` from `telemetry.py`.
