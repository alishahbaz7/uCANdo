"use strict";

const $ = (id) => document.getElementById(id);
const api = (path, opts) =>
  fetch(path, { headers: { "Content-Type": "application/json" }, ...opts }).then((r) => r.json());
const apiUpload = (path, file) => {
  const fd = new FormData();
  fd.append("file", file);
  return fetch(path, { method: "POST", body: fd }).then((r) => r.json());
};
const POST = (p, body) => api(p, { method: "POST", body: body ? JSON.stringify(body) : undefined });

const state = { connected: false, recording: false, view: "dashboard" };
let pollTimer = null;

// ---- shared inline SVG icon set (Feather-style) ----
const _ico = (b, extra = "") => `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"${extra}>${b}</svg>`;
const ICONS = {
  power: _ico('<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/>'),
  record: '<svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="6" fill="#e25555"/></svg>',
  play: '<svg class="ico" viewBox="0 0 24 24"><polygon points="6 4 20 12 6 20 6 4" fill="currentColor"/></svg>',
  pause: _ico('<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>'),
  stop: _ico('<rect x="6" y="6" width="12" height="12" rx="1.5"/>'),
  step: '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 4 15 12 5 20 5 4" fill="currentColor"/><line x1="19" y1="5" x2="19" y2="19"/></svg>',
  refresh: _ico('<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>'),
  chevronDown: _ico('<polyline points="6 9 12 15 18 9"/>'),
  chevronUp: _ico('<polyline points="18 15 12 9 6 15"/>'),
  close: _ico('<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>'),
  check: _ico('<polyline points="20 6 9 17 4 12"/>'),
  arrowRight: _ico('<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>'),
  upload: _ico('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>'),
  download: _ico('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'),
  clipboard: _ico('<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/>'),
  grid: _ico('<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/>'),
  alert: _ico('<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'),
};
// Back-compat aliases used by the topbar renderer
const ICON_POWER = ICONS.power, ICON_RECORD = ICONS.record, ICON_STOP = ICONS.stop;
const _bigGrid = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="width:30px;height:30px;color:var(--accent)"><rect x="3" y="3" width="18" height="18" rx="3"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/></svg>';

// Populate version chip from API
api("/api/info").then((d) => {
  const chip = $("verChip");
  if (chip) chip.textContent = `v${d.version} · ${d.app}`;
});

// Each view: a short fixed title + a one-line description.
const VIEW_META = {
  dashboard: { t: "Dashboard", d: "Live values decoded from standard protocols (OBD-II, J1939) — no DBC required." },
  logger: { t: "CAN Logger", d: "Live capture with per-ID stats and recording to .asc / .blf / .csv." },
  replay: { t: "TX Replay", d: "Play a recorded log back onto the bus with speed, loop, and step control." },
  re: { t: "Reverse Engineering", d: "Find candidate signals in an unknown log — entropy, bit-flip rate, sniffer, OBD correlation." },
  autore: { t: "Auto-RE", d: "Confidence-tiered (A/B/C) identification: CANMatch, OBD correlation, and known-value matching." },
  framedec: { t: "Frame Decoder", d: "Decode raw CAN frames against a DBC or JSON signature — byte, bit, and signal view." },
  convert: { t: "Converter", d: "Convert a signal database among DBC, Signature JSON, and CSV in any direction." },
  dbc: { t: "DBC Builder", d: "Edit messages and signals, then round-trip to a .dbc file." },
  oem: { t: "OEM Database", d: "Store, fingerprint, and auto-apply vehicle DBC profiles (CANMatch)." },
  signals: { t: "Signal Viewer", d: "Live DBC decode into strip charts, with computed signals and alarms." },
  scheduler: { t: "TX Scheduler", d: "Transmit cyclic or one-shot frames on the bus." },
  automation: { t: "Automation", d: "Rules, scheduled jobs, restbus simulation, and scripting." },
  dtc: { t: "DTC Codes", d: "Read and clear trouble codes — OBD-II, UDS, and J1939." },
  decoder: { t: "Protocol Decoder", d: "Live OBD-II / UDS (ISO-TP) / J1939 frame interpretation." },
};
function setViewMeta(view) {
  const m = VIEW_META[view] || { t: view, d: "" };
  $("viewTitle").textContent = m.t;
  const desc = $("viewDesc");
  desc.textContent = m.d;
  desc.title = m.d;
}

// ---------------------------------------------------------------- navigation
document.querySelectorAll(".nav").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const view = btn.dataset.view;
    state.view = view;
    document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
    $("view-" + view).classList.remove("hidden");
    setViewMeta(view);
    startPolling(view);
    if (view === "replay" || view === "re") refreshLogs();
    if (view === "dbc") renderDbc();
    if (view === "logger") loadLogDir();
    if (view === "autore") initAutoRE();
    if (view === "oem") renderOem();
    if (view === "automation") renderAutomation();
    if (view === "scheduler") pollTx();
  });
});

function startPolling(view) {
  if (pollTimer) clearInterval(pollTimer);
  if (view === "dashboard") pollTimer = setInterval(pollDashboard, 400);
  else if (view === "signals") pollTimer = setInterval(pollSignals, 400);
  else if (view === "scheduler") pollTimer = setInterval(pollTx, 700);
  else if (view === "dtc") pollTimer = setInterval(pollDtc, 700);
  else if (view === "decoder") pollTimer = setInterval(pollDecode, 500);
}
function setStatus(t) { $("statusText").textContent = t; }

// ------------------------------------------------------------- connect/record
async function loadDevices() {
  const { devices } = await api("/api/devices");
  $("devSelect").innerHTML = devices
    .map((d) => `<option value='${JSON.stringify({ hw: d.hw, channel: d.channel })}'>${d.label}</option>`)
    .join("");
}
$("btnConnect").addEventListener("click", async () => {
  if (state.connected) return void POST("/api/disconnect");
  $("connectError").classList.add("hidden");
  await loadDevices();
  $("connectModal").classList.remove("hidden");
});
$("btnRefreshDevs").addEventListener("click", loadDevices);
$("btnCancelConnect").addEventListener("click", () => $("connectModal").classList.add("hidden"));
$("btnDoConnect").addEventListener("click", async () => {
  const dev = JSON.parse($("devSelect").value);
  const res = await POST("/api/connect", {
    hw: dev.hw, channel: dev.channel,
    bitrate: parseInt($("bitrateSelect").value, 10), simulate: $("simCheck").checked,
  });
  if (res.ok) $("connectModal").classList.add("hidden");
  else { const e = $("connectError"); e.textContent = res.error || "Connection failed"; e.classList.remove("hidden"); }
});
$("btnRecord").addEventListener("click", async () => {
  if (state.recording) {
    const r = await POST("/api/logger/record/stop");
    if (r.path) setStatus(`Saved ${r.frames} frames → ${r.path}`);
    return;
  }
  $("recordModal").classList.remove("hidden");
});
$("btnCancelRecord").addEventListener("click", () => $("recordModal").classList.add("hidden"));
$("btnDoRecord").addEventListener("click", async () => {
  const r = await POST("/api/logger/record/start", { name: $("recName").value || "capture", format: $("recFormat").value });
  $("recordModal").classList.add("hidden");
  setStatus(r.ok ? "Recording → " + r.path : "Record error: " + (r.error || "?"));
});
$("btnClear").addEventListener("click", () => POST("/api/logger/clear"));

// ----------------------------------------------------------------- CAN Logger
const fmtPeriod = (ms) => (!ms ? "—" : ms >= 1000 ? (ms / 1000).toFixed(2) + " s" : ms.toFixed(1) + " ms");

function renderLogger(snap) {
  state.connected = !!snap.connected;
  state.recording = !!snap.recording;
  const chip = $("hwChip");
  chip.dataset.state = state.connected ? "on" : "off";
  $("hwChipText").textContent = state.connected ? "Connected" : "Not connected";
  $("btnConnect").innerHTML = ICON_POWER + `<span>${state.connected ? "Disconnect" : "Connect"}</span>`;
  $("btnRecord").disabled = !state.connected;
  $("btnRecord").dataset.on = state.recording ? "1" : "0";
  $("btnRecord").innerHTML = (state.recording ? ICON_STOP : ICON_RECORD) + `<span>${state.recording ? "Stop" : "Record"}</span>`;
  $("recBadge").classList.toggle("hidden", !state.recording);

  if (snap.replay) renderReplay(snap.replay);
  if (!snap.running) { if (state.view === "logger") setStatus(state.connected ? "Connected · idle" : "Ready"); return; }

  $("statTotal").textContent = (snap.total || 0).toLocaleString();
  $("statIds").textContent = snap.unique_ids || 0;
  $("statFps").textContent = snap.fps || 0;
  $("statLoad").textContent = (snap.bus_load_pct || 0) + "%";
  $("statElapsed").textContent = (snap.elapsed_s || 0).toFixed(1) + "s";
  $("recInfo").textContent = state.recording ? `REC ${snap.record_frames} frames` : "";
  if (state.view === "logger") setStatus("Capturing");

  $("idTable").querySelector("tbody").innerHTML = (snap.ids || []).map((s) => `
    <tr><td class="mono">0x${s.id_hex}</td><td><span class="tag">${s.ext ? "EXT" : "STD"}</span></td>
    <td>${s.dlc}</td><td>${s.count.toLocaleString()}</td><td>${fmtPeriod(s.period_ms)}</td>
    <td class="mono">${s.data || ""}</td></tr>`).join("");
  $("feedTable").querySelector("tbody").innerHTML = (snap.recent || []).map((f) => `
    <tr><td>${f.ts.toFixed(3)}</td><td>0x${f.id_hex}</td><td>${f.dlc}</td><td>${f.data}</td></tr>`).join("");
}

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
  ws.onmessage = (e) => { try { renderLogger(JSON.parse(e.data)); } catch (_) {} };
  ws.onclose = () => setTimeout(connectWS, 1000);
}
connectWS();

