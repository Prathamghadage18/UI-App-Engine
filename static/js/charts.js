/**
 * =============================================================================
 * PrintOps SCADA Dashboard  —  static/js/charts.js
 * Hutamaki Print Line Monitor  ·  Gallus EM 280
 *
 * Standalone modular version of the SCADA dashboard JS.
 * This file can be loaded via <script src="/static/js/charts.js"></script>
 * as an alternative to the inline <script> in dashboard.html.
 *
 * NOTE: Currently ALL active JS is inline in dashboard.html {% block scripts %}.
 *       This file is kept in sync for future use or external loading.
 *
 * Responsibilities:
 *   1. Chart.js global defaults (light SCADA theme)
 *   2. Weekly trend chart initialisation  (4 charts per machine)
 *   3. API response mappers  (backend → frontend field translation)
 *   4. KPI DOM updaters  (snapshot + shift table re-render)
 *   5. Live fetch orchestrator  (polls machines in parallel)
 *
 * Backend API endpoints (FastAPI — routers/api.py):
 *   GET /api/snapshot/{machine_key}  → KPI snapshot
 *   GET /api/shifts/{machine_key}    → Shift performance
 *   GET /api/weekly/{machine_key}    → 7-day trend data
 *
 * Depends on (loaded before this file in base.html):
 *   - Chart.js 4.x CDN
 *   - Bootstrap Icons CDN
 *   - base.html global JS hooks:
 *       window.SCADA_SCALE      →  shared Chart.js axis config
 *       window.setDbStatus(s)   →  header DB indicator
 *       window.showAlert(msg)   →  footer blinking alert
 *       window.clearAlert()     →  clear footer alert
 *       window.setLastUpdated() →  footer timestamp
 *       window.resetCountdown(n)→  footer countdown reset
 *
 * DOM element ID conventions (set in dashboard.html):
 *   status-{machineId}          →  badge-run / badge-stop span
 *   util-{machineId}            →  utilisation kpi-value span
 *   util-bar-{machineId}        →  utilisation bar-fill div
 *   runhours-{machineId}        →  run hours kpi-value span
 *   prod-{machineId}            →  production kpi-value span
 *   energy-{machineId}          →  energy kpi-value span
 *   epm-{machineId}             →  energy/meter kpi-value span
 *   eff-dot-{machineId}         →  efficiency colour dot
 *   eff-label-{machineId}       →  efficiency text label
 *   shifts-{machineId}          →  shift table <tbody>
 *   chart-prod-{machineId}      →  production bar chart canvas
 *   chart-energy-{machineId}    →  energy line chart canvas
 *   chart-hours-{machineId}     →  run hours line chart canvas
 *   chart-epm-{machineId}       →  kWh/m line chart canvas
 *   prod-latest-{shortId}       →  chart title latest value badge
 *   energy-latest-{shortId}     →  chart title latest value badge
 *   hours-latest-{shortId}      →  chart title latest value badge
 *   epm-latest-{shortId}        →  chart title latest value badge
 *
 * machineId format: 'gallus_em280'
 * shortId = machineId.split('_')[0] → 'gallus'
 * machine_key (backend) = shortId   → 'gallus'
 *
 * =============================================================================
 */

'use strict';


/* =============================================================================
   §1  CONFIGURATION
   ============================================================================= */

/** Polling intervals (seconds) — three separate tiers. */
const SHIFT_SEC  = 5;       /* Shift values — real-time (~5s) */
const KPI_SEC    = 15;      /* KPI snapshot  — every 15s      */
const CHART_SEC  = 30 * 60; /* Weekly charts — every 30 min   */

/** Footer countdown tracks the fastest visible refresh (shifts). */
const COUNTDOWN_SEC = SHIFT_SEC;

/** FastAPI router prefix — must match routers/api.py. */
const API_BASE = '/api';

/**
 * Machine registry.
 *   id  → DOM element IDs (e.g. util-gallus_em280, chart-prod-gallus_em280)
 *   key → API path parameter (e.g. /api/snapshot/gallus)
 */
const MACHINES = [
  { id: 'gallus_em280', key: 'gallus' },
  /* { id: 'bobst_m5', key: 'bobst' }, */
];

