"use strict";

const COLORS = { kerja: "#22c55e", idle: "#eab308", quiet: "#64748b", error: "#ef4444" };
const ROLE_COLORS = { Explore: "#38bdf8", judge: "#a78bfa", "general-purpose": "#34d399", agent: "#94a3b8" };
const STATUS_DOT = { ok: "var(--green)", error: "var(--red)", running: "var(--yellow)" };
const STATE = { snap: null, ok: true, filterRoom: null, selected: null, expandedAgent: null, openContent: null, content: {}, insightsOpen: false, insightsScope: "all", insightsData: null, query: "" };
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

function sparkline(values, color) {
  if (!values || values.length < 2) return "";
  const w = 76, h = 20, max = Math.max(...values, 1);
  const pts = values
    .map((v, i) => `${(i / (values.length - 1) * w).toFixed(1)},${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`)
    .join(" ");
  return `<svg width="${w}" height="${h}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
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
    <span class="dot ${s.status === "kerja" ? "pulse-kerja" : ""}" style="background:${c}"></span>
    <span class="who">${esc(s.name || s.short_name)}</span>
    ${roleBadge(s.role)}
    <span style="margin-left:auto">${fmtTokens(s.tokens)} tok</span>
  </div>`;
}

function agentRow(a) {
  const c = COLORS[a.status] || COLORS.quiet;
  const title = a.title || "tanpa judul";
  const err = a.error_count > 0 ? ` <span class="err-chip">${a.error_count} err</span>` : "";
  const meta = [a.name, fmtDuration(a.age_ms), a.status_detail, a.current_tool, a.model ?? "-",
    fmtTokens(a.tokens) + " tok", a.tool_calls + " tools"]
    .filter((x) => x != null && x !== "").map(esc).join(" &middot; ");
  const bar = a.target_budget > 0
    ? `<div class="bar"><div style="width:${Math.min(100, Math.round(a.target_used / a.target_budget * 100))}%;background:${c}"></div></div>`
    : "";
  return `<div class="agent" onclick="openAgent('${esc(a.id)}')">
    <div class="avatar ${a.status === "kerja" ? "pulse-kerja" : ""}" style="border-color:${c}">${esc((a.name || "?").slice(0, 2))}</div>
    <div class="a-main">
      <div class="a-tool">${esc(title)}${err}</div>
      <div class="a-meta">${meta}</div>
      ${bar}
    </div>
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
      return `<div>
        <span class="chip ${open ? "chip-open" : ""}" onclick="toggleExpand('${esc(a.id)}')">${esc(a.name || a.short_name)} + ${a.subagents.length} sub${roles ? " &middot; " + roles : ""}</span>
        ${open ? `<div class="sub-rows">${a.subagents.map(subRow).join("")}</div>` : ""}
      </div>`;
    })
    .join("");
  return `<div class="room">
    <div class="room-head ${active}" onclick="toggleFilter('${esc(r.name)}')">
      <span class="room-name">${esc(r.name)}</span>
      <span class="room-obj">${esc(r.objective ?? "")}</span>
      <span class="room-tok">${fmtTokens(r.tokens)} tok</span>
    </div>
    <div class="agents">${agents || '<div class="kv">kosong</div>'}</div>
    ${chips ? `<div class="subs">${chips}</div>` : ""}
  </div>`;
}

function skeletonCard() {
  const agent = `<div class="agent">
    <div class="skeleton" style="width:38px;height:38px;border-radius:50%"></div>
    <div class="a-main">
      <div class="skeleton" style="height:12px;width:70%;margin-bottom:6px"></div>
      <div class="skeleton" style="height:10px;width:45%"></div>
    </div>
  </div>`;
  return `<div class="room">
    <div class="skeleton" style="height:15px;width:40%;margin-bottom:12px"></div>
    ${agent}${agent}${agent}
  </div>`;
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
    $("rooms").innerHTML = `<div class="empty"><div class="empty-title">${esc(msg)}</div>
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
    $("rooms").innerHTML = `<div class="empty"><div class="empty-title">gak ada yang cocok buat "${esc(STATE.query)}"</div></div>`;
    return;
  }
  $("rooms").innerHTML = list.map(roomCard).join("");
}

