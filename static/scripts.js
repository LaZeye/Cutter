/* Cutter — dashboard behaviour */

const COLORS = {
  bone:  "#E8E4DC",
  muted: "#8C97A6",
  brass: "#C9922E",
  teal:  "#6FA3A0",
  clay:  "#B5544A",
  good:  "#5FA377",
  plan:  "#9B8AA6",
  rule:  "#3E4854",
  faint: "rgba(140, 151, 166, 0.28)",
  band:  "rgba(201, 146, 46, 0.10)",
};

// Pace states, shared by the countdown, the weekly dots and the readout.
const STATUS = {
  ahead:    { color: COLORS.good,  label: "Ahead of plan", css: "ahead" },
  on_track: { color: COLORS.brass, label: "On track",      css: "on-track" },
  behind:   { color: COLORS.clay,  label: "Behind plan",   css: "behind" },
};

// Headroom above the camp-start rail and below the target rail.
const RAIL_PADDING = 3;

const charts = { camp: null, overall: null, detail: null };

let unit = "lb";
let chartsAvailable = false;
let currentRange = "3m";
let campBands = [];
let editingCampId = null;
let detailCampId = null;
let endingCampId = null;
let latestActive = null;
let pendingOverwrite = false;

const $ = (id) => document.getElementById(id);

/* --- helpers --- */