/**
 * Shift time labels — backend doesn't return shift time ranges,
 * so we derive them from MachineConfig shift start/end patterns.
 */
const SHIFT_TIMES = {
  'Shift 1': '07–15',
  'Shift 2': '15–23',
  'Shift 3': '23–07',
};

/** Energy-per-meter efficiency thresholds (kWh per meter). */
const EFF_GOOD = 12.50;
const EFF_WARN = 13.00;

/** Chart colours — matched to CSS variables. */
const CLR = {
  cyan:   '#0077b6',
  amber:  '#e65100',
  green:  '#2e7d32',
  blue:   '#0277bd',
};


/* =============================================================================
   §2  CHART.JS GLOBAL DEFAULTS
   Set once — inherited by every chart instance.
   ============================================================================= */

Chart.defaults.color               = '#1f2937';
Chart.defaults.borderColor         = '#e8ecf0';
Chart.defaults.font.family         = "'Share Tech Mono', monospace";
Chart.defaults.font.size           = 10;
Chart.defaults.plugins.legend.display = false;
Chart.defaults.animation.duration     = 550;
Chart.defaults.responsive             = true;
Chart.defaults.maintainAspectRatio    = false;

/** Shared tooltip options. */
const TOOLTIP_DEFAULTS = {
  backgroundColor : '#ffffff',
  borderColor     : '#bcc5d0',
  borderWidth     : 1,
  titleColor      : '#111827',
  bodyColor       : '#0d0d0d',
  bodyFont        : { family: "'Share Tech Mono', monospace", size: 13 },
  titleFont       : { family: "'Share Tech Mono', monospace", size: 10 },
  padding         : 8,
  cornerRadius    : 3,
};


/* =============================================================================
   §3  CHART REGISTRY
   ============================================================================= */

/** @type {Object.<string, Chart>} */
const _charts = {};

function destroyChart(canvasId) {
  if (_charts[canvasId]) {
    _charts[canvasId].destroy();
    delete _charts[canvasId];
  }
}

function destroyAllCharts() {
  Object.keys(_charts).forEach(destroyChart);
}


/* =============================================================================
   §4  CHART BUILDERS
   ============================================================================= */

function buildBarChart(canvasId, labels, data, color) {
  destroyChart(canvasId);
  const canvas = document.getElementById(canvasId);
  if (!canvas) {
    console.warn(`[charts.js] Canvas not found: #${canvasId}`);
    return null;
  }

  const instance = new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor     : color + '40',
        borderColor          : color,
        borderWidth          : 1,
        borderRadius         : 2,
        borderSkipped        : false,
        hoverBackgroundColor : color + '70',
        hoverBorderColor     : color,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend  : { display: false },
        tooltip : { ...TOOLTIP_DEFAULTS },
      },
      scales: {
        x: { ...window.SCADA_SCALE.x },
        y: { ...window.SCADA_SCALE.y },
      },
    },
  });

  _charts[canvasId] = instance;
  return instance;
}

function buildLineChart(canvasId, labels, data, color, yMax = null, yMin = null) {
  destroyChart(canvasId);
  const canvas = document.getElementById(canvasId);
  if (!canvas) {
    console.warn(`[charts.js] Canvas not found: #${canvasId}`);
    return null;
  }

  const yScale = { ...window.SCADA_SCALE.y };
  if (yMax !== null) yScale.max = yMax;
  if (yMin !== null) yScale.min = yMin;

  const instance = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data,
        borderColor          : color,
        backgroundColor      : color + '12',
        borderWidth          : 1.5,
        pointRadius          : 3,
        pointHoverRadius     : 5,
        pointBackgroundColor : color,
        pointBorderColor     : '#f4f6f9',
        pointBorderWidth     : 1.5,
        fill                 : true,
        tension              : 0.35,
        spanGaps             : true,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend  : { display: false },
        tooltip : { ...TOOLTIP_DEFAULTS },
      },
      scales: {
        x: { ...window.SCADA_SCALE.x },
        y: yScale,
      },
      interaction: { mode: 'index', intersect: false },
    },
  });

  _charts[canvasId] = instance;
  return instance;
}