// ------------------------------------------------------------------ TX Replay
async function refreshLogs() {
  const { logs } = await api("/api/logs");
  const opts = logs.length
    ? logs.map((l) => `<option value="${l.path}">${l.name} (${(l.size / 1024).toFixed(0)} KB)</option>`).join("")
    : `<option value="">— no logs yet (record one first) —</option>`;
  ["replaySelect", "reSelect", "cmpA", "cmpB", "autoreSelect"].forEach((id) => { if ($(id)) $(id).innerHTML = opts; });
  loadReEngines();
}
let reEnginesLoaded = false;
async function loadReEngines() {
  if (reEnginesLoaded || !$("reEngine")) return;
  const { engines } = await api("/api/re/engines");
  if (!engines) return;
  $("reEngine").innerHTML = engines
    .map((e) => `<option value="${e.name}" title="${e.description || ""}">${e.name}</option>`).join("");
  reEnginesLoaded = true;
}
$("btnReplayRescan").addEventListener("click", refreshLogs);
$("btnReRescan").addEventListener("click", refreshLogs);
$("btnReplayUpload").addEventListener("click", () => $("replayFile").click());
$("replayFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const r = await apiUpload("/api/upload", f);
  await refreshLogs();
  if (r.path) { $("replaySelect").value = r.path; loadReplay(); }
});
$("replaySelect").addEventListener("change", loadReplay);
async function loadReplay() {
  const path = $("replaySelect").value; if (!path) return;
  const r = await POST("/api/replay/load", { path });
  if (r.ok) $("replayMeta").textContent =
    `${r.meta.frames} frames · ${r.meta.duration_s}s · ${r.meta.ids.length} IDs · ch ${r.meta.channels.join("+") || "?"}`;
  else $("replayMeta").textContent = r.error;
}
$("btnPlay").addEventListener("click", () =>
  POST("/api/replay/play", { speed: parseFloat($("speedRange").value), loop: $("replayLoop").checked })
    .then((r) => { if (!r.ok) setStatus(r.error); }));
$("btnPause").addEventListener("click", () => POST("/api/replay/pause"));
$("btnStop").addEventListener("click", () => POST("/api/replay/stop"));
$("btnStep").addEventListener("click", () => POST("/api/replay/step"));
$("speedRange").addEventListener("input", () => {
  $("speedLabel").textContent = parseFloat($("speedRange").value).toFixed(1) + "×";
});
function renderReplay(s) {
  $("replayState").textContent = s.state;
  $("replayBar").style.width = (s.progress * 100).toFixed(1) + "%";
  $("replayCursor").textContent = `${s.cursor_s.toFixed(3)} s · ${s.sent} sent · ${s.cursor}/${s.total}`;
}

// -------------------------------------------------------- Reverse Engineering
let lastRe = null;
function entropyColor(h) {  // 0 (blue, constant) → 8 (red, noisy)
  const t = Math.min(1, h / 8);
  const r = Math.round(40 + 200 * t), g = Math.round(120 * (1 - Math.abs(t - 0.5) * 2)), b = Math.round(220 * (1 - t));
  return `rgb(${r},${g + 60},${b})`;
}
const KIND_COLOR = {
  counter: "#7bd88f", crc: "#e06c75", physical: "#61afef",
  "multi-state": "#e5c07b", constant: "#6b7280", event: "#c678dd",
};
function candChip(c) {
  const col = KIND_COLOR[c.kind] || "#9aa0a6";
  const conf = c.confidence != null ? ` ${Math.round(c.confidence * 100)}%` : "";
  const order = c.byte_order === "little_endian" ? " LE" : "";
  const step = c.step != null ? ` +${c.step}` : "";
  return `<span class="cand-chip" title="${c.kind}${order} · bit ${c.start_bit} len ${c.length}${step}"
    style="border-color:${col};color:${col}">${c.kind}${order} @${c.start_bit}/${c.length}${step}${conf}</span>`;
}

$("btnAnalyze").addEventListener("click", async () => {
  const path = $("reSelect").value; if (!path) return;
  const engine = $("reEngine") ? $("reEngine").value || "read" : "read";
  setStatus(`Analyzing ${path} (${engine}) …`);
  const r = await POST("/api/re/analyze", { path, engine });
  if (!r.ok) return void setStatus("RE error: " + r.error);
  lastRe = r.result; setStatus("Analysis complete");
  $("reSummary").textContent = `${r.result.id_count} IDs · ${r.result.total_frames} frames · ${r.result.engine || engine}`;
  $("reTable").querySelector("tbody").innerHTML = r.result.ids.map((id, i) => {
    const ent = id.bytes.map((b) =>
      `<div class="ebyte" title="byte ${b.index}: ${b.kind}, H=${b.entropy}" style="background:${entropyColor(b.entropy)}">${b.entropy.toFixed(1)}</div>`).join("");
    const cands = id.candidates.map(candChip).join(" ") || "—";
    const mux = id.multiplexor ? ` <span class="cand-chip" style="border-color:#c678dd;color:#c678dd" title="multiplexor">mux@byte${id.multiplexor.selector_byte}</span>` : "";
    return `<tr><td class="mono">0x${id.id_hex}</td><td>${id.frames}</td><td>${id.period_ms} ms</td>
      <td>${id.length}</td><td><div class="entropy-row">${ent}</div></td><td>${cands}${mux}</td>
      <td><button class="btn-mini" onclick="seedDbc(${i})">${ICONS.arrowRight} DBC</button></td></tr>`;
  }).join("");
});
window.seedDbc = async (i) => {
  if (!lastRe) return;
  await POST("/api/dbc/seed", lastRe.ids[i]);
  setStatus(`Sent 0x${lastRe.ids[i].id_hex} to DBC Builder`);
};

// ----- shared "changed IDs" renderer for sniffer + compare -----------------
const changedStore = {};   // ns -> {id_hex -> id_result} for promote
function renderChanged(wrapId, ns, result) {
  changedStore[ns] = {};
  const rows = (result.changed || []).map((c) => {
    changedStore[ns][c.id_hex] = c;
    const bits = c.candidates.map((cd) => `<span class="cand-chip" style="border-color:#c678dd;color:#c678dd">@${cd.start_bit}/${cd.length}</span>`).join(" ");
    const bytes = c.changed_bytes.map((b) => `byte${b.index}: ${b.baseline.join("/")}→${b.after.join("/")}`).join("; ");
    return `<tr><td class="mono">0x${c.id_hex}</td><td>${bits}</td><td class="muted-line">${bytes}</td>
      <td><button class="btn-mini" onclick="promoteChanged('${ns}','${c.id_hex}')">${ICONS.arrowRight} DBC</button></td></tr>`;
  }).join("");
  const extra = [];
  if (result.new_ids && result.new_ids.length) extra.push(`new IDs: ${result.new_ids.map((x) => "0x" + x).join(", ")}`);
  if (result.removed_ids && result.removed_ids.length) extra.push(`gone: ${result.removed_ids.map((x) => "0x" + x).join(", ")}`);
  $(wrapId).innerHTML = `<table class="data-table"><thead><tr><th>ID</th><th>Changed bits</th><th>Bytes (before→after)</th><th></th></tr></thead>
    <tbody>${rows || `<tr><td colspan="4" class="muted-line" style="padding:14px">No bit changes detected.</td></tr>`}</tbody></table>
    ${extra.length ? `<div class="muted-line" style="padding:8px 14px">${extra.join(" · ")}</div>` : ""}`;
}
window.promoteChanged = async (ns, idHex) => {
  const id_result = changedStore[ns] && changedStore[ns][idHex];
  if (!id_result) return;
  await POST("/api/re/promote", { id_result });
  setStatus(`Promoted 0x${idHex} changes to DBC Builder`);
};

// ----- state-change sniffer -------------------------------------------------
function setSniffStatus(s) {
  $("sniffStatus").textContent = `${s.phase} · baseline ${s.baseline_frames}f/${s.baseline_ids}id · after ${s.after_frames}f/${s.after_ids}id`;
}
$("btnSniffArm").addEventListener("click", async () => {
  const r = await POST("/api/re/sniff/arm");
  if (!r.ok) return void setStatus("Sniffer: " + r.error);
  setSniffStatus(r); setStatus("Sniffer armed — perform the action now, then click step 2.");
});
$("btnSniffMark").addEventListener("click", async () => { setSniffStatus(await POST("/api/re/sniff/mark")); });
$("btnSniffStop").addEventListener("click", async () => { setSniffStatus(await POST("/api/re/sniff/stop")); });
$("btnSniffResult").addEventListener("click", async () => {
  const r = await api("/api/re/sniff/result");
  if (r && r.result) { renderChanged("sniffResultWrap", "sniff", r.result); setSniffStatus(r.result.status); }
});

// ----- compare two logs -----------------------------------------------------
$("btnCompare").addEventListener("click", async () => {
  const a = $("cmpA").value, b = $("cmpB").value;
  if (!a || !b) return void setStatus("Pick two logs to compare");
  setStatus("Comparing …");
  const r = await POST("/api/re/compare", { path_a: a, path_b: b });
  if (!r.ok) return void setStatus("Compare error: " + r.error);
  renderChanged("cmpResultWrap", "cmp", r.result);
  setStatus(`Compared · ${r.result.changed_id_count} IDs changed`);
});

// ----- LibreCAN correlation: auto-label vs OBD ground truth -----
const corrStore = {};
$("btnCorrelate").addEventListener("click", async () => {
  const path = $("reSelect").value; if (!path) return;
  setStatus("Correlating signals vs OBD ground truth …");
  const r = await POST("/api/re/correlate", { path });
  if (!r.ok) return void setStatus("Correlate error: " + r.error);
  const res = r.result;
  res.labeled_ids.forEach((d) => (corrStore[d.id_hex] = d));
  const rows = res.labeled_ids.map((d) => d.labeled.map((L) =>
    `<tr><td class="mono">0x${d.id_hex}</td><td>${L.label}</td><td>@${L.start_bit}/${L.length} ${L.byte_order === "little_endian" ? "LE" : "BE"}</td>
      <td>r=${L.r}</td><td>×${L.scale} ${L.offset >= 0 ? "+" : ""}${L.offset}</td>
      <td><button class="btn-mini" onclick="promoteCorr('${d.id_hex}')">${ICONS.arrowRight} DBC</button></td></tr>`).join("")).join("");
  $("corrResultWrap").innerHTML = `<table class="data-table"><thead><tr><th>ID</th><th>Label (OBD)</th><th>Bits</th><th>Fit</th><th>Scale/offset</th><th></th></tr></thead>
    <tbody>${rows || `<tr><td colspan="6" class="muted-line" style="padding:14px">No signals correlated above threshold. Capture must include OBD-II PID responses.</td></tr>`}</tbody></table>`;
  setStatus(`Correlated · ground truth: ${res.ground_truth.join(", ") || "none found"}`);
});
window.promoteCorr = async (idHex) => {
  const d = corrStore[idHex]; if (!d) return;
  await POST("/api/re/promote", { id_result: { ...d, candidates: d.labeled } });
  setStatus(`Promoted labelled signals for 0x${idHex} → DBC (with recovered scale/offset)`);
};

