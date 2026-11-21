#!/usr/bin/env python3
import argparse
import json
import pathlib
import shutil
import subprocess
import sys

# =============================================================================
# D1: PulseGrid Billing & Usage Dashboard (6 planted visual/responsive/runtime/a11y bugs)
# =============================================================================
D1_FILES = {
"index.html": """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PulseGrid — Billing & Usage</title>
  <link rel="stylesheet" href="./styles.css" />
</head>
<body>
  <header class="topbar">
    <div class="brand">
      <span class="brand-mark">PG</span>
      <div>
        <div class="brand-name">PulseGrid</div>
        <div class="brand-sub muted">Cloud Metering & Billing</div>
      </div>
    </div>
    <div class="header-actions">
      <button id="export-btn" class="btn btn-secondary" type="button">Export CSV Report</button>
      <button id="new-plan-btn" class="btn btn-primary" type="button">Upgrade Enterprise Plan</button>
    </div>
  </header>

  <main class="container">
    <section class="page-head">
      <h1>Billing &amp; Usage</h1>
      <p class="muted">Review current-cycle compute spend, metered overages, and invoice settlement status.</p>
    </section>

    <section class="kpi-grid" aria-label="Billing summary">
      <article class="kpi-card">
        <div class="kpi-label muted">Monthly Recurring</div>
        <div class="kpi-value">$48,920</div>
        <div class="kpi-delta muted">+12.4% vs last cycle</div>
      </article>
      <article class="kpi-card">
        <div class="kpi-label muted">Metered Compute</div>
        <div class="kpi-value">1.42M req</div>
        <div class="kpi-delta muted">71% of 2M quota</div>
      </article>
      <article class="kpi-card">
        <div class="kpi-label muted">Pending Settlement</div>
        <div class="kpi-value">$6,140</div>
        <div class="kpi-delta muted">2 invoices awaiting ACH</div>
      </article>
      <article class="kpi-card">
        <div class="kpi-label muted">Overdue Balance</div>
        <div class="kpi-value">$4,890</div>
        <div class="kpi-delta muted">2 accounts past due</div>
      </article>
    </section>

    <section class="panel">
      <div class="toolbar">
        <div class="tabs" role="tablist" aria-label="Invoice status filter">
          <button class="tab active" data-filter="all" type="button">All (7)</button>
          <button class="tab" data-filter="paid" type="button">Paid (3)</button>
          <button class="tab" data-filter="pending" type="button">Pending (2)</button>
          <button class="tab" data-filter="overdue" type="button">Overdue (2)</button>
        </div>
        <input id="search-input" class="search" type="search" placeholder="Search account or invoice ID..." aria-label="Search invoices" />
      </div>

      <table class="invoices-table">
        <thead>
          <tr>
            <th>Invoice</th>
            <th>Account</th>
            <th>Period</th>
            <th>Amount</th>
            <th>Status</th>
            <th>Method</th>
          </tr>
        </thead>
        <tbody id="invoice-tbody"></tbody>
      </table>
    </section>
  </main>

  <div id="drawer-backdrop" class="drawer-backdrop hidden"></div>
  <aside id="invoice-drawer" class="drawer hidden">
    <div class="drawer-header">
      <div>
        <h2 id="drawer-title">Invoice</h2>
        <div id="drawer-subtitle" class="muted"></div>
      </div>
      <button id="drawer-close" class="btn-icon" type="button">&times;</button>
    </div>
    <div id="drawer-body" class="drawer-body"></div>
  </aside>

  <div id="toast" class="toast hidden" role="status" aria-live="polite"></div>
  <script src="./app.js"></script>
</body>
</html>
""",
"styles.css": """
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Arial, sans-serif;
  background: #f1f4f9;
  color: #1c2430;
}

/* BUG 4: Low contrast muted text (~2.1:1 on #f1f4f9 / #ffffff) */
.muted {
  color: #aeb7c4;
  font-size: 13px;
}

/* BUG 2: Sticky topbar has higher z-index (50) than the invoice drawer (10)! */
.topbar {
  position: sticky;
  top: 0;
  z-index: 50;
  background: #ffffff;
  border-bottom: 1px solid #d9e0ea;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 6px;
  background: #2b4c7e;
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 13px;
}

.brand-name { font-weight: 700; font-size: 16px; }

/* BUG 3: Fixed width + overflow:hidden clips CTA buttons at tablet/desktop! */
.header-actions {
  display: flex;
  gap: 8px;
  width: 170px;
  overflow: hidden;
  flex-shrink: 0;
}

.btn {
  padding: 8px 14px;
  border-radius: 6px;
  border: 1px solid transparent;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.btn-secondary {
  background: #fff;
  border-color: #cbd5e1;
  color: #334155;
}
.btn-primary {
  background: #2563eb;
  color: #fff;
}

.container {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px;
}

.page-head h1 { margin: 0 0 6px; font-size: 24px; }
.page-head p { margin: 0 0 20px; }

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}

.kpi-card {
  background: #fff;
  border: 1px solid #dce3ec;
  border-radius: 8px;
  padding: 16px;
}

.kpi-value {
  font-size: 26px;
  font-weight: 700;
  margin: 6px 0 4px;
}

.panel {
  background: #fff;
  border: 1px solid #dce3ec;
  border-radius: 8px;
  padding: 16px;
}

/* BUG 1: Fixed min-width forces horizontal overflow on mobile 375px and tablet! */
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  min-width: 760px;
}

.tabs {
  display: flex;
  gap: 6px;
}

.tab {
  padding: 7px 12px;
  border-radius: 6px;
  border: 1px solid #dce3ec;
  background: #f8fafc;
  color: #475569;
  cursor: pointer;
  font-size: 13px;
}
.tab.active {
  background: #1e293b;
  color: #fff;
  border-color: #1e293b;
}

.search {
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  width: 260px;
  font-size: 13px;
}

/* BUG 1 cont: Table has fixed min-width with no scroll wrapper */
.invoices-table {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
}
.invoices-table th,
.invoices-table td {
  text-align: left;
  padding: 12px 10px;
  border-bottom: 1px solid #e7edf5;
  font-size: 14px;
}
.invoices-table tbody tr {
  cursor: pointer;
}
.invoices-table tbody tr:hover {
  background: #f8fafc;
}

.badge {
  display: inline-block;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}
.badge-paid { background: #dcfce7; color: #166534; }
/* BUG 4 cont: Low contrast pending badge (~1.8:1) */
.badge-pending { background: #fef9c3; color: #d4b84a; }
.badge-overdue { background: #fee2e2; color: #991b1b; }

.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  z-index: 9;
}

/* BUG 2 cont: Drawer z-index (10) sits UNDER sticky topbar (50) */
.drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 420px;
  background: #ffffff;
  border-left: 1px solid #cbd5e1;
  z-index: 10;
  padding: 20px;
  overflow-y: auto;
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 12px;
  margin-bottom: 16px;
}

.drawer-header h2 { margin: 0; font-size: 18px; }
.btn-icon {
  background: transparent;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  width: 32px;
  height: 32px;
  font-size: 18px;
  cursor: pointer;
}

.hidden { display: none !important; }

.toast {
  position: fixed;
  bottom: 20px;
  right: 20px;
  background: #1e293b;
  color: #fff;
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 13px;
  z-index: 100;
}

@media (max-width: 900px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
}
""",
"app.js": """
const INVOICES = [
  { id: 'INV-2026-1041', account: 'Northstar Robotics', period: 'Oct 2026', amount: 18400, status: 'paid', paymentMethod: 'wire', items: [{ desc: 'Dedicated GPU Cluster (4x)', amt: 16000 }, { desc: 'Metered Egress (12 TB)', amt: 2400 }] },
  { id: 'INV-2026-1042', account: 'Helios Genomics', period: 'Oct 2026', amount: 12850, status: 'paid', paymentMethod: 'ach', items: [{ desc: 'Enterprise Compute Tier', amt: 11500 }, { desc: 'Storage Snapshot Add-on', amt: 1350 }] },
  { id: 'INV-2026-1043', account: 'Vektor Logistics', period: 'Oct 2026', amount: 3820, status: 'pending', paymentMethod: 'ach', items: [{ desc: 'Standard Platform', amt: 3200 }, { desc: 'API Burst Overage', amt: 620 }] },
  { id: 'INV-2026-1044', account: 'Kestrel Media Labs', period: 'Oct 2026', amount: 2320, status: 'pending', paymentMethod: 'card', items: [{ desc: 'Pro Plan (16 seats)', amt: 1920 }, { desc: 'Transcoding Minutes', amt: 400 }] },
  { id: 'INV-2026-1045', account: 'Cinder Financial', period: 'Sep 2026', amount: 3190, status: 'overdue', paymentMethod: undefined, items: [{ desc: 'Enterprise API Tier', amt: 2800 }, { desc: 'Audit Log Retention', amt: 390 }] },
  { id: 'INV-2026-1046', account: 'Boreal Energy Co', period: 'Sep 2026', amount: 1700, status: 'overdue', paymentMethod: 'wire', items: [{ desc: 'IoT Telemetry Ingest', amt: 1700 }] },
  { id: 'INV-2026-1047', account: 'Sable Architecture', period: 'Oct 2026', amount: 6640, status: 'paid', paymentMethod: 'card', items: [{ desc: 'Render Farm Compute', amt: 6640 }] },
];

let activeFilter = 'all';
let searchTerm = '';

const tbody = document.getElementById('invoice-tbody');
const drawer = document.getElementById('invoice-drawer');
const backdrop = document.getElementById('drawer-backdrop');
const drawerTitle = document.getElementById('drawer-title');
const drawerSubtitle = document.getElementById('drawer-subtitle');
const drawerBody = document.getElementById('drawer-body');
const toast = document.getElementById('toast');

function formatUSD(n) {
  return '$' + n.toLocaleString('en-US');
}

function showToast(msg) {
  toast.textContent = msg;
  toast.classList.remove('hidden');
  setTimeout(() => toast.classList.add('hidden'), 2400);
}

function renderTable() {
  const filtered = INVOICES.filter((inv) => {
    // BUG 5a: Overdue filter uses wrong property name 'state' instead of 'status' and throws on typo!
    if (activeFilter !== 'all') {
      if (activeFilter === 'overdue') {
        if (inv.billingState.status !== 'overdue') return false;
      } else if (inv.status !== activeFilter) {
        return false;
      }
    }
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      return inv.id.toLowerCase().includes(q) || inv.account.toLowerCase().includes(q);
    }
    return true;
  });

  tbody.innerHTML = '';
  for (const inv of filtered) {
    const tr = document.createElement('tr');
    tr.dataset.id = inv.id;
    tr.innerHTML = `
      <td><strong>${inv.id}</strong></td>
      <td>${inv.account}</td>
      <td class="muted">${inv.period}</td>
      <td>${formatUSD(inv.amount)}</td>
      <td><span class="badge badge-${inv.status}">${inv.status}</span></td>
      <td>${inv.paymentMethod ? inv.paymentMethod.toUpperCase() : '—'}</td>
    `;
    tr.addEventListener('click', () => openDrawer(inv));
    tbody.appendChild(tr);
  }
}

function openDrawer(inv) {
  // BUG 5b: Crashes with TypeError when inv.paymentMethod is undefined (INV-2026-1045)!
  const methodLabel = inv.paymentMethod.toUpperCase();
  drawerTitle.textContent = inv.id;
  drawerSubtitle.textContent = `${inv.account} · ${inv.period}`;
  drawerBody.innerHTML = `
    <p><strong>Status:</strong> <span class="badge badge-${inv.status}">${inv.status}</span></p>
    <p><strong>Payment Method:</strong> ${methodLabel}</p>
    <p><strong>Total Due:</strong> ${formatUSD(inv.amount)}</p>
    <h3>Line Items</h3>
    <ul>
      ${inv.items.map((it) => `<li>${it.desc} — ${formatUSD(it.amt)}</li>`).join('')}
    </ul>
  `;
  drawer.classList.remove('hidden');
  backdrop.classList.remove('hidden');
}

function closeDrawer() {
  drawer.classList.add('hidden');
  backdrop.classList.add('hidden');
}

document.querySelectorAll('.tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    activeFilter = btn.dataset.filter;
    renderTable();
  });
});

document.getElementById('search-input').addEventListener('input', (e) => {
  searchTerm = e.target.value.trim();
  renderTable();
});

document.getElementById('drawer-close').addEventListener('click', closeDrawer);
// BUG 6: No Escape handler, no backdrop click handler, no role="dialog"/aria-modal/focus management

document.getElementById('export-btn').addEventListener('click', () => {
  showToast('Exported 7 invoices to pulsegrid-invoices.csv');
});

document.getElementById('new-plan-btn').addEventListener('click', () => {
  showToast('Enterprise plan upgrade request queued');
});

renderTable();
"""
}

