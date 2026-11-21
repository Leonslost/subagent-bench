# `@designer` Benchmark Suite Reference

4 UI/UX & Playwright-verification challenges testing bug hunting, greenfield design craft, multi-turn critique continuity, and complex keyboard-first interactive applications — paired with automated Playwright checks, `png_reads` visual-audit telemetry, and a blind side-by-side HTML screenshot gallery.

## Prerequisites
- `node` (for the multi-port static dev server)
- `python3` + `git`
- Playwright MCP configured with `--output-dir /tmp/opencode/playwright-mcp` (so screenshots stay outside repos)
- Optional: ImageMagick (`magick`) for `--standalone` compressed WebP embedding in the blind HTML gallery (gracefully falls back to PNG base64 if missing)

## Critical Operational Rules
1. **Run `@designer` STRICTLY SEQUENTIALLY (1 at a time)** and NEVER run orchestrator Playwright grading calls while a `@designer` subagent is active. Playwright MCP shares browser/viewport state!
2. **Playwright screenshot rules:**
   - Save screenshots strictly under `/tmp/opencode/playwright-mcp/<bench-name>/<challenge>/<cfg>/`.
   - Always pass `scale: "css"` on `tools.playwright.browser_take_screenshot`.
   - Always call `await tools.playwright.browser_close()` at the end of every grading script.
   - On D4 theme toggle checks, wait `400–450ms` inside `browser_evaluate` after clicking the toggle so CSS transitions finish before reading `getComputedStyle` (check BOTH `document.body` and `document.documentElement`) and taking `desktop-alt-theme-1280.png`.
   - Clear `localStorage` before taking default-theme and mobile-375 screenshots so persisted theme toggles don't leak across captures.
3. **D2 → Snapshot → D4 Continuity:**
   - Immediately after a config finishes `d2-greenfield`, copy `<work-dir>/runs/d2-greenfield/<cfg>` to `<work-dir>/snapshots/d2-greenfield/<cfg>`, grade & screenshot D2, and then continue D2's exact `sessionID` (same `model`) with the D4 Follow-Up Nudge prompt.
   - Note: `subagent(sessionID=...)` only resolves child sessions created by the **current** parent session. If an orchestrator handoff splits D2 and D4 for a config, run D4 as a fresh session against the completed D2 run directory and transparently document the cold-context caveat in the report.

## Scaffold & Dev Server Commands

```bash
WORK=/tmp/opencode/designer-bench
PW_DIR=/tmp/opencode/playwright-mcp/designer-bench
SCRIPTS=<skill_dir>/scripts/designer

# 1. Build templates, isolated run workspaces, and pre-created Playwright screenshot dirs
python3 "$SCRIPTS/build_templates.py" \
  --work-dir "$WORK" \
  --configs "cfg-a,cfg-b,cfg-c,cfg-d" \
  --screenshots-dir "$PW_DIR"

# 2. Start the multi-port static server (writes ports.json & server.pid, Cache-Control: no-store)
setsid -f node "$SCRIPTS/server.mjs" \
  --work-dir "$WORK" \
  --base-port 4200 \
  </dev/null >"$WORK/server.log" 2>&1

# Check allocated ports
cat "$WORK/ports.json"
```

Port layout (`--base-port 4200`): `d1-bughunt` = `4201..`, `d2-greenfield`/`d4-nudge` = `4301..`, `d3-interactive` = `4401..`. Always read exact ports from `<work-dir>/ports.json`.

---

## Automated Grading Checklists & Screenshots

Save per-run grading JSONs to `<work-dir>/results/<challenge>_<cfg>.json` with `{ challenge, config, session_id, score, checks }`.

### D1 (`d1-bughunt` — 8 checks)
- Zero horizontal overflow at `1280×800`, `768×1024`, `375×812`.
- Zero clipped header buttons at `1280` & `768`.
- WCAG AA contrast (`>= 4.5`) on muted text and `Pending` badge.
- Status filter tabs work accurately (`All: 7`, `Paid: 3`, `Pending: 2`, `Overdue: 2`).
- Clicking an invoice row opens an accessible detail drawer (`role="dialog"` / `aria-modal="true"`), unoccluded by headers/overlays, and `Escape` closes it.
- `0` JS console errors + repo clean (`telemetry.py hygiene`).
- **Screenshots:** `desktop-1280.png` (`fullPage: true`), `tablet-768.png` (`fullPage: true`), `mobile-375.png` (`fullPage: true`), `drawer-1280.png` (`fullPage: false`).