function renderFeed() {
  $("feed-title").textContent = STATE.filterRoom ? `Activity: ${STATE.filterRoom}` : "Activity";
  if (!STATE.snap) {
    $("feed-rows").innerHTML = Array.from({ length: 5 },
      () => '<div class="feed-row"><div class="skeleton" style="height:10px;width:85%"></div></div>').join("");
    return;
  }
  let rows = STATE.snap.activity
    .filter((x) => !STATE.filterRoom || x.room === STATE.filterRoom);
  if (STATE.query) {
    rows = rows.filter((x) => `${x.room}/${x.agent} ${x.tool}`.toLowerCase().includes(STATE.query));
  }
  $("feed-rows").innerHTML = rows.map((x) => {
    const c = STATUS_DOT[x.status] || "var(--gray)";
    const pulse = x.status === "running" ? " pulse-running" : "";
    const d = x.duration_ms != null ? ` (${Math.round(x.duration_ms / 1000)}s)` : "";
    return `<div class="feed-row"><span class="dot${pulse}" style="background:${c}"></span>
      <span class="who">${esc(x.room)}/${esc(x.agent)}</span><span>${esc(x.tool)}${d}</span></div>`;
  }).join("") || (STATE.query ? '<div class="kv">gak ada aktivitas yang cocok</div>'
    : '<div class="kv">belum ada aktivitas</div>');
}

function renderTopbar() {
  const u = STATE.snap?.usage;
  $("stat-working").innerHTML = u ? `<b>${u.working_count}</b> agent kerja` : "";
  document.title = u && u.working_count > 0 ? `(${u.working_count}) Voidlight Office` : "Voidlight Office";
  if (!u) { $("stat-tokens").innerHTML = ""; return; }
  const models = Object.entries(u.per_model || {})
    .map(([m, n]) => `${esc(m)} ${fmtTokens(n)}`).join(" &middot; ");
  $("stat-tokens").innerHTML = `<b>${fmtTokens(u.today_total)}</b> tok today${models ? " &middot; " + models : ""}`;
}

