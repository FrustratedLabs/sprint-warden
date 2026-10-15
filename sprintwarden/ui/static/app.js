// sprintwarden dashboard. Vanilla JS, no build step, no network beyond this server.
// All user data is inserted with textContent (never innerHTML). Every icon and status
// mark comes from icons.js (vendored Lucide data) and is built with createElementNS.
"use strict";

const app = document.getElementById("app");
const updated = document.getElementById("updated");
const auto = document.getElementById("autorefresh");
const LABEL = { pass: "PASS", fail: "FAIL", stale: "STALE", none: "NO RUNS", error: "ERROR", bypassed: "BYPASSED" };
// Status marks are Lucide icons. Each sits next to a word that says the same thing
// (or carries it as its aria-label), so colour is never the only cue (spec §11).
const MARK = {
  pass: "check", fail: "x", stale: "clock", none: "minus", error: "octagon-alert", bypassed: "triangle-alert", warn: "triangle-alert",
  satisfied: "check", failing: "x", skipped: "skip-forward", "no-tests": "circle-dashed",
  passed: "check", failed: "x", milestone: "diamond",
};
const AC_TEXT = { satisfied: "done", failing: "failing", skipped: "skipped", "no-tests": "no tests" };
const SPRINT_TEXT = { planned: "planned", active: "in progress", closed: "done", parked: "parked" };
const SPRINT_ICON = { planned: "circle-dashed", active: "circle-dot", closed: "circle-check", parked: "circle-pause" };
const COLUMNS = [
  { id: "planned", label: "Planned", empty: "Nothing planned. Add the next sprint with", cmd: 'sprint new "<title>"' },
  { id: "active", label: "In progress", empty: "No sprint in progress. Pick one up with", cmd: "sprint start <id>" },
  { id: "closed", label: "Done", empty: "Nothing done yet. A sprint lands here when a human runs", cmd: "sprint close <id>" },
  { id: "parked", label: "Parked", empty: "Nothing parked. Set a sprint aside with", cmd: 'sprint park <id> --reason "…"' },
];
const TABS = [
  ["timeline", "Sprints", "list-checks"],
  ["board", "Board", "square-kanban"],
  ["matrix", "Regression matrix", "grid-3x3"],
  ["trends", "Trends", "chart-line"],
  ["runs", "Runs", "logs"],
];
const SPRINT_ONLY_TABS = new Set(["timeline", "board"]);
let timer = null;
let rendering = false;
let pending = null;
let lastBase = null;
let lastSel = null;
let closeHref = null;

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

function icon(name, cls) {
  const el = s("svg", { class: cls ? `icon ${cls}` : "icon", viewBox: "0 0 24 24", "aria-hidden": "true",
    focusable: "false", fill: "none", stroke: "currentColor", "data-lucide": name });
  for (const [tag, attrs] of (typeof ICONS !== "undefined" && ICONS[name]) || []) el.append(s(tag, attrs));
  return el;
}

// A status mark. Pass `label` when no word sits beside it, so screen readers get one.
function mark(kind, label) {
  const el = icon(MARK[kind] || SPRINT_ICON[kind] || "minus", `mark m-${kind}`);
  if (label) {
    el.removeAttribute("aria-hidden");
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", label);
    el.append(s("title", { text: label }));
  }
  return el;
}

function runStatus(result) { return ["pass", "bypassed", "error"].includes(result) ? result : "fail"; }

async function api(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

const enc = encodeURIComponent;

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

// Sprint dates are plain "YYYY-MM-DD" days.
function day(text) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text || "");
  if (!m) return text || "";
  const d = new Date(+m[1], +m[2] - 1, +m[3]);
  const opts = { month: "short", day: "numeric" };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString(undefined, opts);
}

function short(sha) { return sha ? sha.slice(0, 7) : ""; }

function plural(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }

function sprintKey(k) {
  if (k === "legacy") return -1;
  const m = /^S(\d+)$/i.exec(k);
  return m ? parseInt(m[1], 10) : 1e9;
}

function pill(status, text) {
  return h("span", { class: `pill ${status}` }, mark(status), text || LABEL[status] || status);
}

function sprintPill(status) {
  return h("span", { class: `pill sp-${status}` }, icon(SPRINT_ICON[status] || "circle-dashed", "mark"), SPRINT_TEXT[status] || status);
}

function chip(text, cls, title) { return h("span", { class: cls ? `chip ${cls}` : "chip", title, text }); }

function code(text) { return h("code", { text }); }

function metaItem(name, ...content) {
  return h("span", { class: "meta-item" }, icon(name, "sm"), ...content);
}

function agentIcon(agent) { return !agent || agent === "human" ? "user" : "bot"; }

function crumb(...items) {
  const out = [h("a", { href: "#/" }, icon("arrow-left", "sm"), "Projects")];
  for (const it of items) out.push(h("span", { class: "sep", text: "/" }), it);
  return h("nav", { class: "crumb", "aria-label": "Breadcrumb" }, out);
}