// ----------------------------------------------------------- OEM CAN Database
async function renderOem() {
  const { profiles } = await api("/api/oem/profiles");
  $("oemTable").querySelector("tbody").innerHTML = (profiles || []).map((p) => {
    const apply = p.id_count ? `<button class="btn-mini" onclick="oemApply(${p.id})">Apply</button>` : "";
    return `<tr><td>${p.oem}</td><td>${p.name}</td><td class="muted-line">${p.model || "—"}</td>
      <td>${p.id_count}</td><td><span class="tag">${p.status}</span></td>
      <td>${apply} <button class="btn-mini" onclick="oemDelete(${p.id})">${ICONS.close}</button></td></tr>`;
  }).join("") || `<tr><td colspan="6" class="muted-line" style="padding:14px">No profiles.</td></tr>`;
}
window.oemApply = async (id) => {
  const r = await POST("/api/oem/apply?pid=" + id);
  setStatus(r.ok ? `Applied profile → Signal Viewer (${r.signals ? r.signals.length : 0} signals)` : "Apply: " + r.error);
};
window.oemDelete = async (id) => { await POST("/api/oem/profile/delete?pid=" + id); renderOem(); };
$("btnOemRefresh").addEventListener("click", renderOem);
$("btnOemIdentify").addEventListener("click", async () => {
  const r = await api("/api/oem/identify");
  if (!r.ok) return void ($("oemIdentStatus").textContent = r.error);
  $("oemIdentStatus").textContent = `${r.observed_ids} IDs observed`;
  $("oemIdentWrap").innerHTML = `<table class="data-table"><thead><tr><th>Match</th><th>OEM</th><th>Score</th><th>IDs matched</th><th></th></tr></thead>
    <tbody>${(r.matches || []).map((m) => `<tr><td>${m.name}</td><td>${m.oem}</td>
      <td>${(m.score * 100).toFixed(0)}%</td><td>${m.matched}/${m.profile_ids}</td>
      <td><button class="btn-mini" onclick="oemApply(${m.profile_id})">Apply</button></td></tr>`).join("")
      || `<tr><td colspan="5" class="muted-line" style="padding:14px">No confident match — reverse-engineer it and save a new profile.</td></tr>`}</tbody></table>`;
});
$("btnOemAutoApply").addEventListener("click", async () => {
  const r = await POST("/api/oem/auto-apply");
  if (r.ok && r.applied) setStatus(`Auto-applied "${r.applied.name}" (${(r.match.score * 100).toFixed(0)}%) → Signal Viewer`);
  else setStatus(r.reason ? "No confident decodable match" : ("Auto-apply: " + (r.error || "?")));
  $("btnOemIdentify").click();
});
$("btnOemFromBuilder").addEventListener("click", async () => {
  const oem = $("oemSaveOem").value.trim(), name = $("oemSaveName").value.trim();
  if (!oem || !name) return void setStatus("Enter OEM and profile name");
  const r = await POST("/api/oem/from-builder", { oem, name });
  if (r.ok) { setStatus(`Saved profile "${name}"`); renderOem(); }
  else setStatus("Save: " + r.error);
});

// --------------------------------------------------------------- Automation
function renderAutomation() { renderRules(); renderJobs(); pollRestbus(); }
async function renderRules() {
  const t = await api("/api/rules");
  $("rulesWrap").innerHTML = `<table class="data-table"><thead><tr><th>Name</th><th>When</th><th>Action</th><th>Fired</th><th></th></tr></thead>
    <tbody>${(t.rules || []).map((r) => `<tr><td>${r.name}</td><td class="mono">${r.when}</td>
      <td>${r.action.type}</td><td>${r.fired}</td>
      <td><button class="btn-mini" onclick="delRule(${r.uid})">${ICONS.close}</button></td></tr>`).join("")
      || `<tr><td colspan="5" class="muted-line" style="padding:12px">No rules.</td></tr>`}</tbody></table>`;
  $("ruleEventsWrap").innerHTML = `<table class="data-table mono"><tbody>${(t.events || []).slice(0, 30).map((e) =>
    `<tr><td>${e.ts}</td><td>${e.rule}</td><td>${e.action}</td><td>${e.detail}</td></tr>`).join("")
    || `<tr><td class="muted-line" style="padding:12px">No events yet.</td></tr>`}</tbody></table>`;
}
$("btnRuleAdd").addEventListener("click", async () => {
  const when = $("ruleWhen").value.trim(); if (!when) return;
  const type = $("ruleActType").value, arg = $("ruleActArg").value.trim();
  let action = { type: "log", message: arg };
  if (type === "transmit") {
    const m = arg.match(/id\s*=\s*(\w+)\s+data\s*=\s*(.+)/i);
    action = m ? { type: "transmit", id: parseInt(m[1], 16), data: m[2] } : { type: "transmit", id: 0, data: "" };
  }
  const r = await POST("/api/rules/add", { name: $("ruleName").value.trim(), when, action });
  if (r.ok) { $("ruleName").value = $("ruleWhen").value = $("ruleActArg").value = ""; renderRules(); }
  else setStatus("Rule: " + r.error);
});
window.delRule = async (uid) => { await POST("/api/rules/remove?uid=" + uid); renderRules(); };

async function renderJobs() {
  const { jobs } = await api("/api/jobs");
  $("jobsWrap").innerHTML = `<table class="data-table"><thead><tr><th>Name</th><th>Kind</th><th>Schedule</th><th>Last run</th><th></th></tr></thead>
    <tbody>${(jobs || []).map((j) => `<tr><td>${j.name}</td><td>${j.kind}</td><td class="mono">${j.schedule || "manual"}</td>
      <td>${j.last_run ? new Date(j.last_run * 1000).toLocaleTimeString() : "—"}</td>
      <td><button class="btn-mini" onclick="runJob(${j.id})">Run</button> <button class="btn-mini" onclick="delJob(${j.id})">${ICONS.close}</button></td></tr>`).join("")
      || `<tr><td colspan="5" class="muted-line" style="padding:12px">No jobs.</td></tr>`}</tbody></table>`;
}
$("btnJobAdd").addEventListener("click", async () => {
  const name = $("jobName").value.trim() || "job"; const every = $("jobEvery").value.trim();
  await POST("/api/jobs/add", { name, kind: $("jobKind").value, schedule: every ? "every:" + every : "", spec: { duration_s: 5 } });
  $("jobName").value = $("jobEvery").value = ""; renderJobs();
});
window.runJob = async (id) => { const r = await POST("/api/jobs/run?jid=" + id); setStatus("Job: " + JSON.stringify(r.result || r)); renderJobs(); };
window.delJob = async (id) => { await POST("/api/jobs/remove?jid=" + id); renderJobs(); };

async function pollRestbus() {
  const s = await api("/api/restbus/status");
  $("restbusStatus").textContent = `${s.running ? "running" : "stopped"} · ${s.messages} msgs · ${s.sent} sent`;
}
$("btnRestbusBuilder").addEventListener("click", async () => { const r = await POST("/api/restbus/load-builder"); setStatus(r.ok ? `Restbus: ${r.messages} messages loaded` : "Restbus: " + r.error); pollRestbus(); });
$("btnRestbusStart").addEventListener("click", async () => { const r = await POST("/api/restbus/start"); if (!r.ok) setStatus("Restbus: " + r.error); pollRestbus(); });
$("btnRestbusStop").addEventListener("click", async () => { await POST("/api/restbus/stop"); pollRestbus(); });

$("btnScriptRun").addEventListener("click", async () => {
  const r = await POST("/api/script/run", { code: $("scriptCode").value });
  $("scriptOut").textContent = (r.error ? "ERROR: " + r.error + "\n" : "") + (r.logs || []).join("\n");
});

// ------------------------------------------------------ Auto-RE (A/B/C tiers)
async function initAutoRE() {
  refreshLogs();
  const p = await api("/api/autore/protocols");
  if ($("autoreProtocols")) $("autoreProtocols").textContent = (p.protocols || []).join(" · ");
  renderAutoRE(await api("/api/autore/report"));
}
$("btnAutoReRescan").addEventListener("click", refreshLogs);
$("btnAutoReAnalyze").addEventListener("click", async () => {
  const path = $("autoreSelect").value; if (!path) return;
  const known = {};
  if ($("autoreOdo").value.trim()) known["Odometer"] = $("autoreOdo").value.trim();
  if ($("autoreFuel").value.trim()) known["Fuel Level"] = $("autoreFuel").value.trim();
  $("autoreStatus").textContent = "Analyzing…";
  const r = await POST("/api/autore/analyze-log", { path, known_values: known });
  $("autoreStatus").textContent = r.ok ? "Done" : ("Error: " + r.error);
  if (r.ok) renderAutoRE(r.report);
});
function autoreLoc(s) {
  const sc = s.scale && s.scale !== 1 ? " ×" + s.scale : "";
  return `0x${s.id_hex} · bit ${s.start_bit}/${s.length} ${s.byte_order === "little_endian" ? "LE" : "BE"}${sc}`;
}
const _ref = (s) => encodeURIComponent(JSON.stringify(
  { frame_id: s.frame_id, start_bit: s.start_bit, length: s.length, byte_order: s.byte_order, ext: s.ext, label: s.label }));
function renderAutoRE(rep) {
  if (!rep) return;
  const c = rep.counts || { A: 0, B: 0, C: 0 };
  $("autoreACount").textContent = c.A + " confirmed";
  $("autoreBCount").textContent = c.B + " to review";
  $("autoreCCount").textContent = c.C + " fields";
  $("autoreA").innerHTML = `<table class="data-table"><thead><tr><th>Signal</th><th>Location</th><th>Conf</th><th>Source</th></tr></thead><tbody>` +
    (rep.A || []).map((s) => `<tr><td><b>${s.label || "—"}</b></td><td class="mono">${autoreLoc(s)}</td><td>${(s.confidence * 100).toFixed(0)}%</td><td class="muted-line">${s.sources.join(",")}</td></tr>`).join("") +
    `</tbody></table>`;
  $("autoreB").innerHTML = `<table class="data-table"><thead><tr><th>Guess (editable)</th><th>Location</th><th>Conf</th><th></th></tr></thead><tbody>` +
    (rep.B || []).map((s, i) => `<tr><td><input id="blbl${i}" value="${s.label || ""}" style="width:140px"/></td>
      <td class="mono">${autoreLoc(s)}</td><td>${(s.confidence * 100).toFixed(0)}%</td>
      <td><button class="btn-mini btn-ico" onclick="autoreConfirm('${_ref(s)}',${i})">${ICONS.check}<span>Confirm</span></button>
          <button class="btn-mini btn-ico" onclick="autoreReject('${_ref(s)}')">${ICONS.close}<span>Reject</span></button></td></tr>`).join("") +
    `</tbody></table>`;
  $("autoreC").innerHTML = `<table class="data-table"><thead><tr><th>Location</th><th>Behaviour</th></tr></thead><tbody>` +
    (rep.C || []).slice(0, 40).map((s) => `<tr><td class="mono">${autoreLoc(s)}</td><td class="muted-line">${s.kind || s.sources.join(",")}</td></tr>`).join("") +
    `</tbody></table>` + ((rep.C || []).length > 40 ? `<div class="muted-line" style="padding:6px">+${rep.C.length - 40} more</div>` : "");
}
window.autoreConfirm = async (ref, i) => {
  const s = JSON.parse(decodeURIComponent(ref));
  const edited = $("blbl" + i); if (edited && edited.value.trim()) s.label = edited.value.trim();
  const r = await POST("/api/autore/confirm", s);
  if (r.ok) { renderAutoRE(r.report); setStatus(`Confirmed ${s.label || "signal"} → tier A`); }
};
window.autoreReject = async (ref) => {
  const r = await POST("/api/autore/reject", JSON.parse(decodeURIComponent(ref)));
  if (r.ok) renderAutoRE(r.report);
};
$("btnAutoReSave").addEventListener("click", async () => {
  const oem = $("autoreOem").value.trim(), name = $("autoreName").value.trim();
  if (!oem || !name) return void setStatus("Enter OEM + profile name");
  const r = await POST("/api/autore/save-profile", { oem, name, tiers: ["A"] });
  setStatus(r.ok ? `Saved profile "${name}" (id ${r.id})` : "Save: " + r.error);
});