function renderBanner() {
  const b = $("banner");
  const meta = STATE.snap?.meta;
  if (meta && meta.partial) {
    b.className = "banner warn show";
    b.textContent = "data parsial: " + (meta.errors || []).join("; ");
  } else if (!STATE.ok) {
    b.className = "banner err show";
    b.textContent = STATE.snap
      ? "server tidak terjangkau, menampilkan data terakhir"
      : "menunggu server /api/snapshot...";
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
    <div class="bar-bg"></div><div class="bar-fill" style="width:${r.share || 0}%"></div>
    <span class="rank-no">${i + 1}</span>
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
      `<span class="who">${esc(r.name)}</span><span>${esc(r.room)}${r.title ? " · " + esc(r.title) : ""}</span>
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
      <button class="close" onclick="closeInsights()">x</button>
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
      return `<div class="content-label">tool: ${esc(e.tool)} · ${esc(e.status ?? "?")}</div>
        <pre class="pre">${esc(e.input ? e.input.content : "(kosong)")}</pre>
        <pre class="pre">${esc(e.output ? e.output.content : "(kosong)")}</pre>`;
    }
    return `<div class="content-label">${esc(e.kind)}${e.role ? " · " + esc(e.role) : ""}</div>
      <pre class="pre">${esc(e.content ?? "")}</pre>`;
  }).join("");
  return `<div class="content">${entries || '<div class="kv">kosong</div>'}</div>`;
}

function renderSlideover() {
  const el = $("slideover");
  const a = STATE.selected && findAgent(STATE.selected);
  if (!a) { el.className = "slideover"; el.innerHTML = ""; return; }
  const c = COLORS[a.status] || COLORS.quiet;
  const turns = (a.turns || []).slice().reverse().map((t) => {
    if (!t.turn_id) {
      return `<div class="list-row"><span><span class="dot" style="background:${STATUS_DOT[t.status] || "var(--gray)"}"></span> ${new Date(t.at).toLocaleTimeString()}</span><span>${fmtTokens(t.output_tokens)} tok</span></div>`;
    }
    const key = "turn:" + t.turn_id;
    const open = STATE.openContent === key;
    return `<div>
      <div class="list-row acc-head" onclick="toggleContent('turn', '${esc(t.turn_id)}')">
        <span><span class="dot" style="background:${STATUS_DOT[t.status] || "var(--gray)"}"></span> ${new Date(t.at).toLocaleTimeString()}</span>
        <span>${fmtTokens(t.output_tokens)} tok <span class="chev">${open ? "▾" : "▸"}</span></span>
      </div>
      ${open ? contentBlock(STATE.content[key]) : ""}
    </div>`;
  }).join("");
  const tools = (a.tools || []).slice().reverse().map((t) => {
    if (!t.call_id) {
      return `<div class="list-row"><span>${esc(t.tool)}</span><span>${t.status}${t.duration_ms != null ? " &middot; " + Math.round(t.duration_ms / 1000) + "s" : ""}</span></div>`;
    }
    const key = "tool:" + t.call_id;
    const open = STATE.openContent === key;
    return `<div>
      <div class="list-row acc-head" onclick="toggleContent('tool', '${esc(t.call_id)}')">
        <span>${esc(t.tool)}</span>
        <span>${t.status}${t.duration_ms != null ? " &middot; " + Math.round(t.duration_ms / 1000) + "s" : ""} <span class="chev">${open ? "▾" : "▸"}</span></span>
      </div>
      ${open ? contentBlock(STATE.content[key]) : ""}
    </div>`;
  }).join("");
  const models = Object.entries(a.models || {})
    .map(([m, n]) => `<div class="list-row"><span>${esc(m)}</span><span>${fmtTokens(n)} tok</span></div>`).join("");
  const pct = a.target_budget > 0 ? Math.min(100, Math.round(a.target_used / a.target_budget * 100)) : null;
  el.innerHTML = `
    <button class="close" onclick="closeAgent()">x</button>
    <h2><span class="avatar" style="border-color:${c}">${esc((a.name || "?").slice(0, 2))}</span>${esc(a.title || "tanpa judul")}</h2>
    <div class="kv">agent: <b>${esc(a.name || a.short_name)}</b> &middot; ${esc(a.short_name ?? "")}</div>
    <div class="kv">role: ${roleBadge(a.role)}</div>
    <div class="kv">status: <b>${esc(a.status_detail)}</b>${a.age_ms != null ? ` &middot; umur <b>${fmtDuration(a.age_ms)}</b>` : ""}</div>
    <div class="kv">model: ${esc(a.model ?? "-")}</div>
    ${a.error_count > 0 ? `<div class="kv">error: <b class="err-text">${a.error_count}</b></div>` : ""}
    <div class="kv">token total: <b>${fmtTokens(a.tokens)}</b> &middot; ${a.tool_calls} tool calls</div>
    ${a.objective ? `<div class="kv">objective: ${esc(a.objective)}</div>` : ""}
    ${pct != null ? `<div class="bar" style="max-width:220px"><div style="width:${pct}%;background:${c}"></div></div>
      <div class="kv">${fmtTokens(a.target_used)} / ${fmtTokens(a.target_budget)} tok (${pct}%)</div>` : ""}
    <div class="list"><h4>Turn terakhir</h4>${turns || '<div class="kv">kosong</div>'}</div>
    <div class="list"><h4>Tool calls</h4>${tools || '<div class="kv">kosong</div>'}</div>
    <div class="list"><h4>Per model</h4>${models || '<div class="kv">kosong</div>'}</div>
    ${a.subagents && a.subagents.length ? `<div class="list"><h4>Subagents (${a.subagents.length})</h4><div class="sub-rows">${a.subagents.map(subRow).join("")}</div></div>` : ""}`;
  el.className = "slideover open";
}

function renderAge() { $("age").textContent = fmtAge(STATE.snap?.generated_at); }

function render() {
  const scrolls = [window.scrollY, $("feed").scrollTop, $("slideover").scrollTop];
  renderTopbar();
  renderBanner();
  renderRooms();
  renderFeed();
  renderSlideover();
  window.scrollTo(0, scrolls[0]);
  $("feed").scrollTop = scrolls[1];
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
  if (e.key === "Escape") {
    closeAgent();
    closeInsights();
  }
});
try {
  STATE.filterRoom = localStorage.getItem("voffice.filterRoom") || null;
  STATE.expandedAgent = localStorage.getItem("voffice.expandedAgent") || null;
} catch (e) { /* penyimpanan tak tersedia: pakai default */ }
setInterval(tick, 3000);
setInterval(renderAge, 1000);
tick();
