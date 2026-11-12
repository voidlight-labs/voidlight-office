"use strict";

const COLORS = { kerja: "#4ade80", idle: "#fbbf24", quiet: "#6b7686", error: "#f87171" };
const ROLE_COLORS = { Explore: "#4fd0f7", judge: "#a78bfa", "general-purpose": "#4ade80", agent: "#94a3b8" };
const STATUS_DOT = { ok: "var(--green)", error: "var(--red)", running: "var(--yellow)" };
const STATE = { snap: null, ok: true, filterRoom: null, selected: null, expandedAgent: null, openContent: null, content: {}, insightsOpen: false, insightsScope: "all", insightsData: null, query: "", lastLogAt: 0, prevUsage: null };
let freshTimer = 0;  // timer stagger konten drawer saat baru kebuka
const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtTokens(n) {
  if (n == null) return "0";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1000) return Math.round(n / 1000) + "k";
  return String(n);
}

function fmtAge(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (s < 60) return `diperbarui ${s}s lalu`;
  const m = Math.round(s / 60);
  if (m < 60) return `diperbarui ${m}m lalu (data beku)`;
  return `diperbarui ${Math.round(m / 60)}j lalu (data beku)`;
}

function fmtDuration(ms) {
  if (ms == null) return "";
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60), rs = s % 60;
  if (m < 60) return rs ? `${m}m ${rs}s` : `${m}m`;
  return `${Math.floor(m / 60)}j ${m % 60}m`;
}