function signed(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}`;
}

function fixed(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
}

function withUnit(value, digits = 1) {
  return value === null || value === undefined ? "—" : `${fixed(value, digits)} ${unit}`;
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dayLabel(iso) {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function longLabel(iso) {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function flash(el, text, ok = true) {
  el.textContent = text;
  el.className = `form-msg ${ok ? "pos" : "neg"}`;
  setTimeout(() => { el.textContent = ""; el.className = "form-msg"; }, 4000);
}

function showBanner(text) {
  const el = $("banner");
  el.textContent = text;
  el.hidden = false;
}

function hideBanner() { $("banner").hidden = true; }

function figure(list, label, value) {
  list.push(`<div><dt>${label}</dt><dd>${value}</dd></div>`);
}

/* --- chart plugins ------------------------------------------------------ */

/* Vertical rule and label at the fight date. */
const fightDayMarker = {
  id: "fightDayMarker",

  afterDatasetsDraw(chart, args, opts) {
    if (!opts || !opts.date) return;

    const x = chart.scales.x.getPixelForValue(new Date(`${opts.date}T00:00:00`).getTime());
    if (!Number.isFinite(x)) return;

    const { top, bottom, left, right } = chart.chartArea;
    if (x < left - 1 || x > right + 1) return;

    const ctx = chart.ctx;
    ctx.save();

    ctx.beginPath();
    ctx.setLineDash([3, 4]);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = opts.color || COLORS.bone;
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.setLineDash([]);

    const label = opts.label || "Fight day";
    ctx.font = "500 11px Barlow, system-ui, sans-serif";

    const padX = 6;
    const boxWidth = ctx.measureText(label).width + padX * 2;
    const boxHeight = 18;

    // Flip the pill left of the rule when it would overflow the canvas.
    const flip = x + boxWidth + 6 > right;
    const boxX = flip ? x - boxWidth - 5 : x + 5;
    const boxY = top + 2;

    ctx.fillStyle = opts.color || COLORS.bone;
    ctx.beginPath();
    ctx.roundRect(boxX, boxY, boxWidth, boxHeight, 2);
    ctx.fill();

    ctx.fillStyle = "#1A1E24";
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.fillText(label, boxX + padX, boxY + boxHeight / 2 + 0.5);

    ctx.restore();
  },
};

/* Shaded bands behind the all-time chart marking each camp. */
const campBandsPlugin = {
  id: "campBands",

  beforeDatasetsDraw(chart, args, opts) {
    const bands = (opts && opts.bands) || [];
    if (!bands.length) return;

    const { top, bottom, left, right } = chart.chartArea;
    const scale = chart.scales.x;
    const ctx = chart.ctx;

    ctx.save();
    bands.forEach((band) => {
      const x0 = scale.getPixelForValue(new Date(`${band.start}T00:00:00`).getTime());
      const x1 = scale.getPixelForValue(new Date(`${band.end}T00:00:00`).getTime());
      if (!Number.isFinite(x0) || !Number.isFinite(x1)) return;

      const a = Math.max(Math.min(x0, x1), left);
      const b = Math.min(Math.max(x0, x1), right);
      if (b <= a) return;

      ctx.fillStyle = COLORS.band;
      ctx.fillRect(a, top, b - a, bottom - top);

      ctx.font = "500 10px Barlow, system-ui, sans-serif";
      ctx.fillStyle = COLORS.muted;
      ctx.textBaseline = "top";
      const text = band.name;
      if (ctx.measureText(text).width < b - a - 6) {
        ctx.fillText(text, a + 4, top + 4);
      }
    });
    ctx.restore();
  },
};

/* --- shared chart config ------------------------------------------------ */

const gridStyle = { color: COLORS.rule, drawTicks: false };
const tickStyle = { color: COLORS.muted, font: { family: "Barlow", size: 11 } };
const tooltipStyle = {
  backgroundColor: "#1A1E24",
  borderColor: COLORS.rule,
  borderWidth: 1,
  titleColor: COLORS.bone,
  bodyColor: COLORS.bone,
  padding: 10,
};

function timeScale(min, max) {
  return {
    type: "time",
    min: min || undefined,
    max: max || undefined,
    time: { unit: "day", tooltipFormat: "MMM d, yyyy", displayFormats: { day: "MMM d" } },
    grid: { ...gridStyle, display: false },
    ticks: { ...tickStyle, maxRotation: 0, autoSkipPadding: 24 },
  };
}

function rawDataset(entries) {
  return {
    label: "Scale",
    data: entries.map(e => ({ x: e.date, y: e.weight })),
    showLine: false,
    pointRadius: 2,
    pointHoverRadius: 4,
    pointBackgroundColor: COLORS.faint,
    pointBorderColor: "transparent",
    order: 6,
  };
}

function trendDataset(trend) {
  return {
    label: "Trend",
    data: trend.map(t => ({ x: t.date, y: t.trend })),
    borderColor: COLORS.brass,
    backgroundColor: COLORS.brass,
    borderWidth: 2.5,
    pointRadius: 0,
    tension: 0.25,
    order: 2,
  };
}

function weeklyDataset(weekly, graded = true) {
  return {
    label: "Weekly average",
    data: weekly.map(w => ({ x: w.date, y: w.average, meta: w })),
    showLine: false,
    pointRadius: 4.5,
    pointHoverRadius: 6.5,
    // Each week is coloured by how it landed against the plan, so a whole
    // camp reads as a run of good and bad weeks at a glance.
    pointBackgroundColor: weekly.map(w =>
      (graded && STATUS[w.status] ? STATUS[w.status].color : COLORS.bone)),
    pointBorderColor: "#202730",
    pointBorderWidth: 1.5,
    order: 1,
  };
}

function weeklyTooltip(c) {
  const base = `${c.dataset.label}: ${c.parsed.y.toFixed(1)} ${unit}`;
  const meta = c.raw && c.raw.meta;
  if (!meta || meta.delta === null || meta.delta === undefined) return base;
  const state = STATUS[meta.status];
  return `${base} — ${signed(meta.delta)} vs plan${state ? ` (${state.label.toLowerCase()})` : ""}`;
}

/* --- data --------------------------------------------------------------- */

async function loadData() {
  let data;

  try {
    const res = await fetch(`/api/data?range=${currentRange}`);
    if (!res.ok) {
      showBanner(`The server returned ${res.status} loading your data.`);
      return;
    }
    data = await res.json();
  } catch (err) {
    console.error(err);
    showBanner("Could not reach the server. Is app.py still running?");
    return;
  }

  hideBanner();
  unit = data.settings.unit || "lb";

  campBands = data.camps.map(c => ({
    start: c.start_date,
    end: c.ended_on || c.fight_date,
    name: c.name,
  }));

  // Text panels first, so a chart failure can never blank them.
  renderCampControls(data.active_camp);
  renderCountdown(data.active_camp);
  renderReadout(data.active_camp, data.overall.stats);
  renderTiles(data.camps);
  renderRanges(data.overall);
  renderToleranceNote(data.tolerance);
  renderLog(data.entries);

  if (!chartsAvailable) {
    showBanner("Charts are unavailable because Chart.js did not load. Your data is intact.");
    return;
  }

  try {
    renderCampChart(data.active_camp);
    renderOverallChart(data.overall);
  } catch (err) {
    console.error("Chart rendering failed:", err);
    showBanner("Charts failed to draw. Your data is intact — see the console for details.");
  }
}

/* --- camp controls ------------------------------------------------------ */

function renderCampControls(active) {
  // Single place that sees the running camp; the header buttons read it here.
  latestActive = active;

  $("start-camp").hidden = !!active;
  $("end-camp").hidden = !active;
  $("camp-panel").hidden = !active;
  $("no-camp-panel").hidden = !!active;

  if (!active) return;

  $("camp-name").textContent = active.camp.name;
  $("camp-window").textContent =
    `${longLabel(active.window.start)} through ${longLabel(active.window.end)} · target ${withUnit(active.stats.target_weight)}`;
}

function renderToleranceNote(tolerance) {
  $("tolerance-note").textContent = tolerance
    ? `Weekly averages are graded against the plan line: within ${fixed(tolerance)} ${unit} is on track.`
    : "";
}

/* --- countdown ---------------------------------------------------------- */

function renderCountdown(active) {
  const strip = $("camp-strip");

  if (!active || !active.stats.camp_length) {
    strip.hidden = true;
    return;
  }

  strip.hidden = false;
  const stats = active.stats;
  const out = stats.days_out;

  $("camp-days").textContent = Math.abs(out);
  $("camp-label").textContent =
    out > 1   ? "days to fight night" :
    out === 1 ? "day to fight night"  :
    out === 0 ? "fight day"           :
                "days since fight night";

  const state = STATUS[stats.pace_status];
  strip.className = state ? `camp ${state.css}` : "camp";

  const chip = $("camp-status");
  if (state) {
    chip.hidden = false;
    chip.textContent = stats.pace_status === "on_track" || stats.pace_delta === null
      ? state.label
      : `${state.label} by ${fixed(Math.abs(stats.pace_delta))} ${unit}`;
  } else {
    chip.hidden = true;
  }

  const ticks = $("ticks");
  ticks.innerHTML = "";

  const total = Math.min(stats.camp_length, 180);
  const elapsed = Math.round((stats.days_elapsed / stats.camp_length) * total);

  for (let i = 0; i < total; i++) {
    const tick = document.createElement("span");
    tick.className = "tick";
    if (i < elapsed) tick.classList.add("done");
    if (i === elapsed) tick.classList.add("today");
    ticks.appendChild(tick);
  }
}

/* --- readout ------------------------------------------------------------ */

function renderReadout(active, overall) {
  const empty = $("readout-empty");
  const body  = $("readout-body");

  if (!overall.entry_count) {
    empty.hidden = false;
    body.hidden = true;
    return;
  }

  empty.hidden = true;
  body.hidden = false;

  $("trend-weight").textContent = fixed(overall.trend_weight);
  $("trend-unit").textContent = unit;
  $("camp-readout").hidden = !active;

  const rows = [];

  if (active) {
    const s = active.stats;
    renderProgressBar(s);
    renderPace(s);

    figure(rows, "Past 7 days", s.seven_day_change === null ? "—" : `${signed(s.seven_day_change)} ${unit}`);
    figure(rows, "Current rate", s.weekly_rate === null ? "—" : `${signed(s.weekly_rate)} ${unit}`);
    figure(rows, "Rate needed", s.required_weekly_rate === null ? "—" : `${signed(-Math.abs(s.required_weekly_rate))} ${unit}`);
    figure(rows, "Plan weight today", withUnit(s.plan_weight_today));
    figure(rows, "Lost this camp", s.total_change === null ? "—" : `${signed(s.total_change)} ${unit}`);
    figure(rows, "Projected on fight day", withUnit(s.projected_weight));

    renderVerdict(s);
  } else {
    figure(rows, "Past 7 days", overall.seven_day_change === null ? "—" : `${signed(overall.seven_day_change)} ${unit}`);
    figure(rows, "Past 30 days", overall.thirty_day_change === null ? "—" : `${signed(overall.thirty_day_change)} ${unit}`);
    figure(rows, "Current rate", overall.weekly_rate === null ? "—" : `${signed(overall.weekly_rate)} ${unit}`);
    figure(rows, "Weigh-ins logged", String(overall.entry_count));
    figure(rows, "Lightest", withUnit(overall.lightest));
    figure(rows, "Heaviest", withUnit(overall.heaviest));

    $("verdict").hidden = true;
  }

  $("figures").innerHTML = rows.join("");
}

function renderProgressBar(s) {
  const gap = s.to_target;
  const bar = $("bar-fill");

  if (gap === null || gap === undefined) {
    $("to-target").textContent = "—";
    bar.style.width = "0%";
    return;
  }

  if (gap > 0) {
    const lost = Math.abs(s.total_change || 0);
    const startGap = lost + gap;
    const done = startGap > 0 ? (lost / startGap) * 100 : 0;
    bar.style.width = `${Math.min(Math.max(done, 0), 100)}%`;
    $("to-target").textContent = `${fixed(gap)} ${unit} above target.`;
  } else {
    bar.style.width = "100%";
    $("to-target").textContent = `On weight, ${fixed(Math.abs(gap))} ${unit} under target.`;
  }
}

function renderPace(s) {
  const el = $("pace");

  if (s.pace_delta === null || s.pace_delta === undefined || !s.pace_status) {
    el.hidden = true;
    return;
  }

  el.hidden = false;

  if (s.pace_status === "ahead") {
    el.className = "pace pos";
    el.textContent = `${fixed(Math.abs(s.pace_delta))} ${unit} ahead of plan.`;
  } else if (s.pace_status === "behind") {
    el.className = "pace neg";
    el.textContent = `${fixed(s.pace_delta)} ${unit} behind plan.`;
  } else {
    el.className = "pace neutral";
    el.textContent = "On plan.";
  }
}

function renderVerdict(s) {
  const el = $("verdict");
  const gap = s.projected_gap;

  if (gap === null || gap === undefined) {
    el.hidden = true;
    return;
  }

  el.hidden = false;

  if (gap <= 0) {
    el.className = "verdict pos";
    el.textContent = `Holding this trend lands you ${fixed(Math.abs(gap))} ${unit} under target on fight day.`;
  } else {
    el.className = "verdict neg";
    el.textContent = `Holding this trend leaves you ${fixed(gap)} ${unit} over target on fight day.`;
  }
}

/* --- camp chart --------------------------------------------------------- */

function renderCampChart(active) {
  if (charts.camp) { charts.camp.destroy(); charts.camp = null; }
  if (!active) return;

  const { window: win, camp, stats } = active;
  const datasets = [rawDataset(active.entries), trendDataset(active.trend)];

  if (active.weekly_averages.length) datasets.push(weeklyDataset(active.weekly_averages));

  if (active.plan.length) {
    datasets.push({
      label: "Plan",
      data: active.plan.map(p => ({ x: p.date, y: p.value })),
      borderColor: COLORS.plan,
      borderWidth: 1.75,
      pointRadius: 0,
      order: 4,
    });
  }

  if (active.projection.length) {
    datasets.push({
      label: "Projection",
      data: active.projection.map(p => ({ x: p.date, y: p.value })),
      borderColor: COLORS.teal,
      borderWidth: 2,
      borderDash: [5, 4],
      pointRadius: 0,
      order: 3,
    });
  }

  // Two rails bound the cut: the camp-start weight on top, the target below.
  // The axis is padded just beyond each so the band sits inside the frame
  // without flattening the trend line against it.
  const ceiling = stats.start_weight !== null ? stats.start_weight : stats.target_weight;

  [["Target", stats.target_weight], ["Camp start", ceiling]].forEach(([label, y], i) => {
    datasets.push({
      label,
      data: [{ x: win.start, y }, { x: win.end, y }],
      borderColor: COLORS.clay,
      borderWidth: 1.5,
      borderDash: [2, 3],
      pointRadius: 0,
      order: 5 + i,
    });
  });

  // Never let the padding crop real data.
  const seen = [];
  active.entries.forEach(e => seen.push(e.weight));
  active.trend.forEach(t => seen.push(t.trend));
  active.plan.forEach(p => seen.push(p.value));
  active.projection.forEach(p => seen.push(p.value));

  const yMin = Math.min(stats.target_weight - RAIL_PADDING, ...(seen.length ? [Math.min(...seen) - 1] : []));
  const yMax = Math.max(ceiling + RAIL_PADDING, ...(seen.length ? [Math.max(...seen) + 1] : []));

  charts.camp = new Chart($("chart-camp"), {
    type: "line",
    data: { datasets },
    plugins: [fightDayMarker],
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "nearest", axis: "x", intersect: false },
      layout: { padding: { top: 4 } },
      plugins: {
        legend: { display: false },
        fightDayMarker: { date: camp.fight_date, color: COLORS.bone, label: "Fight day" },
        tooltip: { ...tooltipStyle, callbacks: { label: weeklyTooltip } },
      },
      scales: {
        x: timeScale(win.start, win.end),
        y: {
          min: yMin,
          max: yMax,
          grid: gridStyle,
          ticks: { ...tickStyle, callback: v => v.toFixed(0) },
        },
      },
    },
  });
}

/* --- all-time chart ----------------------------------------------------- */

function renderRanges(overall) {
  [...$("ranges").querySelectorAll("button")].forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.range === overall.range);
  });

  const win = overall.window;
  $("overall-window").textContent = win.start && win.end
    ? `${longLabel(win.start)} through ${longLabel(win.end)} · ${overall.entries.length} weigh-ins`
    : "Nothing logged yet.";
}

function renderOverallChart(overall) {
  if (charts.overall) { charts.overall.destroy(); charts.overall = null; }

  const datasets = [rawDataset(overall.entries), trendDataset(overall.trend)];
  if (overall.weekly_averages.length) {
    datasets.push(weeklyDataset(overall.weekly_averages, false));
  }

  charts.overall = new Chart($("chart-overall"), {
    type: "line",
    data: { datasets },
    plugins: [campBandsPlugin],
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "nearest", axis: "x", intersect: false },
      plugins: {
        legend: { display: false },
        campBands: { bands: campBands },
        tooltip: {
          ...tooltipStyle,
          callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)} ${unit}` },
        },
      },
      scales: {
        x: timeScale(overall.window.start, overall.window.end),
        y: { grid: gridStyle, ticks: { ...tickStyle, callback: v => v.toFixed(0) } },
      },
    },
  });
}

