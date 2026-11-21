# subagent-bench

A portable, zero-dependency OpenCode V2 skill and `/modelcompare` slash command for running controlled, reproducible head-to-head benchmarks across LLM models and thinking/effort variants (`low`, `medium`, `high`, `xhigh`) on your OpenCode subagent lanes (`@fixer`, `@designer`, `@explorer`, `@oracle`).

Instead of guessing from public leaderboards, `subagent-bench` runs your actual subagent harness on isolated real-world multi-file tasks, pulls exact model/variant/token/timing/Playwright telemetry from OpenCode's SQLite database (`opencode.db`), grades against hidden held-out test suites, audits visual self-critique discipline, and builds a shareable standalone blind HTML screenshot gallery for UI reviews.

---

## What's Included

### 1. `@fixer` Suite (5 Multi-File Projects · 72 Hidden Tests · Stress & Deep Probes)
- **`c1-refactor-ts`** *(10 TS files, 19 hidden tests)* — Exception-to-`Result<T, AppError>` + `AbortSignal`/timeout propagation + legacy compatibility shim.
- **`c2-feature-ts`** *(7 TS files, 13 hidden tests)* — Stateful job dispatcher: per-tenant concurrency caps, cross-tenant round-robin fairness, clock-based idempotency TTL, DLQ + replay, graceful drain.
- **`c3-bugfix-py`** *(7 Python files, 16 hidden tests)* — 4 interacting billing bugs: month-end/leap-day anchor drift, Hamilton cent allocation, `Decimal ROUND_HALF_UP`, coupon compounding/preview purity, idempotent credit notes.
- **`c4-concurrent-go`** *(6 Go files, 10 hidden tests + `10× go test -race`)* — Race-free concurrent DAG runner with cycle validation, slot release during retry backoff, `FailFast` goroutine draining, and serialized `EventSink`.
- **`c5-mvcc-kv-ts`** *(6 TS files, 14 hidden tests + 5 adversarial MVCC/GC probes)* — In-memory MVCC KV store with Snapshot Isolation, First-Committer-Wins conflicts, nested savepoints, merged range scans, and multi-snapshot compaction.

### 2. `@designer` Suite (4 UI/UX Challenges · 28 Automated Checks · Blind Gallery)
- **`d1-bughunt`** — PulseGrid billing dashboard with 8 planted visual, contrast, responsive, JS filter, and accessible drawer bugs.
- **`d2-greenfield`** — Kestrel F2 acoustic hardware showcase with inline SVG/live VU meter, recording mode switcher, spec datasheet, and live accessory configurator.
- **`d4-nudge`** — Multi-turn follow-up design critique continuing D2's exact session (hero spacing + spec strip, `375px` slide-up bottom sheet nav, `Studio Light` / `Night Field` theme toggle).
- **`d3-interactive`** — TraceDeck keyboard-first incident triage workspace (`ArrowDown`/`Enter`/`Escape`, `Ctrl+K` command palette, multi-facet filters, live status/assignee mutation, desktop split-pane → accessible mobile drawer).
- **Visual Self-Critique Telemetry (`png_reads`)** — Measures whether each model actually opened and inspected its own Playwright screenshots with `read()`, exposing models that treat screenshots as a checkbox ritual and ship broken visuals.
- **Blind Side-by-Side HTML Gallery (`build_gallery.py`)** — Independently blinds configs as `Model A`–`Model Z` per challenge with synchronized viewports, `←`/`→` lightbox, synced-scroll 2-up compare, blind ranking (`1st`/`2nd`/`3rd`/`Defect`), a **Reveal Models** scorecard toggle, and `--standalone` WebP embedding (via ImageMagick) for single-file offline sharing.

### 3. `@explorer` & `@oracle` Protocols
- Lightweight, zero-edit evaluation rubrics for read-only codebase/docs recon (`@explorer`) and blind architectural/root-cause escalation reviews (`@oracle`).

---

## Install