/**
 * Build all 4 weekly trend charts for one machine.
 * @param {string} machineId  - e.g. 'gallus_em280'
 * @param {Array}  weeklyData - array: [{ date, production_m, energy_kwh, run_hours, energy_per_m }]
 */
function buildMachineCharts(machineId, weeklyData) {
  if (!Array.isArray(weeklyData) || weeklyData.length === 0) {
    console.warn(`[charts.js] No weekly data for machine: ${machineId}`);
    return;
  }

  const labels = weeklyData.map(d => d.date);

  buildBarChart(  `chart-prod-${machineId}`,   labels, weeklyData.map(d => d.production_m), CLR.cyan);
  buildLineChart( `chart-energy-${machineId}`, labels, weeklyData.map(d => d.energy_kwh),   CLR.amber);
  buildLineChart( `chart-hours-${machineId}`,  labels, weeklyData.map(d => d.run_hours),    CLR.green, 24, 0);
  buildLineChart( `chart-epm-${machineId}`,    labels, weeklyData.map(d => d.energy_per_m), CLR.blue);
}


/* =============================================================================
   §5  API RESPONSE MAPPERS
   Translate backend JSON field names to what DOM updaters expect.
   ============================================================================= */

/**
 * Map GET /api/snapshot/{key} → applySnapshot() shape.
 *
 * Backend: { status, run_hours, production_meters, energy_kwh, energy_per_meter }
 * Frontend: { machine_status, total_run_hours, total_production_m, total_energy_kwh,
 *             energy_per_m, utilization_pct }
 */
function mapSnapshot(raw) {
  const runHours = parseFloat(raw.run_hours || 0);
  return {
    machine_status:     raw.status || 'STOP',
    total_run_hours:    runHours,
    total_production_m: raw.production_meters || 0,
    total_energy_kwh:   raw.energy_kwh || 0,
    energy_per_m:       raw.energy_per_meter || 0,
    utilization_pct:    ((runHours / 24) * 100),
  };
}

/**
 * Map GET /api/shifts/{key} → applyShifts() array.
 *
 * Backend: { shifts: [{ shift, run_hours, production_meters, energy_kwh,
 *                       energy_per_meter, machine_speed_mph, machine_speed_mpm }],
 *            underperforming_shift }
 * Frontend: [{ shift_name, shift_time, run_hours, production_m,
 *              energy_kwh, speed_mph, energy_per_m }]
 */
function mapShifts(raw) {
  return (raw.shifts || []).map(s => ({
    shift_name:      s.shift || '—',
    shift_time:      SHIFT_TIMES[s.shift] || '',
    run_hours:       Math.max(s.run_hours || 0, 0),
    production_m:    Math.max(s.production_meters || 0, 0),
    energy_kwh:      Math.max(s.energy_kwh || 0, 0),
    speed_mph:       Math.max(s.machine_speed_mph || 0, 0),
    speed_mpm:       Math.max(s.machine_speed_mpm || 0, 0),
    energy_per_m:    Math.max(s.energy_per_meter || 0, 0),
  }));
}

/**
 * Map GET /api/weekly/{key} → buildMachineCharts() array.
 *
 * Backend: { dates: [...], production: [...], run_hours: [...],
 *            energy_kwh: [...], energy_per_meter: [...] }
 * Frontend: [{ date, production_m, energy_kwh, run_hours, energy_per_m }]
 */
function mapWeekly(raw) {
  return (raw.dates || []).map((date, i) => ({
    date,
    production_m: (raw.production || [])[i] || 0,
    energy_kwh:   (raw.energy_kwh || [])[i] || 0,
    run_hours:    (raw.run_hours || [])[i] || 0,
    energy_per_m: (raw.energy_per_meter || [])[i] || 0,
  }));
}


/* =============================================================================
   §6  THRESHOLD HELPERS
   ============================================================================= */

function utilBarClass(pct) {
  if (pct >= 85) return 'bar-fill-green';
  if (pct >= 65) return 'bar-fill-amber';
  return 'bar-fill-red';
}