/* --- camp tiles --------------------------------------------------------- */

function renderTiles(camps) {
  const wrap = $("camp-tiles");
  const empty = $("camps-empty");

  wrap.innerHTML = "";

  if (!camps.length) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  camps.forEach((c) => {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "tile " + (c.is_active ? "active" : (c.made_weight ? "made" : "missed"));
    tile.addEventListener("click", () => openDetail(c.id));

    const end = c.ended_on || c.fight_date;

    const badge = c.is_active
      ? '<span class="tile-badge running">Running</span>'
      : (c.made_weight
          ? '<span class="tile-badge made">Made weight</span>'
          : `<span class="tile-badge missed">Missed by ${fixed(c.to_target)}</span>`);

    // The figure is the weight on the scale at fight time, which is the
    // number that actually decided the outcome.
    tile.innerHTML = `
      <span class="tile-name">${escapeHtml(c.name)}</span>
      <span class="tile-dates">${dayLabel(c.start_date)} – ${dayLabel(end)} · ${c.weeks} weeks</span>
      <span class="tile-row">
        <span class="tile-figure">${fixed(c.final_scale)} ${unit}</span>
        ${badge}
      </span>
    `;

    wrap.appendChild(tile);
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

/* --- camp detail modal -------------------------------------------------- */

async function openDetail(campId) {
  detailCampId = campId;

  let detail;
  try {
    const res = await fetch(`/api/camps/${campId}`);
    if (!res.ok) { showBanner("Could not load that camp."); return; }
    detail = await res.json();
  } catch (err) {
    console.error(err);
    showBanner("Could not load that camp.");
    return;
  }

  const { camp, stats, window: win } = detail;
  const end = camp.ended_on || camp.fight_date;

  $("detail-title").textContent = camp.name;
  $("detail-window").textContent =
    `${longLabel(camp.start_date)} through ${longLabel(end)} · ${stats.entry_count} weigh-ins`;

  // Making weight is judged on the closing scale reading, not the trend.
  const verdict = $("detail-verdict");
  const gap = stats.final_scale === null ? null : stats.final_scale - stats.target_weight;

  if (stats.current_weight === null) {
    verdict.className = "detail-verdict";
    verdict.textContent = "No weigh-ins recorded during this camp.";
  } else if (stats.is_active) {
    verdict.className = "detail-verdict neutral";
    verdict.textContent = `Still running — ${fixed(Math.abs(gap))} ${unit} to go.`;
  } else if (gap <= 0) {
    verdict.className = "detail-verdict pos";
    verdict.textContent = `Made weight with ${fixed(Math.abs(gap))} ${unit} to spare.`;
  } else {
    verdict.className = "detail-verdict neg";
    verdict.textContent = `Finished ${fixed(gap)} ${unit} over target.`;
  }

  const days = Math.max(stats.days_elapsed, 1);
  const rows = [];
  figure(rows, "Start weight", withUnit(stats.start_weight));
  figure(rows, "Closing scale", withUnit(stats.final_scale));
  figure(rows, "Target", withUnit(stats.target_weight));
  figure(rows, "Total lost", stats.total_change === null ? "—" : `${signed(stats.total_change)} ${unit}`);
  figure(rows, "Average rate", stats.total_change === null ? "—" : `${signed(stats.total_change / days * 7)} ${unit}/wk`);
  figure(rows, "Length", `${(days / 7).toFixed(1)} weeks`);
  $("detail-figures").innerHTML = rows.join("");

  $("detail-dialog").showModal();

  if (!chartsAvailable) return;

  if (charts.detail) { charts.detail.destroy(); charts.detail = null; }

  const datasets = [rawDataset(detail.entries), trendDataset(detail.trend)];
  if (detail.weekly_averages.length) datasets.push(weeklyDataset(detail.weekly_averages));
  if (detail.plan.length) {
    datasets.push({
      label: "Plan",
      data: detail.plan.map(p => ({ x: p.date, y: p.value })),
      borderColor: COLORS.plan,
      borderWidth: 1.75,
      pointRadius: 0,
      order: 4,
    });
  }
  // Two rails bound the cut: the camp-start weight on top, the target below.
  // The axis is padded just beyond each so the band sits inside the frame
  // without flattening the trend line against it.
  const ceiling = stats.start_weight !== null ? stats.start_weight : stats.target_weight;

  [["Target", stats.target_weight], ["Camp start", ceiling]].forEach(([label, y], i) => {
    datasets.push({
      label,
      data: [{ x: win.start, y }, { x: win.end, y }],
      borderColor: COLORS.clay,
      borderWidth: 1.5,
      borderDash: [2, 3],
      pointRadius: 0,
      order: 5 + i,
    });
  });

  // Never let the padding crop real data.
  const seen = [];
  active.entries.forEach(e => seen.push(e.weight));
  active.trend.forEach(t => seen.push(t.trend));
  active.plan.forEach(p => seen.push(p.value));
  active.projection.forEach(p => seen.push(p.value));

  const yMin = Math.min(stats.target_weight - RAIL_PADDING, ...(seen.length ? [Math.min(...seen) - 1] : []));
  const yMax = Math.max(ceiling + RAIL_PADDING, ...(seen.length ? [Math.max(...seen) + 1] : []));

  charts.detail = new Chart($("chart-detail"), {
    type: "line",
    data: { datasets },
    plugins: [fightDayMarker],
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "nearest", axis: "x", intersect: false },
      layout: { padding: { top: 4 } },
      plugins: {
        legend: { display: false },
        fightDayMarker: { date: camp.fight_date, color: COLORS.bone, label: "Fight day" },
        tooltip: { ...tooltipStyle, callbacks: { label: weeklyTooltip } },
      },
      scales: {
        x: timeScale(win.start, win.end),
        y: { grid: gridStyle, ticks: { ...tickStyle, callback: v => v.toFixed(0) } },
      },
    },
  });
}

/* --- log ---------------------------------------------------------------- */

function renderLog(entries) {
  const body = $("log-body");
  const empty = $("log-empty");

  body.innerHTML = "";

  if (!entries || !entries.length) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  // Only the most recent stretch is worth rendering as rows.
  [...entries].reverse().slice(0, 120).forEach((e) => {
    const tr = document.createElement("tr");

    const dateCell = document.createElement("td");
    dateCell.textContent = longLabel(e.date);

    const weightCell = document.createElement("td");
    weightCell.textContent = fixed(e.weight);

    const noteCell = document.createElement("td");
    noteCell.className = "log-note";
    noteCell.textContent = e.note || "";

    const actionCell = document.createElement("td");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn-remove";
    btn.textContent = "Remove";
    btn.addEventListener("click", () => removeEntry(e.date));
    actionCell.appendChild(btn);

    tr.append(dateCell, weightCell, noteCell, actionCell);
    body.appendChild(tr);
  });
}

async function removeEntry(entryDate) {
  try {
    const res = await fetch(`/api/entries/${entryDate}`, { method: "DELETE" });
    if (res.ok) loadData();
  } catch (err) {
    console.error(err);
    showBanner("Could not remove that weigh-in.");
  }
}

/* --- forms -------------------------------------------------------------- */

function openWeighIn() {
  $("entry-date").value = todayISO();
  $("entry-weight").value = "";
  $("entry-note").value = "";
  $("entry-msg").textContent = "";
  resetOverwrite();

  $("weigh-dialog").showModal();
  $("entry-weight").focus();
}

function resetOverwrite() {
  pendingOverwrite = false;
  $("entry-confirm").hidden = true;
  $("entry-save").textContent = "Save weigh-in";
}

async function submitEntry(ev) {
  ev.preventDefault();
  const msg = $("entry-msg");

  try {
    const res = await fetch("/api/entries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date: $("entry-date").value,
        weight: $("entry-weight").value,
        note: $("entry-note").value,
        overwrite: pendingOverwrite,
      }),
    });

    const data = await res.json();

    if (res.ok) {
      $("weigh-dialog").close();
      return;
    }

    // One weigh-in per day: a second reading for the same date asks first.
    if (res.status === 409 && data.error === "duplicate") {
      pendingOverwrite = true;
      const found = data.existing;
      const el = $("entry-confirm");
      el.hidden = false;
      el.textContent =
        `${dayLabel(found.date)} already reads ${fixed(found.weight)} ${unit}. Save again to replace it.`;
      $("entry-save").textContent = "Replace weigh-in";
      return;
    }

    flash(msg, data.error || "That didn't save.", false);
  } catch (err) {
    console.error(err);
    flash(msg, "Could not reach the server.", false);
  }
}