Clone anywhere and run `./install.sh` (symlinks the skill and `/modelcompare` command into `~/.config/opencode/`):

```bash
git clone <repo-url> ~/Projects/subagent-bench
cd ~/Projects/subagent-bench
./install.sh
```

OpenCode V2 discovers `~/.config/opencode/skills/subagent-bench` and `~/.config/opencode/commands/modelcompare.md` automatically (run `/reload` in an already-open TUI if needed). To remove the symlinks:

```bash
./uninstall.sh
```

---

## Prerequisites

- **Core:** `python3` (stdlib only — zero `pip install`), `node` (v22+ for native TS `node --test` and the Designer static server), `git`
- **For `@fixer` Go challenge (`c4-concurrent-go`):** `go` (with `-race` support)
- **For `@designer`:** Playwright MCP server configured with `--output-dir /tmp/opencode/playwright-mcp`
- **Optional (for `--standalone` compressed WebP gallery export):** ImageMagick (`magick`; falls back cleanly to embedded PNG base64 if absent)

---

## Usage

Invoke via the `/modelcompare` slash command in OpenCode (or just ask naturally — the `subagent-bench` skill auto-triggers on model benchmark requests):

```text
/modelcompare fixer google/gemini-4-neon#medium google/gemini-4-hydrogen#high openai/gpt-6.2-sol#medium
```

```text
/modelcompare designer google/gemini-4-neon#medium google/gemini-4-hydrogen#high openai/gpt-6.1-terra#medium
```

```text
/modelcompare explorer google/gemini-4-hydrogen#medium openai/gpt-6-luna#low
```

### Standalone CLI Utilities

All bundled scripts live under `skills/subagent-bench/scripts/` and accept `--work-dir` and arbitrary `--configs` lists with zero hardcoded paths or model names:

```bash
# Unified OpenCode V2 SQLite telemetry + Playwright png_reads + git hygiene
python3 skills/subagent-bench/scripts/telemetry.py session <session_id> [--slice first_user|second_user|all]
python3 skills/subagent-bench/scripts/telemetry.py hygiene <run_dir>

# Fixer scaffold & grading
python3 skills/subagent-bench/scripts/fixer/bench_tools.py build --work-dir /tmp/opencode/fixer-bench
python3 skills/subagent-bench/scripts/fixer/bench_tools.py prepare --work-dir /tmp/opencode/fixer-bench --configs cfg-a,cfg-b
python3 skills/subagent-bench/scripts/fixer/bench_tools.py grade-all --work-dir /tmp/opencode/fixer-bench --sessions sessions.json

# Designer scaffold, multi-port dev server & standalone blind gallery
python3 skills/subagent-bench/scripts/designer/build_templates.py --work-dir /tmp/opencode/designer-bench --configs cfg-a,cfg-b
node skills/subagent-bench/scripts/designer/server.mjs --work-dir /tmp/opencode/designer-bench --base-port 4200
python3 skills/subagent-bench/scripts/designer/build_gallery.py --work-dir /tmp/opencode/designer-bench --screenshots-dir /tmp/opencode/playwright-mcp/designer-bench --models-json models_meta.json --out ~/gallery.html --standalone
```

---

## Repository Structure

```text
subagent-bench/
├── README.md
├── install.sh
├── uninstall.sh
├── commands/
│   └── modelcompare.md
└── skills/
    └── subagent-bench/
        ├── SKILL.md
        ├── assets/
        │   └── gallery_template.html
        ├── references/
        │   ├── fixer-suite.md
        │   ├── designer-suite.md
        │   ├── explorer-oracle-suite.md
        │   └── report-template.md
        └── scripts/
            ├── telemetry.py
            ├── fixer/
            │   ├── build_c1_c2.py
            │   ├── build_c3_c4.py
            │   ├── build_c5.py
            │   └── bench_tools.py
            └── designer/
                ├── build_templates.py
                ├── server.mjs
                └── build_gallery.py
```
