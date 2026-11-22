/* Dashboard controller: load data, date window navigation, render tiles/charts/tables, sync + VO2 max controls. */
const $ = (s, el = document) => el.querySelector(s);
let DATA = null, RANGE = 7, OFFSET = 0, pollTimer;  // OFFSET = days scrolled back from the latest day

const ago = iso => { if (!iso) return "never synced"; const m = Math.round((Date.now() - new Date(iso)) / 60000);
  return m < 1 ? "synced just now" : m < 60 ? `synced ${m} min ago` : m < 1440 ? `synced ${Math.round(m / 60)} h ago` : `synced ${Math.round(m / 1440)} d ago`; };
const pct = (part, whole) => part != null && whole ? `${Math.round(part / whole * 100)}%` : "–";

function kpi(lbl, v, unit, dec, cmpTxt, color, ic) {
  return `<div class="card kpi"><div class="lbl">${ic ? icon(ic, 14) : ""}${lbl}</div><div class="val" ${color ? `style="color:${color}"` : ""}>${typeof v === "string" ? v : fmt(v, dec)}<small>${unit}</small></div><div class="cmp">${cmpTxt}</div></div>`;
}
const vsAvg = (v, base, dec, higherBetter = true, label = "30-day avg") => {
  const b = avg(base); if (v == null || b == null) return `${label} –`;
  const diff = v - b, good = higherBetter ? diff >= 0 : diff <= 0;
  return `<span class="${good ? "up" : "down"}">${diff >= 0 ? "▲" : "▼"} ${Math.abs(diff).toFixed(dec)}</span> vs ${label} ${b.toFixed(dec)}`;
};

/* The visible slice of days for the current range + offset; weeks follow the same window. */
function windowDays(all) {
  if (!RANGE) return all;
  const end = Math.max(RANGE, all.length - OFFSET), start = Math.max(0, end - RANGE);
  return all.slice(start, end);
}
function setNav(days, all) {
  const first = all[0]?.d, last = all[all.length - 1]?.d;
  $("#period").textContent = days.length ? `${dayLabel(days[0].d)} – ${dayLabel(days[days.length - 1].d)}` : "";
  $("#prev").disabled = !RANGE || !days.length || days[0].d <= first;
  $("#next").disabled = !RANGE || !days.length || days[days.length - 1].d >= last;
}

function sleepTable(days) {
  const rows = [...days].reverse().filter(d => d.sleep != null);
  // d.sleep already includes naps; night-only sleep is the difference. Stages are stacked in one cell as proportional bars.
  const stages = d => barRows([
    { v: d.awake || 0, label: "Awake", val: `${Math.round((d.awake || 0) * 60)}m`, sub: pct(d.awake, d.in_bed), color: css("--muted"), title: "Awake as % of time in bed" },
    { v: d.light || 0, label: "Light", val: hm(d.light), sub: pct(d.light, d.sleep), color: css("--light"), title: "Light sleep as % of total sleep" },
    { v: d.sws || 0, label: "Deep", val: hm(d.sws), sub: pct(d.sws, d.sleep), color: css("--sws"), title: "Deep (slow-wave) sleep as % of total sleep" },
    { v: d.rem || 0, label: "REM", val: hm(d.rem), sub: pct(d.rem, d.sleep), color: css("--rem"), title: "REM sleep as % of total sleep" }]);
  return `<tr><th>Night of</th><th>Total slept</th><th>Slept at night</th><th>In bed</th><th>Stages</th><th>Nap</th><th>Bedtime</th><th>Woke up</th></tr>` +
    rows.map(d => `<tr><td>${dowLabel(d.d)}</td><td><b>${hm(d.sleep)}</b></td><td>${hm(d.sleep - (d.nap || 0))}</td><td>${hm(d.in_bed)}</td><td class="stages">${stages(d)}</td>
      <td>${d.nap ? Math.round(d.nap * 60) + " min" : "–"}</td><td>${d.bed || "–"}</td><td>${d.wake || "–"}</td></tr>`).join("");
}