function openCampDialog(camp) {
  editingCampId = camp ? camp.id : null;

  $("camp-dialog-title").textContent = camp ? "Edit camp" : "Start camp";
  $("camp-form-save").textContent = camp ? "Save changes" : "Start camp";
  $("camp-form-msg").textContent = "";

  $("camp-form-name").value = camp ? camp.name : "";
  $("camp-form-start").value = camp ? camp.start_date : todayISO();
  $("camp-form-fight").value = camp ? camp.fight_date : "";
  $("camp-form-target").value = camp ? camp.target_weight : "";

  $("camp-dialog").showModal();
  $("camp-form-name").focus();
}

async function submitCamp(ev) {
  ev.preventDefault();
  const msg = $("camp-form-msg");

  const payload = {
    name: $("camp-form-name").value,
    start_date: $("camp-form-start").value,
    fight_date: $("camp-form-fight").value,
    target_weight: $("camp-form-target").value,
  };

  const url = editingCampId ? `/api/camps/${editingCampId}` : "/api/camps";
  const method = editingCampId ? "PUT" : "POST";

  try {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (res.ok) {
      $("camp-dialog").close();
    } else {
      flash(msg, data.error || "That didn't save.", false);
    }
  } catch (err) {
    console.error(err);
    flash(msg, "Could not reach the server.", false);
  }
}

