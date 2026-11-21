# Benchmark Comparison Report Template

Write the final comparison report (e.g., `~/<agent>-benchmark-<label>.md`) using this structure so every benchmark produces consistent, apples-to-apples decision evidence.

```markdown
# `@<agent>` Subagent Benchmark: <Model A> vs. <Model B>

**Date:** YYYY-MM-DD  
**Target Config:** `<resolved path to oh-my-opencode-slim.jsonc>` (`presets.<preset>.<agent>`)  
**Current Setting:** `<current model>` (`variant: "<current>"`)  
**Scope:** <N> isolated `@<agent>` runs — <C> challenges × <M> configs  
**Verification:** Exact model/variant, timing, and token telemetry from `opencode.db`, <automated checks summary>, and <qualitative/visual audit summary>.  
*(For `@designer`:)* **Blind Visual Review Gallery:** `<path to gallery.html>`

---

## Benchmark Suite
List each challenge with its scope, hidden checks / probes, and what capability it differentiates.

---

## Overall Comparison
Include one top-level summary table comparing all configs side by side:
- **Fixer columns:** Config | Hidden Tests | Extra Stress/Probes | Avg Wall Time (note stall-free avg if any external stalls occurred) | Median `tok/s` | Avg Turns | Tool Calls / Errors | Reasoning / Output Toks | Total Cost
- **Designer columns:** Config | Auto Checks | Visual Defects Found | Avg Wall Time | Median `tok/s` | Avg Turns | Tool Calls / Errors | PNGs Visually Read (`png_reads / screenshots`) | Reasoning / Output Toks | Total Cost
- **Explorer/Oracle columns:** Config | Rubric Score | Citation/Recall Accuracy | Avg Wall Time | Avg Turns | Per-Hop Latency | Tool Calls / Errors | Total Cost

### Per-Challenge Breakdown Table
Show exact per-challenge `wall_s` (plus turns / probes / `png_reads`) so outliers, stalls, and variance are never hidden by averages.

---

## Detailed Findings
1. **Accuracy, Edge-Case Depth & Self-Verification Discipline** (highlight hidden failures, deep probe gaps, or `png_reads == 0` visual defects).
2. **Quality, Craft & Edit Discipline** (module boundaries, scope creep, typography/layout/a11y polish).
3. **Speed & Multi-Hop Latency** (how decode speed × turns compounds in real loops; flag any external API stall windows transparently).

---

## Verdict & Recommendations
- State clearly whether cost is a constraint or secondary.
- Rank the **Top 2–3 Choices** with explicit trade-offs (e.g., Best Overall Craft vs. Best Speed/Quality Compromise vs. Fastest Reliable Loop).
- List **Configurations to Skip** and the exact empirical reason why.
- *(For `@designer`)* Remind the user to score the blind gallery and click **Reveal Models** before finalizing the config edit.

---

## Config Snippets (`<resolved path>`)
Provide copy-pasteable JSONC blocks for the top 2–3 options under `presets.<preset>.<agent>`.
```