function render() {
  const root = $("#root");
  if (!DATA) { root.innerHTML = `<div class="card empty">Loading…</div>`; return; }
  if (!DATA.whoop_connected) { root.innerHTML = `<div class="card empty"><p>Connect your WHOOP account to start syncing.</p><a class="btn primary" href="/auth/whoop">Connect WHOOP</a></div>`; return; }
  if (!DATA.days.length) { root.innerHTML = `<div class="card empty">${DATA.sync_running ? "First sync in progress…" : "No data yet. Click <b>Sync now</b>."}${DATA.sync_error ? `<div class="err">${DATA.sync_error}</div>` : ""}</div>`; return; }
  $("#gen").innerHTML = `${DATA.days.length} days of history · ${ago(DATA.last_sync)}${DATA.strava_pending ? ` · Strava: ${DATA.strava_pending} activit${DATA.strava_pending === 1 ? "y" : "ies"} still fetching detail (rate-limited, continues automatically)` : ""}${DATA.sync_error ? ` · <span class="err">last sync failed: ${DATA.sync_error}</span>` : ""}`;

  const all = DATA.days, days = windowDays(all), L = days.map(d => d.d), col = k => days.map(d => d[k]);
  setNav(days, all);
  const lastWeekKey = days.length ? days[days.length - 1].d : null;
  const weekIdx = DATA.weeks.findIndex(w => lastWeekKey && w.w <= lastWeekKey && lastWeekKey <= w.end);
  const nWeeks = RANGE ? Math.max(8, Math.round(RANGE / 7)) : DATA.weeks.length;
  const weeks = DATA.weeks.slice(Math.max(0, (weekIdx < 0 ? DATA.weeks.length : weekIdx + 1) - nWeeks), weekIdx < 0 ? DATA.weeks.length : weekIdx + 1);
  const cur = DATA.weeks.find(w => w.current) || DATA.weeks[DATA.weeks.length - 1], prev = DATA.weeks[DATA.weeks.length - 2];
  const lastRec = [...all].reverse().find(d => d.rec != null) || all[all.length - 1], last = all[all.length - 1], base30 = all.slice(-31, -1);
  const vo2 = DATA.vo2max.length ? DATA.vo2max[DATA.vo2max.length - 1] : null, vo2prev = DATA.vo2max.length > 1 ? DATA.vo2max[DATA.vo2max.length - 2] : null;
  const est = DATA.fitness && DATA.fitness.vo2max ? DATA.fitness.vo2max.estimate : null;
  const dLabel = days.length <= 14 ? dowLabel : dayLabel, dense = days.length <= 31;
  const exByDay = {}; DATA.workouts.forEach(w => { if (w.cat === "walk") return; const e = exByDay[w.d] ||= { run: 0, strength: 0, other: 0, n: 0 }; e[w.cat === "run" || w.cat === "strength" ? w.cat : "other"] += (w.min || 0) / 60; e.n++; });
  const ex = k => days.map(d => exByDay[d.d] ? +exByDay[d.d][k].toFixed(2) : 0);

  root.innerHTML = `
  <div class="kpis">
    ${kpi("Recovery", lastRec.rec, "%", 0, vsAvg(lastRec.rec, base30.map(d => d.rec), 0), recColor(lastRec.rec), "heart")}
    ${kpi("HRV", lastRec.hrv, "ms", 0, vsAvg(lastRec.hrv, base30.map(d => d.hrv), 0), null, "pulse")}
    <div class="card kpi"><div class="lbl">${icon("lungs", 14)}VO2 max <button class="edit" id="vo2Btn" title="Enter the value from the WHOOP app">✎</button></div>
      <div class="val">${vo2 ? fmt(vo2.v, 1) : est ? fmt(est, 1) : "–"}<small>ml/kg/min</small></div>
      <div class="cmp">${vo2 && est ? `WHOOP app · our estimate from runs <b>${fmt(est, 1)}</b>` : vo2prev ? `<span class="${vo2.v >= vo2prev.v ? "up" : "down"}">${vo2.v >= vo2prev.v ? "▲" : "▼"} ${Math.abs(vo2.v - vo2prev.v).toFixed(1)}</span> since ${dayLabel(vo2prev.d)}` : vo2 ? `entered ${dayLabel(vo2.d)}` : est ? `estimated from your runs` : "not entered yet"}</div>
      <form id="vo2Form" class="vo2form" hidden><input type="number" step="0.1" min="10" max="99" name="value" placeholder="e.g. 48.5" required><button class="btn" type="submit">Save</button></form></div>
    ${kpi("Sleep", last.sleep, "h", 1, last.nap ? `incl. ${Math.round(last.nap * 60)} min nap · need ${fmt(last.need, 1)} h` : `need ${fmt(last.need, 1)} h · ${vsAvg(last.sleep, base30.map(d => d.sleep), 1)}`, null, "moon")}
    ${kpi("Day strain", last.strain, "", 1, vsAvg(last.strain, base30.map(d => d.strain), 1), null, "bolt")}
    ${kpi("Exercised this week", cur ? cur.hours : null, "h", 1, prev ? vsAvg(cur.hours, [prev.hours], 1, true, "last week") : "", null, "timer")}
  </div>
  <div class="grid">
    <div class="card full"><h2>${icon("target")}This week</h2><div class="note">Sleep and training against your goals — patterns, not medical advice.</div><ul class="insights" id="ins"></ul></div>
    <div class="card full"><h2>${icon("pulse")}Fitness</h2><div class="note">Derived from raw heart-rate and pace streams, not from vendor scores · methods in the README</div>
      <div class="minis" id="fitTiles"></div><div id="fitZones"></div>
      <h3>VO2 max estimate per run (last 20)</h3><div class="chart" id="cVo2"></div></div>
    <div class="card full"><h2>${icon("run")}Running</h2><div class="note">Half-marathon prep: volume, pace and recent runs</div>
      <div class="minis" id="runTiles"></div>
      <div id="prTiles"></div>
      <h3>Weekly distance</h3><div class="chart" id="cRunKm"></div>
      <h3>Pace per run (last 20)</h3><div class="chart" id="cPace"></div>
      <h3>Last 10 runs</h3><div class="tbl"><table id="runTable"></table></div><div id="unmatched"></div></div>
    <div class="card full"><h2>${icon("dumbbell")}Strength</h2><div class="note">Sessions logged as strength workouts</div>
      <div class="minis" id="strTiles"></div><h3>Last 10 sessions</h3><div class="tbl"><table id="strTable"></table></div></div>
    <div class="card full"><h2>${icon("moon")}Sleep per night</h2><div class="note">Hours asleep (stages, naps included) next to hours in bed · the gap is time awake</div><div class="chart tall" id="cSleepD"></div>
      <div class="legend"><span><i style="background:var(--light)"></i>Light</span><span><i style="background:var(--sws)"></i>Deep</span><span><i style="background:var(--rem)"></i>REM</span><span><i style="background:var(--grid);border:1px solid var(--line)"></i>In bed</span><span><i style="background:var(--ink);height:2px"></i>Sleep need</span></div>
      <h3>${icon("bed", 12)}Night by night</h3><div class="tbl"><table id="sleepTable"></table></div></div>
    <div class="card full"><h2>${icon("timer")}Hours exercised per day</h2><div class="note">Walking excluded</div><div class="chart" id="cHours"></div>
      <div class="legend"><span><i style="background:var(--blue)"></i>Running</span><span><i style="background:var(--purple)"></i>Strength</span><span><i style="background:var(--teal)"></i>Other</span></div></div>
    <div class="card full"><h2>${icon("flame")}Calories burned per day</h2><div class="note">Total daily burn</div><div class="chart" id="cKcal"></div></div>
    <div class="card full"><h2>${icon("bolt")}Day strain</h2><div class="note">Daily strain</div><div class="chart" id="cStrainD"></div></div>
    <div class="card full"><h2>${icon("heart")}Recovery</h2><div class="note">Daily score with 7-day average</div><div class="chart" id="cRec"></div>
      <div class="legend"><span><i style="background:var(--green)"></i>67–100</span><span><i style="background:var(--yellow)"></i>34–66</span><span><i style="background:var(--red)"></i>0–33</span><span><i style="background:var(--ink);height:2px"></i>7-day avg</span></div></div>
    <div class="card full"><h2>${icon("list")}Recent workouts</h2><div class="tbl"><table id="wk"></table></div></div>
  </div>`;

  const dtip = (i, body) => `<b>${dowLabel(L[i])}</b><br>${body}`;
  const every = dense ? 1 : undefined, top = dense ? (fn => fn) : () => undefined;
  const hmShort = h => h >= 1 ? `${Math.floor(h)}h${String(Math.round((h % 1) * 60)).padStart(2, "0")}` : `${Math.round(h * 60)}m`;
  const sleepSeg = (v, si, gi, i) => gi === 0 && si > 0 ? [hmShort(v), pct(v, days[i].sleep)] : hmShort(v);  // Deep/REM: hours + % of sleep
  groupChart($("#cSleepD"), L, { labelFn: dLabel, labelEvery: every, segLabel: dense ? sleepSeg : null, topLabel: dense ? v => hmShort(v) : null, groups: [
      { segments: [{ values: col("light"), color: css("--light") }, { values: col("sws"), color: css("--sws"), dark: true }, { values: col("rem"), color: css("--rem") }] },
      { segments: [{ values: col("in_bed"), color: css("--grid") }] }],
    lines: [{ values: col("need"), color: css("--ink"), dash: "4 3" }],
    tip: i => { const d = days[i]; return dtip(i, `Asleep <b>${hm(d.sleep)}</b> of ${hm(d.in_bed)} in bed · awake ${Math.round((d.awake || 0) * 60)} min${d.nap ? ` · nap ${Math.round(d.nap * 60)} min` : ""}<br>Light ${hm(d.light)} (${pct(d.light, d.sleep)}) · Deep ${hm(d.sws)} (${pct(d.sws, d.sleep)}) · REM ${hm(d.rem)} (${pct(d.rem, d.sleep)})<br>Need ${hm(d.need)} · bedtime ${d.bed || "–"}`); } });
  $("#sleepTable").innerHTML = sleepTable(days);
  groupChart($("#cHours"), L, { labelFn: dLabel, labelEvery: every, segLabel: dense ? v => hmShort(v) : null, topLabel: dense ? v => hmShort(v) : null,
    groups: [{ segments: [{ values: ex("run"), color: css("--blue"), dark: true }, { values: ex("strength"), color: css("--purple"), dark: true }, { values: ex("other"), color: css("--teal") }] }],
    tip: i => { const e = exByDay[L[i]]; return dtip(i, e ? `<b>${hm(e.run + e.strength + e.other)}</b> · running ${hm(e.run)} · strength ${hm(e.strength)} · other ${hm(e.other)}` : "Rest day"); } });
  groupChart($("#cKcal"), L, { labelFn: dLabel, labelEvery: every, topLabel: dense ? v => Math.round(v).toLocaleString() : null, groups: [{ segments: [{ values: col("kcal"), color: css("--orange") }] }], yFmt: v => Math.round(v).toLocaleString(),
    tip: i => dtip(i, `<b>${(days[i].kcal || 0).toLocaleString()} kcal</b>`) });
  groupChart($("#cStrainD"), L, { labelFn: dLabel, labelEvery: every, topLabel: dense ? v => fmt(v, 1) : null, groups: [{ segments: [{ values: col("strain"), color: css("--blue") }] }], yMax: 21,
    tip: i => dtip(i, `Strain <b>${fmt(days[i].strain, 1)}</b> · ${fmt(days[i].kcal)} kcal`) });
  tsChart($("#cRec"), L, { labelFn: dLabel, labelEvery: every, topLabel: dense ? i => fmt(days[i].rec) : null, bars: [{ values: col("rec") }], barColor: v => recColor(v), lines: [{ values: rolling(col("rec"), 7), color: css("--ink") }], yMin: 0, yMax: 100,
    tip: i => dtip(i, `Recovery <b>${fmt(days[i].rec)}%</b> · HRV ${fmt(days[i].hrv)} ms · RHR ${fmt(days[i].rhr)}`) });

  renderFitness(); renderRunning(weeks, cur, prev); renderStrength(cur, prev); renderInsights(days, DATA.weeks, cur, prev);

  const wks = DATA.workouts.filter(w => !RANGE || (w.d >= L[0] && w.d <= L[L.length - 1])).slice(0, 40);
  $("#wk").innerHTML = `<tr><th>Date</th>${DATA.strava_connected ? "<th>Source</th>" : ""}<th>Activity</th><th>Duration</th><th>Strain</th><th>Avg / max HR</th><th>kcal</th><th>Distance</th><th>Pace</th><th>HR zones (min)</th></tr>` +
    (wks.length ? wks.map(w => `<tr><td>${dayLabel(w.d)} ${w.t}</td>${DATA.strava_connected ? `<td>${srcTag(w)}</td>` : ""}<td style="text-transform:capitalize">${w.sport}</td><td>${fmt(w.min)} min</td><td>${fmt(w.strain, 1)}</td><td>${fmt(w.avg_hr)} / ${fmt(w.max_hr)}</td><td>${fmt(w.kcal)}</td><td>${w.km ? w.km + " km" : "–"}</td><td>${w.pace_str ? w.pace_str + " /km" : "–"}</td><td>${zones(w.zones, w.zones_src)}</td></tr>`).join("")
      : `<tr><td colspan="10" class="sub">No workouts in this range.</td></tr>`);

  $("#vo2Btn").onclick = () => { const f = $("#vo2Form"); f.hidden = !f.hidden; if (!f.hidden) f.value.focus(); };
  $("#vo2Form").onsubmit = async e => { e.preventDefault();
    const r = await fetch("/api/metrics/vo2max", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value: +e.target.value.value }) });
    if (r.status === 401) { location.href = "/login"; return; } if (r.ok) { DATA.vo2max = (await r.json()).vo2max; render(); } };
}