function utilValueClass(pct) {
  if (pct >= 85) return 'kpi-green';
  if (pct >= 65) return 'kpi-cyan';
  return 'kpi-amber';
}

function epmConfig(epm) {
  if (epm <= EFF_GOOD) return { cls: 'kpi-cyan',  dotColor: 'var(--green)',  label: 'Efficient' };
  if (epm <= EFF_WARN) return { cls: 'kpi-amber', dotColor: 'var(--amber)',  label: 'Average'   };
  return                     { cls: 'kpi-red',   dotColor: 'var(--red)',    label: 'High'      };
}

function shiftBarClass(pct) {
  if (pct >= 85) return 'bar-fill-green';
  if (pct >= 65) return 'bar-fill-amber';
  return 'bar-fill-red';
}

function shortId(machineId) {
  return machineId.split('_')[0];
}


/* =============================================================================
   §7  DOM HELPERS
   ============================================================================= */

function setHTML(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setStyle(id, prop, value) {
  const el = document.getElementById(id);
  if (el) el.style[prop] = value;
}


/* =============================================================================
   §8  KPI DOM UPDATERS
   ============================================================================= */

function applyStatus(machineId, status) {
  const el = document.getElementById(`status-${machineId}`);
  if (!el) return;
  el.textContent = status;
  el.className   = status === 'RUN' ? 'badge-run' : 'badge-stop';
}

/**
 * Apply mapped snapshot data to all KPI elements for one machine.
 * @param {string} machineId - e.g. 'gallus_em280'
 * @param {Object} snap      - mapped snapshot object
 */
function applySnapshot(machineId, snap) {
  /* Status badge */
  applyStatus(machineId, snap.machine_status);

  /* Stopped-at indicator */
  const isStopped = snap.machine_status !== 'RUN';
  document.querySelectorAll(`#panel-${machineId} .prod-stopped-at`).forEach(el => {
    if (isStopped) {
      const now = new Date().toLocaleTimeString('en-GB', { hour12: false, hour: '2-digit', minute: '2-digit' });
      el.textContent = `(${now}) `;
      el.style.display = 'inline';
    } else {
      el.style.display = 'none';
    }
  });

  /* Utilisation */
  const pct     = parseFloat(snap.utilization_pct || 0);
  const pctStr  = pct.toFixed(1);
  const runH    = parseFloat(snap.total_run_hours || 0);
  const idleH   = Math.max(0, 24 - runH).toFixed(1);
  const uValCls = utilValueClass(pct);
  const uBarCls = utilBarClass(pct);

  const utilEl = document.getElementById(`util-${machineId}`);
  if (utilEl) {
    utilEl.className = `kpi-value ${uValCls}`;
    utilEl.innerHTML = `${pctStr}<span class="kpi-unit">%</span>`;
  }

  const barEl = document.getElementById(`util-bar-${machineId}`);
  if (barEl) {
    barEl.className   = `bar-fill ${uBarCls}`;
    barEl.style.width = `${pctStr}%`;
  }

  /* Run hours */
  setHTML(`runhours-${machineId}`,
    `${runH.toFixed(1)}<span class="kpi-unit">h</span>`);

  const runBlock = document.getElementById(`runhours-${machineId}`);
  if (runBlock) {
    const sub = runBlock.nextElementSibling;
    if (sub && sub.classList.contains('kpi-sub')) {
      sub.textContent = `Idle: ${idleH}h`;
    }
  }

  /* Production */
  const prodVal = parseFloat(snap.total_production_m || 0);
  const prodFmt = prodVal >= 1 ? Math.round(prodVal).toLocaleString('en-GB') : prodVal.toFixed(2);
  setHTML(`prod-${machineId}`, `${prodFmt}<span class="kpi-unit">m</span>`);

  /* Energy */
  const kwh = parseFloat(snap.total_energy_kwh || 0).toFixed(1);
  setHTML(`energy-${machineId}`, `${kwh}<span class="kpi-unit">kWh</span>`);

  /* Energy per meter + efficiency indicator */
  const epmVal = parseFloat(snap.energy_per_m || 0);
  const epmStr = epmVal.toFixed(2);
  const eff    = epmConfig(epmVal);

  const epmEl = document.getElementById(`epm-${machineId}`);
  if (epmEl) {
    epmEl.className = `kpi-value ${eff.cls}`;
    epmEl.innerHTML = `${epmStr}<span class="kpi-unit" style="font-size:11px"> kWh/m</span>`;
  }

  setStyle(`eff-dot-${machineId}`, 'background', eff.dotColor);
  setText(`eff-label-${machineId}`, eff.label);

  /* Chart title latest-value badges */
  const sid = shortId(machineId);
  setText(`prod-latest-${sid}`,   `${prodFmt} m`);
  setText(`energy-latest-${sid}`, `${kwh} kWh`);
  setText(`hours-latest-${sid}`,  `${runH.toFixed(1)} h`);
  setText(`epm-latest-${sid}`,    epmStr);
}

/**
 * Re-render shift table rows for one machine.
 * @param {string} machineId - e.g. 'gallus_em280'
 * @param {Array}  shifts    - mapped shift array
 */
function applyShifts(machineId, shifts, serverHourIst) {
  const tbody = document.getElementById(`shifts-${machineId}`);
  if (!tbody || !Array.isArray(shifts) || shifts.length === 0) return;

  const productions = shifts.map(s => s.production_m);
  const maxProd     = Math.max(...productions);
  const minProd     = Math.min(...productions);
  const multiShift  = shifts.length > 1;

  const nowHour = Number.isInteger(serverHourIst)
    ? serverHourIst
    : new Date().getHours();

  function isActiveShift(shiftTime) {
    switch (shiftTime) {
      case '07–15': return nowHour >= 7  && nowHour < 15;
      case '15–23': return nowHour >= 15 && nowHour < 23;
      case '23–07': return nowHour >= 23 || nowHour < 7;
      default:      return false;
    }
  }

  const rows = shifts.map(s => {
    const isWorst   = multiShift && s.production_m === minProd;
    const isBest    = multiShift && s.production_m === maxProd;
    const isActive  = isActiveShift(s.shift_time || '');

    const rowClass = isActive ? 'row-active'
                   : isWorst  ? 'row-worst'
                   : '';

    let tagHTML = '';
    if (isBest) {
      tagHTML = `<span class="tag-pill tag-best"><i class="bi bi-arrow-up"></i>Best</span>`;
    } else if (isWorst) {
      tagHTML = `<span class="tag-pill tag-worst"><i class="bi bi-arrow-down"></i>Low</span>`;
    }

    const speedMpm = parseFloat(s.speed_mpm || 0).toFixed(1);
    const speedMph = parseFloat(s.speed_mph || 0).toFixed(0);
    const prodValS = parseFloat(s.production_m || 0);
    const prodFmt  = prodValS >= 1 ? Math.round(prodValS).toLocaleString('en-GB') : prodValS.toFixed(2);
    const prodStyle = isWorst ? '' : 'style="color: var(--cyan)"';

    return `
      <tr class="${rowClass}">
        <td class="td-shift-name">
          ${s.shift_name || '—'}
          <span class="shift-time-badge">${s.shift_time || ''}</span>
          ${tagHTML}
        </td>
        <td>${parseFloat(s.run_hours || 0).toFixed(1)}</td>
        <td ${prodStyle}><span class="prod-stopped-at" style="display:none"></span>${prodFmt}</td>
        <td>${parseFloat(s.energy_kwh || 0).toFixed(1)}</td>
        <td style="color: var(--cyan); font-family: var(--font-mono); font-weight: 600;">
          ${speedMpm}<span style="font-size: 11px; font-weight: 400;"> m/min</span>
        </td>
        <td style="color: var(--text-dim)">${parseFloat(s.energy_per_m || 0).toFixed(2)}</td>
      </tr>`;
  });

  tbody.innerHTML = rows.join('');
}


/* =============================================================================
   §9  LIVE FETCH ORCHESTRATOR
   Three independent polling loops with different intervals:
     refreshShifts()    — every 5s   (real-time shift values)
     refreshKPI()       — every 15s  (KPI snapshot)
     fetchWeeklyData()  — every 30m  (7-day trend charts)
   ============================================================================= */

/**
 * Fetch shift performance data for all machines.
 * Runs every SHIFT_SEC (5s) for near real-time shift updates.
 */
async function refreshShifts() {
  try {
    const jobs = MACHINES.map(m =>
      fetch(`${API_BASE}/shifts/${m.key}`, { signal: AbortSignal.timeout(8000) })
        .then(r => { if (!r.ok) throw new Error(`Shifts HTTP ${r.status}`); return r.json(); })
        .then(raw => ({ id: m.id, d: mapShifts(raw), serverHourIst: raw.server_hour_ist }))
    );

    const results = await Promise.all(jobs);
    results.forEach(({ id, d, serverHourIst }) => applyShifts(id, d, serverHourIst));

    window.resetCountdown(SHIFT_SEC);

  } catch (err) {
    console.error('[charts.js] refreshShifts error:', err);
  }
}

/**
 * Fetch KPI snapshot data for all machines.
 * Runs every KPI_SEC (15s).
 */
async function refreshKPI() {
  try {
    const jobs = MACHINES.map(m =>
      fetch(`${API_BASE}/snapshot/${m.key}`, { signal: AbortSignal.timeout(8000) })
        .then(r => { if (!r.ok) throw new Error(`Snapshot HTTP ${r.status}`); return r.json(); })
        .then(raw => ({ id: m.id, d: mapSnapshot(raw) }))
    );

    const results = await Promise.all(jobs);
    results.forEach(({ id, d }) => applySnapshot(id, d));

    window.setDbStatus('ok');
    window.clearAlert();
    window.setLastUpdated();

  } catch (err) {
    console.error('[charts.js] refreshKPI error:', err);
    window.setDbStatus('error');
    window.showAlert(`KPI fetch error — retrying in ${KPI_SEC}s`);
  }
}

/**
 * Fetch 7-day weekly trend data for all machines and rebuild charts.
 * Runs every CHART_SEC (30 min) + once on page load.
 */
async function fetchWeeklyData() {
  try {
    const results = await Promise.all(
      MACHINES.map(m =>
        fetch(`${API_BASE}/weekly/${m.key}`, { signal: AbortSignal.timeout(12000) })
          .then(r => { if (!r.ok) throw new Error(`Weekly HTTP ${r.status}`); return r.json(); })
          .then(raw => ({ id: m.id, data: mapWeekly(raw) }))
      )
    );

    results.forEach(({ id, data }) => buildMachineCharts(id, data));

    /* Update chart date range label */
    results.forEach(({ data }) => {
      if (data.length >= 2) {
        const rangeEl = document.querySelector('.charts-section .section-label span');
        if (rangeEl) {
          rangeEl.textContent = `${data[0].date} – ${data[data.length - 1].date}`;
        }
      }
    });

  } catch (err) {
    console.error('[charts.js] fetchWeeklyData error:', err);
  }
}


/* =============================================================================
   §10  INITIALISATION
   Three independent polling loops:
     Shifts  → every  5s  (real-time)
     KPI     → every 15s
     Charts  → every 30 min
   ============================================================================= */

document.addEventListener('DOMContentLoaded', async () => {

  /* 1. First load — fetch everything in parallel */
  await Promise.all([
    fetchWeeklyData(),
    refreshKPI(),
    refreshShifts(),
  ]);

  /* 2. Start three independent polling loops */
  setInterval(refreshShifts,   SHIFT_SEC * 1000);  /* 5s   — real-time shifts   */
  setInterval(refreshKPI,      KPI_SEC   * 1000);  /* 15s  — KPI snapshot        */
  setInterval(fetchWeeklyData, CHART_SEC * 1000);  /* 30m  — weekly trend charts  */

});


/* =============================================================================
   §11  PUBLIC API
   ============================================================================= */

window.SCADA = {
  refreshShifts,
  refreshKPI,
  rebuildCharts: fetchWeeklyData,
  destroyCharts: destroyAllCharts,
  testSnapshot: applySnapshot,
  testShifts: applyShifts,
  config: { SHIFT_SEC, KPI_SEC, CHART_SEC, API_BASE, MACHINES, EFF_GOOD, EFF_WARN },
};