### D2 (`d2-greenfield` — 6 checks)
- Zero horizontal overflow at `1280×800`, `768×1024`, `375×812`.
- `0` broken images (`complete && naturalWidth > 0`).
- `0` JS console errors.
- Mode switcher dynamically updates preamp gain / specs (`+42 dB` Ambience, `+58 dB` Dialogue Boom, `+24 dB` Foley Close).
- Toggling `Acoustic Fur Windjammer` (`+$65`) updates live total `$490` → `$555`.
- Repo clean (`data.js` untouched, no stray PNGs).
- **Screenshots:** `desktop-1280.png` (`fullPage: true`), `tablet-768.png` (`fullPage: true`), `mobile-375.png` (`fullPage: true`).

### D4 (`d4-nudge` — 5 checks)
- Zero horizontal overflow at `1280×800` and `375×812`.
- Theme toggle changes computed `body`/`html` background or text color after 400ms transition wait.
- Mobile `375px` header menu trigger opens bottom sheet/drawer cleanly and `Escape` closes it.
- Zero regression on D2 mode switcher (`Foley Close` → `+24 dB`) and accessory total (`Windjammer` → `$555`).
- `0` JS console errors + repo clean.
- **Screenshots:** `desktop-default-1280.png` (`fullPage: true`), `desktop-alt-theme-1280.png` (`fullPage: true`), `mobile-375.png` (`fullPage: true`), `mobile-nav-375.png` (`fullPage: false`).

### D3 (`d3-interactive` — 9 checks)
- Zero horizontal overflow at `1280×800`, `768×1024`, `375×812`.
- `0` JS console errors.
- Live search filters (`postgres` → `INC-408`) and displays an empty state for `"zzz_no_match_999"`.
- Composable multi-facet filter (`Critical` + `Open` → `INC-408` only) + `Reset filters` restores all 18 rows.
- Keyboard `ArrowDown` updates `aria-selected="true"` and `Enter` updates the inspector.
- `Control+k` opens command palette and `Escape` closes it.
- Changing status `<select>` inside the inspector immediately updates the corresponding list row badge.
- Mobile `375px` row click opens an accessible overlay drawer (`role="dialog"` / `aria-modal="true"`) with zero overflow, and `Escape` closes it.
- Repo clean.
- **Screenshots:** `desktop-1280.png` (`fullPage: true`), `palette-1280.png` (`fullPage: false`), `tablet-768.png` (`fullPage: true`), `mobile-375.png` (`fullPage: true`), `mobile-drawer-375.png` (`fullPage: false`).

## Eyes-On Visual Audit & `png_reads` Discipline Check
After automated grading, **always**:
1. Run `telemetry.py session <sid>` (`--slice first_user` for D2, `--slice second_user` for D4) and inspect `playwright.png_reads` vs `playwright.screenshot`. Flag any config with `png_reads == 0` — models that skip reading screenshots routinely ship contrast bugs or CSS `[hidden]` overrides.
2. Open desktop, alt-theme, and mobile screenshots yourself with `read()` across every config to verify real contrast, layout density, typography pairing, SVG alignment, and overlay polish.

## Building the Blind Review Gallery

Create `<work-dir>/models_meta.json`:
```json
{
  "benchmarkId": "designer-modelA-vs-modelB",
  "models": {
    "cfg-a": { "name": "ModelA · medium", "model": "provider/modelA#medium", "family": "ModelA", "tier": "medium" },
    "cfg-b": { "name": "ModelB · high",   "model": "provider/modelB#high",   "family": "ModelB", "tier": "high" }
  }
}
```

Generate the blind side-by-side HTML gallery (with `--standalone` WebP embedding for offline sharing):
```bash
python3 "$SCRIPTS/build_gallery.py" \
  --work-dir "$WORK" \
  --screenshots-dir "$PW_DIR" \
  --models-json "$WORK/models_meta.json" \
  --out ~/designer-bench-gallery.html \
  --standalone
```