# =============================================================================
# D2: Kestrel F2 — Greenfield Field Recorder Studio Page (clean starter with real data)
# =============================================================================
D2_FILES = {
"data.js": """
window.KESTREL_DATA = {
  product: {
    name: 'Kestrel F2',
    tagline: '32-Bit Float Pocket Field Recorder',
    batch: 'Batch 04',
    basePrice: 490,
    shipWindow: 'Ships January 2027',
    chassis: 'Bead-blasted 6061-T6 aluminum · 186g',
  },
  modes: [
    {
      id: 'ambience',
      label: 'Ambience',
      subtitle: 'Wide stereo soundscapes & quiet exterior environments',
      sampleRate: '96 kHz / 32-bit float',
      preampGain: '+42 dB dual-ADC',
      noiseFloor: '-131.5 dBu EIN',
      battery: '14.5 hrs (2× AA Li)',
      inputConfig: 'Matched XY Condenser Pair + High-Pass 40 Hz',
      peakLevelDb: -18,
      notes: 'Dual-stage analog conversion captures rustling leaves and sudden thunderclaps without touching a trim knob.',
    },
    {
      id: 'dialogue',
      label: 'Dialogue Boom',
      subtitle: 'Location film production & documentary boom capture',
      sampleRate: '48 kHz / 32-bit float + TC',
      preampGain: '+58 dB ultra-linear',
      noiseFloor: '-132.0 dBu EIN',
      battery: '11.0 hrs (+48V Phantom)',
      inputConfig: 'Locking Mini-XLR · +48V Phantom · LTC Timecode',
      peakLevelDb: -9,
      notes: 'Sub-millisecond TCXO timecode sync locks cleanly to cinema cameras with zero drift across 12-hour shoot days.',
    },
    {
      id: 'foley',
      label: 'Foley Close',
      subtitle: 'High-SPL transient capture & ultrasonic pitching',
      sampleRate: '192 kHz / 32-bit float',
      preampGain: '+24 dB headroom-first',
      noiseFloor: '-129.8 dBu EIN',
      battery: '9.5 hrs (192 kHz dual)',
      inputConfig: '138 dB SPL Max · Ultrasonic 80 kHz Response',
      peakLevelDb: -3,
      notes: 'Preserve harmonic detail above 40 kHz so metallic impacts and textures pitch down three octaves without aliasing.',
    },
  ],
  specs: [
    { group: 'Conversion', label: 'Architecture', value: 'Dual-ADC 32-bit float (zero-clipping headroom)' },
    { group: 'Conversion', label: 'Dynamic Range', value: '136 dB A-weighted combined' },
    { group: 'Conversion', label: 'Equivalent Input Noise', value: '-132.0 dBu (150Ω terminated)' },
    { group: 'Conversion', label: 'Sample Rates', value: '48 / 96 / 192 kHz Broadcast WAV (BWF)' },
    { group: 'Hardware', label: 'Enclosure', value: 'CNC 6061-T6 aluminum, IP54 weather-sealed switches' },
    { group: 'Hardware', label: 'Controls', value: 'Detented brass gain wheel, tactile transport toggles' },
    { group: 'Hardware', label: 'Display', value: '1.3" high-contrast amber OLED (daylight readable)' },
    { group: 'Hardware', label: 'Storage & Power', value: 'Dual microSDXC (redundant mirror), USB-C PD + 2× AA' },
  ],
  fieldNotes: [
    {
      quote: 'I clipped zero takes across six weeks in Patagonia—wind gusts hit 90 km/h and the dual-ADC stage never flinched.',
      author: 'Maren Lindqvist',
      role: 'Location Sound Mixer, Reykjavik',
    },
    {
      quote: 'The brass transport toggles work blind inside a rain jacket. It feels like a 1974 Nagra shrunk into a shirt pocket.',
      author: 'Kenji Takahashi',
      role: 'Field Recordist & Sound Designer, Tokyo',
    },
  ],
  accessories: [
    { id: 'windjammer', name: 'Acoustic Fur Windjammer', desc: 'Custom high-wind blimp slip-on (-32 dB wind rumble)', price: 65 },
    { id: 'xlr-cable', name: 'Braided Mini-XLR to XLR Cable', desc: 'Neutrik locking connector, 60 cm ultra-flexible jacket', price: 45 },
    { id: 'hard-case', name: 'Molded Ballistic Field Case', desc: 'Weather-sealed EVA shell with microSD & AA caddy', price: 55 },
  ],
};
""",
"index.html": """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Kestrel F2 — 32-Bit Float Field Recorder</title>
  <link rel="stylesheet" href="./styles.css" />
</head>
<body>
  <div id="app">
    <p>Kestrel F2 starter page — design and implement using window.KESTREL_DATA.</p>
  </div>
  <script src="./data.js"></script>
  <script src="./app.js"></script>
</body>
</html>
""",
"styles.css": """
/* Starter stylesheet — build the complete Kestrel F2 experience here. */
body { margin: 0; font-family: system-ui, sans-serif; }
""",
"app.js": """
// Starter script — window.KESTREL_DATA contains product, modes, specs, fieldNotes, and accessories.
console.log('Loaded Kestrel F2 data:', window.KESTREL_DATA?.product?.name);
"""
}

