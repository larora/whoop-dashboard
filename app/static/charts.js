/* Small inline-SVG chart helpers shared by the dashboard. No dependencies. */
const NS = "http://www.w3.org/2000/svg";
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const avg = a => { const v = a.filter(x => x != null); return v.length ? v.reduce((p, c) => p + c, 0) / v.length : null; };
const fmt = (x, d = 0) => x == null ? "–" : Number(x).toFixed(d);
const paceFmt = p => { if (!p) return "–"; const m = Math.floor(p), s = Math.round((p - m) * 60); return `${m}:${String(s).padStart(2, "0")}`; };
const hm = h => h == null ? "–" : `${Math.floor(h)}h ${String(Math.round((h - Math.floor(h)) * 60)).padStart(2, "0")}m`;
const recColor = v => v == null ? css("--grid") : v >= 67 ? css("--green") : v >= 34 ? css("--yellow") : css("--red");
const dayLabel = d => new Date(d + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
const dowLabel = d => new Date(d + "T12:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
const weekLabel = w => dayLabel(w);
const rolling = (arr, n) => arr.map((_, i) => { const w = arr.slice(Math.max(0, i - n + 1), i + 1); return w.filter(x => x != null).length >= Math.min(3, n) ? avg(w) : null; });

function el(tag, attrs = {}, parent) { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }

/* Vertical gradient per colour so bars have a little depth; ids are reused within one SVG. */
let gradSeq = 0;
function gradient(svg, color) {
  svg._grads ||= {}; if (svg._grads[color]) return svg._grads[color];
  const id = `g${++gradSeq}`, defs = svg._defs ||= el("defs", {}, svg);
  const g = el("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
  el("stop", { offset: "0%", "stop-color": color, "stop-opacity": 1 }, g);
  el("stop", { offset: "100%", "stop-color": color, "stop-opacity": .72 }, g);
  return svg._grads[color] = `url(#${id})`;
}

function attachTip(host, svg, W, n, xAt, pad, ih, tip) {
  const tipEl = document.createElement("div"); tipEl.className = "tip"; host.appendChild(tipEl);
  const cursor = el("line", { y1: pad.t, y2: pad.t + ih, stroke: css("--muted"), "stroke-dasharray": "3 3", opacity: 0 }, svg);
  svg.addEventListener("mousemove", e => {
    const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * W / r.width;
    const iw = W - pad.l - pad.r, i = Math.min(n - 1, Math.max(0, Math.floor((px - pad.l) / iw * n)));
    cursor.setAttribute("x1", xAt(i)); cursor.setAttribute("x2", xAt(i)); cursor.setAttribute("opacity", 1);
    tipEl.innerHTML = tip(i); tipEl.style.opacity = 1;
    const tx = xAt(i) * r.width / W; tipEl.style.left = Math.min(r.width - tipEl.offsetWidth, Math.max(0, tx - tipEl.offsetWidth / 2)) + "px"; tipEl.style.top = "-6px";
  });
  svg.addEventListener("mouseleave", () => { tipEl.style.opacity = 0; cursor.setAttribute("opacity", 0); });
}

function axes(svg, W, H, pad, lo, hi, yFmt) {
  const ih = H - pad.t - pad.b, y = v => pad.t + ih - (v - lo) / ((hi - lo) || 1) * ih;
  for (let k = 0; k <= 4; k++) {
    const v = lo + (hi - lo) * k / 4;
    el("line", { x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), stroke: css("--grid"), "stroke-dasharray": k ? "" : "", }, svg);
    el("text", { x: pad.l - 8, y: y(v) + 4, "text-anchor": "end", "font-size": 10, fill: css("--muted") }, svg).textContent = yFmt ? yFmt(v) : +v.toFixed(hi - lo < 10 ? 1 : 0);
  }
  return y;
}

function xLabels(svg, labels, x, H, iw, labelFn, labelEvery) {
  const n = labels.length, step = labelEvery || Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 70))));
  labels.forEach((d, i) => { if (i % step === 0) el("text", { x: x(i), y: H - 6, "text-anchor": "middle", "font-size": 10, fill: css("--muted") }, svg).textContent = labelFn(d); });
}