---

## Verbatim Prompts (Replace `<WORK>`, `<CFG>`, and `<PORT>` Only)

### D1 — `d1-bughunt`
```text
Workspace: ONLY read/edit files inside `<WORK>/runs/d1-bughunt/<CFG>` (`index.html`, `styles.css`, `app.js`).
Live dev server (auto-serves edits on reload): `http://127.0.0.1:<PORT>/`

Task: Users report that the PulseGrid Billing & Usage dashboard looks rough and has visual, responsive, accessibility, and runtime interaction issues across desktop (`1280px`), tablet (`768px`), and mobile (`375px`).

Inspect the live app in Playwright across all three breakpoints (`375px`, `768px`, `1280px`), exercise all interactive controls (status filter tabs, search input, clicking invoice rows including overdue accounts to inspect the slide-over detail drawer, closing the drawer, header actions), check console messages, and fix every visual, responsive, accessibility, and runtime issue you uncover while elevating the overall design polish and visual hierarchy.

Constraints:
- Keep all existing data, KPI cards, filter tabs (`All`, `Paid`, `Pending`, `Overdue`), search input, invoice rows, detail drawer, and Export/Upgrade actions functional.
- Stay self-contained (no `npm install` or build step; plain HTML/CSS/JS).
- Keep any Playwright screenshots/snapshots outside the repo (under `/tmp/opencode/playwright-mcp/`).
- Close the browser when finished if done, and report what you verified in Playwright (viewports, interactions, console).
```

### D2 — `d2-greenfield`
```text
Workspace: ONLY read/edit files inside `<WORK>/runs/d2-greenfield/<CFG>` (`index.html`, `styles.css`, `app.js`, keeping `data.js` intact).
Live dev server (auto-serves edits on reload): `http://127.0.0.1:<PORT>/`

Task: Design and build the marketing & interactive product showcase page for **Kestrel F2** — a machined aluminum 32-bit float pocket field recorder for film sound recordists and field composers, using the structured product data in `window.KESTREL_DATA` (`data.js`).

Aesthetic & Product Direction:
- Precision acoustic hardware — tactile, editorial, atmospheric, unmistakable craft (think Braun / Leica / Nagra / Teenage Engineering instrument feel). Avoid generic purple SaaS gradients, default Inter/Arial blandness, and cookie-cutter 3-column icon cards.
- Build a cohesive, distinctive visual system with custom CSS tokens, expressive display/mono typography pairing (Google Fonts or refined local stack with crisp fallbacks), purposeful spacing rhythm, and refined micro-interactions.

Required Sections & Interactions (all driven by `window.KESTREL_DATA`):
1. **Responsive Header & Navigation**: Brand wordmark, section links (Overview, Modes, Specs, Field Notes, Reserve), and Batch 04 reservation CTA, clean across `375px`, `768px`, and `1280px`.
2. **Hero Section**: Headline, subhead, primary CTA (`Reserve Batch 04 — $490`) + secondary CTA (`Inspect Specs`), and an original **inline SVG / CSS hardware diagram or live animated waveform/VU meter visual** (no broken external images).
3. **Interactive Recording Mode Switcher**: Tabs/toggles for all 3 modes (`Ambience`, `Dialogue Boom`, `Foley Close`) that dynamically update displayed sample rate, preamp gain, noise floor, battery life, input configuration, peak level indicator/meter, and acoustic note.
4. **Technical Specifications & Field Notes**: Full structured spec table grouped by category (`Conversion`, `Hardware`) plus the field engineer quotes from `data.js`.
5. **Interactive Batch 04 Configurator / Reservation Section or Drawer**: Toggle optional accessories (`Acoustic Fur Windjammer` $65, `Braided Mini-XLR to XLR Cable` $45, `Molded Ballistic Field Case` $55) with live calculated total starting at `$490` and an interactive reservation confirmation state.

Constraints & Verification:
- Stay self-contained (plain HTML/CSS/JS, zero `npm install`, zero broken image URLs).
- Verify visually in Playwright across `1280px`, `768px`, and `375px` (screenshots + accessibility checks + interactive testing of mode switcher and accessory total + console error check).
- Save any Playwright artifacts strictly under `/tmp/opencode/playwright-mcp/` (keep the repo clean). Close the browser when finished and report what you verified.
```

### D4 — `d4-nudge` (Continue D2's exact `sessionID` + same `model`)
```text
Follow-up design critique on Kestrel F2 (`<WORK>/runs/d2-greenfield/<CFG>`, live at `http://127.0.0.1:<PORT>/`):

