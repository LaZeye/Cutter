/* Cutter — dashboard behaviour */

const COLORS = {
  bone:  "#E8E4DC",
  muted: "#8C97A6",
  brass: "#C9922E",
  teal:  "#6FA3A0",
  clay:  "#B5544A",
  rule:  "#3E4854",
};

let weightChart = null;
let weeklyChart = null;
let unit = "lb";
let chartsAvailable = false;

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

function dayLabel(iso) {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
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

function hideBanner() {
  $("banner").hidden = true;
}

/* --- data --- */

async function loadData() {
  let data;

  try {
    const res = await fetch(`/api/data?alpha=${$("alpha").value}`);
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

  // Text-based panels render first so a chart failure can never blank them.
  fillSettings(data.settings);
  renderCamp(data.stats);
  renderReadout(data.stats);
  renderLog(data.entries, data.trend);

  if (!chartsAvailable) {
    showBanner("Charts are unavailable because Chart.js did not load. Your data is intact.");
    return;
  }

  try {
    renderWeightChart(data);
    renderWeeklyChart(data.weekly_rates);
  } catch (err) {
    console.error("Chart rendering failed:", err);
    showBanner("Charts failed to draw. Your data is intact — see the console for details.");
  }
}

function fillSettings(s) {
  if (!$("target-weight").value) $("target-weight").value = s.target_weight || "";
  if (!$("fight-date").value)    $("fight-date").value    = s.fight_date || "";
  if (!$("camp-start").value)    $("camp-start").value    = s.camp_start || "";
}

/* --- countdown strip --- */

function renderCamp(stats) {
  const strip = $("camp-strip");

  if (stats.days_out === null || stats.camp_length === null) {
    strip.hidden = true;
    return;
  }

  strip.hidden = false;
  const out = stats.days_out;

  $("camp-days").textContent = Math.abs(out);
  $("camp-label").textContent =
    out > 1   ? "days to fight night" :
    out === 1 ? "day to fight night"  :
    out === 0 ? "fight day"           :
                "days since fight night";

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

/* --- readout --- */

function renderReadout(stats) {
  const empty = $("readout-empty");
  const body  = $("readout-body");

  if (!stats.entry_count) {
    empty.hidden = false;
    body.hidden = true;
    return;
  }

  empty.hidden = true;
  body.hidden = false;

  $("trend-weight").textContent = fixed(stats.trend_weight);
  $("trend-unit").textContent = unit;
  $("raw-weight").textContent = `${fixed(stats.latest_weight)} ${unit}`;
  $("raw-date").textContent = dayLabel(stats.latest_date);

  renderProgressBar(stats);

  $("seven-day").textContent = stats.seven_day_change === null
    ? "—" : `${signed(stats.seven_day_change)} ${unit}`;

  $("weekly-rate").textContent = stats.weekly_rate === null
    ? "—" : `${signed(stats.weekly_rate)} ${unit}`;

  $("required-rate").textContent = stats.required_weekly_rate === null
    ? "—" : `${signed(-Math.abs(stats.required_weekly_rate))} ${unit}`;

  $("projected").textContent = stats.projected_weight === null
    ? "—" : `${fixed(stats.projected_weight)} ${unit}`;

  renderVerdict(stats);
}

function renderProgressBar(stats) {
  const gap = stats.to_target;

  if (gap === null || gap === undefined) {
    $("to-target").textContent = "Set a target weight to track the gap.";
    $("bar-fill").style.width = "0%";
    return;
  }

  if (gap > 0) {
    const lost = Math.abs(stats.total_change || 0);
    const startGap = lost + gap;
    const done = startGap > 0 ? (lost / startGap) * 100 : 0;
    $("bar-fill").style.width = `${Math.min(Math.max(done, 0), 100)}%`;
    $("to-target").textContent = `${fixed(gap)} ${unit} above target.`;
  } else {
    $("bar-fill").style.width = "100%";
    $("to-target").textContent = `On weight, ${fixed(Math.abs(gap))} ${unit} under target.`;
  }
}

function renderVerdict(stats) {
  const el = $("verdict");
  const gap = stats.projected_gap;

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

/* --- charts --- */

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

function renderWeightChart(data) {
  const raw   = data.entries.map(e => ({ x: e.date, y: e.weight }));
  const trend = data.trend.map(t => ({ x: t.date, y: t.trend }));
  const proj  = (data.projection || []).map(p => ({ x: p.date, y: p.value }));

  const datasets = [
    {
      label: "Scale",
      data: raw,
      showLine: false,
      pointRadius: 2.5,
      pointHoverRadius: 4,
      pointBackgroundColor: COLORS.muted,
      pointBorderColor: "transparent",
      order: 3,
    },
    {
      label: "Trend",
      data: trend,
      borderColor: COLORS.brass,
      backgroundColor: COLORS.brass,
      borderWidth: 2.5,
      pointRadius: 0,
      tension: 0.25,
      order: 1,
    },
  ];

  if (proj.length) {
    datasets.push({
      label: "Projection",
      data: proj,
      borderColor: COLORS.teal,
      borderWidth: 2,
      borderDash: [5, 4],
      pointRadius: 0,
      order: 2,
    });
  }

  const target = parseFloat(data.settings.target_weight);
  if (!Number.isNaN(target) && trend.length) {
    const first = trend[0].x;
    const last = proj.length ? proj[proj.length - 1].x : trend[trend.length - 1].x;
    datasets.push({
      label: "Target",
      data: [{ x: first, y: target }, { x: last, y: target }],
      borderColor: COLORS.clay,
      borderWidth: 1.5,
      borderDash: [2, 3],
      pointRadius: 0,
      order: 4,
    });
  }

  if (weightChart) weightChart.destroy();

  weightChart = new Chart($("chart-weight"), {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "nearest", axis: "x", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...tooltipStyle,
          callbacks: {
            label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)} ${unit}`,
          },
        },
      },
      scales: {
        x: {
          type: "time",
          time: {
            unit: "day",
            tooltipFormat: "MMM d, yyyy",
            displayFormats: { day: "MMM d" },
          },
          grid: { ...gridStyle, display: false },
          ticks: { ...tickStyle, maxRotation: 0, autoSkipPadding: 24 },
        },
        y: {
          grid: gridStyle,
          ticks: { ...tickStyle, callback: (v) => v.toFixed(0) },
        },
      },
    },
  });
}

function renderWeeklyChart(rates) {
  const data = rates || [];

  if (weeklyChart) weeklyChart.destroy();

  weeklyChart = new Chart($("chart-weekly"), {
    type: "bar",
    data: {
      labels: data.map(r => dayLabel(r.week)),
      datasets: [{
        data: data.map(r => r.change),
        backgroundColor: data.map(r => (r.change <= 0 ? COLORS.brass : COLORS.clay)),
        borderRadius: 2,
        barPercentage: 0.7,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          ...tooltipStyle,
          callbacks: {
            title: (items) => `Week of ${items[0].label}`,
            label: (c) => `${signed(c.parsed.y)} ${unit}`,
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { ...tickStyle, autoSkip: true, maxRotation: 0 } },
        y: { grid: gridStyle, ticks: { ...tickStyle, callback: (v) => signed(v, 0) } },
      },
    },
  });
}

/* --- log --- */

function renderLog(entries, trend) {
  const body = $("log-body");
  const empty = $("log-empty");

  body.innerHTML = "";

  if (!entries || !entries.length) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  const trendByDate = Object.fromEntries((trend || []).map(t => [t.date, t.trend]));

  [...entries].reverse().forEach((e) => {
    const tr = document.createElement("tr");

    const dateCell = document.createElement("td");
    dateCell.textContent = dayLabel(e.date);

    const weightCell = document.createElement("td");
    weightCell.textContent = fixed(e.weight);

    const trendCell = document.createElement("td");
    trendCell.textContent = fixed(trendByDate[e.date]);

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

    tr.append(dateCell, weightCell, trendCell, noteCell, actionCell);
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

/* --- forms --- */

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
      }),
    });

    const data = await res.json();

    if (res.ok) {
      flash(msg, "Weigh-in saved.");
      $("entry-weight").value = "";
      $("entry-note").value = "";
      loadData();
    } else {
      flash(msg, data.error || "That didn't save.", false);
    }
  } catch (err) {
    console.error(err);
    flash(msg, "Could not reach the server.", false);
  }
}

async function submitSettings(ev) {
  ev.preventDefault();
  const msg = $("settings-msg");

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_weight: $("target-weight").value,
        fight_date: $("fight-date").value,
        camp_start: $("camp-start").value,
      }),
    });

    const data = await res.json();

    if (res.ok) {
      flash(msg, "Settings saved.");
      loadData();
    } else {
      flash(msg, data.error || "That didn't save.", false);
    }
  } catch (err) {
    console.error(err);
    flash(msg, "Could not reach the server.", false);
  }
}

/* --- boot --- */

document.addEventListener("DOMContentLoaded", () => {
  chartsAvailable = typeof Chart !== "undefined";
  if (!chartsAvailable) {
    console.error("Chart.js is not defined — check static/vendor/chart.umd.min.js loaded.");
  }

  $("entry-form").addEventListener("submit", submitEntry);
  $("settings-form").addEventListener("submit", submitSettings);

  $("alpha").addEventListener("input", (ev) => {
    $("alpha-out").textContent = Number(ev.target.value).toFixed(2);
  });
  $("alpha").addEventListener("change", loadData);

  $("entry-date").value = new Date().toISOString().slice(0, 10);
  $("alpha-out").textContent = Number($("alpha").value).toFixed(2);

  loadData();
});