# =============================================================================
# D3: TraceDeck — Interactive Incident & Issue Triage Workspace (starter with 18 records)
# =============================================================================
D3_FILES = {
"data.js": """
window.TRACEDECK_INCIDENTS = [
  { id: 'INC-409', title: 'Checkout webhook retries spiking on EU-West shard', severity: 'critical', status: 'investigating', service: 'billing-webhooks', assignee: 'Elena Vance', updated: '4m ago', tags: ['eu-west', 'queue', 'p0'], summary: 'Exponential backoff queue grew from 120 to 14,800 pending webhooks after Stripe TLS rotation.', timeline: [{ at: '14:12', text: 'PagerDuty alert fired: webhook lag > 300s' }, { at: '14:16', text: 'Elena Vance acknowledged and scaled worker pool 2x -> 6x' }, { at: '14:21', text: 'Identified stale keep-alive sockets on worker-eu-04' }] },
  { id: 'INC-408', title: 'PostgreSQL read replica replication lag > 45s', severity: 'critical', status: 'open', service: 'core-db', assignee: 'Marcus Chen', updated: '11m ago', tags: ['postgres', 'replication'], summary: 'Bulk backfill job saturated WAL replay throughput on replica-02.', timeline: [{ at: '14:04', text: 'Read replica lag crossed 45s threshold' }, { at: '14:09', text: 'Auto-routed reporting queries to replica-03' }] },
  { id: 'INC-407', title: 'OAuth token refresh returns 401 for Safari 19 ITP users', severity: 'high', status: 'investigating', service: 'auth-gateway', assignee: 'Priya Nair', updated: '23m ago', tags: ['oauth', 'safari', 'cookies'], summary: 'SameSite attribute omitted on rotated refresh cookie after v4.18 deploy.', timeline: [{ at: '13:48', text: 'Support escalated 19 customer login loops' }, { at: '13:55', text: 'Reproduced locally on Safari; bisecting commit 8f31c2' }] },
  { id: 'INC-406', title: 'Search autocomplete p99 latency regressed to 1.8s', severity: 'high', status: 'open', service: 'search-index', assignee: 'Unassigned', updated: '37m ago', tags: ['latency', 'elasticsearch'], summary: 'Prefix ngram cache hit ratio dropped from 94% to 51% after index rollover.', timeline: [{ at: '13:34', text: 'SLO burn alert: search p99 > 800ms for 15m' }] },
  { id: 'INC-405', title: 'PDF invoice export drops CJK glyphs on Linux workers', severity: 'medium', status: 'open', service: 'doc-renderer', assignee: 'Sofia Morales', updated: '1h ago', tags: ['pdf', 'fonts', 'i18n'], summary: 'Base container image upgrade removed Noto Sans CJK fallback font package.', timeline: [{ at: '13:02', text: 'Tokyo enterprise account reported blank invoice table cells' }] },
  { id: 'INC-404', title: 'CDN stale-while-revalidate serving 2h old pricing JSON', severity: 'high', status: 'resolved', service: 'edge-cdn', assignee: 'Devon Brooks', updated: '1h ago', tags: ['cache', 'cdn'], summary: 'Surrogate-Key purge header truncated when > 4KB.', timeline: [{ at: '12:15', text: 'Detected stale cache on edge POPs' }, { at: '12:44', text: 'Deployed batched purge keys; verified fresh response globally' }] },
  { id: 'INC-403', title: 'S3 multipart upload stalls for files > 2.1 GB', severity: 'medium', status: 'investigating', service: 'media-ingest', assignee: 'Elena Vance', updated: '2h ago', tags: ['s3', 'upload', '32bit'], summary: 'Signed 32-bit integer overflow in part-offset byte calculation.', timeline: [{ at: '11:50', text: 'Customer upload aborted at 2,147,483,648 bytes' }, { at: '12:10', text: 'Confirmed BigInt fix needed in chunker.ts' }] },
  { id: 'INC-402', title: 'Dark mode focus outline invisible on primary toolbar', severity: 'low', status: 'open', service: 'web-console', assignee: 'Sofia Morales', updated: '2h ago', tags: ['a11y', 'css'], summary: 'Focus ring color matches dark surface token #181c24.', timeline: [{ at: '11:30', text: 'Flagged during quarterly keyboard accessibility audit' }] },
  { id: 'INC-401', title: 'Rate limiter miscounts burst credits across clock skew', severity: 'high', status: 'investigating', service: 'api-edge', assignee: 'Marcus Chen', updated: '3h ago', tags: ['ratelimit', 'redis'], summary: 'Node-local Date.now() used instead of Redis TIME in Lua token bucket.', timeline: [{ at: '10:42', text: 'Spurious 429s observed on 2 of 12 edge nodes' }] },
  { id: 'INC-400', title: 'Audit CSV download omits timezone offset in header', severity: 'low', status: 'resolved', service: 'compliance', assignee: 'Priya Nair', updated: '3h ago', tags: ['csv', 'timezone'], summary: 'Timestamps formatted without explicit UTC Z suffix.', timeline: [{ at: '09:50', text: 'PR #1842 merged adding ISO-8601 UTC formatting' }] },
  { id: 'INC-399', title: 'Memory leak in long-lived SSE notification streams', severity: 'high', status: 'open', service: 'realtime-hub', assignee: 'Devon Brooks', updated: '4h ago', tags: ['memory', 'sse'], summary: 'Abort listeners retained in EventEmitter map after abrupt mobile disconnects.', timeline: [{ at: '09:15', text: 'Pod RSS climbed linearly to 3.8 GB before OOMKill' }] },
  { id: 'INC-398', title: 'GraphQL batch query bypasses field depth limit', severity: 'critical', status: 'resolved', service: 'api-edge', assignee: 'Priya Nair', updated: '5h ago', tags: ['security', 'graphql'], summary: 'Aliased fragment spreads were counted once instead of per expansion.', timeline: [{ at: '08:05', text: 'Security scanner caught recursive fragment edge case' }, { at: '08:52', text: 'Patched depth analyzer & added regression test' }] },
  { id: 'INC-397', title: 'Scheduled digest emails duplicated during DST fall-back', severity: 'medium', status: 'open', service: 'scheduler', assignee: 'Unassigned', updated: '6h ago', tags: ['cron', 'dst'], summary: '01:30 America/New_York cron job fired twice during repeated hour.', timeline: [{ at: '07:30', text: '412 workspace digests sent twice' }] },
  { id: 'INC-396', title: 'Metrics ingestion drops histogram buckets with +Inf label', severity: 'medium', status: 'investigating', service: 'telemetry', assignee: 'Marcus Chen', updated: '7h ago', tags: ['prometheus', 'metrics'], summary: 'Strict label regex rejected + character in le bucket key.', timeline: [{ at: '06:40', text: 'p95/p99 Grafana panels showing NaN after collector update' }] },
  { id: 'INC-395', title: 'Mobile drawer scroll locks body after closing via back gesture', severity: 'low', status: 'open', service: 'web-console', assignee: 'Sofia Morales', updated: '8h ago', tags: ['mobile', 'ux'], summary: 'popstate navigation bypasses drawer cleanup hook.', timeline: [{ at: '05:55', text: 'Reported on iOS Safari swipe-back' }] },
  { id: 'INC-394', title: 'TLS certificate auto-renewal failing on staging ingress', severity: 'medium', status: 'resolved', service: 'infra-k8s', assignee: 'Devon Brooks', updated: '9h ago', tags: ['tls', 'cert-manager'], summary: 'ACME HTTP-01 challenge blocked by new WAF bot rule.', timeline: [{ at: '04:10', text: 'Added /.well-known/acme-challenge allowlist rule' }] },
  { id: 'INC-393', title: 'Keyboard shortcut Ctrl+K hijacked while typing in textarea', severity: 'low', status: 'resolved', service: 'web-console', assignee: 'Elena Vance', updated: '12h ago', tags: ['keyboard', 'ux'], summary: 'Global keydown listener did not check active editable target.', timeline: [{ at: '01:20', text: 'Fixed target guard and verified in Playwright' }] },
  { id: 'INC-392', title: 'Billing proration off by 1 cent on 3-seat mid-cycle split', severity: 'medium', status: 'resolved', service: 'billing-core', assignee: 'Priya Nair', updated: '1d ago', tags: ['billing', 'rounding'], summary: 'Truncated integer division dropped remainder cent across seats.', timeline: [{ at: 'Yesterday', text: 'Switched to Hamilton largest-remainder allocation' }] },
];
window.TRACEDECK_ASSIGNEES = ['Unassigned', 'Elena Vance', 'Marcus Chen', 'Priya Nair', 'Sofia Morales', 'Devon Brooks'];
""",
"index.html": """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>TraceDeck — Incident Triage Workspace</title>
  <link rel="stylesheet" href="./styles.css" />
</head>
<body>
  <div id="app">
    <p>TraceDeck starter page — build the Incident Triage Workspace using window.TRACEDECK_INCIDENTS.</p>
  </div>
  <script src="./data.js"></script>
  <script src="./app.js"></script>
</body>
</html>
""",
"styles.css": """
/* Starter stylesheet — build the TraceDeck Incident Triage Workspace here. */
body { margin: 0; font-family: system-ui, sans-serif; }
""",
"app.js": """
// Starter script — window.TRACEDECK_INCIDENTS (18 records) and window.TRACEDECK_ASSIGNEES are loaded.
console.log('Loaded TraceDeck incidents:', window.TRACEDECK_INCIDENTS?.length);
"""
}