Looks solid so far—let's tighten four specific things without breaking any existing interactions (mode switcher, accessory total calculation, reservation flow):
1. Give the hero slightly more vertical breathing room on desktop (`1280px`) and add a crisp horizontal technical spec/metadata strip directly beneath the hero fold (e.g., `6061-T6 ALUMINUM · 186g`, `136 dB DYNAMIC RANGE`, `-132 dBu EIN`, `BATCH 04 · JAN 2027`).
2. On mobile (`375px`), ensure the navigation opens as a clean slide-up bottom sheet or compact drawer panel from a single unobtrusive header menu button (with `Escape` and backdrop close) so header links never wrap or crowd the top bar.
3. Add a working theme toggle button in the header (`Studio Light` / `Night Field` mode) that smoothly switches your CSS theme variables across the entire page with strong readable contrast in both themes.
4. Re-verify in Playwright across `1280px`, `768px`, and `375px` (testing both themes, the mobile nav sheet/drawer, mode switching, accessory price updates, and console messages — keep artifacts under `/tmp/opencode/playwright-mcp/`). Close the browser when finished and report what you verified.
```

### D3 — `d3-interactive`
```text
Workspace: ONLY read/edit files inside `<WORK>/runs/d3-interactive/<CFG>` (`index.html`, `styles.css`, `app.js`, keeping `data.js` intact).
Live dev server (auto-serves edits on reload): `http://127.0.0.1:<PORT>/`

Task: Design and build **TraceDeck** — a crisp, keyboard-first Incident & Issue Triage Workspace driven by `window.TRACEDECK_INCIDENTS` (18 incidents) and `window.TRACEDECK_ASSIGNEES` (`data.js`).

Required Features & UX:
1. **Live Search + Multi-Facet Filters**:
   - Search input matching incident title, ID, service, or tags.
   - Severity filter (`All`, `Critical`, `High`, `Medium`, `Low`) and Status filter (`All`, `Open`, `Investigating`, `Resolved`) that compose together cleanly.
   - Display active match count, a `Reset filters` action when filters are active, and a well-crafted empty state when zero incidents match.
2. **Keyboard Navigation & Command Palette (`Ctrl+K` / `⌘K` + header trigger button)**:
   - `ArrowDown` / `ArrowUp` moves the active row selection through the filtered list with a clear visual active state (`aria-selected="true"`), `Enter` opens the selected incident in the detail inspector, and `Escape` closes the command palette or overlay inspector.
   - Command palette (`Ctrl+K` / `⌘K` or header trigger) supports live filtering to quick-filter by severity/status, reset filters, or jump directly to an incident via keyboard. Do not hijack shortcuts while typing inside search/text inputs (except `Ctrl+K` / `Escape`).
3. **Incident Detail Inspector (Split Pane on Desktop → Accessible Drawer on Tablet/Mobile)**:
   - Shows incident ID, severity/status badges, summary, live **Status selector** (`open` / `investigating` / `resolved` — mutating status updates the list row and counts immediately!), live **Assignee selector** (`window.TRACEDECK_ASSIGNEES`), tags, and chronological event timeline.
   - At `1280px`: spacious split-pane layout; at `768px` and `375px`: collapses cleanly into an accessible overlay drawer (`role="dialog"`, `aria-modal="true"`, backdrop + `Escape` close) with zero horizontal overflow.

Constraints & Verification:
- Stay self-contained (plain HTML/CSS/JS, zero `npm install`, inline SVG favicon to avoid 404s).
- Verify visually and interactively in Playwright across `1280px`, `768px`, and `375px` (screenshots, search + empty state, multi-facet filters + reset, `ArrowDown`/`Enter`/`Escape`, `Ctrl+K` command palette, status mutation updating the list, mobile drawer, and console error check).
- Keep all Playwright artifacts under `/tmp/opencode/playwright-mcp/`. Close the browser when finished and report what you verified.
```