function setSyncUI() {
  const b = $("#syncBtn"), busy = DATA && DATA.sync_running;
  b.disabled = !!busy || !(DATA && DATA.whoop_connected); b.classList.toggle("busy", !!busy);
  $("#syncBtn .txt").textContent = busy ? "Syncing…" : "Sync now";
}
async function load() {
  try { const r = await fetch("/api/data", { cache: "no-store" }); if (r.status === 401) { location.href = "/login"; return; } DATA = await r.json(); }
  catch (e) { $("#gen").textContent = "Could not load data"; return; }
  render(); setSyncUI(); clearTimeout(pollTimer);
  if (DATA.sync_running) pollTimer = setTimeout(load, 3000);
}
$("#syncBtn").onclick = async () => { $("#syncBtn").disabled = true; $("#syncBtn").classList.add("busy"); $("#syncBtn .txt").textContent = "Syncing…";
  const r = await fetch("/sync", { method: "POST" }); if (r.status === 401) { location.href = "/login"; return; } pollTimer = setTimeout(load, 1500); };
document.querySelectorAll("#range button").forEach(b => b.onclick = () => { document.querySelectorAll("#range button").forEach(x => x.classList.toggle("on", x === b)); RANGE = +b.dataset.d; OFFSET = 0; render(); });
$("#prev").onclick = () => { OFFSET = Math.min(OFFSET + RANGE, Math.max(0, DATA.days.length - RANGE)); render(); };
$("#next").onclick = () => { OFFSET = Math.max(0, OFFSET - RANGE); render(); };
document.addEventListener("keydown", e => { if (e.target.tagName === "INPUT") return; if (e.key === "ArrowLeft" && !$("#prev").disabled) $("#prev").click(); if (e.key === "ArrowRight" && !$("#next").disabled) $("#next").click(); });
const themeBtn = $("#theme");
const paintThemeBtn = () => { const t = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); themeBtn.textContent = t === "dark" ? "☀" : "☾"; };
themeBtn.onclick = () => { const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = next; try { localStorage.setItem("theme", next); } catch (e) {} paintThemeBtn(); render(); };
paintThemeBtn();
let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(render, 150); });
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", render);
render(); load();