function emptyState(name, ...lines) {
  return h("div", { class: "empty-state" }, icon(name), lines.map((l) => h("p", {}, l)));
}

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
    else out.push(h("a", { href: m[5], rel: "noopener noreferrer", target: "_blank", class: "link", text: t.slice(1, t.indexOf("]")) }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// An AC whose only non-passing tests are skipped (e.g. allowed, toolchain-specific
// tests) is not satisfied, but it isn't failing either: show it as skipped.
function acState(a) {
  const st = a.result.state;
  const tests = a.result.tests || [];
  if (st === "failing" && tests.length && tests.every((t) => t.outcome === "passed" || t.outcome === "skipped")) return "skipped";
  return st;
}

// One segment per acceptance criterion, so "2 of 3" reads at a glance.
function segments(states, label) {
  if (!states.length) return h("div", { class: "segs empty", role: "img", "aria-label": "no acceptance criteria" }, h("span"));
  return h("div", { class: "segs", role: "img", "aria-label": label },
    states.map((st) => h("span", { class: st })));
}

// ---------------------------------------------------------------- portfolio

async function renderPortfolio() {
  const data = await api("/api/projects");
  const projects = data.projects;
  const head = h("div", { class: "page-head" }, h("h1", { text: "Portfolio" }));
  if (!projects.length) {
    return [head, emptyState("layout-grid", "No projects registered yet.",
      ["Run ", code("sprint init --ratchet-only"), " or ", code("sprint register"), " in a repo."])];
  }
  const counts = {};
  for (const p of projects) counts[p.status] = (counts[p.status] || 0) + 1;
  const words = { fail: "failing", error: "unreadable", stale: "stale", none: "without runs", pass: "passing" };
  head.append(h("div", { class: "summary" },
    h("span", { text: plural(projects.length, "project") }),
    ["fail", "error", "stale", "none", "pass"].filter((k) => counts[k]).map((k) =>
      h("span", { class: `marked c-${k === "pass" ? "ok" : k === "fail" || k === "error" ? "bad" : k === "stale" ? "warn" : "none"}` },
        mark(k), `${counts[k]} ${words[k]}`))));
  return [head, h("div", { class: "grid", role: "list" }, projects.map(card))];
}

function card(p) {
  if (p.status === "error") {
    return h("div", { class: "card error", role: "listitem" },
      h("div", { class: "card-head" }, h("h3", { text: p.name }), pill("error")),
      h("p", { class: "card-error", text: p.error }),
      h("div", { class: "card-foot mono", text: p.path }));
  }
  const l = p.latest;
  const c = (l && l.counts) || {};
  const t = (l && l.totals) || {};
  const bits = [];
  if (t.total !== undefined) bits.push(h("span", { text: plural(t.total, "test") }));
  if (c.regressions) bits.push(h("span", { class: "bad marked" }, mark("fail"), plural(c.regressions, "regression")));
  if (c.failing && c.failing !== c.regressions) bits.push(h("span", { class: "bad", text: `${c.failing} failing` }));
  if (c.missing) bits.push(h("span", { class: "bad", text: `${c.missing} missing` }));
  if (c.new_skips) bits.push(h("span", { class: "warn", text: plural(c.new_skips, "new skip") }));
  const joined = bits.flatMap((b, i) => (i ? [h("span", { class: "faint", text: "·" }), b] : [b]));
  const states = Array.from({ length: p.acs.total }, (_, i) => (i < p.acs.satisfied ? "satisfied" : "no-tests"));
  return h("a", { class: `card ${p.status}`, href: `#/p/${enc(p.key)}`, role: "listitem" },
    h("div", { class: "card-head" }, h("h3", { text: p.name }), pill(p.status)),
    h("div", { class: "meta" },
      chip(p.project_key, "key"),
      metaItem("layers", p.stack),
      metaItem(p.mode === "sprints" ? "workflow" : "shield", p.mode === "sprints" ? "sprints" : "ratchet only"),
      p.branch ? metaItem("git-branch", p.branch) : null),
    p.sprint
      ? h("div", { class: "card-sprint" },
        h("div", { class: "row" }, icon("circle-dot", "c-info"), h("span", { class: "mono", text: p.sprint.id }),
          h("span", { class: "grow", text: p.sprint.title }),
          h("span", { class: "faint num", text: `${p.acs.satisfied}/${p.acs.total} ACs` })),
        segments(states, `${p.acs.satisfied} of ${p.acs.total} acceptance criteria satisfied`))
      : p.mode === "sprints" ? h("div", { class: "card-sprint idle" }, icon("circle-dashed"), "No sprint in progress") : null,
    p.next ? h("div", { class: "card-line" }, icon("arrow-right", "sm"), "Up next",
      h("span", { class: "mono", text: p.next.id }), h("span", { text: p.next.title })) : null,
    h("div", { class: "card-line" }, icon("flask-conical", "sm"), joined.length ? joined : "No gate runs yet"),
    p.mode !== "sprints" && p.baseline ? h("div", { class: "card-line" }, icon("shield-check", "sm"),
      `Baseline of ${plural(p.baseline.total, "test")}`, h("span", { class: "faint", text: `since ${day((p.baseline.created || "").slice(0, 10))}` })) : null,
    roadmap(p.roadmap || []),
    p.stale ? h("div", { class: "card-stale" }, icon("clock", "sm"), `Stale: ${p.stale}`) : null,
    l ? h("div", { class: "card-foot" },
      h("span", { class: "meta-item", title: `last gate run ${when(l.timestamp)}` }, icon("clock", "sm"), rel(l.timestamp)),
      metaItem(agentIcon(l.agent), l.agent || "?"),
      l.head ? metaItem("git-commit-horizontal", h("span", { class: "mono", text: short(l.head) })) : null) : null);
}

// Done sprints collapse into a count; the rest are listed, so S01…S60 still fits.
function roadmap(items) {
  if (!items.length) return null;
  const done = items.filter((x) => x.status === "closed");
  const rest = items.filter((x) => x.status !== "closed");
  const order = { active: 0, planned: 1, parked: 2 };
  rest.sort((a, b) => order[a.status] - order[b.status] || sprintKey(a.id) - sprintKey(b.id));
  const shown = rest.slice(0, 7);
  return h("div", { class: "roadmap", "aria-label": "Sprints" },
    done.length ? h("span", { class: "rm closed", title: done.map((x) => `${x.id} ${x.title}`).join("\n") }, icon(SPRINT_ICON.closed, "mark"), `${done.length} done`) : null,
    shown.map((x) => h("span", { class: `rm ${x.status}`, title: `${x.id} ${x.title} (${SPRINT_TEXT[x.status]})` }, icon(SPRINT_ICON[x.status], "mark"), x.id)),
    rest.length > shown.length ? h("span", { class: "rm", text: `+${rest.length - shown.length}` }) : null);
}

// ---------------------------------------------------------------- project

async function renderProject(key, tab, sel) {
  const [d, r] = await Promise.all([api(`/api/projects/${enc(key)}`),
    api(`/api/projects/${enc(key)}/runs?limit=60`)]);
  if (d.status === "error") {
    return [crumb(h("span", { text: d.name })),
      h("div", { class: "page-head" }, h("div", { class: "title-row" }, h("h1", { text: d.name }), pill("error"))),
      h("div", { class: "banner bad" }, icon("octagon-alert"), d.error), h("p", { class: "mono faint", text: d.path })];
  }
  const runs = r.runs;
  const sprintsMode = d.mode === "sprints";
  if (!tab || (!sprintsMode && SPRINT_ONLY_TABS.has(tab))) tab = sprintsMode ? "timeline" : "matrix";
  const b = d.baseline;
  const head = [
    crumb(h("span", { text: d.name })),
    h("div", { class: "page-head" },
      h("div", { class: "title-row" }, h("h1", { text: d.name, title: d.path }), chip(d.project_key, "key"), pill(d.status)),
      h("div", { class: "meta" },
        metaItem("layers", d.stack),
        metaItem(sprintsMode ? "workflow" : "shield", sprintsMode ? "sprints" : "ratchet only"),
        d.branch ? metaItem("git-branch", d.branch) : null,
        b ? metaItem("shield-check", `baseline ${b.total} tests (${(b.created || "").slice(0, 10)}, ${b.reason})`) : metaItem("shield", "no baseline"),
        d.removals.length ? metaItem("ban", plural(d.removals.length, "accepted removal")) : null,
        d.skips.length ? metaItem("skip-forward", plural(d.skips.length, "allowed skip")) : null)),
    d.stale ? h("div", { class: "banner warn" }, icon("clock"), h("span", { text: `The latest run is stale: ${d.stale}.` })) : null,
    h("nav", { class: "tabs", "aria-label": "Views" }, TABS.filter(([id]) => sprintsMode || !SPRINT_ONLY_TABS.has(id)).map(([id, label, ic]) =>
      h("a", { href: `#/p/${enc(key)}/${id}`, "aria-current": id === tab ? "page" : null }, icon(ic, "sm"), label))),
  ];
  const ctx = { all: false, key, sel: sel ? { key, id: sel } : null };
  const views = {
    timeline: () => timeline(d),
    board: () => projectBoard(d, ctx),
    matrix: () => matrix(key, runs),
    trends: () => trends(key, runs),
    runs: () => runsTable(key, runs),
  };
  return [...head, ...(views[tab] || views.matrix)()];
}

function timeline(d) {
  if (!d.sprints.length) return [emptyState("list-checks", "No sprint files in .sprint/sprints/.", ["Create one with ", code('sprint new "<title>"'), "."])];
  return d.sprints.map((sp) => {
    const done = sp.acs.filter((a) => acState(a) === "satisfied").length;
    return h("section", { class: `sprint ${sp.status}`, "aria-label": `Sprint ${sp.id}` },
      h("div", { class: "sprint-head" },
        icon(SPRINT_ICON[sp.status] || "circle-dashed", `c-${sp.status}`),
        h("h3", {}, `${sp.id} · ${sp.title}`),
        sprintPill(sp.status),
        h("span", { class: "faint", text: sprintDates(sp) }),
        sp.acs.length ? h("span", { class: "faint num", text: `${done}/${sp.acs.length} ACs` }) : null),
      sp.goal ? h("p", { class: "goal", text: sp.goal }) : null,
      acList(sp),
      sp.out_of_scope && sp.out_of_scope.length ? h("p", { class: "out" }, icon("ban", "sm"), "Out of scope:", sp.out_of_scope.map((x) => chip(x))) : null,
      sp.notes.length ? h("ul", { class: "notes" }, sp.notes.map((n) => h("li", {}, icon("message-square-text", "sm"), h("span", {}, inlineMd(n))))) : null);
  });
}

function sprintDates(sp) {
  return [sp.started && `started ${day(sp.started)}`, sp.closed && `closed ${day(sp.closed)}`,
    sp.parked && `parked ${day(sp.parked)}`].filter(Boolean).join(" · ");
}

function acList(sp) {
  return [
    h("ul", { class: "acs" }, sp.acs.map((a) => h("li", {},
      h("span", { class: `st st-${acState(a)}` }, mark(acState(a)), AC_TEXT[acState(a)] || acState(a)),
      h("span", {}, h("strong", { text: a.id }), ` ${a.desc} `, h("code", { text: a.tests.join(", ") || "(no tests listed)" }))))),
    sp.acs.some((a) => a.result.tests && a.result.tests.length) ? h("div", { class: "tests" },
      sp.acs.flatMap((a) => (a.result.tests || []).slice(0, 8).map((t) => {
        const kind = t.outcome === "passed" || t.outcome === "skipped" ? t.outcome : "failed";
        return h("span", { title: `${t.id} (${t.outcome})`, class: kind === "passed" ? null : kind === "skipped" ? "k" : "f" },
          mark(kind, t.outcome), t.id.split(".").pop());
      }))) : null,
  ];
}

// ---------------------------------------------------------------- board

function columnsFor(items) {
  const by = { planned: [], active: [], closed: [], parked: [] };
  for (const it of items) (by[it.sp.status] || by.planned).push(it);
  const num = (it) => sprintKey(it.sp.id);
  by.planned.sort((a, b) => num(a) - num(b));
  by.active.sort((a, b) => (a.project || "").localeCompare(b.project || ""));
  by.closed.sort((a, b) => (b.sp.closed || "").localeCompare(a.sp.closed || "") || num(b) - num(a));
  by.parked.sort((a, b) => num(a) - num(b));
  return by;
}

function board(items, ctx) {
  const by = columnsFor(items);
  ctx.compact = cardSize() === "compact";
  const nodes = [h("div", { class: `board${ctx.compact ? " compact" : ""}`, role: "region", "aria-label": "Sprint board" }, COLUMNS.map((c) =>
    h("section", { class: `col col-${c.id}`, "aria-label": `${c.label}: ${by[c.id].length}` },
      h("header", { class: "col-head" }, icon(SPRINT_ICON[c.id], `c-${c.id}`), h("h2", { text: c.label }),
        h("span", { class: "count", text: by[c.id].length })),
      by[c.id].length
        ? h("div", { class: "col-cards" }, by[c.id].map((it) => boardCard(it, ctx)))
        : h("div", { class: "col-empty" }, `${c.empty} `, code(c.cmd), "."))))];
  if (ctx.sel) {
    const it = items.find((x) => x.sp.id === ctx.sel.id && (!ctx.all || x.key.toLowerCase() === ctx.sel.key.toLowerCase()));
    if (it) nodes.push(...drawer(it, ctx));
  }
  return nodes;
}

function boardHref(it, ctx) {
  return ctx.all ? `#/board/${enc(it.key)}/${enc(it.sp.id)}` : `#/p/${enc(ctx.key)}/board/${enc(it.sp.id)}`;
}

function boardCard(it, ctx) {
  const sp = it.sp;
  const sum = sp.ac_summary || { total: 0, satisfied: 0 };
  const selected = ctx.sel && ctx.sel.id === sp.id && (!ctx.all || ctx.sel.key.toLowerCase() === it.key.toLowerCase());
  const attrs = { class: `bcard ${sp.status}${selected ? " selected" : ""}${sp.regressed ? " regressed" : ""}${ctx.compact ? " compact" : ""}`,
    href: boardHref(it, ctx), "data-sprint": sp.id, "data-project": it.key, "aria-current": selected ? "true" : null };
  const bar = segments(sp.acs.map(acState), `${sum.satisfied} of ${sum.total} acceptance criteria satisfied`);
  if (ctx.compact) {
    // compact: ID, title and the AC bar; the panel has the rest
    return h("a", { ...attrs, title: sp.goal || null },
      h("div", { class: "bcard-top" }, h("span", { class: "mono bcard-id", text: sp.id }), ctx.all ? chip(it.label, "key", it.project) : null),
      h("div", { class: "bcard-title", text: sp.title || "(untitled)" }), bar);
  }
  const flags = [];
  if (sp.next) flags.push(chip("Up next", "next"));
  if (sp.regressed) flags.push(h("span", { class: "chip regressed", title: `${plural(sp.failing, "test")} failing, ${sp.missing} missing in the latest run` }, mark("fail"), "regressed"));
  else if (sp.status === "active" && sp.failing) flags.push(h("span", { class: "chip failing" }, mark("fail"), `${sp.failing} failing`));
  const foot = [metaItem("list-checks", `${sum.satisfied}/${sum.total} ACs`)];
  if (sp.stats && sp.stats.total) foot.push(metaItem("flask-conical", plural(sp.stats.total, "test")));
  if (sp.status === "active" && sp.started) foot.push(metaItem("calendar", `since ${day(sp.started)}`));
  if (sp.status === "closed" && sp.closed) foot.push(metaItem("calendar-check", day(sp.closed)));
  return h("a", attrs,
  h("div", { class: "bcard-top" }, h("span", { class: "mono bcard-id", text: sp.id }),
    ctx.all ? chip(it.label, "key", it.project) : null, h("span", { class: "spacer" }), flags),
  h("div", { class: "bcard-title", text: sp.title || "(untitled)" }),
  sp.goal ? h("div", { class: "bcard-goal", text: sp.goal }) : null,
  sp.status === "active" && sp.acs.length ? h("ul", { class: "checklist" }, sp.acs.slice(0, 6).map((a) => h("li", {},
    h("span", { class: `g ${acState(a)}` }, mark(acState(a), AC_TEXT[acState(a)])),
    h("span", { class: "id", text: a.id }), h("span", { class: "d", text: a.desc })))) : null,
  sp.status === "parked" && (sp.parked || sp.parked_reason) ? h("div", { class: "bcard-note" }, icon("circle-pause", "sm"),
    h("span", { text: [sp.parked && `Parked ${day(sp.parked)}`, sp.parked_reason].filter(Boolean).join(" · ") })) : null,
  bar,
  h("div", { class: "bcard-foot" }, foot));
}

function drawer(it, ctx) {
  const sp = it.sp;
  closeHref = ctx.all ? "#/board" : `#/p/${enc(ctx.key)}/board`;
  const st = sp.stats || {};
  const facts = [];
  const fact = (ic, label, value) => facts.push(h("dt", {}, icon(ic, "sm"), label), h("dd", {}, value));
  if (ctx.all) fact("layout-grid", "Project", h("a", { class: "link", href: `#/p/${enc(it.key)}/board/${enc(sp.id)}`, text: it.project }));
  if (sp.started) fact("calendar", "Started", day(sp.started));
  if (sp.closed) fact("calendar-check", "Closed", day(sp.closed));
  if (sp.parked) fact("circle-pause", "Parked", [day(sp.parked), sp.parked_reason].filter(Boolean).join(" · "));
  fact("flask-conical", "Tests", st.total
    ? `${st.total} in the latest run: ${st.passed} passed${st.failed ? `, ${st.failed} failed` : ""}${st.skipped ? `, ${st.skipped} skipped` : ""}`
    : "none named for this sprint yet");
  if (sp.regressed) fact("triangle-alert", "Regressed", `${plural(sp.failing, "test")} failing, ${sp.missing} missing since it closed`);
  fact("file-text", "File", h("span", { class: "mono", text: `.sprint/sprints/${sp.file}` }));
  const sum = sp.ac_summary || { total: 0, satisfied: 0 };
  return [
    h("a", { class: "scrim", href: closeHref, tabindex: "-1", "aria-hidden": "true" }),
    h("aside", { class: "drawer", id: "drawer", role: "dialog", "aria-labelledby": "drawer-title", tabindex: "-1" },
      h("div", { class: "drawer-head" }, icon(SPRINT_ICON[sp.status], `c-${sp.status}`), h("span", { class: "mono", text: sp.id }),
        sprintPill(sp.status), sp.next ? chip("Up next", "next") : null, h("span", { class: "spacer" }),
        h("a", { class: "icon-btn", href: closeHref, id: "drawer-close", "aria-label": "Close", title: "Close (Esc)" }, icon("x"))),
      h("h2", { class: "drawer-title", id: "drawer-title", text: sp.title || "(untitled)" }),
      sp.goal ? h("p", { class: "drawer-goal" }, icon("target"), h("span", { text: sp.goal })) : null,
      h("dl", { class: "facts" }, facts),
      h("section", {}, h("h2", { text: `Acceptance criteria · ${sum.satisfied}/${sum.total}` }),
        sp.acs.length ? acList(sp) : h("p", { class: "faint", text: "None yet. Add [[ac]] tables to the sprint file." })),
      sp.out_of_scope && sp.out_of_scope.length ? h("section", {}, h("h2", { text: "Out of scope" }),
        h("p", { class: "out" }, sp.out_of_scope.map((x) => chip(x)))) : null,
      sp.notes.length ? h("section", {}, h("h2", { text: "Notes and decisions" }),
        h("ul", { class: "notes" }, sp.notes.map((n) => h("li", {}, icon("message-square-text", "sm"), h("span", {}, inlineMd(n)))))) : null,
      h("section", {}, h("h2", { text: "Move it" }), h("ul", { class: "cmds" }, moves(sp).map(([cmd, what]) =>
        h("li", {}, cmd ? code(cmd) : null, h("span", { text: what })))))),
  ];
}

function moves(sp) {
  const id = sp.id;
  if (sp.status === "planned") return [[`sprint start ${id}`, "make it the sprint in progress"], [`sprint park ${id} --reason "…"`, "set it aside"]];
  if (sp.status === "active") return [[`sprint close ${id}`, "human only; needs a passing gate and every AC satisfied"], [`sprint park ${id} --reason "…"`, "set it aside; its tests stay in the ratchet"]];
  if (sp.status === "parked") return [[`sprint unpark ${id}`, "back to Planned"], [`sprint start ${id}`, "straight to In progress"]];
  return [[null, "Done. Its tests are in the baseline, and the ratchet keeps them passing."]];
}

function boardCounts(items) {
  const by = columnsFor(items);
  return h("span", { text: COLUMNS.map((c) => `${by[c.id].length} ${c.label.toLowerCase()}`).join(" · ") });
}

// Full or compact board cards, remembered in this browser. ?cards=compact in the URL picks one too.
const CARDS_KEY = "sprintwarden.board.cards";
let cards = null;
function cardSize() {
  if (cards) return cards;
  const asked = new URLSearchParams(location.search).get("cards");
  let saved = null;
  try { saved = localStorage.getItem(CARDS_KEY); } catch (_) { /* storage may be unavailable */ }
  cards = [asked, saved].find((v) => v === "full" || v === "compact") || "full";
  return cards;
}
function setCardSize(v) {
  cards = v;
  try { localStorage.setItem(CARDS_KEY, v); } catch (_) { /* storage may be unavailable */ }
  render(false);
}
function cardSwitch() {
  const now = cardSize();
  return h("div", { class: "seg", role: "group", "aria-label": "Card size" },
    [["full", "layout-list", "Full", "Full cards: goal, checklist and details"],
      ["compact", "rows-3", "Compact", "Compact cards: ID, title and the AC bar"]].map(([v, ic, label, title]) =>
      h("button", { type: "button", class: "seg-btn", "aria-pressed": now === v ? "true" : "false", title, onclick: () => setCardSize(v) },
        icon(ic, "sm"), label)));
}

function readOnlyNote() {
  return h("span", { class: "readonly" }, icon("square-terminal", "sm"), "Read-only: cards move with the ", code("sprint"), " CLI");
}

function projectBoard(d, ctx) {
  const items = d.sprints.map((sp) => ({ sp, key: ctx.key, project: d.name, label: d.project_key }));
  if (!items.length) return [emptyState("square-kanban", "No sprint files yet.", ["Plan the first one with ", code('sprint new "<title>"'), "."])];
  return [h("div", { class: "board-bar" }, boardCounts(items), h("span", { class: "spacer" }), cardSwitch(), readOnlyNote()), ...board(items, ctx)];
}

const FILTER_KEY = "sprintwarden.board.hidden";
function hiddenProjects() {
  try { return new Set(JSON.parse(localStorage.getItem(FILTER_KEY) || "[]")); } catch (_) { return new Set(); }
}
function setHidden(set) {
  try { localStorage.setItem(FILTER_KEY, JSON.stringify([...set])); } catch (_) { /* storage may be unavailable */ }
}

async function renderAllBoard(selKey, selId) {
  const data = await api("/api/board");
  const head = h("div", { class: "page-head" }, h("h1", { text: "Board" }),
    h("p", { class: "lede", text: "Every sprint in every registered project: what's planned next, what's in progress, what's done and what's parked." }));
  if (!data.projects.length) {
    return [head, emptyState("square-kanban", "No project uses sprints yet.",
      ["The board shows sprints; ratchet-only projects have none. Turn them on with ", code('project.mode = "sprints"'), " in ", code(".sprint/config.toml"), "."])];
  }
  const hidden = hiddenProjects();
  const toggle = (key) => () => {
    if (hidden.has(key)) hidden.delete(key); else hidden.add(key);
    setHidden(hidden);
    render(false);
  };
  const filters = h("div", { class: "filters", role: "group", "aria-label": "Projects shown" }, data.projects.map((p) =>
    h("button", { type: "button", class: "filter", "aria-pressed": hidden.has(p.key) ? "false" : "true", onclick: toggle(p.key), title: p.name },
      h("span", { class: "mono", text: p.project_key }), h("span", { text: p.name }))));
  const items = data.projects.filter((p) => !hidden.has(p.key)).flatMap((p) =>
    p.sprints.map((sp) => ({ sp, key: p.key, project: p.name, label: p.project_key })));
  const others = data.without_sprints
    ? h("span", { class: "faint", text: `${plural(data.without_sprints, "project")} without sprints not shown` }) : null;
  const ctx = { all: true, sel: selKey && selId ? { key: selKey, id: selId } : null };
  return [head, h("div", { class: "board-bar" }, filters, h("span", { class: "spacer" }), readOnlyNote()),
    h("div", { class: "board-bar" }, boardCounts(items), others, h("span", { class: "spacer" }), cardSwitch()), ...board(items, ctx)];
}

// ---------------------------------------------------------------- matrix, trends, runs

function matrix(key, runs) {
  const cols = runs.slice(0, 30).reverse();
  if (!cols.length) return [emptyState("grid-3x3", "No gate runs yet.", ["Run ", code("sprint gate"), "."])];
  const rows = [...new Set(cols.flatMap((r) => Object.keys(r.by_sprint || {})))].sort((a, b) => sprintKey(a) - sprintKey(b));
  const resultRow = h("tr", { class: "gate" }, h("th", { class: "row", text: "gate" }), cols.map((r) => {
    const st = r.result === "pass" ? "ok" : r.result === "bypassed" ? "warn" : "bad";
    const label = `${LABEL[r.result] || r.result} · ${when(r.timestamp)}`;
    return h("td", {}, h("a", { href: `#/p/${enc(key)}/run/${r.id}`, class: `cell ${st}`, title: label, "aria-label": label },
      mark(runStatus(r.result))));
  }));
  const head = h("tr", {}, h("th", { class: "row", text: "run" }), cols.map((r) =>
    h("th", { class: "run", title: `${when(r.timestamp)} · ${r.agent} · ${r.trigger}` },
      h("a", { href: `#/p/${enc(key)}/run/${r.id}`, text: stamp(r.timestamp) }))));
  const body = rows.map((sp) => h("tr", {}, h("th", { class: "row", text: sp }), cols.map((r) => {
    const b = (r.by_sprint || {})[sp];
    if (r.bypassed) return h("td", {}, h("span", { class: "cell warn", title: "bypassed: no tests ran" }, mark("bypassed", "bypassed")));
    if (!b) return h("td", {}, h("span", { class: "cell empty", text: "·" }));
    const failing = (r.failing || []).filter((f) => f.sprint === sp);
    const title = failing.length
      ? `${sp}: ${b.failed} failing\n` + failing.map((f) => `${f.regression ? "REGRESSION " : ""}${f.id}`).join("\n")
      : `${sp}: ${b.passed} passed${b.skipped ? `, ${b.skipped} skipped` : ""}`;
    if (b.failed) return h("td", {}, h("span", { class: "cell bad", title }, mark("failed", "failing"), b.failed));
    if (b.skipped) return h("td", {}, h("span", { class: "cell warn", title }, mark("passed", "passed"), b.passed, mark("skipped", "skipped"), b.skipped));
    return h("td", {}, h("span", { class: "cell ok", title }, mark("passed", "passed"), b.total));
  })));
  return [
    h("p", { class: "lede", text: "Rows: test buckets by sprint. Columns: the last runs, oldest left. Hover a cell for its failing tests." }),
    h("div", { class: "matrix-wrap panel" }, h("table", { class: "matrix" }, h("thead", {}, head, resultRow), h("tbody", {}, body))),
  ];
}

function passRate(p) { return p.totals.total ? (100 * p.totals.passed) / p.totals.total : 0; }
function pct(v) { return `${Number.isInteger(v) ? v : v.toFixed(1)}%`; }
function shortWhen(iso) {
  const d = new Date(iso);
  return isNaN(d) ? iso || "" : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function shortDay(iso) {
  const d = new Date(iso);
  return isNaN(d) ? iso || "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// A round axis top (1, 2, 2.5 or 5 times a power of ten, times 4 ticks), never below 4.
function niceMax(v) {
  const step = Math.pow(10, Math.floor(Math.log10(Math.max(v, 1) / 4)));
  for (const m of [1, 2, 2.5, 5, 10]) if (step * m * 4 >= v) return Math.max(4, step * m * 4);
  return Math.max(4, step * 40);
}

function tile(label, value, delta, tone) {
  return h("div", { class: "tile" }, h("div", { class: "tile-label", text: label }),
    h("div", { class: "tile-value" }, value), delta ? h("div", { class: `tile-delta${tone ? ` c-${tone}` : ""}` }, delta) : null);
}

// What a reader can conclude from the runs, in plain sentences (newest facts first).
function trendFacts(pts, bypassed) {
  const n = pts.length, first = pts[0], last = pts[n - 1];
  const lt = last.totals, lc = last.counts || {};
  const out = [];
  const add = (ic, tone, text) => out.push(h("li", { class: tone ? `tone-${tone}` : null }, icon(ic, "sm"), h("span", { text })));
  let streak = 1;
  while (streak < n && (pts[n - 1 - streak].result === "pass") === (last.result === "pass")) streak++;
  if (last.result === "pass") {
    add("check", "ok", `The latest run passed with ${plural(lt.total, "test")}${lt.skipped ? ` (${lt.skipped} skipped)` : ""}.${streak > 1 ? ` That's ${streak} passing runs in a row${streak === n ? ", every run shown" : ""}.` : ""}`);
  } else {
    const why = [lt.failed && `${lt.failed} failing`, lc.regressions && plural(lc.regressions, "regression"),
      lc.missing && `${lc.missing} missing`, lc.new_skips && plural(lc.new_skips, "new skip")].filter(Boolean);
    const lastPass = [...pts].reverse().find((p) => p.result === "pass");
    const since = lastPass ? ` The last passing run was ${rel(lastPass.timestamp)}, so the cause is in what changed after it.` : " No run shown here has passed yet.";
    add("x", "bad", `The latest run failed the gate${why.length ? `: ${why.join(", ")}` : ""}.${streak > 1 ? ` That's ${streak} failed runs in a row.` : ""}${since}`);
    if (lc.regressions) add("arrow-left", "bad", `${plural(lc.regressions, "test")} that passed before now ${lc.regressions === 1 ? "fails" : "fail"}. That is a regression: new work broke something that used to work.`);
  }
  const grew = lt.total - first.totals.total;
  const span = shortDay(first.timestamp) === shortDay(last.timestamp) ? `all on ${shortDay(last.timestamp)}` : `${shortDay(first.timestamp)} to ${shortDay(last.timestamp)}`;
  if (grew > 0) add("trending-up", "ok", `Tests grew from ${first.totals.total} to ${lt.total} (+${grew}) over these ${n} runs (${span}). Each sprint is meant to add tests for what it builds.`);
  else if (grew < 0) add("trending-down", "bad", `Tests went down from ${first.totals.total} to ${lt.total} over these ${n} runs (${span}).`);
  else add("move-right", null, `The test count stayed at ${lt.total} for all ${n} runs (${span}). New work normally adds tests, so a long flat stretch can mean changes without tests.`);
  const drops = pts.slice(1).map((p, i) => [pts[i], p]).filter(([a, b]) => b.totals.total < a.totals.total);
  if (drops.length) {
    const [a, b] = drops.reduce((m, x) => (x[0].totals.total - x[1].totals.total > m[0].totals.total - m[1].totals.total ? x : m));
    add("triangle-alert", "warn", `Tests dropped ${drops.length === 1 ? "once" : `${drops.length} times`}; the biggest drop was from ${a.totals.total} to ${b.totals.total} on ${shortWhen(b.timestamp)}. The gate fails when tests disappear, unless a human accepts the removal.`);
  }
  const fails = pts.filter((p) => p.result !== "pass").length;
  const low = pts.reduce((m, p) => (passRate(p) < passRate(m) ? p : m));
  if (!fails) add("check", "ok", `All ${n} runs passed the gate.`);
  else add("flask-conical", null, `${fails} of ${n} runs failed the gate (${Math.round((100 * fails) / n)}%).${passRate(low) < 100 ? ` The lowest pass rate was ${pct(passRate(low))} on ${shortWhen(low.timestamp)}.` : ""}`);
  const ms = [...pts].reverse().find((p) => p.milestone);
  if (ms && ms !== last) {
    const dd = lt.total - ms.totals.total;
    add("diamond", null, `Since the last milestone (${ms.milestone}, ${shortDay(ms.timestamp)}), ${dd ? `tests went ${dd > 0 ? "up" : "down"} by ${Math.abs(dd)}, from ${ms.totals.total} to ${lt.total}` : `the test count hasn't changed (${lt.total})`}.`);
  }
  const bad = Object.entries(last.by_sprint || {}).filter(([, b]) => b.failed).sort(([a], [b]) => sprintKey(a) - sprintKey(b));
  if (bad.length) add("grid-3x3", null, `Failing tests by sprint in the latest run: ${bad.map(([k, b]) => `${k} (${b.failed})`).join(", ")}. The Regression matrix tab shows when each one started failing.`);
  if (bypassed) add("triangle-alert", "warn", `${plural(bypassed, "bypassed run")} (SPRINT_SKIP=1) ${bypassed === 1 ? "isn't" : "aren't"} shown, because no tests ran.`);
  return out;
}

// One measure per chart (never two y-axes), on a shared run axis.
function runChart(pts, o) {
  // drawn at the page's real width, so 11px text stays 11px
  const W = Math.round(Math.min(1600, Math.max(560, (app.clientWidth || 1000) - 90))), H = 196, L = 44, R = 92, T = 26, B = 26;
  const iw = W - L - R, ih = H - T - B, n = pts.length;
  const x = (i) => L + (n === 1 ? iw / 2 : (iw * i) / (n - 1));
  const y = (v) => T + ih - (ih * v) / o.max;
  const svg = s("svg", { class: `chart ${o.cls}`, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": o.label });
  for (let k = 0; k <= 4; k++) {
    const v = (o.max * k) / 4;
    svg.append(s("line", { class: "axis", x1: L, x2: L + iw, y1: y(v), y2: y(v) }));
    svg.append(s("text", { class: "tick", x: L - 8, y: y(v) + 4, "text-anchor": "end", text: o.fmt(v) }));
  }
  let lastLabel = -1e9;
  pts.forEach((p, i) => {
    if (!p.milestone) return;
    svg.append(s("line", { class: "ms", x1: x(i), x2: x(i), y1: T - 6, y2: T + ih }));
    if (!o.milestones) return;
    const g = s("g", { class: "ms-mark", transform: `translate(${x(i) - 6} ${T - 21}) scale(0.5)` });
    for (const [tag, attrs] of ICONS.diamond || []) g.append(s(tag, attrs));
    svg.append(g);
    if (x(i) - lastLabel > 110 && x(i) < L + iw - 60) {
      svg.append(s("text", { class: "ms-label", x: x(i) + 9, y: T - 11, text: p.milestone }));
      lastLabel = x(i);
    }
  });
  svg.append(s("polyline", { class: "line", points: pts.map((p, i) => `${x(i)},${y(o.value(p))}`).join(" ") }));
  pts.forEach((p, i) => {
    const cx = x(i), cy = y(o.value(p));
    if (p.result === "pass") svg.append(s("circle", { class: "dot", cx, cy, r: 4 }));
    else svg.append(s("circle", { class: "ring", cx, cy, r: 6 }), s("path", { class: "dot-fail", d: `M${cx - 4} ${cy - 4}L${cx + 4} ${cy + 4}M${cx + 4} ${cy - 4}L${cx - 4} ${cy + 4}` }));
  });
  const lastV = o.value(pts[n - 1]);
  svg.append(s("text", { class: "end-label", x: L + iw + 12, y: y(lastV) + 4, text: o.endLabel(lastV) }));
  svg.append(s("text", { class: "tick", x: L, y: H - 6, text: shortWhen(pts[0].timestamp) }));
  svg.append(s("text", { class: "tick", x: L + iw, y: H - 6, "text-anchor": "end", text: shortWhen(pts[n - 1].timestamp) }));
  const cross = s("line", { class: "cross", x1: 0, x2: 0, y1: T - 6, y2: T + ih, visibility: "hidden" });
  const hot = s("circle", { class: "hot", cx: 0, cy: 0, r: 6, visibility: "hidden" });
  svg.append(cross, hot);
  return {
    svg,
    xAt: (i) => x(i) / W,
    index(ev) {
      const r = svg.getBoundingClientRect();
      const vx = ((ev.clientX - r.left) / r.width) * W;
      return Math.max(0, Math.min(n - 1, Math.round(((vx - L) / iw) * (n - 1))));
    },
    show(i) {
      for (const el of [cross, hot]) el.setAttribute("visibility", "visible");
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i));
      hot.setAttribute("cx", x(i)); hot.setAttribute("cy", y(o.value(pts[i])));
    },
    hide() { for (const el of [cross, hot]) el.setAttribute("visibility", "hidden"); },
  };
}

// Crosshair + readout shared by both charts; arrow keys move it, Enter opens the run.
function hoverLayer(wrap, charts, pts, key) {
  const tip = h("div", { class: "tip", hidden: true });
  let cur = -1;
  const show = (i) => {
    cur = i;
    const p = pts[i], t = p.totals;
    for (const c of charts) c.show(i);
    tip.replaceChildren(...[
      h("div", { class: "tip-head" }, mark(runStatus(p.result)), h("span", { text: `${LABEL[p.result] || p.result} · ${shortWhen(p.timestamp)}` })),
      h("div", { class: "tip-row" }, h("span", { class: "line-key k1" }), h("strong", { text: t.total }), " tests"),
      h("div", { class: "tip-row" }, h("span", { class: "line-key k2" }), h("strong", { text: pct(passRate(p)) }), " passed"),
      t.failed || t.skipped ? h("div", { class: "tip-row faint", text: [t.failed && `${t.failed} failing`, t.skipped && `${t.skipped} skipped`].filter(Boolean).join(" · ") }) : null,
      p.milestone ? h("div", { class: "tip-row marked c-warn" }, mark("milestone"), p.milestone) : null,
      h("div", { class: "tip-row faint", text: "Click or press Enter to open this run" })].filter(Boolean));
    tip.hidden = false;
    const left = charts[0].xAt(i) * charts[0].svg.getBoundingClientRect().width;
    const max = wrap.clientWidth - tip.offsetWidth - 4;
    tip.style.left = `${Math.max(4, Math.min(max, left + 14 > max ? left - tip.offsetWidth - 14 : left + 14))}px`;
  };
  const hide = () => { cur = -1; for (const c of charts) c.hide(); tip.hidden = true; };
  const open = (i) => { location.hash = `#/p/${enc(key)}/run/${pts[i].id}`; };
  for (const c of charts) {
    c.svg.addEventListener("pointermove", (ev) => show(c.index(ev)));
    c.svg.addEventListener("pointerleave", hide);
    c.svg.addEventListener("click", (ev) => open(c.index(ev)));
  }
  wrap.addEventListener("focus", () => show(cur < 0 ? pts.length - 1 : cur));
  wrap.addEventListener("blur", hide);
  wrap.addEventListener("keydown", (e) => {
    const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    if (step) { e.preventDefault(); show(Math.max(0, Math.min(pts.length - 1, (cur < 0 ? pts.length - 1 : cur) + step))); }
    else if (e.key === "Home" || e.key === "End") { e.preventDefault(); show(e.key === "Home" ? 0 : pts.length - 1); }
    else if (e.key === "Enter" && cur >= 0) open(cur);
    else if (e.key === "Escape") hide();
  });
  wrap.append(tip);
}

function trends(key, runs) {
  const all = runs.filter((r) => r.totals && r.totals.total !== undefined);
  const pts = all.filter((r) => !r.bypassed).slice(0, 60).reverse();
  if (pts.length < 2) return [emptyState("chart-line", "Trends need at least two gate runs.", ["Each ", code("sprint gate"), " run adds a point here."])];
  const n = pts.length, first = pts[0], last = pts[n - 1], prev = pts[n - 2];
  const grew = last.totals.total - first.totals.total;
  const dr = passRate(last) - passRate(prev);
  const fails = pts.filter((p) => p.result !== "pass").length;
  const tiles = h("div", { class: "tiles" },
    tile("Tests now", String(last.totals.total),
      grew ? h("span", { class: "marked" }, icon(grew > 0 ? "trending-up" : "trending-down", "sm"), `${grew > 0 ? "+" : ""}${grew} since ${shortDay(first.timestamp)}`) : `no change since ${shortDay(first.timestamp)}`,
      grew > 0 ? "ok" : grew < 0 ? "bad" : null),
    tile("Pass rate now", pct(passRate(last)),
      dr ? `${Number.isInteger(dr) ? Math.abs(dr) : Math.abs(dr).toFixed(1)} points ${dr > 0 ? "higher" : "lower"} than the run before` : "same as the run before",
      dr > 0 ? "ok" : dr < 0 ? "bad" : null),
    tile("Runs that passed", `${n - fails} of ${n}`, fails ? `${fails} failed the gate` : "none failed", fails ? "bad" : "ok"),
    tile("Latest run", h("span", { class: `marked c-${last.result === "pass" ? "ok" : "bad"}` }, mark(runStatus(last.result)), last.result === "pass" ? "Passed" : "Failed"), rel(last.timestamp)));
  const tests = runChart(pts, {
    cls: "series-tests", label: `total tests in each of the last ${n} gate runs`, max: niceMax(Math.max(...pts.map((p) => p.totals.total))),
    value: (p) => p.totals.total, fmt: (v) => String(Math.round(v)), endLabel: (v) => plural(v, "test"), milestones: true,
  });
  const rate = runChart(pts, {
    cls: "series-rate", label: `pass rate in each of the last ${n} gate runs`, max: 100,
    value: passRate, fmt: (v) => `${v}%`, endLabel: (v) => `${pct(v)} passed`,
  });
  const wrap = h("div", { class: "chart-wrap", tabindex: "0", "aria-label": "Gate runs over time. Use the arrow keys to step through runs and Enter to open one." },
    h("div", { class: "chart-block" }, h("h2", { text: "Tests in each run" }),
      h("p", { class: "chart-sub", text: "How many tests the gate found (total tests). This should only go up: the ratchet fails the gate when tests disappear." }),
      tests.svg),
    h("div", { class: "chart-block" }, h("h2", { text: "Pass rate" }),
      h("p", { class: "chart-sub", text: "The share of those tests that passed (pass rate). 100% is the goal; a dip means something broke in that run." }),
      rate.svg));
  hoverLayer(wrap, [tests, rate], pts, key);
  const keyRow = h("div", { class: "chart-key" },
    h("span", { class: "marked" }, s("svg", { class: "key-mark", viewBox: "0 0 16 16", "aria-hidden": "true" }, s("circle", { class: "dot", cx: 8, cy: 8, r: 4 })), "run passed the gate"),
    h("span", { class: "marked" }, s("svg", { class: "key-mark", viewBox: "0 0 16 16", "aria-hidden": "true" }, s("path", { class: "dot-fail", d: "M4 4L12 12M12 4L4 12" })), "run failed the gate"),
    h("span", { class: "marked" }, mark("milestone"), "milestone: a baseline was set or a sprint was closed"),
    h("span", { class: "faint", text: "Runs are evenly spaced, oldest on the left." }),
    h("span", { class: "spacer" }),
    h("a", { class: "link marked", href: `#/p/${enc(key)}/runs` }, icon("table", "sm"), "Every run as a table"));
  return [
    h("p", { class: "lede" }, "Each time ", code("sprint gate"), ` runs (from an agent hook, a git push, CI or by hand), it records how many tests ran and how many passed. This is that history for the last ${plural(n, "run")}.`),
    tiles,
    h("section", { class: "facts-panel panel" }, h("h2", {}, icon("lightbulb", "sm"), "What this tells you"), h("ul", { class: "insights" }, trendFacts(pts, all.length - all.filter((r) => !r.bypassed).length))),
    h("div", { class: "panel" }, wrap, keyRow),
    h("section", { class: "why panel" }, h("h2", {}, icon("book-open", "sm"), "Why it matters"),
      h("ul", { class: "insights" },
        h("li", {}, icon("trending-up", "sm"), h("span", { text: "A healthy project climbs in steps: each sprint adds tests for what it builds, and earlier tests keep passing." })),
        h("li", {}, icon("shield-check", "sm"), h("span", { text: "Nothing lets the count shrink quietly. If an agent deletes or skips a test, the gate fails until a human accepts it." })),
        h("li", {}, icon("x", "sm"), h("span", { text: "Failed runs are normal while work is in progress. A run of failures, or a failure in an old sprint's tests, is what needs attention." })))),
  ];
}

function runsTable(key, runs) {
  if (!runs.length) return [emptyState("logs", "No gate runs yet.", ["Run ", code("sprint gate"), "."])];
  return [h("div", { class: "panel flush" }, h("table", {},
    h("thead", {}, h("tr", {}, ["when", "result", "sprint", "tests", "failed", "regr.", "missing", "new skips", "agent", "trigger", "commit", ""].map((t, i) =>
      h("th", { class: i >= 3 && i <= 7 ? "num" : null, text: t })))),
    h("tbody", {}, runs.map((r) => {
      const t = r.totals || {}, c = r.counts || {};
      const go = () => { location.hash = `#/p/${enc(key)}/run/${r.id}`; };
      return h("tr", { class: "clickable", onclick: go, tabindex: "0", onkeydown: (e) => { if (e.key === "Enter") go(); } },
        h("td", { title: r.timestamp, text: when(r.timestamp) }),
        h("td", {}, pill(runStatus(r.result), LABEL[r.result] || r.result)),
        h("td", { class: "mono", text: r.sprint || "–" }),
        h("td", { class: "num", text: t.total ?? "–" }),
        h("td", { class: `num${t.failed ? " c-bad" : ""}`, text: t.failed ?? "–" }),
        h("td", { class: `num${c.regressions ? " c-bad" : ""}`, text: c.regressions ?? 0 }),
        h("td", { class: `num${c.missing ? " c-bad" : ""}`, text: c.missing ?? 0 }),
        h("td", { class: `num${c.new_skips ? " c-warn" : ""}`, text: c.new_skips ?? 0 }),
        h("td", {}, h("span", { class: "meta-item" }, icon(agentIcon(r.agent), "sm"), r.agent || "")),
        h("td", { class: "faint", text: r.trigger || "" }),
        h("td", { class: "mono", text: short((r.git || {}).head) }),
        h("td", { class: "c-warn" }, r.milestone ? h("span", { class: "marked" }, mark("milestone"), r.milestone) : null));
    }))))];
}

// ---------------------------------------------------------------- run detail

async function renderRun(key, id) {
  const [d, r] = await Promise.all([api(`/api/projects/${enc(key)}`),
    api(`/api/projects/${enc(key)}/runs/${enc(id)}`)]);
  const g = r.git || {};
  const status = runStatus(r.result);
  const out = [
    crumb(h("a", { href: `#/p/${enc(key)}/runs`, text: d.name }), h("span", { class: "mono", text: id })),
    h("div", { class: "page-head" },
      h("div", { class: "title-row" }, h("h1", { text: `Run ${when(r.timestamp)}` }), pill(status, LABEL[r.result] || r.result)),
      h("div", { class: "meta" },
        metaItem(agentIcon(r.agent), `agent ${r.agent}`), metaItem("zap", `trigger ${r.trigger}`),
        r.sprint ? metaItem("circle-dot", `sprint ${r.sprint}`) : null,
        metaItem("timer", `${r.duration_s}s`),
        metaItem("git-commit-horizontal", h("span", { class: "mono", text: `${short(g.head)}${g.branch ? ` (${g.branch})` : ""}${g.dirty ? " + uncommitted changes" : ""}` })),
        r.milestone ? h("span", { class: "meta-item c-warn" }, mark("milestone"), r.milestone) : null,
        h("span", { class: "mono faint", text: r.id }))),
  ];
  if (d.allure_url) out.push(h("p", {}, h("a", { href: d.allure_url, rel: "noopener noreferrer", target: "_blank", class: "link" }, "Open in Allure ", icon("external-link", "sm")), h("span", { class: "faint", text: " for per-test history" })));
  if (r.bypassed) out.push(h("div", { class: "banner warn" }, icon("triangle-alert"), h("span", { text: `The gate was bypassed (${r.bypass_reason || "SPRINT_SKIP=1"}); no tests ran.` })));
  out.push(h("h2", { text: "Checks" }), h("div", { class: "panel flush" }, h("table", { class: "checks" }, h("tbody", {}, (r.checks || []).map((c) => {
    const cls = c.ok === null ? "c-none" : c.ok ? "c-ok" : c.blocking ? "c-bad" : "c-warn";
    const [kind, word] = c.ok === null ? ["none", "not checked"] : c.ok ? ["pass", "passed"] : c.blocking ? ["fail", "failed"] : ["warn", "warning"];
    return h("tr", {}, h("td", { class: cls }, mark(kind, word)), h("td", { class: "mono", text: c.id }),
      h("td", {}, c.summary, c.detail ? h("div", { class: "msg", text: c.detail }) : null),
      h("td", { class: "faint", text: c.blocking ? "" : "not blocking" }));
  })))));
  const section = (title, items, render) => items && items.length ? [h("h2", { text: `${title} (${items.length}${r.truncated && r.truncated[title.toLowerCase().replace(" ", "_")] ? "+" : ""})` }),
    h("div", { class: "panel flush" }, h("table", {}, h("tbody", {}, items.map(render))))] : [];
  out.push(...section("Failing", r.failing, (f) => h("tr", {},
    h("td", { class: "mono", text: f.sprint }),
    h("td", {}, h("span", { class: "mono", text: f.id }), f.regression ? h("span", { class: "tag-reg" }, icon("arrow-left", "mark"), `REGRESSION ${f.regression_reason || ""}`) : null,
      f.flaky ? h("span", { class: "badge", text: "flaky" }) : null,
      f.message ? h("div", { class: "msg", text: f.message }) : null))));
  out.push(...section("Missing", r.missing, (m) => h("tr", {}, h("td", { class: "mono", text: m.sprint }), h("td", { class: "mono", text: m.id }), h("td", { class: "faint", text: "in baseline, no longer exists" }))));
  out.push(...section("New skips", r.new_skips, (m) => h("tr", {}, h("td", { class: "mono", text: m.sprint }), h("td", { class: "mono", text: m.id }), h("td", { class: "faint", text: m.was === "new" ? "new test, skipped" : `was ${m.was}` }))));
  const by = r.by_sprint || {};
  const keys = Object.keys(by).sort((a, b) => sprintKey(a) - sprintKey(b));
  if (keys.length) {
    out.push(h("h2", { text: "Tests by sprint" }), h("div", { class: "panel flush" }, h("table", {},
      h("thead", {}, h("tr", {}, ["sprint", "total", "passed", "failed", "skipped"].map((t, i) => h("th", { class: i ? "num" : null, text: t })))),
      h("tbody", {}, keys.map((k) => h("tr", {}, h("td", { class: "mono", text: k }), ["total", "passed", "failed", "skipped"].map((f) =>
        h("td", { class: `num ${f === "failed" && by[k].failed ? "c-bad" : ""}`, text: by[k][f] }))))))));
  }
  if (r.runner && r.runner.length) {
    out.push(h("h2", { text: "Runner" }), h("div", { class: "panel flush" }, h("table", {}, h("tbody", {}, r.runner.map((x) =>
      h("tr", {}, h("td", { text: x.suite }), h("td", { class: "mono", text: x.command }), h("td", { class: "num", text: `exit ${x.exit_code}` }),
        h("td", { class: "num", text: `${x.duration_s}s` }), h("td", { class: "err", text: x.error || "" })))))));
  }
  return out;
}

// ---------------------------------------------------------------- router

// base: the page without the sprint panel, so opening/closing it keeps the scroll.
function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "board") {
    return { nav: "board", base: "board", view: () => renderAllBoard(parts[1], parts[2]), sel: parts[2] ? [parts[1], parts[2]] : null };
  }
  if (parts[0] === "p" && parts[1]) {
    if (parts[2] === "run" && parts[3]) return { nav: "projects", base: `p/${parts[1]}/run/${parts[3]}`, view: () => renderRun(parts[1], parts[3]) };
    if (parts[2] === "board") return { nav: "projects", base: `p/${parts[1]}/board`, view: () => renderProject(parts[1], "board", parts[3]), sel: parts[3] ? [parts[1], parts[3]] : null };
    return { nav: "projects", base: `p/${parts[1]}/${parts[2] || ""}`, view: () => renderProject(parts[1], parts[2]) };
  }
  return { nav: "projects", base: "", view: renderPortfolio };
}

async function render(focus) {
  if (rendering) { pending = pending || focus; return; }
  rendering = true;
  const y = window.scrollY;
  const r = route();
  for (const a of document.querySelectorAll("[data-nav]")) {
    if (a.dataset.nav === r.nav) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  closeHref = null;
  try {
    const nodes = await r.view();
    app.replaceChildren(...nodes.filter(Boolean));
    updated.textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    const sameBase = r.base === lastBase;
    lastBase = r.base;
    if (!focus || sameBase) window.scrollTo(0, y);
    else { window.scrollTo(0, 0); app.focus({ preventScroll: true }); }
    if (focus && r.sel) document.getElementById("drawer")?.focus({ preventScroll: true });
    else if (focus && sameBase && lastSel) {
      // the panel just closed: put focus back on the card that opened it
      const [key, id] = lastSel;
      document.querySelector(`.bcard[data-sprint="${CSS.escape(id)}"][data-project="${CSS.escape(key)}" i]`)?.focus({ preventScroll: true });
    }
    lastSel = r.sel;
  } catch (err) {
    app.replaceChildren(emptyState("octagon-alert", `Couldn't load: ${err.message}`, [h("a", { class: "link", href: "#/", text: "Back to all projects" })]));
  } finally {
    rendering = false;
    if (pending !== null) { const f = pending; pending = null; render(f); }
  }
}

// Theme: follow the system, or force light or dark (remembered in this browser).
const THEMES = [["system", "sun-moon", "match system"], ["light", "sun", "light"], ["dark", "moon", "dark"]];
const themeButton = document.getElementById("theme");

function paintTheme() {
  const now = document.documentElement.dataset.theme || "system";
  const i = THEMES.findIndex(([id]) => id === now);
  const [, ic, label] = THEMES[i];
  const next = THEMES[(i + 1) % THEMES.length][2];
  themeButton.replaceChildren(icon(ic));
  themeButton.setAttribute("aria-label", `Theme: ${label}. Click for ${next}`);
  themeButton.title = `Theme: ${label}`;
}

themeButton.addEventListener("click", () => {
  const now = document.documentElement.dataset.theme || "system";
  const next = THEMES[(THEMES.findIndex(([id]) => id === now) + 1) % THEMES.length][0];
  if (next === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = next;
  try {
    if (next === "system") localStorage.removeItem("sprintwarden.theme");
    else localStorage.setItem("sprintwarden.theme", next);
  } catch (_) { /* storage may be unavailable */ }
  paintTheme();
});

function setTimer() {
  if (timer) clearInterval(timer);
  timer = auto.checked ? setInterval(() => render(false), 15000) : null;
}

for (const el of document.querySelectorAll("[data-icon]")) el.replaceWith(icon(el.dataset.icon, el.className));
paintTheme();
try {
  const saved = localStorage.getItem("sprintwarden.autorefresh");
  if (saved !== null) auto.checked = saved === "1";
} catch (_) { /* storage may be unavailable */ }
auto.addEventListener("change", () => {
  try { localStorage.setItem("sprintwarden.autorefresh", auto.checked ? "1" : "0"); } catch (_) { /* ignore */ }
  setTimer();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && closeHref && document.getElementById("drawer")) location.hash = closeHref;
});
window.addEventListener("hashchange", () => render(true));
setTimer();
render(true);
api("/api/version").then((v) => { document.getElementById("version").textContent = `v${v.version}`; }).catch(() => {});