def write_files(root: pathlib.Path, files: dict[str, str]):
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content.lstrip("\n"), encoding="utf-8")


def git_init(root: pathlib.Path):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "bench@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Bench"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial baseline"], cwd=root, check=True)


def load_configs(configs_arg: str | None, configs_json_arg: str | None) -> list[str]:
    if configs_arg:
        configs = [c.strip() for c in configs_arg.split(",") if c.strip()]
        if configs:
            return configs
    if configs_json_arg:
        raw = json.loads(pathlib.Path(configs_json_arg).read_text(encoding="utf-8"))
        if isinstance(raw, list):
            configs = [
                (item["configId"] if isinstance(item, dict) and "configId" in item else item["id"] if isinstance(item, dict) else str(item))
                for item in raw
            ]
            if configs:
                return configs
        elif isinstance(raw, dict) and isinstance(raw.get("configs"), list):
            configs = [
                (item["configId"] if isinstance(item, dict) and "configId" in item else item["id"] if isinstance(item, dict) else str(item))
                for item in raw["configs"]
            ]
            if configs:
                return configs
    raise SystemExit("Error: provide --configs <c1,c2,...> or --configs-json <path>")


def main():
    parser = argparse.ArgumentParser(description="Build Designer benchmark templates and isolated run workspaces.")
    parser.add_argument("--work-dir", default="/tmp/opencode/designer-bench", help="Benchmark working directory")
    parser.add_argument("--configs", default=None, help="Comma-separated config IDs (e.g. neon-med,terra-med,sonnet-high)")
    parser.add_argument("--configs-json", default=None, help="JSON file listing config IDs")
    parser.add_argument("--screenshots-dir", default="/tmp/opencode/playwright-mcp/designer-bench", help="Root directory for Playwright screenshots")
    args = parser.parse_args()

    configs = load_configs(args.configs, args.configs_json)
    work_dir = pathlib.Path(args.work_dir).resolve()
    screenshots_dir = pathlib.Path(args.screenshots_dir).resolve()

    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "results").mkdir(parents=True, exist_ok=True)
    (work_dir / "snapshots").mkdir(parents=True, exist_ok=True)
    (work_dir / "configs.json").write_text(json.dumps(configs, indent=2) + "\n", encoding="utf-8")

    for ch_name in ("d1-bughunt", "d2-greenfield", "d4-nudge", "d3-interactive"):
        for cfg in configs:
            (screenshots_dir / ch_name / cfg).mkdir(parents=True, exist_ok=True)

    challenges = [("d1-bughunt", D1_FILES), ("d2-greenfield", D2_FILES), ("d3-interactive", D3_FILES)]
    for name, files in challenges:
        tpl = work_dir / "templates" / name
        write_files(tpl, files)
        git_init(tpl)
        for cfg in configs:
            dst = work_dir / "runs" / name / cfg
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(tpl, dst)

    total_runs = len(challenges) * len(configs)
    print(f"Built D1, D2, D3 templates and {total_runs} isolated run workspaces in {work_dir} for {len(configs)} configs.")


if __name__ == "__main__":
    main()
