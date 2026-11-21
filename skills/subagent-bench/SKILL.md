---
name: Subagent Bench
description: Run rigorous, controlled head-to-head benchmarks comparing LLM models and thinking/effort variants for OpenCode subagents (@fixer, @designer, @explorer, @oracle). Use this skill whenever the user wants to benchmark, compare, A/B test, evaluate, or choose the best model or thinking level (low/medium/high/xhigh) for any subagent lane or oh-my-opencode-slim preset, mentions `/modelcompare`, asks "which model should I use for fixer/designer/explorer/oracle", wants a blind UI screenshot comparison gallery, or wants to test a newly released model before updating their config.
---

# Subagent Bench

Run controlled, reproducible benchmarks for OpenCode subagent lanes (`@fixer`, `@designer`, `@explorer`, `@oracle`) using isolated workspaces, held-out grading suites, exact `opencode.db` telemetry, visual screenshot audits, and (for UI lanes) a blind side-by-side HTML review gallery.

## Why These Guardrails Matter

Standard single-prompt model tests mislead on agentic subagent lanes because real performance is dominated by **multi-hop tool-loop latency, edit discipline, edge-case depth, and self-verification honesty** — not raw one-shot benchmarks:

- **Automated pass rates hide glaring UI defects.** In real `@designer` runs, fast low-thinking models pass 100% of DOM checks while taking screenshots as a checkbox ritual and never calling `read()` on a single PNG — shipping unreadable headers or stuck empty-state banners. Always track `png_reads` alongside automated checks and visually inspect screenshots.
- **Playwright MCP shares browser/viewport state.** Running multiple `@designer` subagents concurrently — or running your own grading Playwright calls while a `@designer` subagent is active — corrupts viewport sizes, tabs, and console logs. `@designer` runs MUST be strictly sequential (1 at a time), whereas `@fixer` runs have isolated filesystem/git workspaces and parallelize cleanly in waves.
- **Model IDs & variants drift.** Never guess `providerID/modelID#variant` strings. Always look them up via `tools.opencode.models` first, and verify in `opencode.db` telemetry (`msg_models`) that every run actually executed on the intended model and thinking variant.
- **Multi-session handoffs happen on large matrices.** A 24–40 run suite can outlast a single orchestrator context window. Keep a live `state.json` + `HANDOFF.md` in `<work-dir>` so any follow-up session resumes without re-running completed work.

---

## Step 1: Scope & Confirm the Benchmark Matrix