// --------------------------- Frame Decoder (per-ID editable payloads + grid)
let fdMessages = [], fdPayloads = {}, fdDetail = null, fdSelSig = -1, fdTimer = null, fdCurrentDetailId = null;
let fdSource = "dbc";   // "dbc" → show IDs in hex; "json" → show IDs in decimal (native)
// Display the CAN ID in its source's native base. `o` is a catalogue row or a decoded frame.
const fdIdLabel = (o) => fdSource === "json" ? `${o.id}` : `0x${o.id_hex}`;
// Group a clean hex string into space-separated bytes: "0128C3" → "01 28 C3".
const spaceHex = (h) => (h.match(/.{1,2}/g) || []).join(" ");
// Raw bit-pattern as hex, zero-padded to the signal's bit width (e.g. 24-bit → "0x0128C3").
function fdRawHex(s) {
  if (s.raw === null || s.raw === undefined) return "—";
  const nib = Math.max(1, Math.ceil((s.length || 8) / 4));
  const hex = Math.abs(s.raw).toString(16).toUpperCase().padStart(nib, "0");
  return (s.raw < 0 ? "-0x" : "0x") + hex;
}
$("btnFdUpload").addEventListener("click", () => $("fdFile").click());
$("btnFdToggleFill").addEventListener("click", () => {
  const box = $("fdFillBox");
  box.classList.toggle("hidden");
  $("btnFdToggleFill").classList.toggle("active", !box.classList.contains("hidden"));
});

function _fdLoaded(filename, messages) {
  fdMessages = messages; fdPayloads = {};
  fdMessages.forEach((m) => (fdPayloads[m.id_hex] = "00".repeat(m.length)));
  // Paste-dump example IDs match the active source's base (decimal for JSON).
  const fill = $("fdFill");
  if (fill) fill.placeholder = fdSource === "json"
    ? "912  0128C30000000000\n900  0205000000000200"
    : "163  0205000000000200\n94   0006320040001C00";
  $("fdDbcStatus").textContent = `${filename} — ${fdMessages.length} messages`;
  $("fdMsgCount").textContent = `${fdMessages.length} IDs`;
  fdDetail = null; fdCurrentDetailId = null;
  $("fdDetailHeader").innerHTML = "";
  $("fdDetailBody").innerHTML = `<div class="fd-placeholder">${_bigGrid}<span>Click a message row to decode</span></div>`;
  renderFdCatalogue();
}

$("fdFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  // Auto-detect format from the file extension (.json → signature, else DBC).
  const isJson = (f.name.split(".").pop() || "").toLowerCase() === "json";
  $("fdDbcStatus").textContent = "Loading…";
  const r = await apiUpload(isJson ? "/api/decode/json-import" : "/api/decode/dbc-import", f);
  if (!r.ok) return void ($("fdDbcStatus").textContent = "error: " + r.error);
  fdSource = isJson ? "json" : "dbc";
  _fdLoaded(f.name, r.messages);
  e.target.value = "";          // allow re-uploading the same file
});
function renderFdCatalogue() {
  $("fdCatalogue").innerHTML =
    `<table class="data-table"><colgroup>
      <col class="c-num"><col class="c-id"><col class="c-dlc"><col class="c-sigs">
    </colgroup><thead><tr>
      <th style="text-align:center">#</th>
      <th>CAN ID${fdSource === "json" ? " (dec)" : ""} · Message</th>
      <th style="text-align:center">DLC</th>
      <th>Signals</th>
    </tr></thead><tbody>` +
    fdMessages.map((m, i) => {
      const sigList = m.signals.join(", ") || "—";
      return `<tr data-id="${m.id_hex}">
        <td>${i + 1}</td>
        <td class="mono" style="font-weight:500">${fdIdLabel(m)}&thinsp;<span style="color:var(--muted);font-weight:400;font-family:inherit">· ${m.name}</span></td>
        <td style="text-align:center">${m.length}</td>
        <td class="muted-line" style="font-size:12px" title="${sigList}">${m.signals.length}: ${sigList}</td>
      </tr>`;
    }).join("") + `</tbody></table>`;
}
$("fdCatalogue").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]"); if (tr) fdDecodeOne(tr.dataset.id);
});
async function fdDecodeOne(idHex) {
  const r = await POST("/api/decode/frames", { frames: [{ id: idHex, data: fdPayloads[idHex] || "" }] });
  if (!r.ok || !r.frames.length) return;
  fdDetail = r.frames[0]; fdSelSig = -1; renderFdDetail();
  document.querySelectorAll("#fdCatalogue tr[data-id]").forEach((tr) => tr.classList.toggle("sel", tr.dataset.id === idHex));
}
window.fdSelectSig = (si) => { fdSelSig = si; if (fdDetail) fdRenderBody(fdDetail); };
function renderFdDetail() {
  const f = fdDetail;
  if (!f) {
    fdCurrentDetailId = null;
    $("fdDetailHeader").innerHTML = "";
    $("fdDetailBody").innerHTML = `<div class="fd-placeholder">${_bigGrid}<span>Click a message row to decode</span><span class="muted-line" style="font-size:12px">Byte view · Signal table · Bit grid will appear here</span></div>`;
    return;
  }
  if (f.error) {
    fdCurrentDetailId = null;
    $("fdDetailHeader").innerHTML = "";
    $("fdDetailBody").innerHTML = `<div style="padding:16px;color:var(--muted)">${fdIdLabel(f)} — ${f.error}</div>`;
    return;
  }
  // Re-render header only when the selected message changes (preserves input focus while typing)
  if (fdCurrentDetailId !== f.id_hex) {
    fdCurrentDetailId = f.id_hex;
    $("fdDetailHeader").innerHTML = `
      <div class="panel-head">
        <span class="mono" style="font-weight:500">${fdIdLabel(f)}&thinsp;<span style="color:var(--muted);font-weight:400;font-family:inherit">· ${f.name}</span></span>
        <span class="tag" style="font-size:11px">DLC ${f.length}</span>
      </div>
      <div class="fd-pay-bar">
        <span class="muted-line" style="font-size:12px;white-space:nowrap">Payload (hex)</span>
        <input id="fdPayInput" class="fdpay" value="${spaceHex(fdPayloads[f.id_hex] || "")}"
          placeholder="${spaceHex("00".repeat(f.length))}"
          maxlength="${f.length * 3}"
          autocomplete="off" spellcheck="false" />
        <span id="fdPayHint" class="muted-line" style="font-size:11px;white-space:nowrap">0 / ${f.length} bytes</span>
      </div>`;
    $("fdPayInput").addEventListener("input", (e) => {
      const inp = e.target;
      // Strip to hex-only, cap at DLC bytes, then auto-space between bytes for readability.
      const clean = inp.value.replace(/[^0-9a-fA-F]/g, "").slice(0, f.length * 2);
      fdPayloads[f.id_hex] = clean;
      const spaced = spaceHex(clean);
      if (inp.value !== spaced) { inp.value = spaced; inp.setSelectionRange(spaced.length, spaced.length); }
      const bytes = Math.floor(clean.length / 2);
      $("fdPayHint").textContent = `${bytes} / ${f.length} bytes`;
      inp.classList.toggle("invalid", clean.length % 2 !== 0);
      clearTimeout(fdTimer);
      fdTimer = setTimeout(() => fdDecodeBody(f.id_hex), 250);
    });
  }
  // Always re-render body (byte view + signal table + bit grid)
  fdRenderBody(f);
}
async function fdDecodeBody(idHex) {
  const r = await POST("/api/decode/frames", { frames: [{ id: idHex, data: fdPayloads[idHex] || "" }] });
  if (!r.ok || !r.frames.length) return;
  fdDetail = r.frames[0]; fdSelSig = -1; fdRenderBody(fdDetail);
}
function fdRenderBody(f) {
  const COLS = [7, 6, 5, 4, 3, 2, 1, 0];
  const sel = (fdSelSig >= 0 && f.signals[fdSelSig]) ? f.signals[fdSelSig] : null;
  const cells = new Set((sel ? sel.cells : []).map((c) => c[0] + ":" + c[1]));
  const msbKey = sel && sel.msb_cell ? sel.msb_cell[0] + ":" + sel.msb_cell[1] : null;
  const lsbKey = sel && sel.lsb_cell ? sel.lsb_cell[0] + ":" + sel.lsb_cell[1] : null;
  const single = msbKey && msbKey === lsbKey;   // 1-bit signal: MSB == LSB
  const idx = f.bytes.map((_, i) => `<td>${String(i).padStart(2, "0")}</td>`).join("");
  const val = f.bytes.map((b) => `<td>${b.toString(16).toUpperCase().padStart(2, "0")}</td>`).join("");

  // Check if any signal in this frame has a DBC value description
  const hasChoices = f.signals.some((s) => s.choice !== null && s.choice !== undefined);

  const rows = f.signals.map((s, si) => {
    const oor = s.out_of_range;
    const physColor = oor ? "var(--red)" : "var(--accent)";
    const oorBadge = oor
      ? `<span title="Outside DBC range [${s.min ?? "?"}…${s.max ?? "?"}]"
           style="margin-left:5px;font-size:10px;background:#3a1c1c;color:var(--red);border-radius:3px;padding:1px 5px;vertical-align:middle">OOR</span>`
      : "";
    // Value description column cell
    const descCell = hasChoices
      ? `<td style="color:var(--green);font-weight:600;letter-spacing:.02em">${
          s.choice != null
            ? `<span class="tag" style="background:var(--green-bg);color:var(--green);border-color:#2c5a39;font-size:12px">${s.choice}</span>`
            : "<span style=\"color:var(--muted)\">—</span>"
        }</td>`
      : "";
    return `<tr class="${si === fdSelSig ? "sel" : ""}" style="cursor:pointer" onclick="fdSelectSig(${si})" title="Click to highlight bits">
      <td style="text-align:center;color:var(--muted)">${si + 1}</td>
      <td style="font-weight:500">${s.name}</td>
      <td class="mono" style="text-align:right" title="${s.raw} (dec)">${fdRawHex(s)}</td>
      <td class="mono" style="text-align:right;color:${physColor}">${s.physical}${oorBadge}</td>
      <td style="color:var(--muted);font-size:12px">${s.unit || "—"}</td>
      ${descCell}
    </tr>`;
  }).join("") || `<tr><td colspan="${hasChoices ? 6 : 5}" class="muted-line" style="padding:12px;text-align:center">no decoded signals</td></tr>`;

  // Header: add Description column only when needed
  const descHead = hasChoices ? `<th style="color:var(--green)">Description</th>` : "";

  const bitHead = COLS.map((c, ci) => {
    const sub = ci === 0 ? `<br><span style="font-size:9px;letter-spacing:.04em;opacity:.65">MSB</span>` :
                ci === 7 ? `<br><span style="font-size:9px;letter-spacing:.04em;opacity:.65">LSB</span>` : "";
    return `<th>${c}${sub}</th>`;
  }).join("");
  // Inline colours (cache-proof — don't depend on style.css being fresh).
  const C_HI = "#4ea1ff", C_MSB = "#e0a82e", C_LSB = "#46b86a";
  let grid = `<table class="bitgrid"><thead><tr><th></th>${bitHead}</tr></thead><tbody>`;
  for (let b = 0; b < f.bytes.length; b++) {
    grid += `<tr><th>${b}</th>` + COLS.map((c) => {
      const key = b + ":" + c, bit = (f.bytes[b] >> c) & 1;
      let st = "";
      if (!single && key === msbKey) st = `background:${C_MSB};color:#1b1d1f;font-weight:700`;
      else if (!single && key === lsbKey) st = `background:${C_LSB};color:#fff;font-weight:700`;
      else if (cells.has(key)) st = `background:${C_HI};color:#fff;font-weight:700`;
      return `<td style="${st}">${bit}</td>`;
    }).join("") + `</tr>`;
  }
  grid += `</tbody></table>`;
  // Legend (inline-styled, only when a signal is highlighted)
  const sw = (c) => `<i style="width:12px;height:12px;border-radius:3px;display:inline-block;background:${c}"></i>`;
  const chip = (c, label) => `<span style="display:inline-flex;align-items:center;gap:5px">${sw(c)}${label}</span>`;
  const legendStyle = "display:flex;gap:14px;margin-top:8px;font-size:11px;color:var(--muted)";
  const legend = sel
    ? (single
        ? `<div style="${legendStyle}">${chip(C_HI, "signal bit")}</div>`
        : `<div style="${legendStyle}">${chip(C_MSB, "MSB")}${chip(C_HI, "signal bits")}${chip(C_LSB, "LSB")}</div>`)
    : "";

  $("fdDetailBody").innerHTML = `<div style="padding:12px 16px">
    <div class="muted-line" style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">Data Byte View (HEX)</div>
    <table class="byteview mono"><tbody><tr><th>Byte</th>${idx}</tr><tr><th>Value</th>${val}</tr></tbody></table>
    <div style="display:flex;gap:24px;flex-wrap:wrap;margin-top:16px">
      <div style="flex:1;min-width:300px">
        <div class="muted-line" style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">Signal Details</div>
        <table class="data-table" style="min-width:380px">
          <colgroup><col style="width:34px"><col><col style="width:80px"><col style="width:100px"><col style="width:52px">${hasChoices ? '<col style="width:110px">' : ""}</colgroup>
          <thead><tr>
            <th style="text-align:center">#</th><th>Signal</th>
            <th style="text-align:right">Raw</th>
            <th style="text-align:right">Physical</th>
            <th>Unit</th>
            ${descHead}
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div>
        <div class="muted-line" style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">Bit Layout — byte · bit 7(MSB)→0(LSB)</div>
        ${grid}
        ${legend}
      </div>
    </div>
  </div>`;
}
$("btnFdFill").addEventListener("click", () => {
  // ID base follows the active source: decimal for JSON, hex for DBC.
  const idBase = fdSource === "json" ? 10 : 16;
  let matched = 0;
  for (const ln of $("fdFill").value.split("\n")) {
    const t = ln.trim().split(/[\s,]+/); if (t.length < 2) continue;
    const id = parseInt(t[0], idBase); if (isNaN(id)) continue;
    const idHex = id.toString(16).toUpperCase();
    if (idHex in fdPayloads) {
      // join remaining tokens so spaced payloads ("01 28 C3") work, hex-only
      fdPayloads[idHex] = t.slice(1).join("").replace(/[^0-9a-fA-F]/g, "");
      matched++;
    }
  }
  renderFdCatalogue();
  // Refresh the open message so its input + decode reflect the filled payload.
  const openId = fdCurrentDetailId;
  if (openId && openId in fdPayloads) { fdCurrentDetailId = null; fdDecodeOne(openId); }
  setStatus(`Payloads filled from dump — ${matched} message${matched === 1 ? "" : "s"} matched`);
});