function drawLine(svg, l, x, y, iw, baseY, dots) {
  let d = "", pen = false, first = null, last = null;
  l.values.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); pen = true; first ??= i; last = i; });
  if (l.area && first != null) el("path", { d: d + `L${x(last)},${baseY}L${x(first)},${baseY}Z`, fill: l.color, opacity: .12 }, svg);
  el("path", { d, fill: "none", stroke: l.color, "stroke-width": l.width || 2, "stroke-dasharray": l.dash || "", "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
  if (dots || l.dots) l.values.forEach((v, i) => v != null && el("circle", { cx: x(i), cy: y(v), r: 3.5, fill: css("--card"), stroke: l.color, "stroke-width": 2 }, svg));
}

/* Daily time series: optional stacked bars + lines. `topLabel(i)` prints a value above each bar. */
function tsChart(host, labels, { bars = [], lines = [], yMin, yMax, barColor, tip, yFmt, labelFn = dayLabel, labelEvery, topLabel }) {
  host.innerHTML = ""; const W = host.clientWidth || 600, H = host.clientHeight || 220, pad = { l: 38, r: 8, t: topLabel ? 18 : 8, b: 22 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b, n = labels.length, svg = el("svg", { viewBox: `0 0 ${W} ${H}` }, host);
  if (!n) return;
  const stackTop = labels.map((_, i) => bars.reduce((s, b) => s + (b.values[i] || 0), 0));
  const vals = [...(bars.length ? stackTop : []), ...lines.flatMap(l => l.values)].filter(v => v != null);
  const lo = yMin ?? Math.floor(Math.min(...vals) * 0.95), hi = yMax ?? Math.ceil(Math.max(...vals) * 1.05 || 1);
  const y = axes(svg, W, H, pad, lo, hi, yFmt), x = i => pad.l + (i + 0.5) * iw / n;
  xLabels(svg, labels, x, H, iw, labelFn, labelEvery);
  const bw = Math.max(1, Math.min(iw / n * 0.72, 56));
  labels.forEach((_, i) => { let base = lo; bars.forEach(b => { const v = b.values[i]; if (v == null) return;
    const c = barColor ? barColor(v, i) : b.color;
    el("rect", { x: x(i) - bw / 2, y: y(base + v), width: bw, height: Math.max(0, y(base) - y(base + v)), rx: Math.min(4, bw / 3), fill: gradient(svg, c) }, svg); base += v; });
    if (topLabel && stackTop[i]) el("text", { x: x(i), y: y(stackTop[i]) - 5, "text-anchor": "middle", "font-size": 10, "font-weight": 600, fill: css("--ink") }, svg).textContent = topLabel(i); });
  lines.forEach(l => drawLine(svg, l, x, y, iw, pad.t + ih));
  if (topLabel && !bars.length && lines[0]) lines[0].values.forEach((v, i) => v != null &&  // label points when there are no bars
    (el("text", { x: x(i), y: y(v) - 8, "text-anchor": "middle", "font-size": 10, "font-weight": 600, fill: css("--ink") }, svg).textContent = topLabel(i)));
  if (tip) attachTip(host, svg, W, n, x, pad, ih, tip);
}

/* Grouped bars: each group is one bar per label, each bar a stack of segments. Labels inside segments when they fit. */
function groupChart(host, labels, { groups, goal, lines = [], yMin = 0, yMax, tip, yFmt, labelFn = weekLabel, labelEvery, topLabel, segLabel }) {
  host.innerHTML = ""; const W = host.clientWidth || 600, H = host.clientHeight || 220, pad = { l: 38, r: 8, t: 18, b: 22 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b, n = labels.length, svg = el("svg", { viewBox: `0 0 ${W} ${H}` }, host);
  if (!n) return;
  const tops = labels.flatMap((_, i) => groups.map(g => g.segments.reduce((s, sg) => s + (sg.values[i] || 0), 0)));
  const hi = yMax ?? Math.ceil(Math.max(...tops, goal || 0, ...lines.flatMap(l => l.values).filter(v => v != null)) * 1.12 || 1), lo = yMin;
  const y = axes(svg, W, H, pad, lo, hi, yFmt), slot = iw / n, x = i => pad.l + (i + 0.5) * slot;
  const gw = Math.min(slot * 0.78 / groups.length, 64), bw = Math.max(1, gw * 0.88), total = gw * groups.length;
  xLabels(svg, labels, x, H, iw, labelFn, labelEvery);
  labels.forEach((_, i) => groups.forEach((g, gi) => { let base = lo; const bx = x(i) - total / 2 + gi * gw + (gw - bw) / 2, top = g.segments.reduce((s, sg) => s + (sg.values[i] || 0), 0);
    g.segments.forEach((sg, si) => { const v = sg.values[i]; if (!v) return; const h = Math.max(0, y(base) - y(base + v));
      el("rect", { x: bx, y: y(base + v), width: bw, height: h, rx: 3, fill: gradient(svg, sg.color), stroke: css("--card"), "stroke-width": 1 }, svg);
      if (segLabel && h >= 14 && bw >= 34) el("text", { x: bx + bw / 2, y: y(base + v) + h / 2 + 3.5, "text-anchor": "middle", "font-size": 10, "font-weight": 600, fill: sg.dark ? "#fff" : css("--ink"), opacity: .9 }, svg).textContent = segLabel(v, si, gi, i);
      base += v; });
    if (topLabel && top) el("text", { x: bx + bw / 2, y: y(top) - 5, "text-anchor": "middle", "font-size": 10, "font-weight": 600, fill: css("--ink") }, svg).textContent = topLabel(top, gi, i); }));
  lines.forEach(l => drawLine(svg, l, x, y, iw, pad.t + ih));
  if (goal) { el("line", { x1: pad.l, x2: W - pad.r, y1: y(goal), y2: y(goal), stroke: css("--ink"), "stroke-width": 1.5, "stroke-dasharray": "5 4" }, svg);
    el("text", { x: W - pad.r, y: y(goal) - 4, "text-anchor": "end", "font-size": 10, fill: css("--ink") }, svg).textContent = "goal"; }
  if (tip) attachTip(host, svg, W, n, x, pad, ih, tip);
}