function openEndDialog(active) {
  endingCampId = active.camp.id;
  $("end-form-msg").textContent = "";
  $("end-dialog-body").textContent =
    `Close out ${active.camp.name} and move it to your history.`;
  $("end-form-date").value = todayISO();
  updateEndWarning();
  $("end-dialog").showModal();
  $("end-form-date").focus();
}

function updateEndWarning() {
  const el = $("end-warning");
  const chosen = $("end-form-date").value;
  const fight = latestActive ? latestActive.camp.fight_date : null;

  // Closing before fight day means the camp never ran, so it is discarded
  // rather than filed. Say so plainly before the button is pressed.
  if (fight && chosen && chosen < fight) {
    el.hidden = false;
    el.textContent =
      `That is before fight day on ${longLabel(fight)}, so this camp will be discarded instead of saved to your history. Your weigh-ins are kept.`;
    $("end-save").textContent = "Discard camp";
  } else {
    el.hidden = true;
    $("end-save").textContent = "End camp";
  }
}

async function submitEnd(ev) {
  ev.preventDefault();
  const msg = $("end-form-msg");

  try {
    const res = await fetch(`/api/camps/${endingCampId}/end`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ended_on: $("end-form-date").value }),
    });
    const data = await res.json();

    if (res.ok) {
      $("end-dialog").close();
    } else {
      flash(msg, data.error || "That didn't save.", false);
    }
  } catch (err) {
    console.error(err);
    flash(msg, "Could not reach the server.", false);
  }
}