// ----------------------- Converter workbench (upload · edit · select · export)
let cvModel = null, cvSourceFmt = null, cvSourceName = null, cvEdited = false, cvEditMode = false;
const CV_FMT = { dbc: "DBC", json: "JSON", csv: "CSV" };
const _svg = (body) => `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
const CV_ICON = {
  edit: _svg('<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
  lock: _svg('<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>'),
};
const escAttr = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
const cvParseVT = (raw) => {
  const out = {}; let any = false;
  for (const p of String(raw || "").split(";")) {
    const i = p.indexOf(":"); if (i < 0) continue;
    const k = p.slice(0, i).trim(), v = p.slice(i + 1).trim();
    if (k === "" || isNaN(+k)) continue;
    out[+k] = v; any = true;
  }
  return any ? out : null;
};
const cvFmtVT = (vt) => vt ? Object.entries(vt).map(([k, v]) => `${k}:${v}`).join(";") : "";
function cvBeDoubt(start, len, bo) {       // mirror of convert._be_doubt
  if (bo !== "big_endian") return null;
  const first = Math.floor(start / 8), last = Math.floor((start + len - 1) / 8);
  return (last > first && !(start % 8 === 0 && len % 8 === 0))
    ? `sub-byte big-endian (size ${len}) — verify bit layout in a DBC tool` : null;
}

$("btnCvUpload").addEventListener("click", () => $("cvFile").click());
$("cvFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  $("cvFileName").textContent = f.name; $("cvStatus").textContent = "Parsing…";
  const fd = new FormData(); fd.append("file", f);
  let r;
  try { r = await fetch("/api/convert/parse", { method: "POST", body: fd }).then((x) => x.json()); }
  catch (err) { $("cvStatus").textContent = "Network error: " + err; return; }
  if (!r.ok) { $("cvStatus").textContent = "Error: " + r.error; cvModel = null; renderCv(); return; }
  cvModel = r.model; cvSourceFmt = r.source_fmt; cvSourceName = r.source_name;
  cvEdited = false; cvEditMode = false;          // #1: open in read-only view mode
  cvModel.messages.forEach((m) => m.signals.forEach((s) => (s._sel = true)));   // select all by default
  $("cvStatus").textContent = "";
  $("cvWarnings").innerHTML = (r.warnings && r.warnings.length)
    ? cvWarnBox(r.warnings, "from parsing") : "";
  cvBuildFormatOptions();
  renderCv();
});

function cvWarnBox(warns, ctx) {
  return `<div style="border:1px solid #7a5;background:#2a2410;border-radius:8px;padding:10px 14px">
    <div style="color:#e0a82e;margin-bottom:6px">⚠ ${warns.length} note${warns.length === 1 ? "" : "s"} ${ctx || ""}</div>
    <ul style="margin:0;padding-left:18px;color:var(--muted);font-size:13px">${warns.map((w) => `<li>${w}</li>`).join("")}</ul></div>`;
}

function cvBuildFormatOptions() {
  const sel = $("cvTo"), prev = sel.value;
  const opts = [];
  ["json", "dbc", "csv"].forEach((f) => {
    if (f === cvSourceFmt && !cvEdited) return;        // #1: hide same-format until edited
    opts.push(`<option value="${f}">${f === cvSourceFmt ? CV_FMT[f] + " (save edits)" : CV_FMT[f]}</option>`);
  });
  sel.innerHTML = opts.join("");
  if ([...sel.options].some((o) => o.value === prev)) sel.value = prev;
}

function renderCv() {
  const wb = $("cvWorkbench"), empty = $("cvEmpty");
  if (!cvModel) { wb.classList.add("hidden"); empty.classList.remove("hidden"); return; }
  empty.classList.add("hidden"); wb.classList.remove("hidden");
  const chip = $("cvSrcChip"); chip.textContent = "source: " + CV_FMT[cvSourceFmt]; chip.classList.remove("hidden");
  const et = $("cvEditToggle");
  et.innerHTML = cvEditMode ? `${CV_ICON.lock}<span>Editing — click to lock</span>` : `${CV_ICON.edit}<span>Edit</span>`;
  et.classList.toggle("cv-editing", cvEditMode);
  const ro = cvEditMode ? "" : "readonly", dis = cvEditMode ? "" : "disabled";
  const filter = ($("cvSearch").value || "").toLowerCase();
  const html = cvModel.messages.map((m, mi) => {
    const rows = m.signals.map((s, si) => ({ s, si }))
      .filter(({ s }) => !filter || s.name.toLowerCase().includes(filter) || String(m.frame_id).includes(filter));
    if (!rows.length) return "";
    const allSel = m.signals.every((s) => s._sel);
    return `<div class="cv-msg">
      <div class="cv-msg-head">
        <input type="checkbox" ${allSel ? "checked" : ""} onchange="cvToggleMsg(${mi},this.checked)" title="select all in message" />
        <input class="cv-in" style="width:78px" value="${m.frame_id}" ${ro} onchange="cvEditMsg(${mi},'frame_id',this.value)" title="CAN ID (decimal)" />
        <input class="cv-in" style="width:170px" value="${escAttr(m.name)}" ${ro} onchange="cvEditMsg(${mi},'name',this.value)" />
        <span class="muted-line">DLC</span>
        <input class="cv-in n" value="${m.dlc}" ${ro} onchange="cvEditMsg(${mi},'dlc',this.value)" />
        <span class="muted-line">${m.signals.length} signal${m.signals.length === 1 ? "" : "s"}</span>
      </div>
      <div class="table-wrap"><table class="data-table cv-sigtable"><thead><tr>
        <th></th><th>Signal</th><th>Start</th><th>Len</th><th>Order</th><th>Sgn</th>
        <th>Scale</th><th>Offset</th><th>Min</th><th>Max</th><th>Unit</th><th>Value table</th><th>Comment</th>
      </tr></thead><tbody>${rows.map(({ s, si }) => cvSigRow(mi, si, s)).join("")}</tbody></table></div>
    </div>`;
  }).join("");
  $("cvTable").innerHTML = html || `<div class="muted-line" style="padding:14px">No signals match "${filter}".</div>`;
  cvUpdateSelCount(); cvUpdateLoss();
}

function cvSigRow(mi, si, s) {
  const doubt = cvBeDoubt(s.start_bit, s.length, s.byte_order);
  const warn = doubt ? `<span title="${escAttr(doubt)}" style="color:#e0a82e;margin-left:4px">⚠</span>` : "";
  const isM = s.byte_order === "big_endian";
  const ro = cvEditMode ? "" : "readonly", dis = cvEditMode ? "" : "disabled";
  return `<tr>
    <td style="text-align:center"><input type="checkbox" ${s._sel ? "checked" : ""} onchange="cvToggleSig(${mi},${si},this.checked)" /></td>
    <td><input class="cv-in" value="${escAttr(s.name)}" ${ro} onchange="cvEdit(${mi},${si},'name',this.value)" />${warn}</td>
    <td><input class="cv-in n" value="${s.start_bit}" ${ro} onchange="cvEdit(${mi},${si},'start_bit',this.value)" /></td>
    <td><input class="cv-in n" value="${s.length}" ${ro} onchange="cvEdit(${mi},${si},'length',this.value)" /></td>
    <td><select class="cv-in" ${dis} onchange="cvEdit(${mi},${si},'byte_order',this.value)">
      <option ${isM ? "selected" : ""}>Motorola</option><option ${!isM ? "selected" : ""}>Intel</option></select></td>
    <td style="text-align:center"><input type="checkbox" ${s.is_signed ? "checked" : ""} ${dis} onchange="cvEdit(${mi},${si},'is_signed',this.checked)" /></td>
    <td><input class="cv-in n" value="${s.scale}" ${ro} onchange="cvEdit(${mi},${si},'scale',this.value)" /></td>
    <td><input class="cv-in n" value="${s.offset}" ${ro} onchange="cvEdit(${mi},${si},'offset',this.value)" /></td>
    <td><input class="cv-in n" value="${s.min ?? ""}" ${ro} onchange="cvEdit(${mi},${si},'min',this.value)" /></td>
    <td><input class="cv-in n" value="${s.max ?? ""}" ${ro} onchange="cvEdit(${mi},${si},'max',this.value)" /></td>
    <td><input class="cv-in" style="width:50px" value="${escAttr(s.unit || "")}" ${ro} onchange="cvEdit(${mi},${si},'unit',this.value)" /></td>
    <td><input class="cv-in" style="width:118px" value="${escAttr(cvFmtVT(s.value_table))}" placeholder="0:Off;1:On" ${ro} onchange="cvEdit(${mi},${si},'value_table',this.value)" /></td>
    <td><input class="cv-in" style="width:130px" value="${escAttr(s.comment || "")}" ${ro} onchange="cvEdit(${mi},${si},'comment',this.value)" /></td>
  </tr>`;
}

window.cvEdit = (mi, si, key, val) => {
  const s = cvModel.messages[mi].signals[si];
  if (key === "byte_order") s.byte_order = val === "Motorola" ? "big_endian" : "little_endian";
  else if (key === "start_bit" || key === "length") s[key] = parseInt(val, 10) || 0;
  else if (key === "scale" || key === "offset") s[key] = parseFloat(val) || 0;
  else if (key === "min" || key === "max") s[key] = val === "" ? null : parseFloat(val);
  else if (key === "is_signed") s.is_signed = val;
  else if (key === "value_table") s.value_table = cvParseVT(val);
  else s[key] = val;
  cvMarkEdited();
  renderCv();      // refresh ⚠ markers + loss preview
};
window.cvEditMsg = (mi, key, val) => {
  const m = cvModel.messages[mi];
  if (key === "frame_id" || key === "dlc") m[key] = parseInt(val, 10) || 0;
  else m[key] = val;
  cvMarkEdited();
};
function cvMarkEdited() {
  if (!cvEdited) { cvEdited = true; cvBuildFormatOptions(); }
}
window.cvToggleSig = (mi, si, on) => { cvModel.messages[mi].signals[si]._sel = on; cvUpdateSelCount(); cvUpdateLoss(); };
window.cvToggleMsg = (mi, on) => { cvModel.messages[mi].signals.forEach((s) => (s._sel = on)); renderCv(); };
$("cvSelAll").addEventListener("click", () => { cvModel.messages.forEach((m) => m.signals.forEach((s) => (s._sel = true))); renderCv(); });
$("cvSelNone").addEventListener("click", () => { cvModel.messages.forEach((m) => m.signals.forEach((s) => (s._sel = false))); renderCv(); });
$("cvEditToggle").addEventListener("click", () => { if (cvModel) { cvEditMode = !cvEditMode; renderCv(); } });
$("cvSearch").addEventListener("input", renderCv);
$("cvTo").addEventListener("change", cvUpdateLoss);
$("btnCvClear").addEventListener("click", () => {
  cvModel = null; cvSourceFmt = null; cvSourceName = null; cvEdited = false; cvEditMode = false;
  $("cvFile").value = "";
  $("cvFileName").textContent = "no file selected";
  $("cvSrcChip").classList.add("hidden");
  $("cvStatus").textContent = ""; $("cvWarnings").innerHTML = ""; $("cvSelCount").textContent = "";
  renderCv();
});

function cvUpdateSelCount() {
  let sel = 0, tot = 0;
  cvModel.messages.forEach((m) => m.signals.forEach((s) => { tot++; if (s._sel) sel++; }));
  $("cvSelCount").textContent = `${sel} of ${tot} signals selected`;
  $("btnCvDownload").disabled = sel === 0;
}
function cvUpdateLoss() {
  const to = $("cvTo").value; if (!to) return;
  let msg;
  if (to === "json") {
    let u = 0, r = 0, v = 0, c = 0;
    cvModel.messages.forEach((m) => m.signals.forEach((s) => {
      if (!s._sel) return;
      if (s.unit) u++; if (s.min != null || s.max != null) r++; if (s.value_table) v++; if (s.comment) c++;
    }));
    const d = [];
    if (u) d.push(`units (${u})`); if (r) d.push(`min/max (${r})`); if (v) d.push(`value tables (${v})`); if (c) d.push(`comments (${c})`);
    d.push("message names");
    msg = `→ JSON will drop: ${d.join(", ")}.`;
  } else {
    msg = `→ ${CV_FMT[to]} preserves all fields.`;
  }
  let dbt = 0;
  cvModel.messages.forEach((m) => m.signals.forEach((s) => { if (s._sel && cvBeDoubt(s.start_bit, s.length, s.byte_order)) dbt++; }));
  if (dbt) msg += ` ⚠ ${dbt} sub-byte big-endian signal${dbt === 1 ? "" : "s"}${to === "dbc" ? " will get a verify comment" : ""}.`;
  $("cvLoss").textContent = msg;
}

$("btnCvDownload").addEventListener("click", async () => {
  if (!cvModel) return;
  const to = $("cvTo").value;
  const fm = { messages: [] };
  cvModel.messages.forEach((m) => {
    const sigs = m.signals.filter((s) => s._sel).map((s) => {
      const { _sel, doubt, ...clean } = s; return clean;
    });
    if (sigs.length) fm.messages.push({
      name: m.name, frame_id: parseInt(m.frame_id, 10) || 0,
      is_extended: !!m.is_extended, dlc: parseInt(m.dlc, 10) || 8, signals: sigs,
    });
  });
  if (!fm.messages.length) { $("cvStatus").textContent = "Select at least one signal."; return; }
  $("cvStatus").textContent = "Preparing…";
  const r = await POST("/api/convert/export", { model: fm, to, source_name: cvSourceName });
  if (!r.ok) { $("cvStatus").textContent = "Download error: " + r.error; return; }
  const blob = new Blob([r.content], { type: "text/plain" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = r.filename; a.click();
  $("cvStatus").textContent = `Downloaded ${r.filename}`;
  $("cvWarnings").innerHTML = (r.warnings && r.warnings.length)
    ? cvWarnBox(r.warnings, "— annotated in the file")
    : `<div class="muted-line" style="color:var(--green)">Clean conversion — downloaded ${r.filename}</div>`;
});

// -------------------------------------------------------------- DBC Builder
let dbcModel = { messages: [] };
async function renderDbc() {
  dbcModel = await api("/api/dbc");
  const host = $("dbcMessages");
  host.innerHTML = dbcModel.messages.map((m, mi) => `
    <div class="dbc-msg">
      <div class="dbc-msg-head">
        <input value="${m.name}" onchange="dbcEdit(${mi},null,'name',this.value)" style="width:200px" />
        <span class="muted-line">ID 0x${m.frame_id.toString(16).toUpperCase()} · len</span>
        <input type="number" value="${m.length}" onchange="dbcEdit(${mi},null,'length',+this.value)" style="width:60px" />
        <span style="flex:1"></span>
        <button class="btn-mini" onclick="dbcAddSig(${mi})">+ Signal</button>
        <button class="btn-mini" onclick="dbcDelMsg(${mi})">${ICONS.close}</button>
      </div>
      <table class="data-table dbc-sig-table"><thead><tr>
        <th>Name</th><th>Start</th><th>Len</th><th>Order</th><th>Signed</th><th>Scale</th><th>Offset</th><th>Unit</th><th></th>
      </tr></thead><tbody>
      ${m.signals.map((s, si) => `<tr>
        <td><input value="${s.name}" onchange="dbcEdit(${mi},${si},'name',this.value)"/></td>
        <td><input type="number" value="${s.start_bit}" onchange="dbcEdit(${mi},${si},'start_bit',+this.value)"/></td>
        <td><input type="number" value="${s.length}" onchange="dbcEdit(${mi},${si},'length',+this.value)"/></td>
        <td><select onchange="dbcEdit(${mi},${si},'byte_order',this.value)">
          <option value="little_endian" ${s.byte_order === "little_endian" ? "selected" : ""}>Intel</option>
          <option value="big_endian" ${s.byte_order === "big_endian" ? "selected" : ""}>Motorola</option></select></td>
        <td style="text-align:center"><input type="checkbox" ${s.is_signed ? "checked" : ""} onchange="dbcEdit(${mi},${si},'is_signed',this.checked)"/></td>
        <td><input type="number" step="any" value="${s.scale}" onchange="dbcEdit(${mi},${si},'scale',+this.value)"/></td>
        <td><input type="number" step="any" value="${s.offset}" onchange="dbcEdit(${mi},${si},'offset',+this.value)"/></td>
        <td><input value="${s.unit || ""}" onchange="dbcEdit(${mi},${si},'unit',this.value)"/></td>
        <td><button class="btn-mini" onclick="dbcDelSig(${mi},${si})">${ICONS.close}</button></td>
      </tr>`).join("")}
      </tbody></table>
    </div>`).join("") || `<div class="placeholder" style="padding:40px">No messages. Add one, or seed from Reverse Engineering.</div>`;
}
const dbcSave = () => POST("/api/dbc/set", { messages: dbcModel.messages });
window.dbcEdit = (mi, si, key, val) => { (si === null ? dbcModel.messages[mi] : dbcModel.messages[mi].signals[si])[key] = val; dbcSave(); };
window.dbcAddSig = (mi) => { dbcModel.messages[mi].signals.push({ name: "sig_" + dbcModel.messages[mi].signals.length, start_bit: 0, length: 8, byte_order: "little_endian", is_signed: false, scale: 1, offset: 0, unit: "" }); dbcSave().then(renderDbc); };
window.dbcDelSig = (mi, si) => { dbcModel.messages[mi].signals.splice(si, 1); dbcSave().then(renderDbc); };
window.dbcDelMsg = (mi) => { dbcModel.messages.splice(mi, 1); dbcSave().then(renderDbc); };
$("btnDbcAddMsg").addEventListener("click", () => {
  const hex = prompt("New message frame ID (hex):", "200"); if (!hex) return;
  dbcModel.messages.push({ frame_id: parseInt(hex, 16), name: "MSG_" + hex.toUpperCase(), length: 8, is_extended: false, comment: "", signals: [] });
  dbcSave().then(renderDbc);
});
$("btnDbcImport").addEventListener("click", () => $("dbcFile").click());
$("dbcFile").addEventListener("change", async (e) => { const f = e.target.files[0]; if (f) { await apiUpload("/api/dbc/import", f); renderDbc(); } });
$("btnDbcExport").addEventListener("click", async () => {
  const txt = await fetch("/api/dbc/export").then((r) => r.text());
  const blob = new Blob([txt], { type: "text/plain" });
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const ts = `${pad(now.getDate())}${pad(now.getMonth()+1)}${String(now.getFullYear()).slice(-2)}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${ts}.dbc`; a.click();
});
$("btnDbcToViewer").addEventListener("click", async () => {
  const r = await POST("/api/signals/use-builder");
  setStatus(r.ok ? `Loaded ${r.signals.length} signals into Signal Viewer` : r.error);
});

// ------------------------------------------------------------- Signal Viewer
const sigSelected = new Set();
const SIG_COLORS = ["#4ea1ff", "#46b86a", "#e2a055", "#c46bde", "#e25555", "#3fc7c7", "#d4d04e"];
$("btnSigUseBuilder").addEventListener("click", async () => { await POST("/api/signals/use-builder"); refreshSigList(); });
$("btnSigImport").addEventListener("click", () => $("sigDbcFile").click());
$("sigDbcFile").addEventListener("change", async (e) => { const f = e.target.files[0]; if (f) { await apiUpload("/api/signals/import", f); refreshSigList(); } });
$("btnSigClear").addEventListener("click", () => POST("/api/signals/clear"));
async function refreshSigList() {
  const info = await api("/api/signals");
  $("sigStatus").textContent = info.loaded ? `${info.signals.length} signals · ${info.messages} messages` : "No DBC loaded";
  $("sigList").innerHTML = (info.signals || []).map((s, i) => `
    <label class="sig-item"><input type="checkbox" data-key="${s.key}" ${sigSelected.has(s.key) ? "checked" : ""} onchange="toggleSig('${s.key}')"/>
    <span class="sig-swatch" style="background:${SIG_COLORS[i % SIG_COLORS.length]}"></span>${s.key} ${s.unit ? "(" + s.unit + ")" : ""}</label>`).join("");
}
window.toggleSig = (key) => { sigSelected.has(key) ? sigSelected.delete(key) : sigSelected.add(key); renderChartShells(); };
function renderChartShells() {
  $("charts").innerHTML = [...sigSelected].map((k, i) => `
    <div class="chart-card"><div class="chart-title"><span>${k}</span><span id="cv-${cssId(k)}-v"></span></div>
    <canvas class="chart" id="cv-${cssId(k)}" data-key="${k}" data-color="${SIG_COLORS[i % SIG_COLORS.length]}"></canvas></div>`).join("");
}
const cssId = (k) => k.replace(/[^a-zA-Z0-9]/g, "_");
async function pollSignals() {
  pollDerived();
  if (!sigSelected.size) return;
  const res = await api("/api/signals/series?keys=" + encodeURIComponent([...sigSelected].join(",")));
  for (const key of sigSelected) drawChart(key, res.series[key] || []);
}

// ----- computed signals & alarms -----
let computedDefs = [], alarmDefs = [];
async function pollDerived() {
  const d = await api("/api/signals/derived");
  const active = (d.alarms || []).filter((a) => a.active);
  $("sigAlarmBanner").innerHTML = active.length
    ? `<span class="cand-chip" style="border-color:#e25555;color:#e25555">⚠ ${active.map((a) => a.name).join(", ")}</span>` : "";
  $("almList").innerHTML = (d.alarms || []).map((a, i) =>
    `<span class="cand-chip" style="border-color:${a.active ? "#e25555" : "#6b7280"};color:${a.active ? "#e25555" : "#9aa0a6"}">
      ${a.name} [${a.min ?? "−∞"},${a.max ?? "∞"}]${a.active ? " ⚠" : ""} <a href="#" onclick="delAlarm(${i});return false">${ICONS.close}</a></span>`).join("") || "none";
}
$("btnCompAdd").addEventListener("click", async () => {
  const name = $("compName").value.trim(), expr = $("compExpr").value.trim();
  if (!name || !expr) return;
  computedDefs.push({ name, expr });
  await POST("/api/signals/computed", { defs: computedDefs });
  $("compName").value = ""; $("compExpr").value = ""; renderCompList();
});
function renderCompList() {
  $("compList").innerHTML = computedDefs.map((c, i) =>
    `<span class="cand-chip" style="border-color:#61afef;color:#61afef">${c.name} = ${c.expr} <a href="#" onclick="delComp(${i});return false">${ICONS.close}</a></span>`).join("") || "none";
}
window.delComp = async (i) => { computedDefs.splice(i, 1); await POST("/api/signals/computed", { defs: computedDefs }); renderCompList(); refreshSigList(); };
$("btnAlmAdd").addEventListener("click", async () => {
  const key = $("almKey").value.trim();
  if (!key) return;
  const min = $("almMin").value.trim(), max = $("almMax").value.trim();
  alarmDefs.push({ name: key, key, min: min === "" ? null : +min, max: max === "" ? null : +max });
  await POST("/api/signals/alarms", { defs: alarmDefs });
  $("almKey").value = ""; $("almMin").value = ""; $("almMax").value = ""; pollDerived();
});
window.delAlarm = async (i) => { alarmDefs.splice(i, 1); await POST("/api/signals/alarms", { defs: alarmDefs }); pollDerived(); };
function drawChart(key, pts) {
  const cv = $("cv-" + cssId(key)); if (!cv) return;
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, w, h);
  if (pts.length < 2) return;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = xs[0], x1 = xs[xs.length - 1], y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = (x) => ((x - x0) / (x1 - x0 || 1)) * (w - 8) + 4;
  const sy = (y) => h - 6 - ((y - y0) / (y1 - y0 || 1)) * (h - 12);
  ctx.strokeStyle = cv.dataset.color; ctx.lineWidth = 1.5; ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(sx(p[0]), sy(p[1])) : ctx.moveTo(sx(p[0]), sy(p[1]))));
  ctx.stroke();
  const vEl = $("cv-" + cssId(key) + "-v"); if (vEl) vEl.textContent = ys[ys.length - 1].toFixed(2);
}

// -------------------------------------------------------------- TX Scheduler
$("btnTxAdd").addEventListener("click", async () => {
  const id = parseInt($("txId").value, 16);
  if (isNaN(id)) return void setStatus("Invalid TX ID");
  await POST("/api/tx/add", { id, data: $("txData").value, cycle_ms: +$("txCycle").value, mode: $("txMode").value });
  pollTx();
});
// One-click standard OBD-II Mode-01 request rows (added idle; press Start to transmit).
const OBD_PRESET = [
  ["02 01 0C 00 00 00 00 00", "OBD RPM"], ["02 01 0D 00 00 00 00 00", "OBD Speed"],
  ["02 01 05 00 00 00 00 00", "OBD Coolant"], ["02 01 11 00 00 00 00 00", "OBD Throttle"],
  ["02 01 04 00 00 00 00 00", "OBD Load"],
];
$("btnTxObdPreset").addEventListener("click", async () => {
  for (const [data, name] of OBD_PRESET)
    await POST("/api/tx/add", { id: 0x7DF, data, cycle_ms: 300, mode: "cyclic", name });
  pollTx();
  setStatus("Added 5 OBD-II PID request rows — press Start all to begin polling.");
});

// ----- log folder -----
async function loadLogDir() {
  const r = await api("/api/logger/log-dir");
  if ($("logDir")) $("logDir").value = r.custom ? r.dir : "";
}
$("btnLogDirSave").addEventListener("click", async () => {
  const r = await POST("/api/logger/log-dir", { dir: $("logDir").value.trim() });
  setStatus(r.ok ? "Log folder set → " + r.dir : "Log folder: " + (r.error || "?"));
});
$("btnLogDirReset").addEventListener("click", async () => {
  $("logDir").value = "";
  const r = await POST("/api/logger/log-dir", { dir: "" });
  setStatus("Log folder reset → " + r.dir);
});
$("btnTxStart").addEventListener("click", () => POST("/api/tx/start").then((r) => !r.ok && setStatus(r.error)));
$("btnTxStop").addEventListener("click", () => POST("/api/tx/stop"));
window.txToggle = (uid, on) => POST("/api/tx/update", { uid, patch: { enabled: on } });
window.txRemove = (uid) => fetch("/api/tx/remove?uid=" + uid, { method: "POST" }).then(pollTx);
window.txOnce = (uid) => fetch("/api/tx/send-once?uid=" + uid, { method: "POST" });
async function pollTx() {
  const t = await api("/api/tx");
  $("txState").textContent = t.running ? "running" : "stopped";
  $("txTable").querySelector("tbody").innerHTML = t.entries.map((e) => `
    <tr><td style="text-align:center"><input type="checkbox" ${e.enabled ? "checked" : ""} onchange="txToggle(${e.uid},this.checked)"/></td>
    <td>${e.name}</td><td class="mono">0x${e.id_hex}</td><td class="mono">${e.data}</td>
    <td>${e.cycle_ms} ms</td><td>${e.mode}</td><td>${e.count}</td>
    <td><button class="btn-mini" onclick="txOnce(${e.uid})">Send</button>
        <button class="btn-mini" onclick="txRemove(${e.uid})">${ICONS.close}</button></td></tr>`).join("");
}

// ----------------------------------------------------------- Protocol Decoder
function interp(f) {
  if (f.protocol === "OBD-II") return `${f.mode_name}${f.pid_name ? " · " + f.pid_name : ""}${f.value ? " = " + f.value : ""}`;
  if (f.protocol === "UDS") return `${f.type} · ${f.service}${f.nrc_name ? " · NRC " + f.nrc_name : ""}${f.did ? " · DID " + f.did : ""}`;
  if (f.protocol === "J1939") return `PGN ${f.pgn_hex}${f.pgn_name ? " " + f.pgn_name : ""} · prio ${f.priority} · src ${f.source}`;
  if (f.protocol === "ISO-TP") return `${f.type}${f.total_len ? " · " + f.total_len + "B" : ""}`;
  return f.data || "";
}
$("btnDecode").addEventListener("click", async () => {
  const id = parseInt($("decId").value, 16); if (isNaN(id)) return void ($("decResult").textContent = "bad ID");
  const r = await POST("/api/decode/frame", { id, data: $("decData").value, is_extended: $("decExt").checked });
  $("decResult").textContent = r.ok ? `${r.result.protocol}: ${interp(r.result)}` : r.error;
});
async function pollDecode() {
  const r = await api("/api/decode/live");
  const filt = $("protoFilter").value;
  const rows = r.frames.filter((f) => !filt || f.protocol === filt);
  $("decTable").querySelector("tbody").innerHTML = rows.map((f) => `
    <tr><td>${f.ts.toFixed(3)}</td><td>0x${f.id_hex}</td><td><span class="tag">${f.protocol}</span></td><td>${interp(f)}</td></tr>`).join("");
}
$("btnDecClear").addEventListener("click", () => POST("/api/decode/clear").then(pollDecode));

// ----------------------------------------------------------------- Dashboard
$("btnDashClear").addEventListener("click", () => POST("/api/dashboard/clear").then(pollDashboard));
const fmtVal = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1));
async function pollDashboard() {
  const d = await api("/api/dashboard");
  const has = d.groups && d.groups.some((g) => g.items.length);
  $("dashEmpty").classList.toggle("hidden", has);
  $("dashGroups").innerHTML = (d.groups || []).map((g) => `
    <div class="dash-group">
      <div class="dash-group-title">${g.group}</div>
      <div class="gauge-grid">
        ${g.items.map((it) => `
          <div class="gauge ${it.stale ? "stale" : ""}">
            ${it.pid ? `<span class="gauge-meta">PID ${it.pid}</span>` : ""}
            ${it.spn ? `<span class="gauge-meta">SPN ${it.spn}</span>` : ""}
            <div class="gauge-name">${it.name}</div>
            <div class="gauge-val">${fmtVal(it.value)}<span class="gauge-unit">${it.unit}</span></div>
          </div>`).join("")}
      </div>
    </div>`).join("");
}

// ----------------------------------------------------------------- DTC Codes
$("btnDtcScan").addEventListener("click", () => POST("/api/dtc/scan").then((r) => !r.ok && setStatus(r.error)));
$("btnDtcClearList").addEventListener("click", () => POST("/api/dtc/clear").then(pollDtc));
$("btnDtcClearEcu").addEventListener("click", () => {
  if (!confirm("Send Mode 04 to CLEAR diagnostic trouble codes on the vehicle?\nThis erases stored DTCs and freeze-frame data.")) return;
  POST("/api/dtc/clear-ecu").then((r) => setStatus(r.ok ? "Sent Mode 04 clear request" : r.error));
});
async function pollDtc() {
  const d = await api("/api/dtc");
  $("dtcCount").textContent = (d.count || 0) + " codes";
  $("dtcEmpty").classList.toggle("hidden", (d.count || 0) > 0);
  $("dtcGroups").innerHTML = (d.groups || []).map((g) => `
    <div class="dash-group">
      <div class="dash-group-title">${g.group} · ${g.items.length}</div>
      ${g.items.map((it) => `
        <div class="dtc-card ${it.stale ? "stale" : ""}">
          <div class="dtc-code">${it.code}</div>
          <div class="dtc-body">
            <div class="dtc-desc">${it.desc || "<span style='color:var(--muted)'>no description</span>"}</div>
            ${it.status ? `<div class="dtc-status">${it.status}${it.oc !== undefined ? " · OC " + it.oc : ""}</div>` : ""}
          </div>
          <div class="dtc-seen">×${it.seen}</div>
        </div>`).join("")}
    </div>`).join("");
}

// ----------------------------------------------------- Hardware setup panel
async function checkDrivers() {
  const { backends } = await api("/api/drivers/status");
  const need = (backends || []).filter((b) => !b.ready && b.remedy);
  const panel = $("driverPanel");
  if (!need.length) { panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");
  $("driverList").innerHTML = need.map((b) => {
    const r = b.remedy;
    let action = "";
    if (r.type === "pip") action = `<code>${r.command}</code>`;
    else if (r.type === "installer") {
      const dl = b.download || {};
      const pct = dl.total ? Math.round((dl.downloaded / dl.total) * 100) : 0;
      if (dl.state === "downloading") action = `downloading… ${pct}% <button class="btn-mini" onclick="driverPoll('${b.hw}')">refresh</button>`;
      else if (dl.state === "done" || dl.cached) action = `<button class="btn-mini" onclick="driverLaunch('${b.hw}')">Install now</button>`;
      else action = `<button class="btn-mini" onclick="driverDownload('${b.hw}')">Download & install (${r.approx_mb || "?"} MB)</button>`;
    }
    return `<div style="margin:4px 0"><b>${b.label}</b> — <span class="muted-line">${b.detail}</span><br>
      <span class="muted-line">${(r.note || "")}</span> ${action}</div>`;
  }).join("");
}
window.driverDownload = async (hw) => {
  const r = await POST("/api/drivers/download?hw=" + hw);
  if (r.state === "page" && r.url) { window.open(r.url, "_blank"); return; }
  setStatus(r.reused ? "Installer already downloaded — click Install now" : "Downloading driver kit…");
  checkDrivers();
};
window.driverPoll = checkDrivers;
window.driverLaunch = async (hw) => {
  const r = await POST("/api/drivers/launch?hw=" + hw);
  if (r.open_url) window.open(r.open_url, "_blank");
  setStatus(r.ok ? (r.note || "Installer launched — approve the UAC prompt") : ("Install: " + (r.error || "?")));
};
$("btnDriverRecheck").addEventListener("click", checkDrivers);
checkDrivers();

// ----------------------------------- sidebar nav icons (consistent SVG set)
const _svgNav = (body) => `<svg class="nav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
const NAV_ICONS = {
  dashboard: _svgNav('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>'),
  logger: _svgNav('<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>'),
  replay: _svgNav('<polygon points="5 3 19 12 5 21 5 3"/>'),
  re: _svgNav('<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>'),
  autore: _svgNav('<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>'),
  framedec: _svgNav('<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/>'),
  convert: _svgNav('<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>'),
  dbc: _svgNav('<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>'),
  oem: _svgNav('<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>'),
  signals: _svgNav('<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>'),
  scheduler: _svgNav('<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'),
  automation: _svgNav('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'),
  dtc: _svgNav('<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'),
  decoder: _svgNav('<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>'),
};
document.querySelectorAll(".nav").forEach((b) => {
  const ic = NAV_ICONS[b.dataset.view];
  const label = b.textContent.trim();
  if (ic) b.innerHTML = ic + `<span>${label}</span>`;
  b.title = label;            // tooltip — useful when the rail is collapsed
});