function fmtClock(ts) {
  if (!ts) return "--:--:--";
  const d = new Date(ts), p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

// mcp__plugin_playwright_playwright__browser_resize -> "playwright browser resize"; Bash -> "Bash"
function humanizeTool(tool) {
  const raw = String(tool || "");
  if (!raw) return "";
  if (!raw.includes("_")) return raw;  // nama camel/one-word biarkan apa adanya
  let rest = raw, server = "";
  if (rest.includes("__")) {
    const i = rest.lastIndexOf("__");
    server = rest.slice(0, i).replace(/^mcp__(plugin_)?/, "");
    rest = rest.slice(i + 2);
  }
  const clean = (s) => s.split("_").filter(Boolean)
    .filter((w, i, arr) => i === 0 || w.toLowerCase() !== arr[i - 1].toLowerCase())
    .join(" ");
  const action = clean(rest), srv = clean(server);
  if (!srv || action.toLowerCase().startsWith(srv.split(" ")[0].toLowerCase())) return action || raw;
  return `${srv} ${action}`;
}

// sparkline versi bar chart: kolom tipis, kolom terakhir solid
function sparkline(values, color) {
  if (!values || values.length < 2) return "";
  const w = 84, h = 22, max = Math.max(...values, 1);
  const n = values.length, bw = 3;
  const gap = Math.max(1, (w - n * bw) / (n - 1));
  let bars = "";
  values.forEach((v, i) => {
    const bh = Math.max(2, Math.round((v / max) * (h - 2)));
    const x = (i * (bw + gap)).toFixed(1);
    const last = i === n - 1;
    // kelas sb = grow-in saat boot (delay per-bar inline), sb-last = kolom terakhir bernapas
    bars += `<rect class="sb${last ? " sb-last" : ""}" style="animation-delay:${i * 14}ms" x="${x}" y="${h - bh}" width="${bw}" height="${bh}" fill="${color}" opacity="${last ? 1 : .42}"/>`;
  });
  return `<svg class="a-spark" width="${w}" height="${h}" aria-hidden="true">${bars}</svg>`;
}

function roleBadge(role) {
  const c = role ? (ROLE_COLORS[role] || "var(--muted)") : "var(--dim)";
  // hue role dipertahankan buat pengenalan cepat, tapi kekuatan visual diturunkan via alpha
  const border = c.startsWith("#") ? c + "55" : "var(--line)";
  const bg = c.startsWith("#") ? c + "14" : "transparent";
  return `<span class="role-badge" style="color:${c};border-color:${border};background:${bg}">${esc(role || "?")}</span>`;
}

function subRow(s) {
  const c = COLORS[s.status] || COLORS.quiet;
  return `<div class="sub-row" onclick="openAgent('${esc(s.id)}')">
    <i class="dot" style="background:${c}"></i>
    <span class="who">${esc(s.name || s.short_name)}</span>
    ${roleBadge(s.role)}
    <span class="tok">${fmtTokens(s.tokens)} tok</span>
  </div>`;
}

function agentRow(a) {
  const c = COLORS[a.status] || COLORS.quiet;
  const title = a.title || "tanpa judul";
  const err = a.error_count > 0 ? ` <span class="err-chip">${a.error_count} err</span>` : "";
  const detail = a.status_detail || a.status || "";
  const bar = a.target_budget > 0
    ? `<div class="bar"><div style="width:${Math.min(100, Math.round(a.target_used / a.target_budget * 100))}%;background:${c}"></div></div>`
    : "";
  const live = a.status === "kerja" && a.current_tool
    ? `<span class="c-live"><span class="caret">▊</span><span class="tool">${esc(humanizeTool(a.current_tool))}</span></span>`
    : "";
  return `<div class="agent" onclick="openAgent('${esc(a.id)}')" title="${esc(a.objective || title)}">
    <span class="c-status"><i class="lamp ${a.status === "kerja" ? "on" : ""}" style="background:${c}"></i><span style="color:${c}">${esc(detail)}</span></span>
    <span class="c-tag">${esc((a.name || "??").slice(0, 2).toUpperCase())}</span>
    <span class="c-main">
      <span class="a-title"><span class="tt">${esc(title)}</span>${err}</span>
      ${live}
      ${bar}
    </span>
    <span class="c-dur">${esc(fmtDuration(a.age_ms)) || "&mdash;"}</span>
    <span class="c-model">${a.model ? esc(a.model) : "&mdash;"}</span>
    <span class="c-tok">${fmtTokens(a.tokens)} <small>tok</small></span>
    <span class="c-tools">${a.tool_calls} <small>tools</small></span>
    ${sparkline(a.sparkline, c)}
  </div>`;
}

function roomCard(r) {
  const active = STATE.filterRoom === r.name ? "active" : "";
  const agents = r.agents.map(agentRow).join("");
  const chips = r.agents
    .filter((a) => a.subagents.length)
    .map((a) => {
      const open = STATE.expandedAgent === a.id;
      const roles = Object.entries(a.sub_roles || {})
        .map(([role, n]) => `<span style="color:${ROLE_COLORS[role] || "var(--muted)"}">${esc(role)} x${n}</span>`)
        .join(" &middot; ");
      return `<div class="sub-block">
        <div class="sub-toggle ${open ? "open" : ""}" onclick="toggleExpand('${esc(a.id)}')">
          <span class="tree">└─</span> ${esc(a.name || a.short_name)} + ${a.subagents.length} sub${roles ? " &middot; " + roles : ""} <span class="chev rot${open ? " open" : ""}">▸</span>
        </div>
        ${open ? `<div class="sub-rows">${a.subagents.map(subRow).join("")}</div>` : ""}
      </div>`;
    })
    .join("");
  return `<section class="room ${active}">
    <div class="room-head ${active}" onclick="toggleFilter('${esc(r.name)}')">
      <span class="room-mark">■</span>
      <span class="room-name">${esc(r.name)}</span>
      <span class="room-obj">${esc(r.objective ?? "")}</span>
      <span class="room-meta"><b>${fmtTokens(r.tokens)}</b> tok &middot; ${r.agents.length} agent</span>
    </div>
    <div class="agents">${agents || '<div class="room-empty">-- tidak ada agent aktif --</div>'}</div>
    ${chips ? `<div class="subs">${chips}</div>` : ""}
  </section>`;
}

function skeletonCard() {
  const row = `<div class="agent">
    <span class="skeleton" style="width:118px;height:10px"></span>
    <span class="skeleton" style="width:30px;height:22px"></span>
    <span class="c-main"><span class="skeleton" style="height:11px;width:70%"></span></span>
    <span class="skeleton" style="width:84px;height:20px"></span>
  </div>`;
  return `<section class="room">
    <div class="skeleton skel-line" style="width:34%"></div>
    ${row}${row}${row}
  </section>`;
}

function agentMatches(a, q) {
  return [a.name, a.short_name, a.title, a.objective, a.current_tool]
    .some((v) => v && String(v).toLowerCase().includes(q));
}

function renderRooms() {
  if (!STATE.snap) { $("rooms").innerHTML = skeletonCard() + skeletonCard(); return; }
  const rooms = STATE.snap.rooms;
  if (!rooms.length) {
    const meta = STATE.snap.meta;
    const msg = meta && (meta.errors || []).length ? meta.errors.join("; ") : "belum ada aktivitas";
    $("rooms").innerHTML = `<div class="empty"><div class="empty-glyph">[ no signal ]</div>
      <div class="empty-title">${esc(msg)}</div>
      <div class="empty-sub">mulai sesi ZCode, dashboard bakal ngisi sendiri</div></div>`;
    return;
  }
  // filter room yang tersimpan bisa basi (room sudah tidak ada): reset
  if (STATE.filterRoom && !rooms.some((r) => r.name === STATE.filterRoom)) {
    STATE.filterRoom = null;
    saveViewState();
  }
  let list = STATE.filterRoom ? rooms.filter((r) => r.name === STATE.filterRoom) : rooms.slice();
  const q = STATE.query;
  if (q) {
    list = list
      .map((r) => {
        if (r.name.toLowerCase().includes(q)) return r;  // nama room match: tampil utuh
        const agents = r.agents.filter((a) => agentMatches(a, q)
          || (a.subagents || []).some((s) => agentMatches(s, q)));
        return { ...r, agents };
      })
      .filter((r) => r.name.toLowerCase().includes(q) || r.agents.length > 0);
  }
  if (!list.length) {
    $("rooms").innerHTML = `<div class="empty"><div class="empty-glyph">[ no match ]</div>
      <div class="empty-title">gak ada yang cocok buat "${esc(STATE.query)}"</div></div>`;
    return;
  }
  $("rooms").innerHTML = list.map(roomCard).join("");
}

function renderFeed() {
  $("feed-title").textContent = STATE.filterRoom ? `Event Log · ${STATE.filterRoom}` : "Event Log";
  const countEl = $("feed-count");
  if (!STATE.snap) {
    countEl.textContent = "";
    $("feed-rows").innerHTML = Array.from({ length: 6 },
      () => '<div class="log-line"><div class="skeleton" style="height:10px;width:85%"></div></div>').join("");
    return;
  }
  let rows = STATE.snap.activity
    .filter((x) => !STATE.filterRoom || x.room === STATE.filterRoom);
  if (STATE.query) {
    rows = rows.filter((x) => `${x.room}/${x.agent} ${x.tool} ${humanizeTool(x.tool)}`
      .toLowerCase().includes(STATE.query));
  }
  countEl.innerHTML = rows.length ? `<i class="lamp on"></i>${rows.length}` : "";
  // baris yang lebih muda dari render sebelumnya digarisbawahi flash cyan
  const prevMax = STATE.lastLogAt || 0;
  let maxAt = prevMax;
  $("feed-rows").innerHTML = rows.map((x) => {
    const c = STATUS_DOT[x.status] || "var(--gray)";
    const pulse = x.status === "running" ? " pulse-running" : "";
    const d = x.duration_ms != null ? `${Math.round(x.duration_ms / 1000)}s` : "";
    const isNew = prevMax > 0 && (x.at || 0) > prevMax;
    if ((x.at || 0) > maxAt) maxAt = x.at || 0;
    return `<div class="log-line${isNew ? " log-new" : ""}" title="${esc(x.room)}/${esc(x.agent)} &middot; ${esc(x.tool)}">
      <span class="l-time">${esc(fmtClock(x.at))}</span>
      <span class="dot${pulse}" style="background:${c}"></span>
      <span class="l-agent">${esc(x.agent)}</span>
      <span class="l-room">${esc(x.room)}</span>
      <span class="l-tool">${esc(humanizeTool(x.tool))}</span>
      <span class="l-dur">${d}</span>
    </div>`;
  }).join("") || (STATE.query ? '<div class="log-empty">-- gak ada aktivitas yang cocok --</div>'
    : '<div class="log-empty">-- belum ada aktivitas --</div>');
  STATE.lastLogAt = maxAt;
}

function renderTopbar() {
  const u = STATE.snap?.usage;
  const prev = STATE.prevUsage;
  document.title = u && u.working_count > 0 ? `(${u.working_count}) Voidlight Office` : "Voidlight Office";
  if (!u) { $("stat-working").innerHTML = ""; $("stat-tokens").innerHTML = ""; $("stat-models").innerHTML = ""; STATE.prevUsage = null; return; }
  // angka yang berubah dibiarin flash cyan sebentar, biar perubahan kebaca
  const workChanged = prev != null && prev.working_count !== u.working_count;
  $("stat-working").innerHTML = `<i class="lamp ${u.working_count > 0 ? "on" : ""}"></i><b class="${workChanged ? "flash" : ""}">${u.working_count}</b> kerja`;
  const tokChanged = prev != null && prev.today_total !== u.today_total;
  $("stat-tokens").innerHTML = `<b class="${tokChanged ? "flash" : ""}">${fmtTokens(u.today_total)}</b> tok today`;
  const models = Object.entries(u.per_model || {})
    .map(([m, n]) => `${esc(m)} ${fmtTokens(n)}`).join(" &middot; ");
  $("stat-models").innerHTML = models;
  STATE.prevUsage = { working_count: u.working_count, today_total: u.today_total };
}

function renderBanner() {
  const b = $("banner");
  const meta = STATE.snap?.meta;
  if (meta && meta.partial) {
    b.className = "banner warn show";
    b.textContent = "! data parsial: " + (meta.errors || []).join("; ");
  } else if (!STATE.ok) {
    b.className = "banner err show";
    b.textContent = STATE.snap
      ? "! server tidak terjangkau, menampilkan data terakhir"
      : "! menunggu server /api/snapshot...";
  } else {
    b.className = "banner";
  }
}

function findAgent(id) {
  const search = (list) => {
    for (const a of list) {
      if (a.id === id) return a;
      const hit = search(a.subagents || []);
      if (hit) return hit;
    }
    return null;
  };
  for (const r of STATE.snap?.rooms || []) {
    const hit = search(r.agents);
    if (hit) return hit;
  }
  return null;
}

function openAgent(id) { STATE.selected = id; STATE.openContent = null; renderSlideover(); }
function closeAgent() { STATE.selected = null; STATE.openContent = null; renderSlideover(); }
function toggleFilter(name) {
  STATE.filterRoom = STATE.filterRoom === name ? null : name;
  saveViewState();
  render();
}
function toggleExpand(id) {
  STATE.expandedAgent = STATE.expandedAgent === id ? null : id;
  saveViewState();
  render();
}

function onSearch(value) {
  STATE.query = value.trim().toLowerCase();
  render();
}

function saveViewState() {
  try {
    localStorage.setItem("voffice.filterRoom", STATE.filterRoom || "");
    localStorage.setItem("voffice.expandedAgent", STATE.expandedAgent || "");
  } catch (e) { /* penyimpanan tak tersedia: abaikan */ }
}

function openInsights() { STATE.insightsOpen = true; loadInsights(); }
function closeInsights() { STATE.insightsOpen = false; renderInsights(); }
function setInsightsScope(scope) { STATE.insightsScope = scope; loadInsights(); }

function loadInsights() {
  renderInsights();
  fetch(`/api/intelligence?scope=${encodeURIComponent(STATE.insightsScope)}`)
    .then((r) => (r.ok ? r.json() : { error: "http " + r.status }))
    .then((d) => {
      if (STATE.insightsOpen) { STATE.insightsData = d; renderInsights(); }
    })
    .catch((e) => {
      if (STATE.insightsOpen) { STATE.insightsData = { error: String(e) }; renderInsights(); }
    });
}

function fmtBytes(n) {
  if (!n) return "0";
  if (n >= 1e9) return (n / 1e9).toFixed(2) + " GB";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + " MB";
  if (n >= 1e3) return Math.round(n / 1e3) + " kB";
  return n + " B";
}

function breakdown(d) {
  return `in ${fmtTokens(d.input)} &middot; out ${fmtTokens(d.output)} &middot; cc ${fmtTokens(d.cache_creation)} &middot; cr ${fmtTokens(d.cache_read)}`;
}

function rankRows(rows, cols) {
  return rows.map((r, i) => `<div class="rank-row">
    <div class="bar-fill" style="width:${r.share || 0}%"></div>
    <span class="rank-no">${String(i + 1).padStart(2, "0")}</span>
    ${cols(r)}
  </div>`).join("") || '<div class="empty">belum ada data</div>';
}

function renderInsights() {
  const el = $("insights-overlay");
  if (!STATE.insightsOpen) { el.className = "overlay"; el.innerHTML = ""; return; }
  const scope = STATE.insightsScope;
  const d = STATE.insightsData;
  let body;
  if (!d) body = '<div class="empty">menganalisa...</div>';
  else if (d.error) body = `<div class="empty">${esc(d.error)}</div>`;
  else {
    const sessions = rankRows(d.sessions || [], (r) =>
      `<span class="who">${esc(r.name)}</span><span class="detail">${esc(r.room)}${r.title ? " · " + esc(r.title) : ""}</span>
       <span class="detail">${breakdown(r)}</span><span class="total">${fmtTokens(r.total)} tok</span>`);
    const turns = rankRows(d.turns || [], (r) =>
      `<span class="who">${esc(r.name)}</span><span>${new Date(r.at).toLocaleString()}</span>
       <span class="detail">${breakdown(r)} · ${r.tool_calls} tool</span><span class="total">${fmtTokens(r.total)} tok</span>`);
    const tools = rankRows(d.tools || [], (r) =>
      `<span class="who">${esc(r.tool)}</span><span>${r.calls} calls</span>
       <span class="detail">output ${fmtBytes(r.output_bytes)} · est ${fmtTokens(r.est_tokens)} tok</span><span class="total">${fmtBytes(r.output_bytes)}</span>`);
    const partial = (d.errors || []).length
      ? `<div class="rank-note">data parsial: ${esc(d.errors.join("; "))}</div>` : "";
    body = `<div class="insights">
      <button class="close" onclick="closeInsights()">&times;</button>
      <h2>TOKEN INTELLIGENCE</h2>
      <p class="sub">siapa yang paling boros, dan komposisinya: cc = cache creation (konteks makin gemuk), cr = cache read (hemat, bukan bengkak)</p>
      <div class="scope-toggle">
        <button class="${scope === "all" ? "on" : ""}" onclick="setInsightsScope('all')">All time</button>
        <button class="${scope === "today" ? "on" : ""}" onclick="setInsightsScope('today')">Today</button>
      </div>
      ${partial}
      <div class="rank"><h3>Session terboros</h3>${sessions}</div>
      <div class="rank"><h3>Turn terboros</h3>${turns}</div>
      <div class="rank"><h3>Tool paling boros (ranking by output bytes; est token = bagian token turn-nya)</h3>${tools}</div>
    </div>`;
  }
  el.innerHTML = body;
  el.className = "overlay open";
}

function toggleContent(kind, id) {
  const key = kind + ":" + id;
  if (STATE.openContent === key) { STATE.openContent = null; renderSlideover(); return; }
  STATE.openContent = key;
  renderSlideover();
  if (!STATE.content[key]) {
    fetch(`/api/content/${kind}/${encodeURIComponent(id)}`)
      .then((r) => (r.ok ? r.json() : { error: "http " + r.status }))
      .then((d) => { STATE.content[key] = d; if (STATE.openContent === key) renderSlideover(); })
      .catch((e) => { STATE.content[key] = { error: String(e) }; if (STATE.openContent === key) renderSlideover(); });
  }
}

function trimmedNote(part) {
  return part && part.truncated ? `\n... dipotong dari ${part.total_chars} char` : "";
}

function contentBlock(data) {
  if (!data) return '<pre class="pre skel-loading"></pre>';
  if (data.error) return `<pre class="pre">${esc(data.error)}</pre>`;
  if (data.kind === "tool") {
    return `<div class="content">
      <div class="content-label">input</div>
      <pre class="pre">${esc(data.input ? data.input.content : "(kosong)")}${trimmedNote(data.input)}</pre>
      <div class="content-label">output</div>
      <pre class="pre">${esc(data.output ? data.output.content : "(kosong)")}${trimmedNote(data.output)}</pre>
    </div>`;
  }
  const entries = (data.entries || []).map((e) => {
    if (e.kind === "tool") {
      return `<div class="content-label">tool: ${esc(humanizeTool(e.tool))} · ${esc(e.status ?? "?")}</div>
        <pre class="pre">${esc(e.input ? e.input.content : "(kosong)")}</pre>
        <pre class="pre">${esc(e.output ? e.output.content : "(kosong)")}</pre>`;
    }
    return `<div class="content-label">${esc(e.kind)}${e.role ? " · " + esc(e.role) : ""}</div>
      <pre class="pre">${esc(e.content ?? "")}</pre>`;
  }).join("");
  return `<div class="content">${entries || '<div class="log-empty">kosong</div>'}</div>`;
}

function renderSlideover() {
  const el = $("slideover");
  const a = STATE.selected && findAgent(STATE.selected);
  if (!a) { el.className = "slideover"; el.innerHTML = ""; return; }
  const wasOpen = el.classList.contains("open");
  const c = COLORS[a.status] || COLORS.quiet;
  const kv = (label, value, wide = false) =>
    `<div class="kv-row${wide ? " wide" : ""}"><span class="k">${label}</span><span class="lead"></span><span class="v">${value}</span></div>`;
  const turns = (a.turns || []).slice().reverse().map((t) => {
    const tok = `<span class="mono">${fmtTokens(t.output_tokens)} tok</span>`;
    if (!t.turn_id) {
      return `<div class="list-row"><span><i class="dot" style="background:${STATUS_DOT[t.status] || "var(--gray)"}"></i> <span class="mono">${new Date(t.at).toLocaleTimeString()}</span></span><span class="lead"></span>${tok}</div>`;
    }
    const key = "turn:" + t.turn_id;
    const open = STATE.openContent === key;
    return `<div>
      <div class="list-row acc-head" onclick="toggleContent('turn', '${esc(t.turn_id)}')">
        <span><i class="dot" style="background:${STATUS_DOT[t.status] || "var(--gray)"}"></i> <span class="mono">${new Date(t.at).toLocaleTimeString()}</span></span>
        <span class="lead"></span>
        <span class="mono">${tok} <span class="chev rot${open ? " open" : ""}">▸</span></span>
      </div>
      ${open ? contentBlock(STATE.content[key]) : ""}
    </div>`;
  }).join("");
  const tools = (a.tools || []).slice().reverse().map((t) => {
    const meta = `<span class="mono">${t.status}${t.duration_ms != null ? " · " + Math.round(t.duration_ms / 1000) + "s" : ""}</span>`;
    if (!t.call_id) {
      return `<div class="list-row"><span>${esc(humanizeTool(t.tool))}</span><span class="lead"></span>${meta}</div>`;
    }
    const key = "tool:" + t.call_id;
    const open = STATE.openContent === key;
    return `<div>
      <div class="list-row acc-head" onclick="toggleContent('tool', '${esc(t.call_id)}')">
        <span>${esc(humanizeTool(t.tool))}</span>
        <span class="lead"></span>
        <span class="mono">${meta} <span class="chev rot${open ? " open" : ""}">▸</span></span>
      </div>
      ${open ? contentBlock(STATE.content[key]) : ""}
    </div>`;
  }).join("");
  const models = Object.entries(a.models || {})
    .map(([m, n]) => `<div class="list-row"><span>${esc(m)}</span><span class="lead"></span><span class="mono">${fmtTokens(n)} tok</span></div>`).join("");
  const pct = a.target_budget > 0 ? Math.min(100, Math.round(a.target_used / a.target_budget * 100)) : null;
  el.innerHTML = `
    <div class="so-label">// agent detail</div>
    <h2><span class="c-tag" style="color:${c};border-color:${c}66">${esc((a.name || "??").slice(0, 2).toUpperCase())}</span>${esc(a.title || "tanpa judul")}</h2>
    <div class="so-sub">
      ${roleBadge(a.role)}
      <i class="dot" style="background:${c}"></i>
      <span>${esc(a.status_detail)}${a.age_ms != null ? ` &middot; umur <b>${esc(fmtDuration(a.age_ms))}</b>` : ""}</span>
    </div>
    ${kv("agent", esc(a.name || a.short_name))}
    ${kv("model", esc(a.model ?? "-"))}
    ${kv("token total", `${fmtTokens(a.tokens)} tok`)}
    ${kv("tool calls", String(a.tool_calls))}
    ${a.error_count > 0 ? `<div class="kv-row wide"><span class="k">error</span><span class="lead"></span><span class="v err-text">${a.error_count} error tercatat</span></div>` : ""}
    ${a.objective ? `<div class="kv-row wide"><span class="k">objective</span><span class="lead"></span><span class="v">${esc(a.objective)}</span></div>` : ""}
    ${pct != null ? `<div class="kv-row wide"><span class="k">budget target</span><span class="lead"></span><span class="v">${fmtTokens(a.target_used)} / ${fmtTokens(a.target_budget)} tok (${pct}%)</span></div>
      <div class="bar" style="max-width:none"><div style="width:${pct}%;background:${c}"></div></div>` : ""}
    <div class="list"><h4>Turn terakhir</h4>${turns || '<div class="log-empty">kosong</div>'}</div>
    <div class="list"><h4>Tool calls</h4>${tools || '<div class="log-empty">kosong</div>'}</div>
    <div class="list"><h4>Per model</h4>${models || '<div class="log-empty">kosong</div>'}</div>
    ${a.subagents && a.subagents.length ? `<div class="list"><h4>Subagents (${a.subagents.length})</h4><div class="sub-rows">${a.subagents.map(subRow).join("")}</div></div>` : ""}`;
  // stagger konten cuma pas drawer baru kebuka, bukan tiap re-render
  el.className = "slideover open" + (wasOpen ? "" : " fresh");
  if (!wasOpen) {
    clearTimeout(freshTimer);
    freshTimer = setTimeout(() => el.classList.remove("fresh"), 900);
  }
}

function renderAge() { $("age").textContent = fmtAge(STATE.snap?.generated_at); }

function render() {
  const scrolls = [window.scrollY, $("feed-rows").scrollTop, $("slideover").scrollTop];
  renderTopbar();
  renderBanner();
  renderRooms();
  renderFeed();
  renderSlideover();
  window.scrollTo(0, scrolls[0]);
  $("feed-rows").scrollTop = scrolls[1];
  $("slideover").scrollTop = scrolls[2];
  renderAge();
}

function snapshotSig(snap) {
  return JSON.stringify([snap.rooms, snap.activity, snap.usage]);
}

async function tick() {
  const prev = STATE.snap;
  const prevOk = STATE.ok;
  try {
    const res = await fetch("/api/snapshot");
    if (!res.ok) throw new Error("http " + res.status);
    STATE.snap = await res.json();
    STATE.ok = true;
  } catch (e) {
    STATE.ok = false;
  }
  if (STATE.selected && !findAgent(STATE.selected)) STATE.selected = null;
  // render hanya saat data berubah: state UI (hover, seleksi, animasi) tidak dibuang tiap 3 detik
  if (!prev || prevOk !== STATE.ok || snapshotSig(prev) !== snapshotSig(STATE.snap)) render();
}

document.addEventListener("keydown", (e) => {
  if (e.key === "/" && !["INPUT", "TEXTAREA"].includes(e.target.tagName)) {
    e.preventDefault();
    $("search").focus();
  }
  if (e.key === "Escape") {
    closeAgent();
    closeInsights();
  }
});
// boot sequence: entrance animation sekali di render pertama, lalu dimatikan
document.body.classList.add("boot");
setTimeout(() => document.body.classList.remove("boot"), 1600);
try {
  STATE.filterRoom = localStorage.getItem("voffice.filterRoom") || null;
  STATE.expandedAgent = localStorage.getItem("voffice.expandedAgent") || null;
} catch (e) { /* penyimpanan tak tersedia: pakai default */ }
setInterval(tick, 3000);
setInterval(renderAge, 1000);
tick();
