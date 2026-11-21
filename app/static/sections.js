/* Running, strength and insights sections. Expects DATA, helpers from charts.js, and $ from dashboard.js. */
const zoneColors = () => ["--muted", "--light", "--blue", "--teal", "--orange", "--red"].map(css);
const zones = z => { const t = z.reduce((a, b) => a + b, 0) || 1, zc = zoneColors();
  return `<div class="zones"><div class="zbar">${z.map((m, i) => `<span style="width:${m / t * 100}%;background:${zc[i]}"></span>`).join("")}</div>
    <div class="zlist">${z.map((m, i) => m ? `<span><i style="background:${zc[i]}"></i>Z${i} ${m}m</span>` : "").join("")}</div></div>`; };
const mini = (lbl, val, sub = "") => `<div class="mini"><div class="lbl">${lbl}</div><div class="val">${val}</div><div class="cmp">${sub}</div></div>`;
const goalTxt = (n, g) => `<span class="${n >= g ? "up" : ""}">${n}</span><small>/${g}</small>`;

function renderRunning(weeks, cur, prev) {
  const runs = DATA.workouts.filter(w => w.cat === "run"), recent = runs.slice(0, 10), last = runs[0];
  const vo2 = DATA.vo2max.length ? DATA.vo2max[DATA.vo2max.length - 1] : null;
  const paced = runs.filter(r => r.pace).slice(0, 4);
  const longest = runs.filter(r => r.km).slice(0, 30).sort((a, b) => b.km - a.km)[0];
  $("#runTiles").innerHTML =
    mini("This week", `${fmt(cur.run_km, 1)}<small> / ${DATA.goals.run_km} km</small>`, prev ? `last week ${fmt(prev.run_km, 1)} km` : "") +
    mini("Runs this week", goalTxt(cur.runs, DATA.goals.runs), prev ? `last week ${prev.runs}` : "") +
    mini("Avg pace, last 4", `${paced.length ? paceFmt(avg(paced.map(r => r.pace))) : "–"}<small> /km</small>`, last ? `last run ${last.pace_str || "–"} /km` : "") +
    mini("Longest recent run", longest ? `${fmt(longest.km, 1)}<small> km</small>` : "–", longest ? `${dayLabel(longest.d)} · ${longest.pace_str || "–"} /km` : "") +
    mini("VO2 max", vo2 ? `${fmt(vo2.v, 1)}<small> ml/kg/min</small>` : "–", vo2 ? `entered ${dayLabel(vo2.d)}` : "from the WHOOP app");
  const prs = DATA.prs || [], prHost = $("#prTiles");
  if (!DATA.strava_enabled) prHost.innerHTML = "";
  else if (!DATA.strava_connected) prHost.innerHTML = `<div class="connect"><span>Connect Strava for per-km splits, elevation and personal bests.</span><a class="btn" href="/auth/strava">Connect Strava</a></div>`;
  else prHost.innerHTML = `<h3>${icon("sparkle", 12)}Personal bests (Strava)</h3><div class="minis">` +
    (prs.length ? prs.map(p => mini(p.name, `${p.time}<small> ${p.pace_str ? p.pace_str + " /km" : ""}</small>`, p.d ? dayLabel(p.d) : "")).join("") : mini("No best efforts yet", "–", "appear after the first Strava sync")) + `</div>`;
  const L = weeks.map(w => w.w);
  groupChart($("#cRunKm"), L, { groups: [{ segments: [{ values: weeks.map(w => w.run_km), color: css("--blue") }] }], goal: DATA.goals.run_km,
    topLabel: v => fmt(v, 1), tip: i => `Week of <b>${weekLabel(L[i])}</b><br>${fmt(weeks[i].run_km, 1)} km · ${weeks[i].runs} runs · longest ${fmt(weeks[i].longest_run_km, 1)} km` });
  const pr = runs.filter(r => r.pace && r.km >= 1).slice(0, 20).reverse();
  tsChart($("#cPace"), pr.map(r => r.d), { lines: [{ values: pr.map(r => r.pace), color: css("--teal"), dots: true, area: true }], yFmt: paceFmt, labelEvery: 1, topLabel: i => paceFmt(pr[i].pace),
    tip: i => `<b>${paceFmt(pr[i].pace)} /km</b> · ${fmt(pr[i].km, 1)} km · ${pr[i].min} min · HR ${fmt(pr[i].avg_hr)}` });
  const sv = DATA.strava_connected;
  $("#runTable").innerHTML = `<tr><th>Date</th><th>Distance</th><th>Duration</th><th>Pace</th>${sv ? "<th>Elev</th><th>Cadence</th>" : ""}<th>Strain</th><th>Avg / max HR</th><th>kcal</th><th>HR zones (min)</th></tr>` +
    (recent.length ? recent.map((r, i) => { const st = r.strava, has = st && st.splits.length;
      return `<tr class="${has ? "exp" : ""}" data-i="${i}" title="${has ? "Click for per-km splits" : ""}"><td>${has ? "<span class=\"caret\">▸</span>" : ""}${dayLabel(r.d)} ${r.t}</td><td>${r.km ? fmt(r.km, 2) + " km" : "–"}</td><td>${fmt(r.min)} min</td><td>${r.pace_str ? r.pace_str + " /km" : "–"}</td>${sv ? `<td>${st && st.elev_m != null ? st.elev_m + " m" : "–"}</td><td>${st && st.cadence ? st.cadence + " spm" : "–"}</td>` : ""}<td>${fmt(r.strain, 1)}</td><td>${fmt(r.avg_hr)} / ${fmt(r.max_hr)}</td><td>${fmt(r.kcal)}</td><td>${zones(r.zones)}</td></tr>` +
        (has ? `<tr class="splits" hidden><td colspan="${sv ? 10 : 8}">${splitsBlock(st)}</td></tr>` : ""); }).join("")
      : `<tr><td colspan="${sv ? 10 : 8}" class="sub">No runs yet.</td></tr>`);
  $("#runTable").querySelectorAll("tr.exp").forEach(tr => tr.onclick = () => { const d = tr.nextElementSibling; d.hidden = !d.hidden; tr.querySelector(".caret").textContent = d.hidden ? "▸" : "▾"; });
  const um = DATA.unmatched_runs || [];
  $("#unmatched").innerHTML = sv && um.length ? `<div class="note" style="margin-top:8px">${um.length} Strava run${um.length > 1 ? "s" : ""} without a WHOOP record (e.g. ${um.slice(0, 3).map(u => `${dayLabel(u.d)} ${fmt(u.km, 1)} km`).join(", ")}) — shown in Claude via get_run_detail, not counted above.</div>` : "";
}