// ----------------------------------- icons on static action buttons (by id)
const BTN_ICONS = {
  btnPlay: [ICONS.play, "Play"], btnPause: [ICONS.pause, "Pause"],
  btnStop: [ICONS.stop, "Stop"], btnStep: [ICONS.step, "Step"],
  btnTxStart: [ICONS.play, "Start all"], btnTxStop: [ICONS.stop, "Stop"],
  btnRestbusStart: [ICONS.play, "Start"], btnRestbusStop: [ICONS.stop, "Stop"],
  btnScriptRun: [ICONS.play, "Run script"],
  btnReplayRescan: [ICONS.refresh, "Logs"], btnReRescan: [ICONS.refresh, "Logs"],
  btnAutoReRescan: [ICONS.refresh, "Logs"], btnOemRefresh: [ICONS.refresh, ""],
  btnRefreshDevs: [ICONS.refresh, "Rescan"], btnDbcToViewer: [ICONS.arrowRight, "Signal Viewer"],
  btnFdToggleFill: [ICONS.clipboard, "Paste frames"],
  btnDbcImport: [ICONS.upload, "Upload .dbc"], btnDbcExport: [ICONS.download, "Download .dbc"],
  btnSigImport: [ICONS.upload, "Upload .dbc"],
};
Object.entries(BTN_ICONS).forEach(([id, [ic, label]]) => {
  const el = $(id);
  if (!el) return;
  el.innerHTML = ic + (label ? `<span>${label}</span>` : "");
  el.classList.add("btn-ico");
});

// --------------------------- sidebar: simple open ↔ collapsed toggle (persisted)
// (auto-hide/hover-flyout mode is disabled for now — needs more work.)
const _appEl = document.querySelector(".app");
let navMode = "open";
function applyNavMode(mode) {
  navMode = mode === "rail" ? "rail" : "open";   // only two states supported
  _appEl.classList.toggle("nav-rail", navMode === "rail");
  $("navToggle").title = navMode === "rail" ? "Expand sidebar" : "Collapse sidebar";
  try { localStorage.setItem("ucando_nav_mode", navMode); } catch (e) {}
}
$("navToggle").addEventListener("click", () => applyNavMode(navMode === "rail" ? "open" : "rail"));
let _savedMode = "open";
try { _savedMode = localStorage.getItem("ucando_nav_mode") || "open"; } catch (e) {}
applyNavMode(_savedMode === "rail" ? "rail" : "open");   // legacy "auto" → open

// Initial header title/description + kick off polling for the Dashboard view.
setViewMeta(state.view);
startPolling(state.view);