async function deleteCamp() {
  if (!detailCampId) return;

  try {
    const res = await fetch(`/api/camps/${detailCampId}`, { method: "DELETE" });
    if (res.ok) {
      $("detail-dialog").close();
    } else {
      showBanner("Could not delete that camp.");
    }
  } catch (err) {
    console.error(err);
    showBanner("Could not delete that camp.");
  }
}

/* --- boot --------------------------------------------------------------- */

document.addEventListener("DOMContentLoaded", () => {
  chartsAvailable = typeof Chart !== "undefined";
  if (!chartsAvailable) {
    console.error("Chart.js is not defined — check static/vendor/chart.umd.min.js loaded.");
  }

  $("entry-form").addEventListener("submit", submitEntry);
  $("open-weigh-in").addEventListener("click", openWeighIn);

  // Editing the date or weight retracts a pending overwrite confirmation.
  $("entry-date").addEventListener("input", resetOverwrite);
  $("entry-weight").addEventListener("input", resetOverwrite);

  $("end-form-date").addEventListener("input", updateEndWarning);
  $("camp-form").addEventListener("submit", submitCamp);
  $("end-form").addEventListener("submit", submitEnd);
  $("detail-delete").addEventListener("click", deleteCamp);

  $("start-camp").addEventListener("click", () => openCampDialog(null));
  $("start-camp-empty").addEventListener("click", () => openCampDialog(null));

  $("edit-camp").addEventListener("click", () => {
    if (latestActive) openCampDialog(latestActive.camp);
  });
  $("end-camp").addEventListener("click", () => {
    if (latestActive) openEndDialog(latestActive);
  });

  // Every dialog closes the same way: a data-close button, the backdrop, or
  // Escape. Reloading on close keeps the page in step whatever route was used.
  document.querySelectorAll("dialog").forEach((dlg) => {
    dlg.addEventListener("click", (ev) => { if (ev.target === dlg) dlg.close(); });
    dlg.addEventListener("close", () => {
      if (dlg.id === "detail-dialog" && charts.detail) {
        charts.detail.destroy();
        charts.detail = null;
      }
      loadData();
    });
  });

  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => $(btn.dataset.close).close());
  });

  $("ranges").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-range]");
    if (!btn) return;
    currentRange = btn.dataset.range;
    loadData();
  });

  loadData();
});