/* Per-km splits as a mini bar chart of pace + a compact table. Faster km = taller bar. */
function splitsBlock(st) {
  const sp = st.splits, paces = sp.map(x => x.pace).filter(Boolean), slow = Math.max(...paces), fast = Math.min(...paces);
  const bars = sp.map(x => { const h = x.pace ? 18 + (slow - x.pace) / ((slow - fast) || 1) * 42 : 4;
    return `<div class="sp"><div class="spv">${x.pace_str || "–"}</div><div class="spb" style="height:${h}px" title="km ${x.km}: ${x.pace_str} /km, HR ${x.hr || "–"}, ${x.elev > 0 ? "+" : ""}${x.elev ?? 0} m"></div><div class="spk">${x.km}</div></div>`; }).join("");
  const eff = st.efforts.filter(e => e.name !== "400m" && e.name !== "1/2 mile").map(e => `<span class="eff${e.pr_rank === 1 ? " pr" : ""}">${e.name} <b>${e.time}</b>${e.pr_rank === 1 ? " PR" : e.pr_rank ? ` #${e.pr_rank}` : ""}</span>`).join("");
  return `<div class="splitwrap"><div class="splitmeta">${st.name ? `<b>${st.name}</b> · ` : ""}${st.moving_min} min moving · ${st.elev_m ?? 0} m elevation${st.cadence ? ` · ${st.cadence} spm` : ""}</div>
    <div class="spchart">${bars}</div>
    <table class="sptable"><tr><th>km</th>${sp.map(x => `<td>${x.km}</td>`).join("")}</tr><tr><th>pace</th>${sp.map(x => `<td>${x.pace_str || "–"}</td>`).join("")}</tr><tr><th>HR</th>${sp.map(x => `<td>${x.hr || "–"}</td>`).join("")}</tr><tr><th>elev</th>${sp.map(x => `<td>${x.elev == null ? "–" : (x.elev > 0 ? "+" : "") + x.elev}</td>`).join("")}</tr></table>
    ${eff ? `<div class="effs">Best efforts in this run: ${eff}</div>` : ""}</div>`;
}

function renderStrength(cur, prev) {
  const sess = DATA.workouts.filter(w => w.cat === "strength"), recent = sess.slice(0, 10);
  const last4 = sess.slice(0, 4);
  $("#strTiles").innerHTML =
    mini("Sessions this week", goalTxt(cur.strength, DATA.goals.strength), prev ? `last week ${prev.strength}` : "") +
    mini("Hours this week", hm(cur.strength_h), prev ? `last week ${hm(prev.strength_h)}` : "") +
    mini("Avg session, last 4", last4.length ? `${fmt(avg(last4.map(s => s.min)))}<small> min</small>` : "–", last4.length ? `strain ${fmt(avg(last4.map(s => s.strain)), 1)} · ${fmt(avg(last4.map(s => s.kcal)))} kcal` : "") +
    mini("Last session", sess[0] ? dayLabel(sess[0].d) : "–", sess[0] ? `${sess[0].min} min · strain ${fmt(sess[0].strain, 1)}` : "");
  $("#strTable").innerHTML = `<tr><th>Date</th><th>Activity</th><th>Duration</th><th>Strain</th><th>Avg / max HR</th><th>kcal</th><th>HR zones (min)</th></tr>` +
    (recent.length ? recent.map(s => `<tr><td>${dayLabel(s.d)} ${s.t}</td><td style="text-transform:capitalize">${s.sport}</td><td>${fmt(s.min)} min</td><td>${fmt(s.strain, 1)}</td><td>${fmt(s.avg_hr)} / ${fmt(s.max_hr)}</td><td>${fmt(s.kcal)}</td><td>${zones(s.zones)}</td></tr>`).join("")
      : `<tr><td colspan="7" class="sub">No strength sessions yet. Sessions logged as ${["weightlifting", "strength trainer"].join(", ")} etc. appear here.</td></tr>`);
}

function renderInsights(days, weeks, cur, prev) {
  const ins = [], g = DATA.goals, last7 = days.slice(-7), prev7 = days.slice(-14, -7);
  const pct = (a, b) => a != null && b ? (a - b) / b * 100 : null;
  // Sleep
  const sl = avg(last7.map(d => d.sleep)), nd = avg(last7.map(d => d.need)), bed = avg(last7.map(d => d.in_bed)), awake = avg(last7.map(d => d.awake)), nap = avg(last7.map(d => d.nap));
  if (sl != null) {
    let s = `Last 7 nights you slept <b>${hm(sl)}</b> per night${nap ? ` (incl. ${Math.round(nap * 60)} min of naps)` : ""}`;
    if (nd != null) s += sl >= nd ? `, meeting your ${hm(nd)} need.` : `, <b>${Math.round((nd - sl) * 60)} min short</b> of your ${hm(nd)} need.`;
    ins.push(s);
    if (bed != null && awake != null) ins.push(`You spent <b>${hm(bed)}</b> in bed, of which <b>${Math.round(awake * 60)} min</b> awake (${fmt(sl / bed * 100)}% efficiency).`);
  }
  const d7 = pct(sl, avg(prev7.map(d => d.sleep)));
  if (d7 != null && Math.abs(d7) >= 5) ins.push(`That's <b>${Math.abs(d7).toFixed(0)}% ${d7 > 0 ? "more" : "less"}</b> sleep than the week before.`);
  // Training vs goals
  if (cur) {
    const need = n => n > 0 ? `<b>${n} more</b> to hit ${g.runs}` : "goal met";
    ins.push(`This week: <b>${cur.runs}/${g.runs}</b> runs (${need(g.runs - cur.runs)}), <b>${cur.strength}/${g.strength}</b> strength sessions${cur.strength >= g.strength ? " — goal met" : ` (${g.strength - cur.strength} more to go)`}.`);
    ins.push(`<b>${fmt(cur.run_km, 1)} km</b> run of your ${g.run_km} km target${cur.run_km < g.run_km ? ` — ${fmt(g.run_km - cur.run_km, 1)} km to go` : " — done"}; <b>${hm(cur.strength_h)}</b> of strength work; <b>${hm(cur.hours)}</b> exercised in total (walking excluded).`);
    if (prev) { const dh = cur.hours - prev.hours; ins.push(`Compared with last week: ${dh >= 0 ? "▲" : "▼"} ${hm(Math.abs(dh))} exercise, ${cur.run_km - prev.run_km >= 0 ? "▲" : "▼"} ${fmt(Math.abs(cur.run_km - prev.run_km), 1)} km running, ${cur.strength - prev.strength >= 0 ? "▲" : "▼"} ${Math.abs(cur.strength - prev.strength)} strength sessions.`); }
  }
  const done = weeks.slice(-5, -1).filter(w => w.nights || w.sessions);
  if (done.length >= 2) { const hit = done.filter(w => w.runs >= g.runs && w.strength >= g.strength).length;
    ins.push(`You hit both session goals in <b>${hit} of the last ${done.length}</b> full weeks; average ${fmt(avg(done.map(w => w.run_km)), 1)} km and ${fmt(avg(done.map(w => w.sessions)), 1)} sessions a week.`); }
  const runs = DATA.workouts.filter(w => w.cat === "run" && w.pace && w.km >= 3), r4 = runs.slice(0, 4), r8 = runs.slice(4, 12);
  if (r4.length >= 3 && r8.length >= 3) { const a = avg(r4.map(r => r.pace)), b = avg(r8.map(r => r.pace)), diff = (b - a) * 60;
    ins.push(`Your last 4 runs averaged <b>${paceFmt(a)} /km</b>, ${Math.abs(diff).toFixed(0)}s per km ${diff > 0 ? "faster" : "slower"} than the 8 before.`); }
  $("#ins").innerHTML = ins.map(s => `<li>${s}</li>`).join("") || "<li>Not enough data yet.</li>";
}
