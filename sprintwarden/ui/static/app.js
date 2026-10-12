// sprintwarden dashboard. Vanilla JS, no build step, no network beyond this server.
// All user data is inserted with textContent (never innerHTML).
"use strict";

const app = document.getElementById("app");
const crumbs = document.getElementById("crumbs");
const updated = document.getElementById("updated");
const auto = document.getElementById("autorefresh");
const SYM = { pass: "✓", fail: "✗", stale: "⏱", none: "–", error: "!", bypassed: "⚠" };
const LABEL = { pass: "PASS", fail: "FAIL", stale: "STALE", none: "NO RUNS", error: "ERROR", bypassed: "BYPASSED" };
const AC_SYM = { satisfied: "✓ done", failing: "✗ failing", "no-tests": "∅ no tests" };
let timer = null;
let rendering = false;

// ---------------------------------------------------------------- helpers

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const svgNS = "http://www.w3.org/2000/svg";
function s(tag, attrs, ...children) {
  const el = document.createElementNS(svgNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "text") el.textContent = v;
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c) el.append(c);
  return el;
}

async function api(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function rel(iso) {
  if (!iso) return "never";
  const secs = (Date.now() - Date.parse(iso)) / 1000;
  if (!isFinite(secs)) return iso;
  if (secs < 60) return "just now";
  const units = [["d", 86400], ["h", 3600], ["min", 60]];
  for (const [u, n] of units) if (secs >= n) return `${Math.floor(secs / n)} ${u} ago`;
  return iso;
}

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}