Before scaffolding anything, clarify (or confirm from the user's prompt):

1. **Target subagent lane(s):** `fixer`, `designer`, `explorer`, or `oracle`.
2. **Candidate configs:** Exact `providerID/modelID#variant` references resolved via `tools.opencode.models` (e.g., `google/gemini-4-neon#medium` vs `google/gemini-4-hydrogen#high`, or a thinking-level sweep `low`, `medium`, `high`).
   - Give each config a short filesystem-safe slug (`neon-med`, `hydro-high`, `terra-med`, `sonnet-high`).
   - Note: `xhigh` on multi-hop subagent lanes (`@fixer`/`@designer`) almost always incurs a 2×–3.5× wall-clock latency tax with minimal quality gain; exclude `xhigh` by default unless the user explicitly asks for it or is benchmarking `@oracle`.
3. **Suite scope:** Full suite (recommended for config decisions) or a fast subset (e.g., 2 challenges for a quick sanity check).
4. **Target config file:** Check whether `~/.config/opencode/oh-my-opencode-slim.jsonc` (or `opencode.jsonc`) is a symlink (e.g., GNU Stow into `~/dotfiles/...`). Always edit the **resolved real path** when updating config so symlinks are never replaced with plain copies — and wait for user approval (and blind gallery review on `@designer`) before changing live config.

---

## Step 2: Load the Lane-Specific Playbook & Scaffold

Read ONLY the reference file(s) matching the requested lane:

- **`@fixer` lane:** Read `references/fixer-suite.md`
  - **5 multi-file projects** (`c1-refactor-ts`, `c2-feature-ts`, `c3-bugfix-py`, `c4-concurrent-go`, `c5-mvcc-kv-ts`), **72 hidden held-out grading tests**, Go `10× -race` flake/stress test, and 5 adversarial MVCC/GC deep probes.
  - Scripts: `scripts/fixer/bench_tools.py` (which invokes `build_c1_c2.py`, `build_c3_c4.py`, `build_c5.py`).
  - Execution: **Parallel waves** (e.g., 4–8 isolated subagents per wave; zero shared write scopes).
- **`@designer` lane:** Read `references/designer-suite.md`
  - **4 UI/UX & Playwright challenges** (`d1-bughunt`, `d2-greenfield`, `d4-nudge` continuing D2's exact `sessionID`, and `d3-interactive`), 28 automated checks, `png_reads` visual-critique telemetry, and a blind side-by-side HTML screenshot gallery (with `--standalone` WebP single-file export).
  - Scripts: `scripts/designer/build_templates.py`, `scripts/designer/server.mjs`, `scripts/designer/build_gallery.py`, `assets/gallery_template.html`.
  - Execution: **Strictly sequential (1 `@designer` at a time)**, never overlapping with orchestrator Playwright grading.
- **`@explorer` or `@oracle` lanes:** Read `references/explorer-oracle-suite.md`
  - Lightweight, zero-edit evaluation protocols (ground-truth codebase tracing/doc accuracy for `@explorer`; architecture/root-cause/trade-off blind rubric for `@oracle`).

All lanes share the unified telemetry & hygiene script:
```bash
python3 <skill_dir>/scripts/telemetry.py session <session_id> [--slice all|first_user|second_user]
python3 <skill_dir>/scripts/telemetry.py hygiene <run_dir>
python3 <skill_dir>/scripts/telemetry.py batch <sessions.json>
```
`telemetry.py` auto-discovers OpenCode's SQLite DB (`$XDG_DATA_HOME/opencode/opencode.db` or `~/.local/share/opencode/opencode.db`; override with `--db`).

---

## Step 3: Execute Runs Cleanly & Track State

1. **Workspace root:** Put all ephemeral benchmark artifacts under `/tmp/opencode/<bench-name>/` (e.g. `/tmp/opencode/fixer-bench/` or `/tmp/opencode/designer-bench/`), keeping the user's real repos completely clean.
2. **State persistence:** Maintain `<work-dir>/state.json` recording:
   - `models`: `{ "<slug>": "<provider/model#variant>" }`
   - `sessions`: `{ "<challenge>": { "<slug>": "<session_id>" } }`
   - `completed` and `remaining_queue`
   If a session runs long or approaches context compaction, write `<work-dir>/HANDOFF.md` with exact resume instructions and verbatim prompts.
3. **Strict prompt parity:** Every candidate config MUST receive the **exact same verbatim prompt** (differing only in workspace path and dev-server port). Never hint at hidden grading tests or deep probes.
4. **Watch for external API stalls:** Check `tok_s` and `max_turn_s` from `telemetry.py`. If a transient provider stall hits a subset of runs, report both raw times and an unconfounded stall-free average rather than silently skewing results.

---

## Step 4: Grade, Audit & Produce Deliverables

Read `references/report-template.md` before writing the final report.

1. **Automated grading:**
   - **Fixer:** Run `bench_tools.py grade-all --sessions <work-dir>/sessions.json --work-dir <work-dir>` (grades visible + hidden suites in clean scratch copies, Go `-race` stress, C5 deep probes, git diff stats, and `opencode.db` telemetry).
   - **Designer:** Grade each completed run sequentially in Playwright (`scale: "css"`, `browser_close()` at the end of every grading script), snapshot D2 before continuing into D4, save per-run result JSONs in `<work-dir>/results/`, and run `telemetry.py` (`--slice first_user` for D2, `--slice second_user` for D4).
2. **Qualitative & visual audit (never skip!):**
   - **Fixer:** Diff key modules across tied configs to assess modularity, scope discipline (no over-editing adjacent files), and unprompted edge-case rigor.
   - **Designer:** Visually inspect rendered desktop/alt-theme/mobile screenshots yourself with `read()` AND check `playwright.png_reads` vs `playwright.screenshot` from `telemetry.py` to spot models that skip visual self-review.
3. **Blind HTML gallery (Designer lane):**
   - Generate the blind side-by-side review gallery with `scripts/designer/build_gallery.py`:
     ```bash
     python3 <skill_dir>/scripts/designer/build_gallery.py \
       --work-dir <work-dir> \
       --screenshots-dir /tmp/opencode/playwright-mcp/<bench-name> \
       --models-json <work-dir>/models_meta.json \
       --out ~/<bench-name>-gallery.html \
       --standalone
     ```
   - `--standalone` embeds all screenshots as crisp `sharp-yuv` WebP data URIs (via ImageMagick `magick`) so the single HTML file works offline, survives `/tmp` cleanup, and can be shared directly with teammates.
4. **Comparison report:**
   - Write a structured Markdown report (e.g., `~/<agent>-benchmark-<label>.md`) following `references/report-template.md`: overall table, per-challenge matrix, speed/accuracy/craft findings, top 2–3 config recommendations, configs to skip, and copy-pasteable `oh-my-opencode-slim.jsonc` snippets.
5. **Apply config only after user picks:**
   - For `@designer`, let the user score the blind gallery and reveal models first.
   - Once confirmed, update the resolved `oh-my-opencode-slim.jsonc` path (preserving symlinks) with a concise benchmark-backed comment explaining why that model/variant won.