function stamp(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return iso || "";
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function short(sha) { return sha ? sha.slice(0, 7) : ""; }

function pill(status, text) {
  return h("span", { class: `pill ${status}`, title: LABEL[status] || status },
    `${SYM[status] || "?"} ${text || LABEL[status] || status}`);
}

function sprintKey(k) {
  if (k === "legacy") return -1;
  const m = /^S(\d+)$/i.exec(k);
  return m ? parseInt(m[1], 10) : 1e9;
}

// CSP forbids style attributes; CSSOM properties set from script are allowed.
function barFill(pct) {
  const el = h("span");
  el.style.width = `${pct}%`;
  return el;
}

function plural(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }

// Minimal inline markdown for sprint notes: `code`, **bold**, *em*, [text](http...).
function inlineMd(text) {
  const out = [];
  const rx = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
  let last = 0;
  let m;
  while ((m = rx.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (m[1]) out.push(h("code", { text: t.slice(1, -1) }));
    else if (m[2]) out.push(h("strong", { text: t.slice(2, -2) }));
    else if (m[3]) out.push(h("em", { text: t.slice(1, -1) }));
    else out.push(h("a", { href: m[5], rel: "noopener noreferrer", target: "_blank", text: t.slice(1, t.indexOf("]")) }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function setCrumbs(...items) {
  crumbs.replaceChildren(...items.flatMap((it, i) => [i ? " / " : "", it]));
}

// ---------------------------------------------------------------- portfolio

async function renderPortfolio() {
  const data = await api("/api/projects");
  setCrumbs();
  const projects = data.projects;
  if (!projects.length) {
    return [h("div", { class: "empty-state" },
      h("p", { text: "No projects registered yet." }),
      h("p", {}, "Run ", h("code", { text: "sprint init --ratchet-only" }), " or ", h("code", { text: "sprint register" }), " in a repo."))];
  }
  const counts = {};
  for (const p of projects) counts[p.status] = (counts[p.status] || 0) + 1;
  const summary = Object.entries(counts).map(([k, v]) => `${v} ${(LABEL[k] || k).toLowerCase()}`).join(" · ");
  return [
    h("h1", { text: "Portfolio" }),
    h("p", { class: "muted" }, `${plural(projects.length, "project")} · ${summary}`),
    h("div", { class: "grid", role: "list" }, projects.map(card)),
  ];
}

function card(p) {
  if (p.status === "error") {
    return h("div", { class: "card error", role: "listitem" },
      h("div", { class: "card-head" }, h("h3", { text: p.name }), pill("error")),
      h("div", { class: "line err", text: p.error }),
      h("div", { class: "line muted mono", text: p.path }));
  }
  const l = p.latest;
  const c = (l && l.counts) || {};
  const t = (l && l.totals) || {};
  const bits = [];
  if (t.total !== undefined) bits.push(plural(t.total, "test"));
  if (c.regressions) bits.push(plural(c.regressions, "regression"));
  if (c.failing && c.failing !== c.regressions) bits.push(`${c.failing} failing`);
  if (c.missing) bits.push(`${c.missing} missing`);
  if (c.new_skips) bits.push(plural(c.new_skips, "new skip"));
  const acPct = p.acs.total ? Math.round((100 * p.acs.satisfied) / p.acs.total) : 0;
  return h("a", { class: `card ${p.status}`, href: `#/p/${encodeURIComponent(p.key)}`, role: "listitem" },
    h("div", { class: "card-head" },
      h("h3", { text: p.name }),
      h("span", { class: "badge", text: p.project_key }),
      pill(p.status)),
    h("div", { class: "line muted" },
      h("span", { class: "badge", text: p.stack }), " ", p.mode, p.branch ? ` · ${p.branch}` : ""),
    p.sprint
      ? [h("div", { class: "line" }, h("strong", { text: p.sprint.id }), ` ${p.sprint.title}`),
        h("div", { class: "bar", role: "img", "aria-label": `${p.acs.satisfied} of ${p.acs.total} acceptance criteria satisfied` },
          barFill(acPct)),
        h("div", { class: "line muted", text: `${p.acs.satisfied}/${p.acs.total} ACs satisfied` })]
      : p.mode === "sprints" ? h("div", { class: "line muted", text: "no active sprint" }) : null,
    h("div", { class: "line", text: bits.join(" · ") || "no gate runs yet" }),
    l ? h("div", { class: "line muted" },
      `last run ${rel(l.timestamp)} · ${l.agent || "?"} · ${short(l.head)}`,
      p.stale ? h("span", { class: "c-warn", text: ` · stale: ${p.stale}` }) : "") : null);
}

// ---------------------------------------------------------------- project

const TABS = [["timeline", "Sprints"], ["matrix", "Regression matrix"], ["trends", "Trends"], ["runs", "Runs"]];

async function renderProject(key, tab) {
  const [d, r] = await Promise.all([api(`/api/projects/${encodeURIComponent(key)}`),
    api(`/api/projects/${encodeURIComponent(key)}/runs?limit=60`)]);
  const runs = r.runs;
  if (!tab) tab = d.mode === "sprints" ? "timeline" : "matrix";
  setCrumbs(h("a", { href: "#/", text: "Portfolio" }), h("span", { text: d.name }));
  const head = [
    h("div", { class: "card-head" }, h("h1", { text: d.name, title: d.path }), h("span", { class: "badge", text: d.project_key }), pill(d.status)),
    h("div", { class: "meta" },
      h("span", {}, h("span", { class: "badge", text: d.stack }), ` ${d.mode}`),
      d.branch ? h("span", { text: `branch ${d.branch}` }) : null,
      d.baseline ? h("span", { text: `baseline ${d.baseline.total} tests (${(d.baseline.created || "").slice(0, 10)}, ${d.baseline.reason})` }) : h("span", { text: "no baseline" }),
      d.removals.length ? h("span", { text: plural(d.removals.length, "accepted removal") }) : null,
      d.skips.length ? h("span", { text: plural(d.skips.length, "allowed skip") }) : null),
    d.stale ? h("p", { class: "c-warn", text: `⏱ The latest run is stale: ${d.stale}.` }) : null,
    h("nav", { class: "tabs", "aria-label": "Views" }, TABS.filter(([id]) => id !== "timeline" || d.mode === "sprints").map(([id, label]) =>
      h("a", { href: `#/p/${encodeURIComponent(key)}/${id}`, "aria-current": id === tab ? "page" : null, text: label }))),
  ];
  const views = { timeline: () => timeline(d), matrix: () => matrix(key, runs), trends: () => trends(runs), runs: () => runsTable(key, runs) };
  return [...head, ...(views[tab] || views.matrix)()];
}

function timeline(d) {
  if (!d.sprints.length) return [h("p", { class: "muted", text: "No sprint files in .sprint/sprints/." })];
  return d.sprints.map((sp) => {
    const done = sp.acs.filter((a) => a.result.state === "satisfied").length;
    return h("section", { class: `sprint ${sp.status}`, "aria-label": `Sprint ${sp.id}` },
      h("div", { class: "sprint-head" },
        h("h3", {}, `${sp.id} · ${sp.title}`),
        h("span", { class: `pill ${sp.status === "active" ? "stale" : sp.status === "closed" ? "pass" : "none"}`,
          text: sp.status === "active" ? "● active" : sp.status === "closed" ? "✓ closed" : "○ planned" }),
        h("span", { class: "muted", text: [sp.started && `started ${sp.started}`, sp.closed && `closed ${sp.closed}`].filter(Boolean).join(" · ") }),
        sp.acs.length ? h("span", { class: "muted", text: `${done}/${sp.acs.length} ACs` }) : null),
      sp.goal ? h("p", { class: "goal", text: sp.goal }) : null,
      h("ul", { class: "acs" }, sp.acs.map((a) => h("li", {},
        h("span", { class: `st st-${a.result.state}`, text: AC_SYM[a.result.state] || a.result.state }),
        h("span", {}, h("strong", { text: a.id }), ` ${a.desc}`, " ", h("code", { class: "muted", text: a.tests.join(", ") || "(no tests listed)" })),
      ))),
      sp.acs.some((a) => a.result.tests && a.result.tests.length) ? h("div", { class: "tests" },
        sp.acs.flatMap((a) => (a.result.tests || []).slice(0, 8).map((t) => h("span", { title: t.id },
          `${t.outcome === "passed" ? "✓" : t.outcome === "skipped" ? "⊘" : "✗"} ${t.id.split(".").pop()}`)))) : null,
      sp.out_of_scope && sp.out_of_scope.length ? h("p", { class: "muted", text: `Out of scope: ${sp.out_of_scope.join(", ")}` }) : null,
      sp.notes.length ? h("ul", { class: "notes" }, sp.notes.map((n) => h("li", {}, inlineMd(n)))) : null);
  });
}

function matrix(key, runs) {
  const cols = runs.slice(0, 30).reverse();
  if (!cols.length) return [h("p", { class: "muted", text: "No gate runs yet." })];
  const rows = [...new Set(cols.flatMap((r) => Object.keys(r.by_sprint || {})))].sort((a, b) => sprintKey(a) - sprintKey(b));
  const resultRow = h("tr", {}, h("th", { class: "row", text: "gate" }), cols.map((r) => {
    const st = r.result === "pass" ? "ok" : r.result === "bypassed" ? "warn" : "bad";
    return h("td", {}, h("a", { href: `#/p/${encodeURIComponent(key)}/run/${r.id}`, class: `cell ${st}`,
      title: `${LABEL[r.result] || r.result} · ${when(r.timestamp)}`, text: SYM[r.result] || "?" }));
  }));
  const head = h("tr", {}, h("th", { class: "row", text: "run" }), cols.map((r) =>
    h("th", { class: "run", title: `${when(r.timestamp)} · ${r.agent} · ${r.trigger}` },
      h("a", { href: `#/p/${encodeURIComponent(key)}/run/${r.id}`, text: stamp(r.timestamp) }))));
  const body = rows.map((sp) => h("tr", {}, h("th", { class: "row", text: sp }), cols.map((r) => {
    const b = (r.by_sprint || {})[sp];
    if (r.bypassed) return h("td", {}, h("span", { class: "cell warn", text: "⚠" }));
    if (!b) return h("td", {}, h("span", { class: "cell empty", text: "·" }));
    const failing = (r.failing || []).filter((f) => f.sprint === sp);
    const title = failing.length
      ? `${sp}: ${b.failed} failing\n` + failing.map((f) => `${f.regression ? "REGRESSION " : ""}${f.id}`).join("\n")
      : `${sp}: ${b.passed} passed${b.skipped ? `, ${b.skipped} skipped` : ""}`;
    if (b.failed) return h("td", {}, h("span", { class: "cell bad", title, text: `✗ ${b.failed}` }));
    if (b.skipped) return h("td", {}, h("span", { class: "cell warn", title, text: `✓${b.passed} ⊘${b.skipped}` }));
    return h("td", {}, h("span", { class: "cell ok", title, text: `✓ ${b.total}` }));
  })));
  return [
    h("p", { class: "muted", text: "Rows: test buckets by sprint. Columns: the last runs, oldest left. Hover a cell for its failing tests." }),
    h("div", { class: "matrix-wrap panel" }, h("table", { class: "matrix" }, h("thead", {}, head, resultRow), h("tbody", {}, body))),
  ];
}

function trends(runs) {
  const pts = runs.filter((r) => r.totals && r.totals.total !== undefined && !r.bypassed).slice(0, 60).reverse();
  if (pts.length < 2) return [h("p", { class: "muted", text: "Trends need at least two gate runs." })];
  const W = 960, H = 280, L = 52, R = 52, T = 18, B = 34;
  const iw = W - L - R, ih = H - T - B;
  const maxTotal = Math.max(...pts.map((p) => p.totals.total), 1);
  const x = (i) => L + (pts.length === 1 ? iw / 2 : (iw * i) / (pts.length - 1));
  const y1 = (v) => T + ih - (ih * v) / maxTotal;
  const rate = (p) => (p.totals.total ? (100 * p.totals.passed) / p.totals.total : 0);
  const y2 = (v) => T + ih - (ih * v) / 100;
  const svg = s("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Total tests and pass rate over runs" });
  for (let k = 0; k <= 4; k++) {
    const yy = T + (ih * k) / 4;
    svg.append(s("line", { class: "axis", x1: L, x2: W - R, y1: yy, y2: yy }));
    svg.append(s("text", { x: L - 6, y: yy + 4, "text-anchor": "end", text: Math.round(maxTotal * (1 - k / 4)) }));
    svg.append(s("text", { x: W - R + 6, y: yy + 4, text: `${100 - k * 25}%` }));
  }
  pts.forEach((p, i) => {
    if (p.milestone) {
      svg.append(s("line", { class: "ms", x1: x(i), x2: x(i), y1: T, y2: T + ih }));
      const right = x(i) > W - R - 90;
      svg.append(s("text", { class: "ms-label", x: right ? x(i) - 3 : x(i) + 3, y: T + 10,
        "text-anchor": right ? "end" : "start", text: `◆ ${p.milestone}` }));
    }
  });
  svg.append(s("polyline", { class: "l1", points: pts.map((p, i) => `${x(i)},${y1(p.totals.total)}`).join(" ") }));
  svg.append(s("polyline", { class: "l2", points: pts.map((p, i) => `${x(i)},${y2(rate(p))}`).join(" ") }));
  pts.forEach((p, i) => {
    const tip = `${when(p.timestamp)}\n${p.totals.total} tests, ${rate(p).toFixed(1)}% passing\n${LABEL[p.result] || p.result}${p.milestone ? ` · ${p.milestone}` : ""}`;
    svg.append(s("circle", { class: p.result === "pass" ? "p1" : "fail-dot", cx: x(i), cy: y1(p.totals.total), r: 3.5 }, s("title", { text: tip })));
    svg.append(s("rect", { class: "p2", x: x(i) - 2.5, y: y2(rate(p)) - 2.5, width: 5, height: 5 }, s("title", { text: tip })));
  });
  const first = pts[0], last = pts[pts.length - 1];
  svg.append(s("text", { x: L, y: H - 10, text: (first.timestamp || "").slice(0, 10) }));
  svg.append(s("text", { x: W - R, y: H - 10, "text-anchor": "end", text: (last.timestamp || "").slice(0, 10) }));
  return [
    h("div", { class: "panel" }, svg,
      h("div", { class: "legend" },
        h("span", {}, h("span", { class: "sw1" }), "total tests (left axis; ● pass, red ● fail)"),
        h("span", {}, h("span", { class: "sw2" }), "pass rate (right axis, ■)"),
        h("span", { class: "c-warn", text: "◆ baseline / sprint close" }))),
    h("p", { class: "muted", text: `${pts.length} runs · tests ${first.totals.total} → ${last.totals.total}` }),
  ];
}

function runsTable(key, runs) {
  if (!runs.length) return [h("p", { class: "muted", text: "No gate runs yet." })];
  return [h("div", { class: "panel" }, h("table", {},
    h("thead", {}, h("tr", {}, ["when", "result", "sprint", "tests", "failed", "regr.", "missing", "new skips", "agent", "trigger", "commit", ""].map((t, i) =>
      h("th", { class: i >= 3 && i <= 7 ? "num" : null, text: t })))),
    h("tbody", {}, runs.map((r) => {
      const t = r.totals || {}, c = r.counts || {};
      const go = () => { location.hash = `#/p/${encodeURIComponent(key)}/run/${r.id}`; };
      return h("tr", { class: "clickable", onclick: go, tabindex: "0", onkeydown: (e) => { if (e.key === "Enter") go(); } },
        h("td", { title: r.timestamp, text: when(r.timestamp) }),
        h("td", {}, pill(r.result === "pass" ? "pass" : r.result === "bypassed" ? "stale" : "fail", LABEL[r.result] || r.result)),
        h("td", { text: r.sprint || "–" }),
        h("td", { class: "num", text: t.total ?? "–" }),
        h("td", { class: "num", text: t.failed ?? "–" }),
        h("td", { class: "num", text: c.regressions ?? 0 }),
        h("td", { class: "num", text: c.missing ?? 0 }),
        h("td", { class: "num", text: c.new_skips ?? 0 }),
        h("td", { text: r.agent || "" }),
        h("td", { class: "muted", text: r.trigger || "" }),
        h("td", { class: "mono", text: short((r.git || {}).head) }),
        h("td", { class: "muted", text: r.milestone ? `◆ ${r.milestone}` : "" }));
    }))))];
}

// ---------------------------------------------------------------- run detail

async function renderRun(key, id) {
  const [d, r] = await Promise.all([api(`/api/projects/${encodeURIComponent(key)}`),
    api(`/api/projects/${encodeURIComponent(key)}/runs/${encodeURIComponent(id)}`)]);
  setCrumbs(h("a", { href: "#/", text: "Portfolio" }), h("a", { href: `#/p/${encodeURIComponent(key)}/runs`, text: d.name }), h("span", { class: "mono", text: id }));
  const g = r.git || {};
  const status = r.result === "pass" ? "pass" : r.result === "bypassed" ? "stale" : "fail";
  const out = [
    h("div", { class: "card-head" }, h("h1", { text: `Run ${when(r.timestamp)}` }), pill(status, LABEL[r.result] || r.result)),
    h("div", { class: "meta" },
      h("span", { text: `agent ${r.agent}` }), h("span", { text: `trigger ${r.trigger}` }),
      r.sprint ? h("span", { text: `sprint ${r.sprint}` }) : null,
      h("span", { text: `${r.duration_s}s` }),
      h("span", { class: "mono", text: `${short(g.head)}${g.branch ? ` (${g.branch})` : ""}${g.dirty ? " + uncommitted changes" : ""}` }),
      r.milestone ? h("span", { class: "c-warn", text: `◆ ${r.milestone}` }) : null,
      h("span", { class: "mono", text: r.id })),
  ];
  if (d.allure_url) out.push(h("p", {}, h("a", { href: d.allure_url, rel: "noopener noreferrer", target: "_blank", text: "Open in Allure ↗" }), h("span", { class: "muted", text: " for per-test history" })));
  if (r.bypassed) out.push(h("p", { class: "c-warn", text: `⚠ The gate was bypassed (${r.bypass_reason || "SPRINT_SKIP=1"}); no tests ran.` }));
  out.push(h("h2", { text: "Checks" }), h("div", { class: "panel" }, h("table", { class: "checks" }, h("tbody", {}, (r.checks || []).map((c) => {
    const cls = c.ok === null ? "c-none" : c.ok ? "c-ok" : c.blocking ? "c-bad" : "c-warn";
    const symb = c.ok === null ? "–" : c.ok ? "✓" : c.blocking ? "✗" : "!";
    return h("tr", {}, h("td", { class: cls, text: symb }), h("td", { text: c.id }),
      h("td", {}, c.summary, c.detail ? h("div", { class: "msg", text: c.detail }) : null),
      h("td", { class: "muted", text: c.blocking ? "" : "not blocking" }));
  })))));
  const section = (title, items, render) => items && items.length ? [h("h2", { text: `${title} (${items.length}${r.truncated && r.truncated[title.toLowerCase().replace(" ", "_")] ? "+" : ""})` }),
    h("div", { class: "panel" }, h("table", {}, h("tbody", {}, items.map(render))))] : [];
  out.push(...section("Failing", r.failing, (f) => h("tr", {},
    h("td", { class: "mono", text: f.sprint }),
    h("td", {}, h("span", { class: "mono", text: f.id }), f.regression ? h("span", { class: "tag-reg", text: ` ← REGRESSION ${f.regression_reason || ""}` }) : null,
      f.flaky ? h("span", { class: "badge", text: "flaky" }) : null,
      f.message ? h("div", { class: "msg", text: f.message }) : null))));
  out.push(...section("Missing", r.missing, (m) => h("tr", {}, h("td", { class: "mono", text: m.sprint }), h("td", { class: "mono", text: m.id }), h("td", { class: "muted", text: "in baseline, no longer exists" }))));
  out.push(...section("New skips", r.new_skips, (m) => h("tr", {}, h("td", { class: "mono", text: m.sprint }), h("td", { class: "mono", text: m.id }), h("td", { class: "muted", text: m.was === "new" ? "new test, skipped" : `was ${m.was}` }))));
  const by = r.by_sprint || {};
  const keys = Object.keys(by).sort((a, b) => sprintKey(a) - sprintKey(b));
  if (keys.length) {
    out.push(h("h2", { text: "Tests by sprint" }), h("div", { class: "panel" }, h("table", {},
      h("thead", {}, h("tr", {}, ["sprint", "total", "passed", "failed", "skipped"].map((t, i) => h("th", { class: i ? "num" : null, text: t })))),
      h("tbody", {}, keys.map((k) => h("tr", {}, h("td", { class: "mono", text: k }), ["total", "passed", "failed", "skipped"].map((f) =>
        h("td", { class: `num ${f === "failed" && by[k].failed ? "c-bad" : ""}`, text: by[k][f] }))))))));
  }
  if (r.runner && r.runner.length) {
    out.push(h("h2", { text: "Runner" }), h("div", { class: "panel" }, h("table", {}, h("tbody", {}, r.runner.map((x) =>
      h("tr", {}, h("td", { text: x.suite }), h("td", { class: "mono", text: x.command }), h("td", { class: "num", text: `exit ${x.exit_code}` }),
        h("td", { class: "num", text: `${x.duration_s}s` }), h("td", { class: "err", text: x.error || "" })))))));
  }
  return out;
}

// ---------------------------------------------------------------- router

function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "p" && parts[1]) {
    if (parts[2] === "run" && parts[3]) return () => renderRun(parts[1], parts[3]);
    return () => renderProject(parts[1], parts[2]);
  }
  return renderPortfolio;
}

async function render(focus) {
  if (rendering) return;
  rendering = true;
  const y = window.scrollY;
  try {
    const nodes = await route()();
    app.replaceChildren(...nodes.filter(Boolean));
    updated.textContent = `updated ${new Date().toLocaleTimeString()}`;
    if (focus) { app.focus({ preventScroll: true }); window.scrollTo(0, 0); } else window.scrollTo(0, y);
  } catch (err) {
    app.replaceChildren(h("div", { class: "empty-state err" }, `Couldn't load: ${err.message}`), h("p", {}, h("a", { href: "#/", text: "← back to portfolio" })));
  } finally {
    rendering = false;
  }
}

function setTimer() {
  if (timer) clearInterval(timer);
  timer = auto.checked ? setInterval(() => render(false), 15000) : null;
}

try {
  const saved = localStorage.getItem("sprintwarden.autorefresh");
  if (saved !== null) auto.checked = saved === "1";
} catch (_) { /* storage may be unavailable */ }
auto.addEventListener("change", () => {
  try { localStorage.setItem("sprintwarden.autorefresh", auto.checked ? "1" : "0"); } catch (_) { /* ignore */ }
  setTimer();
});
window.addEventListener("hashchange", () => render(true));
setTimer();
render(true);
api("/api/version").then((v) => { document.getElementById("version").textContent = `v${v.version}`; }).catch(() => {});
